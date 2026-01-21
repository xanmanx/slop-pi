"""
API Token management endpoints.

Allows users to generate, view, and revoke their API tokens
for Claude/AI assistant access.
"""

import secrets
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from app.services.supabase import get_supabase_client as get_supabase
from app.api.deps import get_current_user_id

router = APIRouter(prefix="/api/tokens", tags=["tokens"])


# =============================================================================
# Models
# =============================================================================

class TokenResponse(BaseModel):
    """API token response."""
    id: str
    token: str
    name: str
    created_at: str
    last_used_at: Optional[str] = None
    is_active: bool


class TokenCreateRequest(BaseModel):
    """Request to create a new token."""
    name: str = "Claude API Token"


class TokenUpdateRequest(BaseModel):
    """Request to update token."""
    name: Optional[str] = None
    is_active: Optional[bool] = None


class AIInstructionsResponse(BaseModel):
    """AI instructions for the user."""
    markdown: str
    plain_text: str
    api_base_url: str
    token: str


# =============================================================================
# Helper functions
# =============================================================================

def generate_token() -> str:
    """Generate a secure, URL-safe API token."""
    # slop_ prefix + 32 random URL-safe characters
    random_part = secrets.token_urlsafe(24)
    return f"slop_{random_part}"


# =============================================================================
# Endpoints
# =============================================================================

@router.get("/me", response_model=Optional[TokenResponse])
async def get_my_token(user_id: str = Depends(get_current_user_id)):
    """Get the current user's active API token, if any."""
    supabase = get_supabase()

    result = (
        supabase.table("foodos2_api_tokens")
        .select("id, token, name, created_at, last_used_at, is_active")
        .eq("user_id", user_id)
        .eq("is_active", True)
        .limit(1)
        .execute()
    )

    if not result.data:
        return None

    data = result.data[0]
    return TokenResponse(
        id=data["id"],
        token=data["token"],
        name=data["name"],
        created_at=data["created_at"],
        last_used_at=data.get("last_used_at"),
        is_active=data["is_active"],
    )


@router.post("/generate", response_model=TokenResponse)
async def generate_new_token(
    request: TokenCreateRequest = TokenCreateRequest(),
    user_id: str = Depends(get_current_user_id),
):
    """
    Generate a new API token.
    Deactivates any existing tokens for this user.
    """
    supabase = get_supabase()

    # Deactivate existing tokens
    supabase.table("foodos2_api_tokens").update({
        "is_active": False
    }).eq("user_id", user_id).eq("is_active", True).execute()

    # Generate new token
    new_token = generate_token()

    result = supabase.table("foodos2_api_tokens").insert({
        "user_id": user_id,
        "token": new_token,
        "name": request.name,
        "is_active": True,
    }).execute()

    data = result.data[0]
    return TokenResponse(
        id=data["id"],
        token=data["token"],
        name=data["name"],
        created_at=data["created_at"],
        last_used_at=data.get("last_used_at"),
        is_active=data["is_active"],
    )


@router.post("/regenerate", response_model=TokenResponse)
async def regenerate_token(user_id: str = Depends(get_current_user_id)):
    """
    Regenerate the API token.
    This invalidates the old token immediately.
    """
    supabase = get_supabase()

    # Check if user has an active token
    existing = (
        supabase.table("foodos2_api_tokens")
        .select("id, name")
        .eq("user_id", user_id)
        .eq("is_active", True)
        .limit(1)
        .execute()
    )

    token_name = "Claude API Token"
    if existing.data:
        token_name = existing.data[0].get("name", token_name)

        # Deactivate old token
        supabase.table("foodos2_api_tokens").update({
            "is_active": False
        }).eq("id", existing.data[0]["id"]).execute()

    # Generate new token
    new_token = generate_token()

    result = supabase.table("foodos2_api_tokens").insert({
        "user_id": user_id,
        "token": new_token,
        "name": token_name,
        "is_active": True,
    }).execute()

    data = result.data[0]
    return TokenResponse(
        id=data["id"],
        token=data["token"],
        name=data["name"],
        created_at=data["created_at"],
        last_used_at=data.get("last_used_at"),
        is_active=data["is_active"],
    )


@router.delete("/revoke")
async def revoke_token(user_id: str = Depends(get_current_user_id)):
    """Revoke (deactivate) the current API token."""
    supabase = get_supabase()

    result = supabase.table("foodos2_api_tokens").update({
        "is_active": False
    }).eq("user_id", user_id).eq("is_active", True).execute()

    if not result.data:
        raise HTTPException(status_code=404, detail="No active token found")

    return {"message": "Token revoked successfully"}


