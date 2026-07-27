"""Clerk JWT authentication for protected API routes."""

from __future__ import annotations

import time
from typing import Annotated, Any, cast

import httpx
import structlog
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwk, jwt

from src.config import settings

logger = structlog.get_logger(__name__)

_bearer = HTTPBearer(auto_error=True)

# JWKS cache: (fetched_at_epoch, jwks_payload)
_jwks_cache: tuple[float, dict[str, Any]] | None = None
_JWKS_TTL_SECONDS = 3600


def _get_jwks() -> dict[str, Any]:
    """Fetch Clerk JWKS, caching for ``_JWKS_TTL_SECONDS``."""
    global _jwks_cache
    now = time.time()
    if _jwks_cache is not None and (now - _jwks_cache[0]) < _JWKS_TTL_SECONDS:
        return _jwks_cache[1]

    try:
        response = httpx.get(settings.clerk_jwks_url, timeout=10.0)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("JWKS response is not an object")
        _jwks_cache = (now, payload)
        return payload
    except Exception as exc:
        logger.warning("jwks_fetch_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        ) from exc


def _decode_local_hs256(token: str) -> dict[str, Any]:
    """Local-dev HS256 path when ``clerk_jwks_url`` is set to ``local``."""
    return cast(
        dict[str, Any],
        jwt.decode(
            token,
            settings.dev_jwt_secret,
            algorithms=["HS256"],
            issuer=settings.clerk_issuer,
            options={"verify_aud": False},
        ),
    )


def _decode_rs256_via_jwks(token: str) -> dict[str, Any]:
    header = jwt.get_unverified_header(token)
    kid = header.get("kid")
    jwks = _get_jwks()
    keys = jwks.get("keys") or []
    matching = None
    for key in keys:
        if kid is None or key.get("kid") == kid:
            matching = key
            break
    if matching is None:
        raise JWTError("No matching JWKS key")

    public_key = jwk.construct(matching)
    return cast(
        dict[str, Any],
        jwt.decode(
            token,
            public_key,
            algorithms=["RS256"],
            issuer=settings.clerk_issuer,
            options={"verify_aud": False},
        ),
    )


def decode_access_token(token: str) -> str:
    """Verify JWT and return the Clerk ``sub`` claim (user_id)."""
    try:
        if settings.clerk_jwks_url.strip().lower() == "local":
            claims = _decode_local_hs256(token)
        else:
            claims = _decode_rs256_via_jwks(token)
        sub = claims.get("sub")
        if not sub or not isinstance(sub, str):
            raise JWTError("Missing sub claim")
        return sub
    except HTTPException:
        raise
    except Exception as exc:
        # Never leak JWT/JWKS error details to the client.
        logger.warning("token_verification_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        ) from exc


async def verify_clerk_token(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(_bearer)],
) -> str:
    """FastAPI dependency — returns verified ``user_id`` or raises 401."""
    return decode_access_token(credentials.credentials)


# Type alias for route signatures
CurrentUserId = Annotated[str, Depends(verify_clerk_token)]
