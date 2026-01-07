"""Cron job endpoints - called by system crontab or scheduler."""

from datetime import datetime
import logging

from fastapi import APIRouter, HTTPException, Request, Header

from app.config import get_settings
from app.jobs.consumption import process_all_consumptions
from app.jobs.notifications import send_meal_reminders

router = APIRouter()
logger = logging.getLogger(__name__)
settings = get_settings()


def verify_cron_auth(
    request: Request,
    authorization: str | None = Header(None),
    x_cron_secret: str | None = Header(None),
) -> bool:
    """Verify cron request is authorized."""
    # Allow if no secret configured (dev mode)
    if not settings.cron_secret:
        return True

    # Check Bearer token
    if authorization and authorization == f"Bearer {settings.cron_secret}":
        return True

    # Check X-Cron-Secret header
    if x_cron_secret and x_cron_secret == settings.cron_secret:
        return True

    # Allow localhost requests
    host = request.headers.get("host", "")
    forwarded = request.headers.get("x-forwarded-for", "")
    if any(h in host for h in ["localhost", "127.0.0.1", "192.168.", "10."]):
        return True
    if forwarded in ["127.0.0.1", "::1"]:
        return True

    return False


@router.get("/process-consumptions")
async def cron_process_consumptions(
    request: Request,
    authorization: str | None = Header(None),
    x_cron_secret: str | None = Header(None),
):
    """
    Process scheduled meal and supplement consumptions.

    Call this via crontab every 2 minutes:
    */2 * * * * curl -s http://localhost:8000/api/cron/process-consumptions

    Note: The scheduler already runs this automatically every 2 minutes.
    This endpoint is for manual triggering or external cron jobs.
    """
    if not verify_cron_auth(request, authorization, x_cron_secret):
        raise HTTPException(status_code=401, detail="Unauthorized")

    logger.info("Starting scheduled consumption processing (manual trigger)...")

    try:
        result = await process_all_consumptions()
        logger.info(f"Processed {result['total_processed']} consumptions")
        return {
            "success": True,
            "meals": result.get("meals", {}),
            "supplements": result.get("supplements", {}),
            "total_processed": result.get("total_processed", 0),
            "total_errors": result.get("total_errors", 0),
            "note": "Timezone is per-user from their preferences",
            "timestamp": datetime.utcnow().isoformat(),
        }
    except Exception as e:
        logger.error(f"Error processing consumptions: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/meal-reminders")
async def cron_meal_reminders(
    request: Request,
    authorization: str | None = Header(None),
    x_cron_secret: str | None = Header(None),
):
    """
    Send meal reminders via ntfy.

    Call this 30 minutes before each meal slot:
    30 7 * * * curl -s http://localhost:8000/api/cron/meal-reminders  # breakfast
    30 11 * * * curl -s http://localhost:8000/api/cron/meal-reminders  # lunch
    30 17 * * * curl -s http://localhost:8000/api/cron/meal-reminders  # dinner
    """
    if not verify_cron_auth(request, authorization, x_cron_secret):
        raise HTTPException(status_code=401, detail="Unauthorized")

    logger.info("Sending meal reminders...")

    try:
        result = await send_meal_reminders()
        return {
            "success": True,
            "reminders_sent": result["sent_count"],
            "timestamp": datetime.utcnow().isoformat(),
        }
    except Exception as e:
        logger.error(f"Error sending reminders: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/daily-summary")
async def cron_daily_summary(
    request: Request,
    authorization: str | None = Header(None),
    x_cron_secret: str | None = Header(None),
):
    """
    Send daily nutrition summary.

    Call at end of day:
    0 21 * * * curl -s http://localhost:8000/api/cron/daily-summary
    """
    if not verify_cron_auth(request, authorization, x_cron_secret):
        raise HTTPException(status_code=401, detail="Unauthorized")

    # TODO: Implement daily summary
    return {
        "success": True,
        "message": "Daily summary not yet implemented",
        "timestamp": datetime.utcnow().isoformat(),
    }


@router.post("/trigger/{job_name}")
async def trigger_job(
    job_name: str,
    request: Request,
    authorization: str | None = Header(None),
    x_cron_secret: str | None = Header(None),
):
    """Manually trigger a cron job (for testing)."""
    if not verify_cron_auth(request, authorization, x_cron_secret):
        raise HTTPException(status_code=401, detail="Unauthorized")

    if job_name == "process-consumptions":
        return await cron_process_consumptions(request, authorization, x_cron_secret)
    elif job_name == "meal-reminders":
        return await cron_meal_reminders(request, authorization, x_cron_secret)
    elif job_name == "daily-summary":
        return await cron_daily_summary(request, authorization, x_cron_secret)
    else:
        raise HTTPException(status_code=404, detail=f"Unknown job: {job_name}")
