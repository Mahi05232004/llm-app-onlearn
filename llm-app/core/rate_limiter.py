
import os
from slowapi import Limiter
from slowapi.util import get_remote_address
import redis

from starlette.requests import Request

# Get Redis URL from environment or use default
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")

def get_real_address(request: Request) -> str:
    """
    Get the unique identifier for rate limiting.
    Priority:
    1. X-User-ID header (authenticated user ID)
    2. X-Forwarded-For header (real IP behind proxy)
    3. Direct client IP (fallback)
    """
    # 1. Check for User ID (preferred for authenticated users)
    user_id = request.headers.get("X-User-ID")
    if user_id:
        return user_id

    # 2. Check for Forwarded IP (for unauthenticated / shared IP scenarios)
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    
    # 3. Fallback to direct connection IP
    return request.client.host if request.client else "127.0.0.1"

def get_limiter():
    """
    Initialize and return the SlowAPI Limiter instance with Redis storage.
    """
    return Limiter(
        key_func=get_real_address,
        storage_uri=REDIS_URL,
        strategy="fixed-window", # or "moving-window"
    )

limiter = get_limiter()
