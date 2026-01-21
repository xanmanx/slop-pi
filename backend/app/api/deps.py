"""
Common dependencies for API endpoints.
"""

from fastapi import Query, HTTPException


async def get_current_user_id(user_id: str = Query(..., description="User ID")) -> str:
    """
    Extract user_id from query parameter.

    In this architecture, the frontend authenticates via Supabase
    and passes the authenticated user_id directly to API calls.
    """
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id is required")
    return user_id
