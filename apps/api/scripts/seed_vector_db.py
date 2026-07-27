"""Embed Austin neighborhood profiles into Qdrant using Voyage AI (voyage-3).

Run from apps/api/:
    uv run python scripts/seed_vector_db.py

Requires VOYAGE_API_KEY in environment / .env.
Upserts into collection 'neighborhoods'. Idempotent — safe to re-run.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import voyageai
from qdrant_client import QdrantClient
from qdrant_client.http.models import Distance, PointStruct, VectorParams

from src.config import settings

# ---------------------------------------------------------------------------
# Neighborhood profiles — hand-written for RAG quality
# ---------------------------------------------------------------------------
NEIGHBORHOOD_PROFILES = [
    {
        "neighborhood": "East Austin",
        "city": "Austin",
        "content": (
            "East Austin is one of Austin's most rapidly gentrifying corridors, "
            "stretching east of I-35 from 6th Street to Cesar Chavez. It blends "
            "long-standing Latino community roots with a dense concentration of craft "
            "breweries, food trailers, galleries, and music venues. Safety has improved "
            "significantly over the past decade, though petty theft remains a concern near "
            "certain commercial strips. Noise levels are moderate to high on weekends due "
            "to bar activity. Walkability is excellent — most errands and dining are "
            "reachable on foot. UT Austin is about 2 miles west, a 10-minute bike ride or "
            "20-minute bus ride on Route 7. Ideal for young professionals and grad students "
            "who want nightlife nearby without paying West Campus prices."
        ),
    },
    {
        "neighborhood": "Hyde Park",
        "city": "Austin",
        "content": (
            "Hyde Park is one of Austin's oldest intact residential neighborhoods, "
            "directly north of UT Austin — campus is a 5–10 minute walk or short bike "
            "ride down Guadalupe or Speedway. The area is quiet, tree-lined, and "
            "predominantly owner-occupied Victorian and Craftsman homes alongside "
            "student-oriented apartments. Safety is very good; crime rates are among the "
            "lowest of any near-campus neighborhood. Walkability is high — Quack's Bakery, "
            "Antonelli's Cheese Shop, and several grocers are all walkable. Noise is low "
            "on most streets but spikes near Duval on football weekends. Strongly "
            "recommended for students, faculty, and academics who want calm surroundings "
            "within a 15-minute walk of campus."
        ),
    },
    {
        "neighborhood": "South Congress",
        "city": "Austin",
        "content": (
            "South Congress Avenue (SoCo) is Austin's most iconic commercial corridor, "
            "lined with vintage boutiques, food trucks, Tex-Mex institutions, and the "
            "legendary Continental Club music venue. The residential streets east and west "
            "of the avenue are quiet and walkable. Overall safety is good; car break-ins "
            "near the high-traffic strip are the most reported crime. Noise is significant "
            "on SoCo itself — units on or near the avenue can be loud on weekends. Side "
            "streets are much calmer. UT Austin is 3.5 miles north — about 15 minutes by "
            "car, 25–35 minutes by bus. Best suited for professionals and creatives who "
            "prioritize neighborhood character and dining access over proximity to campus."
        ),
    },
    {
        "neighborhood": "Mueller",
        "city": "Austin",
        "content": (
            "Mueller is a master-planned, mixed-use redevelopment of the old Robert "
            "Mueller Airport, located 3 miles northeast of UT Austin. The neighborhood "
            "features wide sidewalks, dedicated bike lanes, a 140-acre park, a weekly "
            "farmers market, and an HEB grocery. It is consistently ranked among Austin's "
            "safest neighborhoods — the planned layout, good lighting, and active "
            "community association keep crime very low. Noise is minimal; the area has no "
            "bar scene and is primarily residential. Walkability within the development is "
            "excellent; walkability to other Austin destinations requires a car or bus. "
            "UT Austin is reachable in about 12 minutes by bike via dedicated lanes. "
            "Excellent for families, graduate students with children, and anyone who "
            "values safety and planned green space."
        ),
    },
    {
        "neighborhood": "Bouldin Creek",
        "city": "Austin",
        "content": (
            "Bouldin Creek sits south of Town Lake between South Congress and South First "
            "Street, offering a quieter, residential alternative to SoCo with strong "
            "walkability and a progressive community vibe. The neighborhood has cafés, "
            "independent shops, and easy Barton Creek Greenbelt access. Safety is good — "
            "crime rates are low compared to East Austin and downtown. Noise is "
            "neighborhood-scale: dogs, cyclists, and the occasional food truck generator. "
            "UT Austin is 2.5 miles north across the Congress Avenue Bridge — roughly "
            "15 minutes by bike or 25 minutes by bus. A good choice for students and "
            "professionals who want walkability, outdoor access, and a residential feel "
            "without paying Clarksville prices."
        ),
    },
    {
        "neighborhood": "Zilker",
        "city": "Austin",
        "content": (
            "Zilker is anchored by its iconic metropolitan park — 358 acres with Barton "
            "Springs Pool, playing fields, and direct Greenbelt access — and is among "
            "Austin's most desirable and expensive neighborhoods. Residential streets "
            "are extremely quiet and heavily canopied. Safety is excellent; it is a "
            "low-crime area. Walkability to parks is superb; walkability to everyday "
            "retail is moderate. UT Austin is 3 miles north, about 15 minutes by car "
            "or 30–35 minutes by bus. Rental inventory is limited and prices are high. "
            "Best for professionals and families who prioritize outdoor lifestyle, "
            "quiet surroundings, and don't mind car-dependency for errands."
        ),
    },
    {
        "neighborhood": "North Loop",
        "city": "Austin",
        "content": (
            "North Loop is a compact, walkable strip of vintage stores, cheap tacos, "
            "record shops, and divey bars along North Loop Boulevard between Duval and "
            "Airport Boulevard. The surrounding residential streets are quiet and "
            "predominantly rental properties. Safety is adequate — petty crime occurs "
            "but violent crime is uncommon. The area attracts a young, artistic crowd. "
            "Noise from the commercial strip is audible on weekends. Walkability on the "
            "strip itself is excellent; other destinations require a car or bus. UT Austin "
            "is 2 miles south — about 10 minutes by bike. Affordable relative to Hyde "
            "Park and East Austin; a strong option for undergrads and young grad students "
            "on a budget who want neighborhood character."
        ),
    },
    {
        "neighborhood": "Cherrywood",
        "city": "Austin",
        "content": (
            "Cherrywood is a quiet, leafy neighborhood just northeast of UT Austin, "
            "bounded roughly by Manor Road, Airport Boulevard, and 38th Street. It has "
            "a strong neighborhood association, an annual art tour, and a mix of "
            "bungalows and newer infill units. Safety is good — better than East Austin "
            "blocks of similar vintage. Noise is low; Manor Road has some bar activity "
            "but residential streets are peaceful. Walkability is moderate: Manor Road's "
            "food and coffee scene is walkable, but groceries require a short drive. "
            "UT Austin is 1.5–2 miles west, an easy 10-minute bike ride. One of the "
            "better values for quiet, campus-adjacent living."
        ),
    },
    {
        "neighborhood": "Travis Heights",
        "city": "Austin",
        "content": (
            "Travis Heights occupies hilly terrain south of Town Lake, east of South "
            "Congress. It is predominantly single-family homes on winding streets with "
            "significant tree canopy — one of Austin's quietest and most residential "
            "inner-city neighborhoods. Crime is low; the neighborhood consistently "
            "scores well on safety indices. Walkability to SoCo and the lake trail is "
            "good; grocery and retail access requires a car or bus. Noise is very low "
            "on most streets. UT Austin is 3 miles north — about 20 minutes by bike "
            "or 30 minutes by bus. Best for professionals seeking quiet inner-city "
            "living; less convenient for students."
        ),
    },
    {
        "neighborhood": "Clarksville",
        "city": "Austin",
        "content": (
            "Clarksville is one of Austin's oldest Black neighborhoods, now a wealthy "
            "enclave of beautifully preserved craftsman homes, boutique restaurants, "
            "and wine bars west of downtown. Safety is excellent — among the safest "
            "close-in Austin neighborhoods. Noise is low; it has a neighborhood bar "
            "scene but not a party district. Walkability to West 6th Street dining and "
            "Lady Bird Lake trails is superb. UT Austin is about 1 mile east — a "
            "15-minute walk or 5-minute bike. Rental prices are high. Ideal for "
            "professionals and faculty who want walkability, safety, and proximity to "
            "both campus and downtown and can afford the premium."
        ),
    },
    {
        "neighborhood": "Allandale",
        "city": "Austin",
        "content": (
            "Allandale is a quiet, established residential neighborhood in northwest "
            "Austin, primarily 1950s ranch homes on large lots. It has a strong "
            "neighborhood association, good schools, and a family-oriented character. "
            "Safety is very good — one of Austin's consistently low-crime areas. "
            "Noise is minimal; there is no commercial nightlife. Walkability is low — "
            "a car is essentially required for most errands. UT Austin is 4–5 miles "
            "south, a 20-minute drive outside peak hours. Best suited for families, "
            "faculty, and researchers who prioritize quiet, safety, and space over "
            "walkability or campus proximity."
        ),
    },
    {
        "neighborhood": "Rosedale",
        "city": "Austin",
        "content": (
            "Rosedale is a well-maintained, historic residential neighborhood north of "
            "38th Street, featuring mature oak canopy and mid-century architecture. "
            "It borders Hyde Park to the east and has similarly excellent safety "
            "characteristics. Noise is very low — primarily a quiet residential area "
            "with no significant commercial nightlife. Walkability is moderate; "
            "Burnet Road to the west provides retail and dining access. UT Austin is "
            "about 2–2.5 miles south, a 12-minute bike ride. Less dense and more "
            "suburban in feel than Hyde Park. Good for graduate students and junior "
            "faculty who prefer more space and quiet at the cost of a slightly longer "
            "campus commute."
        ),
    },
    {
        "neighborhood": "Windsor Park",
        "city": "Austin",
        "content": (
            "Windsor Park is an affordable, mid-century neighborhood northeast of "
            "Mueller with a diverse demographic and growing arts presence around "
            "the 51st Street corridor. Safety is average for Austin — property crime "
            "occurs but violent crime is relatively uncommon. Noise is low in "
            "residential areas. Walkability is limited outside the 51st Street strip. "
            "UT Austin is 4 miles west, about 25 minutes by bus or 20 minutes by "
            "bike. The trade-off for lower rent is less walkability and a longer "
            "campus commute. A strong option for budget-conscious renters who don't "
            "mind commuting and want a quieter, more residential environment."
        ),
    },
    {
        "neighborhood": "Crestview",
        "city": "Austin",
        "content": (
            "Crestview is a calm, suburban residential neighborhood in north-central "
            "Austin, notable for the Brentwood/Crestview rail stop on Austin's MetroRail "
            "line — providing car-free access to downtown in about 25 minutes. Streets "
            "are quiet and family-oriented. Safety is very good. Walkability to "
            "Anderson Lane's restaurants and retail is decent; wider errands need a car. "
            "UT Austin is 4–5 miles south — the MetroRail is the most practical "
            "car-free option, roughly 35–40 minutes door to door. Best for graduate "
            "students and staff who are comfortable with a longer commute in exchange "
            "for lower rent, quiet surroundings, and rail access."
        ),
    },
    {
        "neighborhood": "South Lamar",
        "city": "Austin",
        "content": (
            "South Lamar Boulevard is a lively mixed-use corridor running south from "
            "Town Lake, lined with the Alamo Drafthouse, Uchi, BookPeople's larger "
            "sibling locations, Whole Foods flagship, and numerous bars and music "
            "venues. Residential streets to the east and west are quieter than the "
            "boulevard. Safety is good overall, though car break-ins near high-traffic "
            "lots are common. Noise is significant on the corridor itself; side streets "
            "are much calmer. Walkability is excellent — one of Austin's most walkable "
            "non-downtown areas. UT Austin is 2.5 miles north, about 15 minutes by "
            "bike or 25 minutes by bus. Excellent for professionals who want an "
            "active, amenity-rich lifestyle close to Town Lake."
        ),
    },
]

COLLECTION_NAME = "neighborhoods"
VOYAGE_MODEL = "voyage-3"
VECTOR_DIM = 1024  # voyage-3 output dimension


def main() -> None:
    if not settings.voyage_api_key:
        print("ERROR: VOYAGE_API_KEY is not set. Add it to your .env file.")
        sys.exit(1)

    # ---- Voyage AI client ----
    vo = voyageai.Client(api_key=settings.voyage_api_key)

    # ---- Qdrant client ----
    qdrant = QdrantClient(
        url=settings.qdrant_url,
        api_key=settings.qdrant_api_key or None,
    )

    # ---- Create or recreate collection ----
    existing = {c.name for c in qdrant.get_collections().collections}
    if COLLECTION_NAME not in existing:
        qdrant.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(size=VECTOR_DIM, distance=Distance.COSINE),
        )
        print(f"Created collection '{COLLECTION_NAME}' (dim={VECTOR_DIM}).")
    else:
        print(f"Collection '{COLLECTION_NAME}' already exists — upserting.")

    # ---- Embed all profiles ----
    texts = [p["content"] for p in NEIGHBORHOOD_PROFILES]
    print(f"Embedding {len(texts)} neighborhood profiles with {VOYAGE_MODEL}…")
    result = vo.embed(texts, model=VOYAGE_MODEL, input_type="document")
    embeddings = result.embeddings
    print(f"Received {len(embeddings)} embeddings (dim={len(embeddings[0])}).")

    # ---- Upsert into Qdrant ----
    points = [
        PointStruct(
            id=i,
            vector=embeddings[i],
            payload={
                "neighborhood": NEIGHBORHOOD_PROFILES[i]["neighborhood"],
                "city": NEIGHBORHOOD_PROFILES[i]["city"],
                "content": NEIGHBORHOOD_PROFILES[i]["content"],
            },
        )
        for i in range(len(NEIGHBORHOOD_PROFILES))
    ]
    qdrant.upsert(collection_name=COLLECTION_NAME, points=points)
    print(f"Upserted {len(points)} points into '{COLLECTION_NAME}'.")

    # ---- Smoke-test semantic query ----
    query = "safe quiet neighborhood near university"
    print(f"\nSmoke-test query: '{query}'")
    q_result = vo.embed([query], model=VOYAGE_MODEL, input_type="query")
    q_vec = q_result.embeddings[0]

    hits = qdrant.query_points(
        collection_name=COLLECTION_NAME,
        query=q_vec,
        limit=3,
    ).points

    print("\nTop-3 results:")
    for hit in hits:
        nbhd = hit.payload.get("neighborhood", "?") if hit.payload else "?"
        print(f"  score={hit.score:.4f}  neighborhood={nbhd}")


if __name__ == "__main__":
    main()
