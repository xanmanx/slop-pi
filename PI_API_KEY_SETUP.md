# Pi Task: Add API Key Authentication

## Overview

Protect the API with a shared secret key. Only requests with valid `X-API-Key` header will be allowed.

## 1. Generate API Key

Run this and save the output:
```bash
openssl rand -base64 32
```

Example output: `K7xR2mN9pQ4sT6vW8yB3cF5hJ0kL1nO7`

## 2. Add to Pi Environment

Add to `/home/xanmanx/slop-pi/.env`:
```
PI_API_KEY=<your-generated-key>
```

If using Docker, also add to `docker-compose.yml` environment section.

## 3. Update config.py

Edit `/home/xanmanx/slop-pi/backend/app/config.py`:

Add this field to the `Settings` class:
```python
# API Security
pi_api_key: str | None = None
```

## 4. Add Middleware to main.py

Edit `/home/xanmanx/slop-pi/backend/app/main.py`:

Add after the CORS middleware (around line 70):

```python
from fastapi import Request, HTTPException

@app.middleware("http")
async def verify_api_key(request: Request, call_next):
    """Verify API key for protected endpoints."""
    # Allow these paths without auth
    public_paths = ["/", "/health", "/health/detailed", "/docs", "/openapi.json", "/redoc"]

    if request.url.path in public_paths:
        return await call_next(request)

    # Check API key
    api_key = request.headers.get("X-API-Key")
    expected_key = settings.pi_api_key

    # If no key configured, allow all (dev mode)
    if not expected_key:
        logger.warning("PI_API_KEY not set - API is unprotected!")
        return await call_next(request)

    if api_key != expected_key:
        logger.warning(f"Invalid API key attempt from {request.client.host}")
        raise HTTPException(status_code=401, detail="Invalid or missing API key")

    return await call_next(request)
```

## 5. Restart the API

```bash
# If using Docker
cd /home/xanmanx/slop-pi
docker compose restart slop-api

# Or if running directly
sudo systemctl restart slop-api
```

## 6. Test

```bash
# Without key - should fail
curl https://api.slxp.app/api/usda/search?q=apple
# Returns: {"detail":"Invalid or missing API key"}

# With key - should work
curl -H "X-API-Key: <your-key>" https://api.slxp.app/api/usda/search?q=apple
# Returns: USDA data

# Health endpoint - always works (no key needed)
curl https://api.slxp.app/health
# Returns: {"status":"healthy",...}
```

## 7. Share the Key

Send the API key to Mac Claude (me) so I can add it to the xProj environment.

The Mac side will use:
- `PI_API_KEY=<key>` (server-side, NOT public)
- `NEXT_PUBLIC_PI_API_URL=https://api.slxp.app`

---

## Security Notes

- The key is sent in headers, not URL params (won't appear in logs)
- Health/docs endpoints remain public for monitoring
- If `PI_API_KEY` is not set, API runs in open mode (for local dev)
- Consider rotating the key periodically
