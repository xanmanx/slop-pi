"""
Notification jobs - meal reminders and daily summaries.
"""

import logging
from datetime import datetime

from app.services.supabase import (
    get_supabase_client,
    TABLES,
    get_all_users,
    get_upcoming_meals,
)
from app.services.notifications import get_notification_service

logger = logging.getLogger(__name__)


async def send_meal_reminders(slot: str | None = None) -> dict:
    """
    Send meal reminders for upcoming meals.

    Args:
        slot: Optional specific slot (breakfast, lunch, dinner, snack).
              If None, sends for all slots based on current time.
    """
    logger.info(f"Sending meal reminders for slot: {slot or 'auto'}")

    notification_service = get_notification_service()
    if not notification_service.enabled:
        logger.warning("Notifications disabled - skipping reminders")
        return {"sent_count": 0, "reason": "notifications_disabled"}

    today = datetime.utcnow().strftime("%Y-%m-%d")
    sent_count = 0

    try:
        users = await get_all_users()

        for user_data in users:
            user_id = user_data["user_id"]

            try:
                meals = await get_upcoming_meals(user_id, today, slot)

                for meal in meals:
                    if meal.get("consumed"):
                        continue  # Skip already consumed

                    food_item = meal.get("food_item") or {}
                    meal_name = food_item.get("name", "Your meal")
                    meal_slot = meal.get("slot", "meal")

                    success = await notification_service.send_meal_reminder(
                        meal_name=meal_name,
                        slot=meal_slot,
                        minutes_until=30,
                    )

                    if success:
                        sent_count += 1

            except Exception as e:
                logger.error(f"Error sending reminder for user {user_id}: {e}")

    except Exception as e:
        logger.error(f"Error in meal reminders: {e}")

    logger.info(f"Sent {sent_count} meal reminders")
    return {"sent_count": sent_count}


async def send_daily_summary() -> dict:
    """Send end-of-day nutrition summary to all users."""
    logger.info("Sending daily summaries")

    notification_service = get_notification_service()
    if not notification_service.enabled:
        return {"sent_count": 0, "reason": "notifications_disabled"}

    client = get_supabase_client()
    today = datetime.utcnow().strftime("%Y-%m-%d")
    sent_count = 0

    try:
        users = await get_all_users()

        for user_data in users:
            user_id = user_data["user_id"]

            try:
                # Get user's target calories from prefs
                prefs_result = (
                    client.table(TABLES["prefs"])
                    .select("target_daily_calories")
                    .eq("user_id", user_id)
                    .single()
                    .execute()
                )
                prefs = prefs_result.data or {}
                target_calories = prefs.get("target_daily_calories", 2000)

                # Get today's consumed meals
                plan_result = (
                    client.table(TABLES["plan"])
                    .select("*, food_item:foodos2_food_items(calories_per_100g, protein_g_per_100g, base_calories)")
                    .eq("user_id", user_id)
                    .eq("date", today)
                    .eq("consumed", True)
                    .execute()
                )
                meals = plan_result.data or []

                # Calculate totals (simplified - real calc would use actual portions)
                total_calories = 0
                total_protein = 0

                for meal in meals:
                    food = meal.get("food_item") or {}
                    # Use base_calories if available, otherwise estimate
                    cals = food.get("base_calories") or food.get("calories_per_100g", 0) * 2
                    protein = food.get("protein_g_per_100g", 0) * 2
                    total_calories += cals
                    total_protein += protein

                success = await notification_service.send_daily_summary(
                    calories_consumed=int(total_calories),
                    calories_target=target_calories,
                    protein_g=int(total_protein),
                    meals_logged=len(meals),
                )

                if success:
                    sent_count += 1

            except Exception as e:
                logger.error(f"Error sending summary for user {user_id}: {e}")

    except Exception as e:
        logger.error(f"Error in daily summaries: {e}")

    logger.info(f"Sent {sent_count} daily summaries")
    return {"sent_count": sent_count}
