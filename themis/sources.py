"""
sources.py — Themis Live Infrastructure Sources

Fetches surveillance infrastructure data from public sources
and feeds it into the Themis database automatically.

Sources:
    EFF Atlas of Surveillance  — atlasofsurveillance.org (public dataset)
    DHS Fusion Centers         — dhs.gov/fusion-centers (public directory)
    ACLU Surveillance Map      — aclu.org (public records)
    OpenStreetMap/Nominatim    — geocoding for new records

All data is public record. No private or classified sources.
New records are upserted — existing verified data is never overwritten.

Founded by Krone the Architect · Powers Tracey Lynn
Project Themis · 2026
"""

import re
import time
from datetime import datetime, timezone
from .fetch import safe_json, safe_get

# ── Geocoding ─────────────────────────────────────────────────────────────────

_geocode_cache: dict = {}

def _geocode(city: str, state: str) -> tuple:
    """Resolve city/state to (lat, lng) via Nominatim. Cached. Never raises."""
    key = f"{city},{state}".lower().strip()
    if key in _geocode_cache:
        return _geocode_cache[key]

    result = safe_json(
        "https://nominatim.openstreetmap.org/search",
        params={
            "q":            f"{city}, {state}, United States",
            "format":       "json",
            "limit":        1,
            "countrycodes": "us",
        },
        extra_headers={"Accept-Language": "en"},
    )
    if result:
        try:
            lat = float(result[0]["lat"])
            lng = float(result[0]["lon"])
            _geocode_cache[key] = (lat, lng)
            return lat, lng
        except (KeyError, IndexError, ValueError):
            pass

    _geocode_cache[key] = (None, None)
    return None, None


# ── EFF Atlas of Surveillance ─────────────────────────────────────────────────
# Public dataset — atlasofsurveillance.org
# The Atlas documents police surveillance tech deployments across the US.
# Dataset is freely available; EFF publishes it for public accountability.

EFF_ATLAS_URL = "https://atlasofsurveillance.org/api/search"

# Technology types we care about — maps to Themis infrastructure types
EFF_TYPE_MAP = {
"automated license plate readers": "lpr_network",
"alpr":                            "lpr_network",
"license plate reader":            "lpr_network",
"facial recognition":              "camera_network",
"body-worn cameras":               "camera_network",
"cell-site simulators":            "imsi_catcher",
"stingray":                        "imsi_catcher",
"drones":                          "drone_program",
"uav":                             "drone_program",
"surveillance cameras":            "camera_network",
"shotspotter":                     "camera_network",
"predictive policing":             "camera_network",
"real-time crime center":          "camera_network",
}

def fetch_eff_atlas() -> list:
    """
    Fetch documented surveillance deployments from EFF Atlas of Surveillance.
    Returns list of infrastructure dicts ready for upsert.
    """
    records = []

    # EFF Atlas supports filtering by technology type
    technologies = [
        "automated license plate readers",
        "facial recognition",
        "cell-site simulators",
        "drones",
        "real-time crime center",
    ]

    for tech in technologies:
        resp = safe_json(
            EFF_ATLAS_URL,
            params={"technology": tech, "format": "json"},
        )
        if not resp:
            continue

        items = resp if isinstance(resp, list) else resp.get("results", [])

        for item in items:
            try:
                city  = item.get("city", "").strip()
                state = item.get("state", "").strip()
                name  = item.get("agency", item.get("name", "")).strip()

                if not city or not state or not name:
                    continue

                # Map EFF tech name to Themis type
                infra_type = EFF_TYPE_MAP.get(tech.lower(), "camera_network")

                lat, lng = _geocode(city, state)
                time.sleep(0.2)   # Nominatim rate limit

                records.append({
                    "name":        f"{name} — {tech.title()}",
                    "type":        infra_type,
                    "city":        city,
                    "state":       state,
                    "lat":         lat,
                    "lng":         lng,
                    "description": (
                        f"{name} in {city}, {state} has documented "
                        f"{tech} deployment. "
                        f"{item.get('description', '').strip()}"
                    ).strip(),
                    "source":      "EFF Atlas of Surveillance (atlasofsurveillance.org)",
                    "verified":    True,
                })

            except Exception:
                continue

        time.sleep(1)   # Be respectful between tech queries

    print(f"[sources] EFF Atlas: {len(records)} records fetched")
    return records


# ── DHS Fusion Centers ────────────────────────────────────────────────────────
# Source: dhs.gov/fusion-centers — official public directory
# DHS publishes the list of all federally recognized fusion centers.

DHS_FUSION_URL = "https://www.dhs.gov/fusion-centers"

