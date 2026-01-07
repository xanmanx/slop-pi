"""
Process scheduled meal and supplement consumptions.

This job runs frequently (every 2 minutes by default) to ensure
meals and supplements are marked as consumed as soon as their
scheduled time passes.

Key features:
1. Timezone-aware - uses configured timezone for accurate time comparisons
2. Uses atomic database function - ensures data consistency
3. Handles both meals and supplements
4. Idempotent - safe to run multiple times
"""

import logging
from datetime import datetime, time as dt_time
from zoneinfo import ZoneInfo

from app.services.supabase import (
    get_supabase_client,
    TABLES,
    get_all_users,
    get_user_prefs,
)
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# Default meal times by slot (used when scheduled_time is not set)
DEFAULT_SLOT_TIMES = {
    "breakfast": "08:00:00",
    "lunch": "12:00:00",
    "dinner": "18:00:00",
    "snack": "15:00:00",
}


def get_local_now() -> datetime:
    """Get current time in the configured timezone."""
    tz = ZoneInfo(settings.timezone)
    return datetime.now(tz)


def parse_time(time_str: str) -> tuple[int, int]:
    """Parse HH:MM or HH:MM:SS string to (hour, minute) tuple."""
    parts = time_str.split(":")
    return int(parts[0]), int(parts[1]) if len(parts) > 1 else 0


def has_time_passed(scheduled_time: str, now: datetime) -> bool:
    """
    Check if a scheduled time has passed.

    Args:
        scheduled_time: Time in HH:MM or HH:MM:SS format
        now: Current datetime (timezone-aware)

    Returns:
        True if scheduled time has passed
    """
    try:
        hour, minute = parse_time(scheduled_time)
        scheduled_dt = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        return now >= scheduled_dt
    except (ValueError, IndexError):
        logger.warning(f"Invalid time format: {scheduled_time}")
        return False


async def consume_meal_atomic(
    client,
    plan_entry_id: str,
    user_id: str,
    consumption_type: str = "meal_time_passed"
) -> dict:
    """
    Call the atomic consumption database function.

    This function handles everything in a single transaction:
    - Recipe flattening (for meals with ingredients)
    - Consumption record creation
    - Inventory updates
    """
    try:
        result = client.rpc(
            "consume_meal_atomic",
            {
                "p_plan_entry_id": plan_entry_id,
                "p_user_id": user_id,
                "p_consumption_type": consumption_type,
            }
        ).execute()

        if result.data:
            return result.data
        return {"success": False, "error": "No response from database function"}
    except Exception as e:
        logger.error(f"Error calling consume_meal_atomic: {e}")
        return {"success": False, "error": str(e)}


