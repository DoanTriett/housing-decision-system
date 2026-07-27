from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


def make_asyncpg_url(url: str) -> tuple[str, dict[str, bool]]:
    """Convert a Postgres URL to asyncpg form and normalize SSL query params."""
    ssl_required = False
    parsed = urlsplit(url)
    query_pairs: list[tuple[str, str]] = []

    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        normalized_key = key.lower()
        if normalized_key == "sslmode":
            ssl_required = value.lower() not in {"disable", "allow"}
            continue
        if normalized_key == "channel_binding":
            continue
        query_pairs.append((key, value))

    scheme = parsed.scheme
    if scheme in {"postgresql", "postgres"}:
        scheme = "postgresql+asyncpg"

    async_url = urlunsplit(
        (
            scheme,
            parsed.netloc,
            parsed.path,
            urlencode(query_pairs),
            parsed.fragment,
        )
    )
    connect_args = {"ssl": True} if ssl_required else {}
    return async_url, connect_args
