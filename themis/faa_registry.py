"""
faa_registry.py — FAA Remote ID Cross-Reference

Argos uses this to distinguish personal drones
from government, law enforcement, and surveillance contractor drones.

Personal drones: respected and ignored.
Government/contractor drones: tracked, logged, reported.

This is the privacy line. It does not move.

Sources:
- FAA DroneZone registration database (public)
- FAA UAS Remote ID rule (effective September 2023)
- Known government agency registration patterns
- Known surveillance contractor registration patterns

Founded by Krone the Architect · Powers Tracey Lynn
Project Themis · 2026
"""

import re
import json
import os
import socket
import urllib.request
import urllib.parse
from datetime import datetime, timezone


# ── Known Government and Contractor Registrations ────────────────────────────
# Sources: FAA public records, FOIA requests, investigative journalism
# These are publicly documented. This is public information.

GOVERNMENT_OPERATORS = {
    # Federal agencies
    "federal": [
        "department of homeland security",
        "dhs",
        "customs and border protection",
        "cbp",
        "immigration and customs enforcement",
        "ice",
        "federal bureau of investigation",
        "fbi",
        "drug enforcement administration",
        "dea",
        "bureau of alcohol tobacco firearms",
        "atf",
        "us marshals",
        "secret service",
        "us secret service",
        "department of defense",
        "dod",
        "us air force",
        "us army",
        "us navy",
        "us marine corps",
        "national guard",
        "us coast guard",
        "transportation security administration",
        "tsa",
        "national reconnaissance office",
        "nro",
        "defense intelligence agency",
        "dia",
        "national security agency",
        "nsa",
        "central intelligence agency",
        "cia",
        "us forest service",
        "bureau of land management",
        "blm",
        "us border patrol",
    ],
    # State and local law enforcement
    "law_enforcement": [
        "police department",
        "police dept",
        "sheriff",
        "sheriff's office",
        "sheriffs office",
        "state police",
        "highway patrol",
        "department of public safety",
        "corrections",
        "department of corrections",
        "district attorney",
        "prosecutors office",
        "fire department",  # sometimes surveillance equipped
        "emergency management",
    ],
    # Known surveillance contractors
    "contractors": [
        "palantir",
        "skydio",
        "axon",
        "taser",
        "clearview",
        "vigilant solutions",
        "digital recognition network",
        "motorola solutions",
        "avigilon",
        "l3harris",
        "leidos",
        "booz allen",
        "saic",
        "general dynamics",
        "northrop grumman",
        "raytheon",
        "lockheed martin",
        "caci international",
        "peraton",
        "maximus",
        "veritone",
        "fusus",
        "shotspotter",
        "soundthinking",
        "thomson reuters",
        "lexisnexis",
        "idemia",
        "nec",
        "zetron",
        "cohu",
        "iter systems",
        "dedrone",
        "d-fend solutions",
        "fortem technologies",
        "robin radar",
        "drone shield",
    ],
}

# ── FAA N-Number Pattern Analysis ────────────────────────────────────────────
# FAA registration numbers follow patterns that can indicate operator type

GOVERNMENT_NNUM_PREFIXES = [
    "N1",   # Often federal agency aircraft
    "N2",   # Often federal/military
    "N9",   # Often law enforcement
]

# Known law enforcement drone N-numbers from public records
# Sources: FAA public aircraft database, FOIA requests
# This list grows as community reports come in
KNOWN_LE_REGISTRATIONS = {
    # Format: "N-NUMBER": "Agency · Location"
    # Populated from public FAA records and investigative journalism
    # Community verified entries added here
}


