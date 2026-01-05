"""Notification service using ntfy.sh for push notifications."""

import logging

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class NotificationService:
    """Push notification service via ntfy.sh."""

    def __init__(self):
        self.server = settings.ntfy_server
        self.topic = settings.ntfy_topic
        self.enabled = bool(self.topic)

    async def send(
        self,
        message: str,
        title: str | None = None,
        priority: int = 3,  # 1=min, 3=default, 5=urgent
        tags: list[str] | None = None,
        click_url: str | None = None,
    ) -> bool:
        """
        Send a push notification via ntfy.

        Priority levels:
        - 1: min (no sound)
        - 2: low
        - 3: default
        - 4: high
        - 5: urgent (persistent, loud)
        """
        if not self.enabled:
            logger.warning("Notifications disabled (no NTFY_TOPIC configured)")
            return False

        headers = {
            "Priority": str(priority),
        }

        if title:
            headers["Title"] = title

        if tags:
            headers["Tags"] = ",".join(tags)

        if click_url:
            headers["Click"] = click_url

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.server}/{self.topic}",
                    content=message,
                    headers=headers,
                    timeout=10,
                )
                response.raise_for_status()
                logger.info(f"Notification sent: {title or message[:50]}")
                return True
        except Exception as e:
            logger.error(f"Failed to send notification: {e}")
            return False

    async def send_meal_reminder(
        self,
        meal_name: str,
        slot: str,
        minutes_until: int = 30,
    ) -> bool:
        """Send a meal reminder notification."""
        slot_emoji = {
            "breakfast": "sunrise",
            "lunch": "sun",
            "dinner": "moon",
            "snack": "cookie",
        }

        return await self.send(
            message=f"{meal_name} in {minutes_until} minutes",
            title=f"Time for {slot}!",
            priority=3,
            tags=[slot_emoji.get(slot, "fork_and_knife"), "slop"],
            click_url="http://slop.local:3000/slop/plan",
        )

    async def send_daily_summary(
        self,
        calories_consumed: int,
        calories_target: int,
        protein_g: int,
        meals_logged: int,
    ) -> bool:
        """Send end-of-day nutrition summary."""
        pct = round(calories_consumed / calories_target * 100) if calories_target else 0

        if pct >= 90 and pct <= 110:
            emoji = "white_check_mark"
            verdict = "Right on target!"
        elif pct < 90:
            emoji = "arrow_down"
            verdict = f"{calories_target - calories_consumed} cal under"
        else:
            emoji = "arrow_up"
            verdict = f"{calories_consumed - calories_target} cal over"

        return await self.send(
            message=f"{calories_consumed} / {calories_target} kcal ({pct}%)\n"
            f"Protein: {protein_g}g\n"
            f"Meals logged: {meals_logged}\n"
            f"{verdict}",
            title="Daily Nutrition Summary",
            priority=2,
            tags=[emoji, "chart_with_upwards_trend"],
        )

    async def send_grocery_reminder(self, items_count: int) -> bool:
        """Remind about upcoming grocery shopping."""
        return await self.send(
            message=f"You have {items_count} items on your grocery list",
            title="Grocery Shopping Day",
            priority=3,
            tags=["shopping_cart", "slop"],
            click_url="http://slop.local:3000/slop/grocery",
        )

    async def send_prep_reminder(self, meals_to_prep: int, prep_date: str) -> bool:
        """Remind about meal prep day."""
        return await self.send(
            message=f"{meals_to_prep} meals to prep for the week",
            title="Meal Prep Day",
            priority=4,
            tags=["cook", "slop"],
            click_url="http://slop.local:3000/slop/prepare",
        )


# Singleton instance
_notification_service: NotificationService | None = None


def get_notification_service() -> NotificationService:
    """Get notification service singleton."""
    global _notification_service
    if _notification_service is None:
        _notification_service = NotificationService()
    return _notification_service
