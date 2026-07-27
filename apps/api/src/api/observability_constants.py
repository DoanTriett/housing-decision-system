"""Day 12 constants for observability aggregation."""

# How many recent UserRequest rows to include in /api/admin/observability/summary.
OBSERVABILITY_RECENT_REQUEST_LIMIT = 50

# Pending requests older than this are flagged as stale (Day 11 carry-over detection).
STALE_PENDING_SECONDS = 90
