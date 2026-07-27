"""Rate limiting helpers — slowapi keyed by authenticated user_id."""

from __future__ import annotations

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from src.api.auth import decode_access_token
from src.config import settings


def get_user_rate_limit_key(request: Request) -> str:
    """Key rate limits by verified user_id (falls back to IP if unauthenticated)."""
    auth = request.headers.get("Authorization") or ""
    if auth.lower().startswith("bearer "):
        token = auth.split(" ", 1)[1].strip()
        try:
            user_id = decode_access_token(token)
            return f"user:{user_id}"
        except Exception:
            pass
    return f"ip:{get_remote_address(request)}"


limiter = Limiter(
    key_func=get_user_rate_limit_key,
    storage_uri=settings.redis_url,
    default_limits=[],
)
