"""
Background job scheduler using APScheduler.

This runs scheduled tasks within the FastAPI process.
For more reliability, you can also use system crontab to hit the /api/cron endpoints.
"""

import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.jobs.consumption import process_scheduled_consumptions
from app.jobs.notifications import send_meal_reminders, send_daily_summary

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


def start_scheduler():
    """Start the background scheduler with all jobs."""

    # Process consumptions every 15 minutes
    scheduler.add_job(
        process_scheduled_consumptions,
        CronTrigger(minute="*/15"),
        id="process_consumptions",
        name="Process scheduled meal consumptions",
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
