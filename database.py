"""
database.py — ThemisDatabase

Neon PostgreSQL persistence layer.
Replaces ephemeral flat files for Render deployment.

Every detection stored. Nothing lost between restarts.

Founded by Krone the Architect · Powers Tracey Lynn
Project Themis · 2026
"""

import os
import json
from datetime import datetime, timezone
from sqlalchemy import (
    create_engine, text,
    Column, String, Float, DateTime, Boolean, Integer, Text
)
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.dialects.postgresql import JSONB

Base = declarative_base()


# ── Models ────────────────────────────────────────────────────────────────────

class Detection(Base):
    __tablename__ = "detections"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    time        = Column(DateTime(timezone=True), nullable=False)
    lead        = Column(String(64))
    type        = Column(String(64))
    detail      = Column(Text)
    severity    = Column(String(32))
    confidence  = Column(Float, default=0.0)
    source      = Column(String(128))
    lat         = Column(Float, nullable=True)
    lng         = Column(Float, nullable=True)
    extra       = Column(JSONB, nullable=True)   # any extra fields
    is_mobile   = Column(Boolean, default=False) # drone/robot = True; camera = False


class Infrastructure(Base):
    __tablename__ = "infrastructure"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    name        = Column(String(256))
    type        = Column(String(64))   # fusion_center | ice_facility | camera_network | lpr_network
    city        = Column(String(128))
    state       = Column(String(64))
    lat         = Column(Float)
    lng         = Column(Float)
    description = Column(Text)
    source      = Column(Text)         # public source URL or citation
    verified    = Column(Boolean, default=True)


# ── Engine ────────────────────────────────────────────────────────────────────

def get_engine():
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        raise RuntimeError("DATABASE_URL not set")
    return create_engine(
        url,
        pool_pre_ping=True,
        pool_recycle=300,
        pool_size=5,
        max_overflow=10,
    )


def get_session():
    engine = get_engine()
    Session = sessionmaker(bind=engine)
    return Session()


def init_db():
    """Create tables and seed static infrastructure data."""
    engine = get_engine()
    Base.metadata.create_all(engine)
    _seed_infrastructure(engine)


# ── Detection writes ──────────────────────────────────────────────────────────

def save_detection(detection: dict):
    """
    Persist a detection dict from ArgosScanner or WitnessIntel.
    Called from engine.py after every scan.
    """
    session = get_session()
    try:
        loc = detection.get("location") or {}
        lat = loc.get("lat") or detection.get("lat")
        lng = loc.get("lng") or detection.get("lng")

        mobile_types = {
            "drone_signal", "drone_bluetooth",
            "robot_detection", "imsi_catcher",
        }

        time_val = detection.get("time")
        if isinstance(time_val, str):
            try:
                time_val = datetime.fromisoformat(time_val)
            except Exception:
                time_val = datetime.now(timezone.utc)
        elif not time_val:
            time_val = datetime.now(timezone.utc)

        # Extra fields — everything not in core columns
        core = {"lead","type","detail","severity","confidence","source",
                "time","location","lat","lng"}
        extra = {k: v for k, v in detection.items() if k not in core}

        row = Detection(
            time       = time_val,
            lead       = detection.get("lead", "Themis"),
            type       = detection.get("type", "unknown"),
            detail     = detection.get("detail", ""),
            severity   = detection.get("severity", "info"),
            confidence = detection.get("confidence", 0.0),
            source     = detection.get("source", ""),
            lat        = lat,
            lng        = lng,
            extra      = extra if extra else None,
            is_mobile  = detection.get("type", "") in mobile_types,
        )
        session.add(row)
        session.commit()
    except Exception as e:
        session.rollback()
        print(f"[DB] save_detection error: {e}")
    finally:
        session.close()


# ── Detection reads ───────────────────────────────────────────────────────────

def get_detections(limit: int = 500) -> list:
    """Return recent detections as dicts for the map API."""
    session = get_session()
    try:
        rows = (
            session.query(Detection)
            .order_by(Detection.time.desc())
            .limit(limit)
            .all()
        )
        return [_detection_to_dict(r) for r in rows]
    except Exception as e:
        print(f"[DB] get_detections error: {e}")
        return []
    finally:
        session.close()


