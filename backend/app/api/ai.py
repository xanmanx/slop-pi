"""AI endpoints - recipe generation, nutrition lookup, batch prep."""

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from app.services.ai import AIService, get_ai_service

router = APIRouter()


# ============================================================================
# Request/Response Models
# ============================================================================

class RecipeRequest(BaseModel):
    """Request to generate a recipe."""
    prompt: str
    ai_mode: str | None = None  # e.g., "lazy", "fancy", "healthy"


class RecipeResponse(BaseModel):
    """Generated recipe response."""
    name: str
    kind: str  # meal, snack
    description: str
    ingredients: list[dict]
    prep_steps: list[str]
    prep_time_minutes: int
    cook_time_minutes: int
    cook_notes: str
    oven_temp_f: int | None = None
    yield_amount: str | None = None
    model_tier: str
    effort_score: int


class LookupRequest(BaseModel):
    """Request to look up nutrition info."""
    query: str
    desired_kind: str = "ingredient"  # ingredient, snack, product


class LookupResponse(BaseModel):
    """Nutrition lookup response."""
    kind: str
    name: str
    serving_g: float
    base_calories: float
    calories_per_100g: float
    protein_g_per_100g: float
    carbs_g_per_100g: float
    fat_g_per_100g: float
    notes: str


class BatchPrepRequest(BaseModel):
    """Request for batch prep instructions."""
    prep_date: str
    meals: list[dict]  # {name, servings, steps}
    ingredients: list[dict]  # {name, totalAmount_g, perServing_g}


class PrepStepsRequest(BaseModel):
    """Request to generate prep steps."""
    name: str
    ingredients: list[dict]
    existing_steps: list[str] = []


class QuickEditRequest(BaseModel):
    """Request to edit an existing recipe."""
    original_recipe: dict
    edit_request: str


# ============================================================================
# Endpoints
# ============================================================================

@router.post("/recipe", response_model=RecipeResponse)
async def generate_recipe(
    body: RecipeRequest,
    ai: AIService = Depends(get_ai_service),
):
    """Generate a recipe from a prompt."""
    if not body.prompt.strip():
        raise HTTPException(status_code=400, detail="Missing prompt")

    try:
        result = await ai.generate_recipe(body.prompt, body.ai_mode)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/lookup", response_model=LookupResponse)
async def lookup_nutrition(
    body: LookupRequest,
    ai: AIService = Depends(get_ai_service),
):
    """Look up nutrition info for a food item."""
    if not body.query.strip():
        raise HTTPException(status_code=400, detail="Missing query")

    try:
        result = await ai.lookup_item(body.query, body.desired_kind)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/batch-prep")
async def generate_batch_prep(
    body: BatchPrepRequest,
    ai: AIService = Depends(get_ai_service),
):
    """Generate optimized batch prep instructions."""
    if not body.meals:
        raise HTTPException(status_code=400, detail="No meals provided")

    try:
        instructions = await ai.generate_batch_prep(
            prep_date=body.prep_date,
            meals=body.meals,
            ingredients=body.ingredients,
        )
        return {
            "ok": True,
            "instructions": instructions,
            "prep_date": body.prep_date,
            "meal_count": len(body.meals),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/prep-steps")
async def generate_prep_steps(
    body: PrepStepsRequest,
    ai: AIService = Depends(get_ai_service),
):
    """Generate or improve prep steps for a recipe."""
    try:
        steps = await ai.generate_prep_steps(
            name=body.name,
            ingredients=body.ingredients,
            existing_steps=body.existing_steps,
        )
        return {"ok": True, "prep_steps": steps}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/quick-edit")
async def quick_edit_recipe(
    body: QuickEditRequest,
    ai: AIService = Depends(get_ai_service),
):
    """Make quick edits to an existing recipe."""
    try:
        result = await ai.quick_edit(body.original_recipe, body.edit_request)
        return {"ok": True, "recipe": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