class FAARegistry:
    """
    Cross-references drone Remote ID broadcasts against
    FAA registration data to identify government and
    contractor surveillance drones.

    Personal drones: ignored.
    Government/contractor: tracked.

    This distinction is the privacy protection.
    It does not move.
    """

    REGISTRY_CACHE_FILE = "themis_faa_cache.json"
    CACHE_TTL_HOURS     = 24

    def __init__(self):
        self._cache = self._load_cache()

    # ── Primary Classification ────────────────────────────────────────────────

    def classify(self, remote_id_data: dict) -> dict:
        """
        Classify a drone based on its Remote ID broadcast.

        Returns:
        {
            "track":       bool — should Themis track this drone?
            "category":    "personal" | "government" | "law_enforcement" |
                          "contractor" | "unknown",
            "operator":    str — identified operator if known,
            "confidence":  float — 0.0 to 1.0,
            "reason":      str — why this classification,
            "privacy_protected": bool — personal drone, leave it alone
        }
        """
        serial      = remote_id_data.get("serial", "")
        n_number    = remote_id_data.get("n_number", "")
        operator_id = remote_id_data.get("operator_id", "").lower()
        ssid        = remote_id_data.get("ssid", "").lower()

        # Check known registrations first
        if n_number in KNOWN_LE_REGISTRATIONS:
            agency = KNOWN_LE_REGISTRATIONS[n_number]
            return {
                "track":             True,
                "category":          "law_enforcement",
                "operator":          agency,
                "confidence":        0.99,
                "reason":            f"Known law enforcement registration: {n_number}",
                "privacy_protected": False,
            }

        # Check operator ID against government operators
        classification = self._check_operator_name(operator_id or ssid)
        if classification["track"]:
            return classification

        # Check N-number patterns
        if n_number:
            classification = self._check_n_number(n_number)
            if classification["track"]:
                return classification

        # Check serial number patterns
        if serial:
            classification = self._check_serial(serial)
            if classification:
                return classification

        # Try FAA lookup if we have a registration number
        if n_number:
            faa_result = self._lookup_faa(n_number)
            if faa_result:
                return faa_result

        # Unknown — low confidence, don't track, protect privacy
        return {
            "track":             False,
            "category":          "personal",
            "operator":          "Unknown — assumed personal",
            "confidence":        0.60,
            "reason":            "No government or contractor indicators found.",
            "privacy_protected": True,
        }

    # ── Operator Name Check ───────────────────────────────────────────────────

    def _check_operator_name(self, name: str) -> dict:
        """Check operator name against known government/contractor lists."""
        name_lower = name.lower()

        for operator in GOVERNMENT_OPERATORS["federal"]:
            if operator in name_lower:
                return {
                    "track":             True,
                    "category":          "federal",
                    "operator":          name,
                    "confidence":        0.92,
                    "reason":            f"Federal agency operator ID: {name}",
                    "privacy_protected": False,
                }

        for operator in GOVERNMENT_OPERATORS["law_enforcement"]:
            if operator in name_lower:
                return {
                    "track":             True,
                    "category":          "law_enforcement",
                    "operator":          name,
                    "confidence":        0.90,
                    "reason":            f"Law enforcement operator ID: {name}",
                    "privacy_protected": False,
                }

        for operator in GOVERNMENT_OPERATORS["contractors"]:
            if operator in name_lower:
                return {
                    "track":             True,
                    "category":          "contractor",
                    "operator":          name,
                    "confidence":        0.88,
                    "reason":            f"Known surveillance contractor: {name}",
                    "privacy_protected": False,
                }

        return {
            "track":             False,
            "category":          "personal",
            "operator":          name,
            "confidence":        0.50,
            "reason":            "No government indicators in operator name.",
            "privacy_protected": True,
        }

    # ── N-Number Check ────────────────────────────────────────────────────────

    def _check_n_number(self, n_number: str) -> dict:
        """
        Analyze FAA N-number for government indicators.
        Government aircraft often follow specific registration patterns.
        """
        n_upper = n_number.upper()

        # Check against known prefixes
        for prefix in GOVERNMENT_NNUM_PREFIXES:
            if n_upper.startswith(prefix):
                return {
                    "track":             True,
                    "category":          "government_possible",
                    "operator":          f"Unknown government — {n_number}",
                    "confidence":        0.55,
                    "reason":            f"N-number prefix {prefix} associated with government aircraft.",
                    "privacy_protected": False,
                }

        return {
            "track":             False,
            "category":          "personal",
            "operator":          "Unknown",
            "confidence":        0.45,
            "reason":            "N-number pattern not associated with government.",
            "privacy_protected": True,
        }

    # ── Serial Number Check ───────────────────────────────────────────────────

    def _check_serial(self, serial: str) -> dict:
        """
        Check drone serial number.
        Some government procurement uses specific serial ranges.
        DJI serials follow manufacturer patterns.
        """
        # DJI government/enterprise serials often contain specific prefixes
        if serial.upper().startswith(("3AANH", "3AANE")):
            return {
                "track":             True,
                "category":          "enterprise_possible",
                "operator":          f"DJI Enterprise — {serial}",
                "confidence":        0.65,
                "reason":            "DJI Enterprise serial prefix — often government/contractor.",
                "privacy_protected": False,
            }

        return None

    # ── FAA Public Lookup ─────────────────────────────────────────────────────

    def _lookup_faa(self, n_number: str) -> dict:
        """
        Look up aircraft registration in FAA public database.
        FAA aircraft registry is public information.
        """
        # Check cache first
        cached = self._cache.get(n_number)
        if cached:
            age_hours = (
                datetime.now(timezone.utc).timestamp() -
                cached.get("cached_at", 0)
            ) / 3600
            if age_hours < self.CACHE_TTL_HOURS:
                return cached.get("result")

        # FAA public registry API
        # https://registry.faa.gov/aircraftinquiry/
        try:
            clean_n = n_number.upper().lstrip("N")
            url = f"https://registry.faa.gov/aircraftinquiry/Search/NNumberInquiry?nNumber={clean_n}"

            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0"
            })
            with urllib.request.urlopen(req, timeout=5) as response:
                html = response.read().decode("utf-8", errors="replace")

            # Parse registrant name from FAA response
            # FAA page contains registrant info in specific HTML patterns
            name_match = re.search(
                r'Name[:\s]+([A-Z\s]+(?:POLICE|SHERIFF|DHS|FBI|CBP|ICE|DEA|'
                r'DEPARTMENT|AGENCY|BUREAU|DIVISION|AUTHORITY|FORCE|SERVICE|'
                r'SOLUTIONS|SYSTEMS|TECHNOLOGIES)[A-Z\s]*)',
                html, re.IGNORECASE
            )

            if name_match:
                registrant = name_match.group(1).strip()
                check = self._check_operator_name(registrant)
                result = {**check, "operator": registrant, "source": "FAA registry"}
                self._cache_result(n_number, result)
                return result

        except Exception:
            pass

        return None

    # ── Community Reports ─────────────────────────────────────────────────────

    def add_community_registration(self, n_number: str, agency: str,
                                    source: str = "community") -> bool:
        """
        Add a community-verified government registration.
        Every verified report strengthens the database.
        """
        KNOWN_LE_REGISTRATIONS[n_number.upper()] = f"{agency} · {source}"

        # Save to local database
        try:
            db_file = "themis_known_registrations.json"
            existing = {}
            if os.path.exists(db_file):
                with open(db_file) as f:
                    existing = json.load(f)
            existing[n_number.upper()] = {
                "agency":     agency,
                "source":     source,
                "added":      datetime.now(timezone.utc).isoformat(),
            }
            with open(db_file, "w") as f:
                json.dump(existing, f, indent=2)
            return True
        except Exception:
            return False

    def load_community_registrations(self):
        """Load community-verified registrations on startup."""
        try:
            db_file = "themis_known_registrations.json"
            if os.path.exists(db_file):
                with open(db_file) as f:
                    data = json.load(f)
                for n_number, info in data.items():
                    KNOWN_LE_REGISTRATIONS[n_number] = (
                        f"{info['agency']} · {info['source']}"
                    )
        except Exception:
            pass

    # ── Cache ─────────────────────────────────────────────────────────────────

    def _cache_result(self, n_number: str, result: dict):
        self._cache[n_number] = {
            "result":    result,
            "cached_at": datetime.now(timezone.utc).timestamp(),
        }
        try:
            with open(self.REGISTRY_CACHE_FILE, "w") as f:
                json.dump(self._cache, f)
        except Exception:
            pass

    def _load_cache(self) -> dict:
        try:
            if os.path.exists(self.REGISTRY_CACHE_FILE):
                with open(self.REGISTRY_CACHE_FILE) as f:
                    return json.load(f)
        except Exception:
            pass
        return {}