def get_infrastructure() -> list:
    """Return all verified static infrastructure as dicts."""
    session = get_session()
    try:
        rows = session.query(Infrastructure).filter_by(verified=True).all()
        return [_infra_to_dict(r) for r in rows]
    except Exception as e:
        print(f"[DB] get_infrastructure error: {e}")
        return []
    finally:
        session.close()


def get_detection_count() -> int:
    session = get_session()
    try:
        return session.query(Detection).count()
    except Exception:
        return 0
    finally:
        session.close()


# ── Serializers ───────────────────────────────────────────────────────────────

def _detection_to_dict(row: Detection) -> dict:
    return {
        "id":         row.id,
        "time":       row.time.isoformat() if row.time else None,
        "lead":       row.lead,
        "type":       row.type,
        "detail":     row.detail,
        "severity":   row.severity,
        "confidence": row.confidence,
        "source":     row.source,
        "lat":        row.lat,
        "lng":        row.lng,
        "is_mobile":  row.is_mobile,
    }


def _infra_to_dict(row: Infrastructure) -> dict:
    return {
        "id":          row.id,
        "name":        row.name,
        "type":        row.type,
        "city":        row.city,
        "state":       row.state,
        "lat":         row.lat,
        "lng":         row.lng,
        "description": row.description,
        "source":      row.source,
    }


# ── Seed data ─────────────────────────────────────────────────────────────────

