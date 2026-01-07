"""AI service - OpenAI integration for recipe generation and nutrition lookup."""

import json
import logging
from functools import lru_cache

from openai import AsyncOpenAI

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class AIService:
    """OpenAI-powered AI service for slop."""

    def __init__(self):
        self.client = AsyncOpenAI(api_key=settings.openai_api_key)

    async def generate_recipe(self, prompt: str, ai_mode: str | None = None) -> dict:
        """Generate a recipe from a prompt."""
        # Determine model based on complexity
        effort_score = self._calculate_effort_score(prompt)
        model = "gpt-4o" if effort_score >= 50 else "gpt-4o-mini"
        temperature = 0.6 if effort_score >= 50 else 0.5

        system_prompt = self._build_recipe_system_prompt(ai_mode)

        response = await self.client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Create a recipe for: {prompt}"},
            ],
            temperature=temperature,
            response_format={"type": "json_object"},
            timeout=60,
        )

        content = response.choices[0].message.content or "{}"
        recipe = json.loads(content)

        return {
            **recipe,
            "model_tier": "gourmet" if model == "gpt-4o" else "quick",
            "effort_score": effort_score,
        }

    async def lookup_item(self, query: str, desired_kind: str = "ingredient") -> dict:
        """Look up nutrition info for a food item."""
        system_prompt = """You are a nutrition lookup assistant with knowledge of food composition.
Return JSON only:
{
  "kind": "ingredient|snack|product",
  "name": "string (clean, standardized name)",
  "serving_g": number,
  "base_calories": number,
  "calories_per_100g": number,
  "protein_g_per_100g": number,
  "carbs_g_per_100g": number,
  "fat_g_per_100g": number,
  "fiber_g_per_100g": number (or 0),
  "sodium_mg_per_100g": number (or 0),
  "caffeine_mg_per_100g": number (or 0 if no caffeine),
  "sugar_g_per_100g": number (or 0),
  "micronutrients": [
    {"name": "nutrient name", "amount_per_100g": number, "unit": "mg|mcg|g"}
  ],
  "notes": "string with source info or caveats"
}

Rules:
- If it's a packaged item (bar, chips, yogurt cup, energy drink, canned beverage), use kind=product
- If it's a snack concept (apple + peanut butter), use kind=snack
- Otherwise use kind=ingredient
- serving_g is grams per typical serving (use mL for beverages, 1g = 1mL approx)
- base_calories is calories per serving
- per_100g fields must be mathematically consistent with base_calories and serving_g
- CAFFEINE: Include for coffee, tea, energy drinks, chocolate. Coffee ~40-80mg/100mL, energy drinks vary by brand
- MICRONUTRIENTS: Include 3-8 relevant ones (vitamins, minerals) if known
- If uncertain, be conservative and note it. Reference common nutrition databases mentally
- For branded products, use publicly available nutrition facts if you know them"""

        response = await self.client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Desired kind: {desired_kind}\nQuery: {query}"},
            ],
            temperature=0.2,
            response_format={"type": "json_object"},
        )

        content = response.choices[0].message.content or "{}"
        return json.loads(content)

    async def generate_batch_prep(
        self,
        prep_date: str,
        meals: list[dict],
        ingredients: list[dict],
    ) -> str:
        """Generate optimized batch prep instructions."""
        meals_text = "\n\n".join(
            f"{i+1}. {m['name']} ({m.get('servings', 1)} serving(s))\n"
            + (
                "\n".join(f"   {j+1}. {s}" for j, s in enumerate(m.get("steps", [])))
                if m.get("steps")
                else "   (No specific steps)"
            )
            for i, m in enumerate(meals)
        )

        ingredients_text = "\n".join(
            f"- {ing['name']}: {ing.get('totalAmount_g', 0):.0f}g total"
            for ing in ingredients
        )

        system_prompt = """You are a helpful meal prep assistant. You help people efficiently batch prep multiple meals at once.

Your job is to create an OPTIMIZED batch prep workflow that:
1. Groups similar tasks together (all chopping first, then all cooking)
2. Suggests an efficient order of operations
3. Identifies tasks that can be done in parallel
4. Provides time-saving tips
5. Notes which prep containers or storage to use

Be practical and friendly. Use clear, numbered steps. Keep it concise but thorough."""

        user_prompt = f"""I need to batch prep the following meals for {prep_date}:

MEALS TO PREP:
{meals_text}

TOTAL INGREDIENTS NEEDED:
{ingredients_text}

Please create an optimized batch prep plan with:
1. All prep tasks in efficient order
2. Similar tasks grouped together
3. Notes on parallel tasks
4. Time estimates where helpful
5. Storage tips for each item"""

        response = await self.client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.7,
            max_tokens=2000,
        )

        return response.choices[0].message.content or ""

    async def generate_prep_steps(
        self,
        name: str,
        ingredients: list[dict],
        existing_steps: list[str],
    ) -> list[str]:
        """Generate or improve prep steps for a recipe."""
        system_prompt = """You write helpful prep steps like a friend teaching you to cook.

Each step should:
- Tell you what "done" looks like ("until golden brown", "until fragrant")
- Include approximate times when helpful
- Be encouraging and clear

Return JSON: {"prep_steps": ["step1", "step2", ...]}"""

        response = await self.client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": f"Recipe: {name}\n"
                    f"Ingredients: {json.dumps(ingredients)}\n"
                    f"Existing steps to improve: {json.dumps(existing_steps)}",
                },
            ],
            temperature=0.4,
            response_format={"type": "json_object"},
        )

        content = response.choices[0].message.content or '{"prep_steps": []}'
        result = json.loads(content)
        return result.get("prep_steps", [])

    async def quick_edit(self, original_recipe: dict, edit_request: str) -> dict:
        """Make quick edits to an existing recipe."""
        system_prompt = """You help tweak recipes. Make the requested changes while keeping everything else the same.

Return the FULL updated recipe in the same JSON format.

Be minimal - only change what's asked. If they say "more garlic", just increase the garlic amount. Don't rewrite the whole thing."""

        response = await self.client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": f"Current recipe:\n{json.dumps(original_recipe, indent=2)}\n\n"
                    f"Change requested: {edit_request}",
                },
            ],
            temperature=0.3,
            response_format={"type": "json_object"},
        )

        content = response.choices[0].message.content or "{}"
        return json.loads(content)

    def _calculate_effort_score(self, prompt: str) -> int:
        """Calculate effort score to determine model selection."""
        words = prompt.strip().split()
        score = 0

        score += min(30, len(words) * 2)
        score += min(20, len(prompt) // 10)

        if any(
            kw in prompt.lower()
            for kw in ["specific", "exactly", "must have", "include", "minutes", "grams"]
        ):
            score += 20

        if any(
            kw in prompt.lower()
            for kw in ["sear", "braise", "roast", "sauté", "caramelize", "deglaze"]
        ):
            score += 15

        if any(
            kw in prompt.lower()
            for kw in [
                "italian",
                "mexican",
                "thai",
                "japanese",
                "french",
                "indian",
                "mediterranean",
            ]
        ):
            score += 15

        return score

    def _build_recipe_system_prompt(self, ai_mode: str | None = None) -> str:
        """Build the system prompt for recipe generation."""
        mode_section = ""
        if ai_mode == "lazy":
            mode_section = """
LAZY MODE ACTIVE:
- Minimize prep work and active cooking time
- Prefer one-pot/one-pan meals
- Use pre-cut, frozen, or canned ingredients where sensible
- Keep ingredient count low (5-8 max)
"""
        elif ai_mode == "fancy":
            mode_section = """
FANCY MODE ACTIVE:
- Restaurant-quality presentation matters
- Use proper techniques (don't skip steps)
- Include finishing touches (garnish, sauce drizzles)
- Elevate simple ingredients with technique
"""
        elif ai_mode == "healthy":
            mode_section = """
HEALTHY MODE ACTIVE:
- Prioritize nutrient density
- Limit added fats and sugars
- Include vegetables prominently
- Use whole grains over refined
- Keep sodium reasonable
"""

        return f"""You're writing a recipe like it's for your favorite cookbook - warm, helpful, makes people excited to cook.
{mode_section}

Return JSON with this structure:
{{
  "name": "Recipe Name",
  "kind": "meal",
  "description": "Brief enticing description",
  "ingredients": [
    {{"name": "ingredient name", "amount_g": 100, "calories_per_100g": 200, "protein_g_per_100g": 10, "carbs_g_per_100g": 20, "fat_g_per_100g": 5}}
  ],
  "prep_steps": ["Step 1...", "Step 2..."],
  "prep_time_minutes": 15,
  "cook_time_minutes": 30,
  "cook_notes": "Any helpful tips"
}}

Use simple, generic ingredient names (e.g., "ground beef" not "80/20 ground beef").
Each prep step should tell what "done" looks like."""


@lru_cache
def get_ai_service() -> AIService:
    """Get cached AI service instance."""
    return AIService()