@router.patch("/update", response_model=TokenResponse)
async def update_token(
    request: TokenUpdateRequest,
    user_id: str = Depends(get_current_user_id),
):
    """Update token name or status."""
    supabase = get_supabase()

    existing = (
        supabase.table("foodos2_api_tokens")
        .select("id")
        .eq("user_id", user_id)
        .eq("is_active", True)
        .limit(1)
        .execute()
    )

    if not existing.data:
        raise HTTPException(status_code=404, detail="No active token found")

    update_data = {}
    if request.name is not None:
        update_data["name"] = request.name
    if request.is_active is not None:
        update_data["is_active"] = request.is_active

    if not update_data:
        raise HTTPException(status_code=400, detail="No updates provided")

    result = supabase.table("foodos2_api_tokens").update(update_data).eq(
        "id", existing.data[0]["id"]
    ).execute()

    data = result.data[0]
    return TokenResponse(
        id=data["id"],
        token=data["token"],
        name=data["name"],
        created_at=data["created_at"],
        last_used_at=data.get("last_used_at"),
        is_active=data["is_active"],
    )


@router.get("/instructions", response_model=AIInstructionsResponse)
async def get_ai_instructions(user_id: str = Depends(get_current_user_id)):
    """
    Get AI-ready instructions with the user's token.
    Returns both markdown and plain text versions.
    """
    supabase = get_supabase()

    # Get user's active token
    result = (
        supabase.table("foodos2_api_tokens")
        .select("token")
        .eq("user_id", user_id)
        .eq("is_active", True)
        .limit(1)
        .execute()
    )

    if not result.data:
        raise HTTPException(
            status_code=404,
            detail="No active token. Generate one first."
        )

    token = result.data[0]["token"]
    api_base = "https://api.slxp.app"

    markdown = f"""# Slop - Meal Planning API Access

You have access to my meal planning app via the following API. Use these endpoints to help me manage meals, inventory, and nutrition.

## Base URL
`{api_base}/claude/{token}`

## Quick Commands

### View Today's Summary
```
GET {api_base}/claude/{token}/today
```

### View Meal Plan
```
GET {api_base}/claude/{token}/meals?days=7
```

### View Inventory
```
GET {api_base}/claude/{token}/inventory
```

### Add to Inventory
```
GET {api_base}/claude/{token}/add?item=ground+beef&qty=454&storage=refrigerator
```
- qty is in grams (454g = 1lb)
- storage: refrigerator, freezer, or pantry

### Use from Inventory
```
GET {api_base}/claude/{token}/use?item=ground+beef&qty=200
```

### Check Expiring Items
```
GET {api_base}/claude/{token}/expiring?days=3
```

### Get Grocery List
```
GET {api_base}/claude/{token}/grocery?days=7
```

### Mark Groceries as Bought
```
GET {api_base}/claude/{token}/bought?days=7
```
(Adds all items from grocery list to inventory)

### Add Meal to Plan
```
GET {api_base}/claude/{token}/plan?meal=chicken+stir+fry&slot=dinner&day=2024-01-21
```
- slot: breakfast, lunch, dinner, or snack

### Search Recipes
```
GET {api_base}/claude/{token}/recipes?q=chicken
```

### Get Recipe Details
```
GET {api_base}/claude/{token}/recipe?name=chicken+stir+fry
```

### Create Recipe with AI
```
GET {api_base}/claude/{token}/create?prompt=high+protein+chicken+stir+fry&mode=healthy
```
- mode: lazy (quick/easy), fancy (restaurant-quality), healthy (nutrient-dense)

### View Nutrition Details
```
GET {api_base}/claude/{token}/nutrition?day=2024-01-20
```

## Tips
- All quantities are in grams (454g = 1lb, 28g = 1oz)
- Dates use YYYY-MM-DD format
- URL encode spaces as + or %20
- Responses are plain text for easy reading

## API Documentation
```
GET {api_base}/claude/{token}
```
(Returns full API documentation)
"""

    plain_text = f"""SLOP MEAL PLANNING API

Base URL: {api_base}/claude/{token}

COMMANDS:

Today's Summary: {api_base}/claude/{token}/today
Meal Plan (7 days): {api_base}/claude/{token}/meals?days=7
Inventory: {api_base}/claude/{token}/inventory
Add to Inventory: {api_base}/claude/{token}/add?item=NAME&qty=GRAMS&storage=refrigerator
Use from Inventory: {api_base}/claude/{token}/use?item=NAME&qty=GRAMS
Expiring Soon: {api_base}/claude/{token}/expiring?days=3
Grocery List: {api_base}/claude/{token}/grocery?days=7
Mark Bought: {api_base}/claude/{token}/bought?days=7
Add to Plan: {api_base}/claude/{token}/plan?meal=NAME&slot=dinner&day=YYYY-MM-DD
Search Recipes: {api_base}/claude/{token}/recipes?q=QUERY
Recipe Details: {api_base}/claude/{token}/recipe?name=NAME
Create Recipe: {api_base}/claude/{token}/create?prompt=DESCRIPTION&mode=healthy
Nutrition: {api_base}/claude/{token}/nutrition?day=YYYY-MM-DD

NOTES:
- Quantities in grams (454g = 1lb)
- Dates: YYYY-MM-DD
- Encode spaces as + in URLs
- Full docs: {api_base}/claude/{token}
"""

    return AIInstructionsResponse(
        markdown=markdown,
        plain_text=plain_text,
        api_base_url=api_base,
        token=token,
    )
