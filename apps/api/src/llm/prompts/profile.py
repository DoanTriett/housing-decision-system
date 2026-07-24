"""Long-term preference extraction prompt for UserProfile updates."""

PROFILE_EXTRACTION_SYSTEM_PROMPT = """\
You extract durable housing preferences from a completed search session.

Given the user's request and the final recommendation, return durable \
preferences that should persist across future sessions — not one-off listing IDs.

Examples of durable keys:
- prefers_laundry (bool)
- prefers_pet_friendly (bool)
- max_acceptable_commute_minutes (int)
- noise_sensitivity ("low"|"medium"|"high")
- safety_priority ("low"|"medium"|"high")
- budget_ceiling (number)
- concerned_about_scams (bool)

Only include preferences clearly supported by the request or recommendation.
Call `submit_preferences` exactly once with a preferences object.
"""
