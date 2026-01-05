"""
Process scheduled meal consumptions.

This job:
1. Finds all plan entries that should have been consumed by now
2. Marks them as consumed (if auto-consume is enabled for the user)
3. Updates inventory accordingly
"""

import logging
from datetime import datetime, timedelta

from app.services.supabase import (
    get_supabase_client,
    TABLES,
    get_all_users,
    get_user_prefs,
)

logger = logging.getLogger(__name__)


async def process_scheduled_consumptions() -> dict:
    """
    Process all scheduled meal consumptions.

    Returns dict with processed_count and any errors.
    """
    logger.info("Starting consumption processing...")

    client = get_supabase_client()
    now = datetime.utcnow()
    today = now.strftime("%Y-%m-%d")
    current_time = now.strftime("%H:%M")

    processed = []
    errors = []

    try:
        # Get all users
        users = await get_all_users()

        for user_data in users:
            user_id = user_data["user_id"]

            try:
                # Get user preferences
                prefs = await get_user_prefs(user_id)
                if not prefs:
                    continue

                # Check if auto-consume is enabled
                auto_consume = prefs.get("auto_consume_meals", True)
                if not auto_consume:
                    continue

                # Get plan entries for today that haven't been consumed yet
                result = (
                    client.table(TABLES["plan"])
                    .select("id, date, slot, default_time, consumed")
                    .eq("user_id", user_id)
                    .eq("date", today)
                    .eq("consumed", False)
                    .execute()
                )

                entries = result.data or []

                for entry in entries:
                    # Check if the scheduled time has passed
                    entry_time = entry.get("default_time", "")
                    if not entry_time:
                        # Use default times by slot
                        slot_times = {
                            "breakfast": "08:00",
                            "lunch": "12:00",
                            "dinner": "18:00",
                            "snack": "15:00",
                        }
                        entry_time = slot_times.get(entry.get("slot", ""), "12:00")

                    # If current time is past the scheduled time, mark as consumed
                    if current_time >= entry_time:
                        update_result = (
                            client.table(TABLES["plan"])
                            .update({
                                "consumed": True,
                                "consumed_at": now.isoformat(),
                            })
                            .eq("id", entry["id"])
                            .execute()
                        )

                        if update_result.data:
                            processed.append({
                                "entry_id": entry["id"],
                                "user_id": user_id,
                                "slot": entry.get("slot"),
                            })
                            logger.debug(f"Marked entry {entry['id']} as consumed")

            except Exception as e:
                logger.error(f"Error processing user {user_id}: {e}")
                errors.append({"user_id": user_id, "error": str(e)})

    except Exception as e:
        logger.error(f"Error in consumption processing: {e}")
        errors.append({"error": str(e)})

    logger.info(f"Consumption processing complete: {len(processed)} processed, {len(errors)} errors")

    return {
        "processed_count": len(processed),
        "processed_entries": processed,
        "errors": errors,
    }