def _seed_infrastructure(engine):
    """
    Seed static surveillance infrastructure.
    All locations sourced from publicly available records:
    EFF Atlas of Surveillance (atlasofsurveillance.org),
    DHS fusion center list (dhs.gov),
    ACLU investigations, and investigative journalism.
    No private or classified data. All public record.
    """
    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        existing = session.query(Infrastructure).count()
        if existing > 0:
            return  # Already seeded

        records = [

            # ── Fusion Centers (DHS, public list) ──────────────────────────
            # Source: dhs.gov/fusion-centers — official public directory
            Infrastructure(
                name="National Capital Region Intelligence Center",
                type="fusion_center",
                city="Washington", state="DC",
                lat=38.8951, lng=-77.0364,
                description="Regional fusion center serving DC metro area. Coordinates federal, state, and local surveillance data.",
                source="dhs.gov/fusion-centers (public directory)",
            ),
            Infrastructure(
                name="New York State Intelligence Center",
                type="fusion_center",
                city="Albany", state="NY",
                lat=42.6526, lng=-73.7562,
                description="New York's primary fusion center. Known to monitor social media and political protests.",
                source="dhs.gov/fusion-centers; NYCLU reporting",
            ),
            Infrastructure(
                name="Chicago Crime Prevention Information Center",
                type="fusion_center",
                city="Chicago", state="IL",
                lat=41.8781, lng=-87.6298,
                description="Chicago fusion center. Operates city's network of 32,000+ cameras. Palantir contract documented.",
                source="dhs.gov/fusion-centers; Chicago Tribune FOIA reports",
            ),
            Infrastructure(
                name="Los Angeles Joint Regional Intelligence Center",
                type="fusion_center",
                city="Los Angeles", state="CA",
                lat=34.0522, lng=-118.2437,
                description="LA fusion center. Serves as hub for LAPD, LASD, and federal agency data sharing.",
                source="dhs.gov/fusion-centers; ACLU of Southern California",
            ),
            Infrastructure(
                name="Houston Regional Intelligence Service Center",
                type="fusion_center",
                city="Houston", state="TX",
                lat=29.7604, lng=-95.3698,
                description="Texas Gulf Coast fusion center. Monitors port, energy infrastructure, and public gatherings.",
                source="dhs.gov/fusion-centers",
            ),
            Infrastructure(
                name="Arizona Counter Terrorism Information Center",
                type="fusion_center",
                city="Phoenix", state="AZ",
                lat=33.4484, lng=-112.0740,
                description="Arizona fusion center. Located near border. CBP and ICE data sharing documented.",
                source="dhs.gov/fusion-centers",
            ),
            Infrastructure(
                name="Atlanta HIDTA / Georgia Information Sharing and Analysis Center",
                type="fusion_center",
                city="Atlanta", state="GA",
                lat=33.7490, lng=-84.3880,
                description="Georgia statewide fusion center. Feeds into federal intelligence systems.",
                source="dhs.gov/fusion-centers",
            ),
            Infrastructure(
                name="Oregon Terrorism Information Threat Assessment Network",
                type="fusion_center",
                city="Portland", state="OR",
                lat=45.5231, lng=-122.6765,
                description="Oregon fusion center. Documented monitoring of Black Lives Matter protests (2020).",
                source="dhs.gov/fusion-centers; OPB investigative reporting",
            ),
            Infrastructure(
                name="Colorado Information Analysis Center",
                type="fusion_center",
                city="Denver", state="CO",
                lat=39.7392, lng=-104.9903,
                description="Colorado fusion center. Palantir deployment documented by EFF.",
                source="dhs.gov/fusion-centers; EFF Atlas of Surveillance",
            ),
            Infrastructure(
                name="Texas Fusion Center",
                type="fusion_center",
                city="Austin", state="TX",
                lat=30.2672, lng=-97.7431,
                description="Statewide Texas fusion center operated by DPS. Feeds into national network.",
                source="dhs.gov/fusion-centers",
            ),
            Infrastructure(
                name="Northern California Regional Intelligence Center",
                type="fusion_center",
                city="Sacramento", state="CA",
                lat=38.5816, lng=-121.4944,
                description="Covers Northern California. Oakland PD ShotSpotter data flows through here.",
                source="dhs.gov/fusion-centers; EFF",
            ),
            Infrastructure(
                name="Detroit and Southeast Michigan Information and Intelligence Center",
                type="fusion_center",
                city="Detroit", state="MI",
                lat=42.3314, lng=-83.0458,
                description="Detroit-area fusion center. Detroit has one of the densest facial recognition deployments in the US.",
                source="dhs.gov/fusion-centers; MIT Media Lab research",
            ),

            # ── ICE Facilities (public record) ─────────────────────────────
            # Source: ICE.gov detention facility locator (public),
            #         TRAC Immigration (tracfed.syr.edu), Freedom for Immigrants
            Infrastructure(
                name="Stewart Detention Center",
                type="ice_facility",
                city="Lumpkin", state="GA",
                lat=32.0496, lng=-84.7963,
                description="CoreCivic-operated ICE detention facility. Capacity: 1,800+. Documented human rights concerns.",
                source="ICE.gov facility locator; Freedom for Immigrants report",
            ),
            Infrastructure(
                name="Adelanto ICE Processing Center",
                type="ice_facility",
                city="Adelanto", state="CA",
                lat=34.5822, lng=-117.4327,
                description="GEO Group-operated ICE facility. Largest ICE facility in California.",
                source="ICE.gov facility locator; ACLU of Southern California",
            ),
            Infrastructure(
                name="Eloy Federal Contract Facility",
                type="ice_facility",
                city="Eloy", state="AZ",
                lat=32.7837, lng=-111.5548,
                description="CoreCivic-operated. Major ICE detention hub in Arizona.",
                source="ICE.gov facility locator",
            ),
            Infrastructure(
                name="South Texas Family Residential Center",
                type="ice_facility",
                city="Dilley", state="TX",
                lat=28.6672, lng=-99.1745,
                description="CoreCivic-operated family detention facility. Largest family detention center in the US.",
                source="ICE.gov facility locator; CARA Pro Bono Project",
            ),
            Infrastructure(
                name="Krome North Service Processing Center",
                type="ice_facility",
                city="Miami", state="FL",
                lat=25.6582, lng=-80.5432,
                description="Federally operated ICE processing center in South Florida.",
                source="ICE.gov facility locator",
            ),
            Infrastructure(
                name="Northwest ICE Processing Center",
                type="ice_facility",
                city="Tacoma", state="WA",
                lat=47.2340, lng=-122.4680,
                description="GEO Group-operated. Primary ICE facility in Pacific Northwest.",
                source="ICE.gov facility locator; La Resistencia",
            ),
            Infrastructure(
                name="York County Prison (ICE contract)",
                type="ice_facility",
                city="York", state="PA",
                lat=39.9626, lng=-76.7277,
                description="County facility with ICE contract. Major detention hub in Northeast.",
                source="ICE.gov facility locator; ACLU PA",
            ),
            Infrastructure(
                name="Broadview ICE Processing Center",
                type="ice_facility",
                city="Broadview", state="IL",
                lat=41.8612, lng=-87.8573,
                description="Federal ICE staging and processing facility near Chicago.",
                source="ICE.gov facility locator; Organized Communities Against Deportations",
            ),
            Infrastructure(
                name="Bergen County Jail (ICE contract)",
                type="ice_facility",
                city="Hackensack", state="NJ",
                lat=40.8859, lng=-74.0435,
                description="County jail with ICE contract. Serves as major detention point for NYC metro area.",
                source="ICE.gov facility locator; NJ ACLU",
            ),
            Infrastructure(
                name="Otay Mesa Detention Center",
                type="ice_facility",
                city="San Diego", state="CA",
                lat=32.5671, lng=-116.9756,
                description="CoreCivic-operated near US-Mexico border. Major CBP/ICE processing hub.",
                source="ICE.gov facility locator",
            ),

            # ── Documented Camera Networks ──────────────────────────────────
            # Source: EFF Atlas of Surveillance, city council records, FOIA
            Infrastructure(
                name="Chicago POD Camera Network",
                type="camera_network",
                city="Chicago", state="IL",
                lat=41.8781, lng=-87.6298,
                description="Chicago's network of 32,000+ Police Observation Device (POD) cameras. Connected to OEMC and fusion center. Facial recognition capable.",
                source="EFF Atlas of Surveillance; Chicago city records; Chicago Tribune FOIA",
            ),
            Infrastructure(
                name="NYC Domain Awareness System",
                type="camera_network",
                city="New York", state="NY",
                lat=40.7128, lng=-74.0060,
                description="Microsoft-built NYPD camera network. 15,000+ cameras citywide. License plate readers, radiation detectors, and facial recognition integrated.",
                source="EFF Atlas of Surveillance; NYPD DAS documentation",
            ),
            Infrastructure(
                name="LA ShotSpotter + Camera Network",
                type="camera_network",
                city="Los Angeles", state="CA",
                lat=34.0522, lng=-118.2437,
                description="LAPD camera and acoustic surveillance network. ShotSpotter covers majority of South and East LA.",
                source="EFF Atlas of Surveillance; LAPD annual reports",
            ),
            Infrastructure(
                name="Detroit Project Green Light",
                type="camera_network",
                city="Detroit", state="MI",
                lat=42.3314, lng=-83.0458,
                description="Detroit's real-time facial recognition camera network. Tied to DataWorks Plus facial recognition. Highest false positive rate in nation documented by MIT researchers.",
                source="EFF Atlas of Surveillance; MIT Media Lab study (Joy Buolamwini)",
            ),
            Infrastructure(
                name="Baltimore CitiWatch / Aerial Surveillance",
                type="camera_network",
                city="Baltimore", state="MD",
                lat=39.2904, lng=-76.6122,
                description="Baltimore's 800+ camera network plus documented aerial surveillance program (Persistent Surveillance Systems). Entire city filmed from plane for months.",
                source="EFF Atlas of Surveillance; Baltimore Sun investigative reporting",
            ),

            # ── License Plate Reader Networks ───────────────────────────────
            # Source: EFF Atlas of Surveillance; Flock Safety public contracts
            Infrastructure(
                name="Flock Safety LPR Network — Atlanta Metro",
                type="lpr_network",
                city="Atlanta", state="GA",
                lat=33.7490, lng=-84.3880,
                description="Flock Safety automated license plate reader network. Data retained and shared with law enforcement regionally.",
                source="EFF Atlas of Surveillance; Flock Safety public contracts database",
            ),
            Infrastructure(
                name="NYPD License Plate Reader Network",
                type="lpr_network",
                city="New York", state="NY",
                lat=40.7128, lng=-74.0060,
                description="NYPD operates one of the largest LPR networks in the US. Reads and stores millions of plates per day. Feeds into Domain Awareness System.",
                source="EFF Atlas of Surveillance; NYPD FOIA responses",
            ),
            Infrastructure(
                name="Vigilant Solutions / Motorola LPR — Chicago",
                type="lpr_network",
                city="Chicago", state="IL",
                lat=41.8781, lng=-87.6298,
                description="Vigilant Solutions (Motorola) LPR network integrated with CPD. National repository access.",
                source="EFF Atlas of Surveillance; CPD contracts database",
            ),
        ]

        for r in records:
            session.add(r)

        session.commit()
        print(f"[DB] Seeded {len(records)} infrastructure records.")

    except Exception as e:
        session.rollback()
        print(f"[DB] Seed error: {e}")
    finally:
        session.close()