async def process_scheduled_consumptions() -> dict:
    """
    Process all scheduled meal consumptions for all users.

    This is the main consumption job that runs every few minutes.
    It finds meals whose scheduled time has passed and marks them as consumed
    using the atomic database function.

    Returns:
        Dict with processed_count, skipped_count, and any errors
    """
    logger.info(f"Starting consumption processing (timezone: {settings.timezone})...")

    client = get_supabase_client()
    now = get_local_now()
    today_str = now.strftime("%Y-%m-%d")
    current_time_str = now.strftime("%H:%M:%S")

    logger.info(f"Processing for date: {today_str}, time: {current_time_str}")

    processed = []
    skipped = []
    errors = []

    try:
        # Get all users with preference profiles
        users = await get_all_users()
        logger.debug(f"Found {len(users)} users to process")

        for user_data in users:
            user_id = user_data.get("user_id")
            if not user_id:
                continue

            try:
                # Get user preferences
                prefs = await get_user_prefs(user_id)
                if not prefs:
                    logger.debug(f"No preferences for user {user_id[:8]}...")
                    continue

                # Check if auto-consume is enabled (default True)
                auto_consume = prefs.get("auto_consume_meals", True)
                if not auto_consume:
                    logger.debug(f"Auto-consume disabled for user {user_id[:8]}...")
                    continue

                # Get plan entries for today that are not batch-prepped
                # We don't filter by is_logged here - the atomic function handles idempotency
                result = (
                    client.table(TABLES["plan"])
                    .select("id, planned_date, slot, scheduled_time, is_batch_prepped, batch_prep_date")
                    .eq("user_id", user_id)
                    .eq("planned_date", today_str)
                    .or_("is_batch_prepped.is.null,is_batch_prepped.eq.false")
                    .execute()
                )

                entries = result.data or []
                logger.debug(f"User {user_id[:8]}... has {len(entries)} entries for today")

                for entry in entries:
                    entry_id = entry.get("id")
                    slot = entry.get("slot", "")

                    # Get scheduled time (use default if not set)
                    scheduled_time = entry.get("scheduled_time")
                    if not scheduled_time:
                        scheduled_time = DEFAULT_SLOT_TIMES.get(slot, "12:00:00")

                    # Check if time has passed
                    if not has_time_passed(scheduled_time, now):
                        logger.debug(f"Entry {entry_id[:8]}... ({slot}) not yet due: {scheduled_time}")
                        skipped.append({
                            "entry_id": entry_id,
                            "reason": "time_not_passed",
                            "scheduled_time": scheduled_time,
                        })
                        continue

                    # Consume using atomic function
                    logger.info(f"Consuming entry {entry_id[:8]}... ({slot}) scheduled for {scheduled_time}")
                    consume_result = await consume_meal_atomic(
                        client, entry_id, user_id, "meal_time_passed"
                    )

                    if consume_result.get("success"):
                        processed.append({
                            "entry_id": entry_id,
                            "user_id": user_id,
                            "slot": slot,
                            "scheduled_time": scheduled_time,
                        })
                        logger.info(f"Successfully consumed entry {entry_id[:8]}...")
                    elif consume_result.get("already_consumed"):
                        skipped.append({
                            "entry_id": entry_id,
                            "reason": "already_consumed",
                        })
                        logger.debug(f"Entry {entry_id[:8]}... already consumed")
                    else:
                        error_msg = consume_result.get("error", "Unknown error")
                        errors.append({
                            "entry_id": entry_id,
                            "error": error_msg,
                        })
                        logger.error(f"Failed to consume entry {entry_id[:8]}...: {error_msg}")

            except Exception as e:
                logger.error(f"Error processing user {user_id[:8]}...: {e}")
                errors.append({"user_id": user_id, "error": str(e)})

    except Exception as e:
        logger.error(f"Error in consumption processing: {e}")
        errors.append({"error": str(e)})

    summary = {
        "processed_count": len(processed),
        "skipped_count": len(skipped),
        "error_count": len(errors),
        "processed_entries": processed,
        "errors": errors if errors else None,
        "timezone": settings.timezone,
        "processed_at": now.isoformat(),
    }

    logger.info(
        f"Consumption processing complete: "
        f"{len(processed)} consumed, {len(skipped)} skipped, {len(errors)} errors"
    )

    return summary


