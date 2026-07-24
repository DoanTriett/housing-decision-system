"""Seed the listings table with 200 synthetic Austin, TX rental listings.

Run from apps/api/:
    uv run python scripts/seed_db.py

Skips seeding if the listings table already has rows.
"""

import os
import random
import sys

# Allow running from apps/api/ without installing the package
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg
from faker import Faker

from src.config import settings

fake = Faker()
random.seed(42)

# ---------------------------------------------------------------------------
# Austin neighborhood data: (name, center_lat, center_lon, vibe)
# ---------------------------------------------------------------------------
NEIGHBORHOODS = [
    ("East Austin", 30.2628, -97.7218, "trendy"),
    ("Hyde Park", 30.3098, -97.7318, "historic"),
    ("South Congress", 30.2441, -97.7498, "eclectic"),
    ("Mueller", 30.2948, -97.6998, "planned"),
    ("Bouldin Creek", 30.2528, -97.7618, "artsy"),
    ("Zilker", 30.2628, -97.7718, "outdoorsy"),
    ("North Loop", 30.3198, -97.7118, "hipster"),
    ("Cherrywood", 30.2798, -97.7168, "quiet"),
    ("Travis Heights", 30.2378, -97.7418, "walkable"),
    ("Clarksville", 30.2798, -97.7618, "upscale"),
    ("Allandale", 30.3398, -97.7518, "family"),
    ("Rosedale", 30.3198, -97.7418, "leafy"),
    ("Windsor Park", 30.3148, -97.6918, "affordable"),
    ("Crestview", 30.3498, -97.7318, "suburban"),
    ("South Lamar", 30.2428, -97.7648, "lively"),
]

BED_OPTIONS = [0.0, 1.0, 1.0, 1.0, 2.0, 2.0, 2.0, 3.0, 3.0]  # studio → 3BR, weighted
BATH_MAP = {0.0: [1.0], 1.0: [1.0, 1.0, 1.5], 2.0: [1.0, 1.5, 2.0], 3.0: [2.0, 2.0, 2.5]}
SQFT_MAP = {0.0: (380, 600), 1.0: (550, 900), 2.0: (850, 1350), 3.0: (1200, 1800)}
PRICE_MAP = {0.0: (700, 1150), 1.0: (900, 1500), 2.0: (1200, 1900), 3.0: (1500, 2500)}

UNIT_TYPES = ["Apt", "Unit", "Suite", "#"]

DESCRIPTION_TEMPLATES = [
    "{adj} {beds_label} in {neighborhood}. Features {feat1} and {feat2}. "
    "{walk} walk to local shops and restaurants. {pet_line}",
    "Charming {beds_label} in the heart of {neighborhood}. {feat1}, {feat2}. "
    "Great natural light. {walk} commute to downtown. {pet_line}",
    "Well-maintained {beds_label} in {neighborhood}. Recently updated {feat1}. "
    "{walk} from coffee shops and parks. {pet_line}",
]
ADJECTIVES = [
    "Bright",
    "Modern",
    "Renovated",
    "Cozy",
    "Spacious",
    "Updated",
    "Classic",
    "Stylish",
    "Newly renovated",
    "Inviting",
]
FEATURES = [
    "hardwood floors",
    "quartz countertops",
    "stainless appliances",
    "central AC/heat",
    "high ceilings",
    "private patio",
    "large closets",
    "updated bathroom",
    "open floor plan",
    "ample storage",
    "ceiling fans",
    "granite counters",
    "tile backsplash",
]
WALK_PHRASES = ["5-minute", "10-minute", "15-minute", "Short"]


def _make_description(
    beds: float,
    neighborhood: str,
    has_laundry: bool,
    is_pet_friendly: bool,
) -> str:
    beds_label = "studio" if beds == 0.0 else f"{int(beds)}BR"
    adj = random.choice(ADJECTIVES)
    feat1, feat2 = random.sample(FEATURES, 2)
    walk = random.choice(WALK_PHRASES)
    pet_line = "Pets welcome with deposit." if is_pet_friendly else "No pets."
    tmpl = random.choice(DESCRIPTION_TEMPLATES)
    return tmpl.format(
        adj=adj,
        beds_label=beds_label,
        neighborhood=neighborhood,
        feat1=feat1,
        feat2=feat2,
        walk=walk,
        pet_line=pet_line,
    )


def _jitter(center: float, spread: float = 0.012) -> float:
    return round(center + random.uniform(-spread, spread), 6)


def _generate_listings(count: int = 200) -> list[dict]:
    listings = []
    for _i in range(count):
        nbhd, lat_c, lon_c, _ = random.choice(NEIGHBORHOODS)
        beds = random.choice(BED_OPTIONS)
        baths = random.choice(BATH_MAP[beds])
        sqft_lo, sqft_hi = SQFT_MAP[beds]
        price_lo, price_hi = PRICE_MAP[beds]
        sqft = random.randint(sqft_lo, sqft_hi)
        price = random.randint(price_lo, price_hi)
        # ~40% pet friendly, ~60% have laundry
        is_pet = random.random() < 0.40
        has_laundry = random.random() < 0.60

        unit = f"{random.choice(UNIT_TYPES)} {random.randint(1, 40):02d}"
        address = f"{fake.building_number()} {fake.street_name()}, {unit}"
        beds_label = "Studio" if beds == 0.0 else f"{int(beds)}BR"
        title = f"{beds_label} in {nbhd}"

        listings.append(
            {
                "title": title,
                "address": address,
                "neighborhood": nbhd,
                "city": "Austin",
                "lat": _jitter(lat_c),
                "lon": _jitter(lon_c),
                "price_monthly": price,
                "beds": beds,
                "baths": baths,
                "sqft": sqft,
                "has_laundry": has_laundry,
                "is_pet_friendly": is_pet,
                "description": _make_description(beds, nbhd, has_laundry, is_pet),
                "is_active": True,
            }
        )
    return listings


def main() -> None:
    url = settings.database_url
    # psycopg needs plain postgresql://, not +asyncpg
    url = url.replace("postgresql+asyncpg://", "postgresql://")

    with psycopg.connect(url) as conn:
        count = conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0]
        if count >= 200:
            print(f"Skipped — listings table already has {count} rows.")
            return

        listings = _generate_listings(200)
        inserted = 0
        with conn.transaction():
            for row in listings:
                conn.execute(
                    """
                    INSERT INTO listings
                        (title, address, neighborhood, city, lat, lon,
                         price_monthly, beds, baths, sqft,
                         has_laundry, is_pet_friendly, description, is_active)
                    VALUES
                        (%(title)s, %(address)s, %(neighborhood)s, %(city)s,
                         %(lat)s, %(lon)s, %(price_monthly)s, %(beds)s,
                         %(baths)s, %(sqft)s, %(has_laundry)s,
                         %(is_pet_friendly)s, %(description)s, %(is_active)s)
                    """,
                    row,
                )
                inserted += 1

    print(f"Inserted {inserted} listings.")


if __name__ == "__main__":
    main()