# ── Stationary Unit Handler ───────────────────────────────────────────────────

class StationaryUnit:
    """
    Handles fixed surveillance infrastructure.
    It doesn't move but it still watches.
    Ledger records it. The community knows it's there.
    First detection logged permanently.
    Location pinged. Added to community map.
    """

    STATIONARY_FILE = "themis_stationary_units.json"

    def __init__(self):
        self._units = self._load()

    def record(self, detection: dict) -> dict:
        """
        Record a stationary surveillance unit.
        First detection creates permanent record.
        Subsequent detections update last_seen only.
        """
        unit_id = self._generate_id(detection)

        if unit_id in self._units:
            # Already known — update last seen
            self._units[unit_id]["last_seen"] = (
                datetime.now(timezone.utc).isoformat()
            )
            self._units[unit_id]["sighting_count"] = (
                self._units[unit_id].get("sighting_count", 1) + 1
            )
            self._save()
            return {"new": False, "unit_id": unit_id}

        # New stationary unit — permanent record
        record = {
            "unit_id":       unit_id,
            "type":          detection.get("type", "unknown"),
            "detail":        detection.get("detail", ""),
            "vendor":        detection.get("vendor", "Unknown"),
            "location":      detection.get("location"),
            "ip":            detection.get("ip", ""),
            "mac":           detection.get("bssid") or detection.get("mac", ""),
            "first_seen":    datetime.now(timezone.utc).isoformat(),
            "last_seen":     datetime.now(timezone.utc).isoformat(),
            "sighting_count": 1,
            "verified":      False,
            "source":        detection.get("source", "Argos"),
            "classification": detection.get("classification", {}),
        }

        self._units[unit_id] = record
        self._save()

        return {"new": True, "unit_id": unit_id, "record": record}

    def get_all(self) -> list:
        return list(self._units.values())

    def get_map_data(self) -> list:
        """Return location data for community map."""
        map_points = []
        for unit in self._units.values():
            if unit.get("location"):
                map_points.append({
                    "type":       unit["type"],
                    "detail":     unit["detail"],
                    "vendor":     unit["vendor"],
                    "location":   unit["location"],
                    "first_seen": unit["first_seen"],
                    "verified":   unit["verified"],
                })
        return map_points

    def _generate_id(self, detection: dict) -> str:
        """Generate a stable ID for a stationary unit."""
        # Use MAC address or IP as stable identifier
        identifier = (
            detection.get("bssid") or
            detection.get("mac") or
            detection.get("ip") or
            detection.get("detail", "")
        )
        import hashlib
        return hashlib.sha256(identifier.encode()).hexdigest()[:16]

    def _save(self):
        try:
            with open(self.STATIONARY_FILE, "w") as f:
                json.dump(self._units, f, indent=2)
        except Exception:
            pass

    def _load(self) -> dict:
        try:
            if os.path.exists(self.STATIONARY_FILE):
                with open(self.STATIONARY_FILE) as f:
                    return json.load(f)
        except Exception:
            pass
        return {}


