"""Mint a local-dev HS256 JWT when CLERK_JWKS_URL=local.

Usage (from apps/api):
  uv run python scripts/make_dev_token.py user_a
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

# Allow `uv run python scripts/make_dev_token.py` from apps/api without PYTHONPATH.
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from jose import jwt  # noqa: E402

from src.config import settings  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Mint a local-dev Clerk-style JWT")
    parser.add_argument("user_id", help="Value for the JWT 'sub' claim")
    parser.add_argument(
        "--hours",
        type=int,
        default=24,
        help="Token lifetime in hours (default: 24)",
    )
    args = parser.parse_args()

    if settings.clerk_jwks_url.strip().lower() != "local":
        raise SystemExit(
            "CLERK_JWKS_URL is not 'local'. Refusing to mint a HS256 token "
            "that production Clerk RS256 verification would reject. "
            "Set CLERK_JWKS_URL=local (and matching CLERK_ISSUER / DEV_JWT_SECRET) "
            "to use this script."
        )

    now = int(time.time())
    token = jwt.encode(
        {
            "sub": args.user_id,
            "iss": settings.clerk_issuer,
            "iat": now,
            "exp": now + args.hours * 3600,
        },
        settings.dev_jwt_secret,
        algorithm="HS256",
    )
    print(token)


if __name__ == "__main__":
    main()