async def process_scheduled_supplements() -> dict:
    """
    Process all scheduled supplement consumptions for all users.

    Similar to meal consumption, but for daily supplements.
    Supplements have a time_of_day field instead of scheduled_time.
    """
    logger.info(f"Starting supplement processing (timezone: {settings.timezone})...")

    client = get_supabase_client()
    now = get_local_now()
    today_str = now.strftime("%Y-%m-%d")

    processed = []
    skipped = []
    errors = []

    try:
        # Get all users
        users = await get_all_users()

        for user_data in users:
            user_id = user_data.get("user_id")
            if not user_id:
                continue

            try:
                # Get active supplements for this user
                result = (
                    client.table(TABLES["supplements"])
                    .select("id, food_item_id, time_of_day, frequency, amount_g, serving_count")
                    .eq("user_id", user_id)
                    .eq("is_active", True)
                    .execute()
                )

                supplements = result.data or []

                for supp in supplements:
                    supp_id = supp.get("id")
                    time_of_day = supp.get("time_of_day")

                    if not time_of_day:
                        continue

                    # Check if time has passed
                    if not has_time_passed(time_of_day, now):
                        skipped.append({
                            "supplement_id": supp_id,
                            "reason": "time_not_passed",
                        })
                        continue

                    # Check if already consumed today
                    consumption_check = (
                        client.table(TABLES["consumption"])
                        .select("id")
                        .eq("user_id", user_id)
                        .eq("supplement_schedule_id", supp_id)
                        .eq("supplement_scheduled_date", today_str)
                        .limit(1)
                        .execute()
                    )

                    if consumption_check.data:
                        skipped.append({
                            "supplement_id": supp_id,
                            "reason": "already_consumed",
                        })
                        continue

                    # Create consumption record for supplement
                    food_item_id = supp.get("food_item_id")
                    amount_g = supp.get("amount_g", 100)
                    serving_count = supp.get("serving_count", 1)
                    total_amount = amount_g * serving_count

                    try:
                        # Insert consumption record
                        insert_result = (
                            client.table(TABLES["consumption"])
                            .insert({
                                "user_id": user_id,
                                "food_item_id": food_item_id,
                                "quantity_consumed_g": max(0.01, total_amount),
                                "consumption_type": "supplement_scheduled_time_passed",
                                "supplement_schedule_id": supp_id,
                                "supplement_scheduled_date": today_str,
                                "consumed_at": now.isoformat(),
                            })
                            .execute()
                        )

                        if insert_result.data:
                            processed.append({
                                "supplement_id": supp_id,
                                "user_id": user_id,
                                "food_item_id": food_item_id,
                            })
                            logger.info(f"Consumed supplement {supp_id[:8]}...")

                            # Update inventory
                            # First get current inventory
                            inv_result = (
                                client.table(TABLES["inventory"])
                                .select("id, quantity_g")
                                .eq("user_id", user_id)
                                .eq("food_item_id", food_item_id)
                                .single()
                                .execute()
                            )

                            if inv_result.data:
                                current_qty = inv_result.data.get("quantity_g", 0)
                                new_qty = max(0, current_qty - total_amount)
                                client.table(TABLES["inventory"]).update({
                                    "quantity_g": new_qty
                                }).eq("id", inv_result.data["id"]).execute()

                    except Exception as e:
                        errors.append({
                            "supplement_id": supp_id,
                            "error": str(e),
                        })
                        logger.error(f"Failed to consume supplement {supp_id[:8]}...: {e}")

            except Exception as e:
                logger.error(f"Error processing supplements for user {user_id[:8]}...: {e}")
                errors.append({"user_id": user_id, "error": str(e)})

    except Exception as e:
        logger.error(f"Error in supplement processing: {e}")
        errors.append({"error": str(e)})

    summary = {
        "processed_count": len(processed),
        "skipped_count": len(skipped),
        "error_count": len(errors),
        "processed_entries": processed,
        "errors": errors if errors else None,
        "timezone": settings.timezone,
        "processed_at": now.isoformat(),
    }

    logger.info(
        f"Supplement processing complete: "
        f"{len(processed)} consumed, {len(skipped)} skipped, {len(errors)} errors"
    )

    return summary


async def process_all_consumptions() -> dict:
    """
    Process both meals and supplements.

    This is the main entry point called by the scheduler.
    """
    logger.info("=" * 60)
    logger.info("STARTING CONSUMPTION PROCESSING CYCLE")
    logger.info("=" * 60)

    meal_result = await process_scheduled_consumptions()
    supplement_result = await process_scheduled_supplements()

    total_processed = (
        meal_result.get("processed_count", 0) +
        supplement_result.get("processed_count", 0)
    )
    total_errors = (
        meal_result.get("error_count", 0) +
        supplement_result.get("error_count", 0)
    )

    logger.info(
        f"CONSUMPTION CYCLE COMPLETE: {total_processed} total consumed, {total_errors} errors"
    )
    logger.info("=" * 60)

    return {
        "meals": meal_result,
        "supplements": supplement_result,
        "total_processed": total_processed,
        "total_errors": total_errors,
    }
