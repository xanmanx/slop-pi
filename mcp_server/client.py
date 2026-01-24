"""Pi backend API client."""

from typing import Any

import httpx

from .config import config


class PiClient:
    """Client for Pi backend API."""

    def __init__(self, base_url: str | None = None, api_key: str | None = None):
        self.base_url = (base_url or config.pi_url).rstrip("/")
        self.api_key = api_key or config.api_key
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers={"X-API-Key": self.api_key},
                timeout=30.0,
            )
        return self._client

    async def close(self):
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def get(self, path: str, params: dict[str, Any] | None = None) -> dict:
        """Make GET request to Pi backend."""
        client = await self._get_client()
        response = await client.get(path, params=params)
        response.raise_for_status()
        return response.json()

    async def post(
        self, path: str, json: dict[str, Any] | None = None, params: dict[str, Any] | None = None
    ) -> dict:
        """Make POST request to Pi backend."""
        client = await self._get_client()
        response = await client.post(path, json=json, params=params)
        response.raise_for_status()
        return response.json()

    async def delete(self, path: str, params: dict[str, Any] | None = None) -> dict:
        """Make DELETE request to Pi backend."""
        client = await self._get_client()
        response = await client.delete(path, params=params)
        response.raise_for_status()
        return response.json()

    # === Meal Planning ===

    async def get_meal_plan(
        self, user_id: str, start_date: str, end_date: str | None = None
    ) -> dict:
        """Get planned meals for a date range.

        Queries Supabase directly for plan_entries.
        """
        params = {"user_id": user_id, "start_date": start_date}
        if end_date:
            params["end_date"] = end_date
        return await self.get("/api/planning/entries", params=params)

    # === Nutrition ===

    async def get_daily_nutrition(
        self,
        user_id: str,
        target_date: str,
        include_supplements: bool = True,
        include_planned: bool = True,
    ) -> dict:
        """Get comprehensive nutrition stats for a day."""
        params = {
            "target_date": target_date,
            "include_supplements": str(include_supplements).lower(),
            "include_planned": str(include_planned).lower(),
        }
        return await self.get(f"/api/nutrition/daily/{user_id}", params=params)

    async def get_nutrition_analytics(
        self, user_id: str, start_date: str, end_date: str | None = None, days: int | None = None
    ) -> dict:
        """Get nutrition analytics over a date range."""
        params = {"start_date": start_date}
        if end_date:
            params["end_date"] = end_date
        if days:
            params["days"] = str(days)
        return await self.get(f"/api/nutrition/analytics/{user_id}", params=params)

    # === Grocery ===

    async def get_grocery_list(
        self,
        user_id: str,
        start_date: str,
        end_date: str,
        include_meals: bool = True,
        subtract_inventory: bool = True,
    ) -> dict:
        """Generate grocery list for date range."""
        params = {
            "start_date": start_date,
            "end_date": end_date,
            "include_meals": str(include_meals).lower(),
            "subtract_inventory": str(subtract_inventory).lower(),
        }
        return await self.get(f"/api/grocery/list/{user_id}", params=params)

    # === Inventory / Expiration ===

    async def get_inventory(self, user_id: str, include_no_expiration: bool = True) -> list:
        """Get all inventory items with expiration info."""
        params = {
            "user_id": user_id,
            "include_no_expiration": str(include_no_expiration).lower(),
        }
        return await self.get("/api/expiration/inventory", params=params)

    async def get_expiring_soon(self, user_id: str, days: int = 7) -> dict:
        """Get items expiring within N days."""
        params = {"user_id": user_id, "days": str(days)}
        return await self.get("/api/expiration/expiring-soon", params=params)

    # === Recipe ===

    async def get_recipe_details(
        self,
        recipe_id: str,
        user_id: str,
        scale: float = 1.0,
        include_rda: bool = True,
    ) -> dict:
        """Get full recipe with flattened ingredients and nutrition."""
        params = {
            "user_id": user_id,
            "scale": str(scale),
            "include_rda": str(include_rda).lower(),
        }
        return await self.get(f"/api/recipes/flatten/{recipe_id}", params=params)

    async def compute_batch_prep(
        self,
        user_id: str,
        plan_entry_ids: list[str],
        include_batch_instructions: bool = True,
    ) -> dict:
        """Compute batch prep data for a set of plan entries."""
        return await self.post(
            "/api/batch-prep/compute",
            json={
                "user_id": user_id,
                "plan_entry_ids": plan_entry_ids,
                "include_batch_instructions": include_batch_instructions,
            },
        )

    # === USDA / Food Search ===

    async def search_usda(self, query: str, page_size: int = 25) -> dict:
        """Search USDA FoodData Central."""
        params = {"query": query, "page_size": str(page_size)}
        return await self.get("/api/usda/search", params=params)

    async def lookup_barcode(self, barcode: str) -> dict:
        """Look up product by barcode."""
        return await self.get(f"/api/barcode/{barcode}")

    # === AI ===

    async def generate_recipe(
        self, prompt: str, ai_mode: str = "lazy"
    ) -> dict:
        """Generate recipe from prompt using AI.

        Args:
            prompt: Description of recipe to generate
            ai_mode: "lazy" (quick/simple), "fancy" (gourmet), or "healthy" (nutritious)
        """
        return await self.post("/api/ai/recipe", json={"prompt": prompt, "ai_mode": ai_mode})

    async def lookup_nutrition(self, query: str, desired_kind: str = "ingredient") -> dict:
        """Look up nutrition info for a food item using AI.

        Args:
            query: Food item to look up
            desired_kind: "ingredient", "snack", or "product"
        """
        return await self.post(
            "/api/ai/lookup", json={"query": query, "desired_kind": desired_kind}
        )

    async def generate_prep_steps(
        self, name: str, ingredients: list[dict], existing_steps: list[str] | None = None
    ) -> dict:
        """Generate or improve prep steps for a recipe.

        Args:
            name: Recipe name
            ingredients: List of ingredients with name and amount
            existing_steps: Optional existing steps to improve
        """
        payload = {"name": name, "ingredients": ingredients}
        if existing_steps:
            payload["existing_steps"] = existing_steps
        return await self.post("/api/ai/prep-steps", json=payload)

    async def quick_edit_recipe(self, original_recipe: dict, edit_request: str) -> dict:
        """Make quick edits to a recipe using AI.

        Args:
            original_recipe: The original recipe dict
            edit_request: What changes to make
        """
        return await self.post(
            "/api/ai/quick-edit",
            json={"original_recipe": original_recipe, "edit_request": edit_request},
        )


# Global client instance
pi_client = PiClient()