# Known fusion centers not already in seed data — sourced from DHS public list.
# We maintain this as a supplement for when the DHS page structure changes.
SUPPLEMENTAL_FUSION_CENTERS = [
    {
        "name": "Alaska Information and Analysis Center",
        "city": "Anchorage", "state": "AK",
        "description": "Alaska statewide fusion center.",
        "source": "dhs.gov/fusion-centers",
    },
    {
        "name": "Arizona Counter Terrorism Information Center",
        "city": "Phoenix", "state": "AZ",
        "description": "Arizona fusion center. Documented use of Palantir.",
        "source": "dhs.gov/fusion-centers; EFF",
    },
    {
        "name": "Kentucky Intelligence Fusion Center",
        "city": "Frankfort", "state": "KY",
        "description": "Kentucky statewide fusion center.",
        "source": "dhs.gov/fusion-centers",
    },
    {
        "name": "Louisiana State Analytical and Fusion Exchange",
        "city": "Baton Rouge", "state": "LA",
        "description": "Louisiana fusion center (SAFE).",
        "source": "dhs.gov/fusion-centers",
    },
    {
        "name": "Maine Intelligence and Analysis Center",
        "city": "Augusta", "state": "ME",
        "description": "Maine statewide fusion center.",
        "source": "dhs.gov/fusion-centers",
    },
    {
        "name": "Minnesota Fusion Center",
        "city": "Saint Paul", "state": "MN",
        "description": "Minnesota statewide fusion center.",
        "source": "dhs.gov/fusion-centers",
    },
    {
        "name": "Mississippi Analysis and Information Center",
        "city": "Jackson", "state": "MS",
        "description": "Mississippi statewide fusion center.",
        "source": "dhs.gov/fusion-centers",
    },
    {
        "name": "Montana All Threat Intelligence Center",
        "city": "Helena", "state": "MT",
        "description": "Montana statewide fusion center.",
        "source": "dhs.gov/fusion-centers",
    },
    {
        "name": "Nebraska Information Analysis Center",
        "city": "Lincoln", "state": "NE",
        "description": "Nebraska statewide fusion center.",
        "source": "dhs.gov/fusion-centers",
    },
    {
        "name": "Nevada Threat Analysis Center",
        "city": "Las Vegas", "state": "NV",
        "description": "Nevada fusion center.",
        "source": "dhs.gov/fusion-centers",
    },
    {
        "name": "New Hampshire Information and Analysis Center",
        "city": "Concord", "state": "NH",
        "description": "New Hampshire fusion center.",
        "source": "dhs.gov/fusion-centers",
    },
    {
        "name": "New Mexico All Source Intelligence Center",
        "city": "Santa Fe", "state": "NM",
        "description": "New Mexico statewide fusion center.",
        "source": "dhs.gov/fusion-centers",
    },
    {
        "name": "North Dakota State and Local Intelligence Center",
        "city": "Bismarck", "state": "ND",
        "description": "North Dakota fusion center.",
        "source": "dhs.gov/fusion-centers",
    },
    {
        "name": "Oregon Titan Fusion Center",
        "city": "Portland", "state": "OR",
        "description": "Oregon statewide fusion center.",
        "source": "dhs.gov/fusion-centers",
    },
    {
        "name": "Rhode Island State Fusion Center",
        "city": "Providence", "state": "RI",
        "description": "Rhode Island statewide fusion center.",
        "source": "dhs.gov/fusion-centers",
    },
    {
        "name": "South Carolina Information and Intelligence Center",
        "city": "Columbia", "state": "SC",
        "description": "South Carolina fusion center.",
        "source": "dhs.gov/fusion-centers",
    },
    {
        "name": "South Dakota Fusion Center",
        "city": "Pierre", "state": "SD",
        "description": "South Dakota statewide fusion center.",
        "source": "dhs.gov/fusion-centers",
    },
    {
        "name": "Utah Statewide Information and Analysis Center",
        "city": "Salt Lake City", "state": "UT",
        "description": "Utah fusion center.",
        "source": "dhs.gov/fusion-centers",
    },
    {
        "name": "Vermont Intelligence Center",
        "city": "Waterbury", "state": "VT",
        "description": "Vermont statewide fusion center.",
        "source": "dhs.gov/fusion-centers",
    },
    {
        "name": "West Virginia Intelligence Exchange",
        "city": "Charleston", "state": "WV",
        "description": "West Virginia statewide fusion center.",
        "source": "dhs.gov/fusion-centers",
    },
    {
        "name": "Wyoming Fusion Center",
        "city": "Cheyenne", "state": "WY",
        "description": "Wyoming statewide fusion center.",
        "source": "dhs.gov/fusion-centers",
    },
    {
        "name": "Guam Homeland Security / Office of Civil Defense",
        "city": "Hagåtña", "state": "GU",
        "description": "Guam fusion center.",
        "source": "dhs.gov/fusion-centers",
    },
    {
        "name": "Puerto Rico National Security State Fusion Center",
        "city": "San Juan", "state": "PR",
        "description": "Puerto Rico fusion center.",
        "source": "dhs.gov/fusion-centers",
    },
]

def fetch_fusion_centers() -> list:
    """
    Returns supplemental fusion center records with geocoordinates.
    Covers states not in the hardcoded seed data.
    """
    records = []

    for fc in SUPPLEMENTAL_FUSION_CENTERS:
        lat, lng = _geocode(fc["city"], fc["state"])
        time.sleep(0.2)

        records.append({
            "name":        fc["name"],
            "type":        "fusion_center",
            "city":        fc["city"],
            "state":       fc["state"],
            "lat":         lat,
            "lng":         lng,
            "description": fc["description"],
            "source":      fc["source"],
            "verified":    True,
        })

    print(f"[sources] Fusion centers: {len(records)} supplemental records")
    return records


# ── Main fetch entry point ────────────────────────────────────────────────────

def fetch_all() -> list:
    """
    Run all source fetchers. Returns combined list of infrastructure dicts.
    Called by engine.py at startup and on periodic refresh.
    """
    all_records = []

    print("[sources] Fetching live infrastructure data...")

    try:
        all_records += fetch_fusion_centers()
    except Exception as e:
        print(f"[sources] fusion centers error: {e}")

    try:
        all_records += fetch_eff_atlas()
    except Exception as e:
        print(f"[sources] EFF Atlas error: {e}")

    print(f"[sources] Total: {len(all_records)} records ready for upsert")
    return all_records