# ── ICE and Immigration Enforcement Resources ─────────────────────────────────
# Community tools for tracking immigration enforcement activity
# These are public community resources — not created by Themis

COMMUNITY_RESOURCES = {
    "ice_tracking": [
        {
            "name":        "ICE Activity Tracker",
            "url":         "https://www.iceinmyarea.org",
            "description": "Anonymous community-driven tool to report and track ICE activity.",
            "type":        "ice_tracker",
        },
        {
            "name":        "IceOut.org — People Over Papers",
            "url":         "https://iceout.org",
            "description": "Report and track ICE activity in your community.",
            "type":        "ice_tracker",
        },
    ],
    "legal_emergency": [
        {
            "name":        "ACLU Know Your Rights",
            "url":         "https://www.aclu.org/know-your-rights/immigrants-rights",
            "description": "Your rights during immigration enforcement.",
            "type":        "legal",
        },
        {
            "name":        "National Immigration Law Center",
            "url":         "https://www.nilc.org",
            "description": "Legal resources and immigrant rights.",
            "type":        "legal",
        },
        {
            "name":        "United We Dream",
            "url":         "https://unitedwedream.org",
            "description": "Immigrant youth-led organization. Know your rights resources.",
            "type":        "community",
        },
        {
            "name":        "National Lawyers Guild",
            "url":         "https://www.nlg.org",
            "description": "Legal observers and emergency legal support.",
            "phone":       "212-679-6018",
            "type":        "legal",
        },
        {
            "name":        "RAICES",
            "url":         "https://www.raicestexas.org",
            "description": "Immigrant defense and family support.",
            "type":        "community",
        },
    ],
    "surveillance_defense": [
        {
            "name":        "EFF Street Level Surveillance",
            "url":         "https://www.eff.org/pages/street-level-surveillance",
            "description": "Documentation of surveillance technologies used by police.",
            "type":        "education",
        },
        {
            "name":        "Atlas of Surveillance",
            "url":         "https://atlasofsurveillance.org",
            "description": "Documented surveillance technology deployments by agency.",
            "type":        "database",
        },
        {
            "name":        "ACLU Surveillance Technologies",
            "url":         "https://www.aclu.org/issues/privacy-technology/surveillance-technologies",
            "description": "ACLU surveillance technology resources and reporting.",
            "type":        "education",
        },
        {
            "name":        "Electronic Frontier Foundation",
            "url":         "https://www.eff.org",
            "description": "Digital rights and surveillance defense.",
            "type":        "advocacy",
        },
    ],
}
