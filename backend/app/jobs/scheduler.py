"""
Background job scheduler using APScheduler.

This runs scheduled tasks within the FastAPI process.
For more reliability, you can also use system crontab to hit the /api/cron endpoints.
"""

import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.jobs.consumption import process_all_consumptions
from app.jobs.notifications import send_meal_reminders, send_daily_summary
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

scheduler = AsyncIOScheduler()


def start_scheduler():
    """Start the background scheduler with all jobs."""

    # Process consumptions frequently (default: every 2 minutes)
    # This ensures meals are marked consumed quickly after their scheduled time
    consumption_interval = settings.consumption_interval_minutes
    logger.info(f"Scheduling consumption processing every {consumption_interval} minutes")

    scheduler.add_job(
        process_all_consumptions,
        IntervalTrigger(minutes=consumption_interval),
        id="process_consumptions",
        name="Process scheduled meal and supplement consumptions",
        replace_existing=True,
    )

    # Meal reminders - 30 min before typical meal times
    # Breakfast reminder at 7:30 AM
    scheduler.add_job(
        lambda: send_meal_reminders("breakfast"),
        CronTrigger(hour=7, minute=30),
        id="reminder_breakfast",
        name="Breakfast reminder",
        replace_existing=True,
    )

    # Lunch reminder at 11:30 AM
    scheduler.add_job(
        lambda: send_meal_reminders("lunch"),
        CronTrigger(hour=11, minute=30),
        id="reminder_lunch",
        name="Lunch reminder",
        replace_existing=True,
    )

    # Dinner reminder at 5:30 PM
    scheduler.add_job(
        lambda: send_meal_reminders("dinner"),
        CronTrigger(hour=17, minute=30),
        id="reminder_dinner",
        name="Dinner reminder",
        replace_existing=True,
    )

    # Daily summary at 9 PM
    scheduler.add_job(
        send_daily_summary,
        CronTrigger(hour=21, minute=0),
        id="daily_summary",
        name="Daily nutrition summary",
        replace_existing=True,
    )

    scheduler.start()
    logger.info("Scheduler started with jobs: %s", [job.id for job in scheduler.get_jobs()])


def shutdown_scheduler():
    """Shutdown the scheduler gracefully."""
    scheduler.shutdown(wait=False)
    logger.info("Scheduler shutdown")


def get_scheduler() -> AsyncIOScheduler:
    """Get the scheduler instance."""
    return scheduler
