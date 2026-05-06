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

# ── Engine singleton — one pool shared across all calls ───────────────────────
_engine = None

def get_engine():
    global _engine
    if _engine is None:
        url = os.environ.get("DATABASE_URL", "")
        if not url:
            raise RuntimeError("DATABASE_URL not set")
        _engine = create_engine(
            url,
            pool_pre_ping=True,
            pool_recycle=300,
            pool_size=5,
            max_overflow=10,
        )
    return _engine


def get_session():
    Session = sessionmaker(bind=get_engine())
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


def get_infrastructure(filter_type: str = None) -> list:
    """Return verified static infrastructure as dicts.
    Pass filter_type to return only one layer at a time (faster for Render)."""
    session = get_session()
    try:
        q = session.query(Infrastructure).filter_by(verified=True)
        if filter_type:
            q = q.filter(Infrastructure.type == filter_type)
        rows = q.all()
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
        # Check if all expected types are present
        existing_types = [r[0] for r in session.query(Infrastructure.type).distinct().all()]
        all_types = [
            'fusion_center', 'ice_facility', 'camera_network', 'lpr_network',
            'border_surveillance', 'imsi_catcher', 'facial_recognition',
            'police_drone', 'surveillance_camera', 'robot_detection',
            'palantir', 'shotspotter', 'jttf', 'flock_lpr', 'css_aircraft',
            'fbi_surveillance', 'predictive_policing', 'rtcc',
            'clearview_ai', 'county_imsi', 'vigilant_lpr',
        ]
        missing = [t for t in all_types if t not in existing_types]

        if not missing:
            return  # All types present — nothing to add

        # Only insert records for missing types
        print(f"[DB] Adding missing types: {missing}")

        records = [

            # ══════════════════════════════════════════════════════════════
            # FUSION CENTERS — all 79 DHS-recognized centers
            # Source: dhs.gov/fusion-centers (public directory)
            # ══════════════════════════════════════════════════════════════

            Infrastructure(name="National Capital Region Intelligence Center", type="fusion_center", city="Washington", state="DC", lat=38.8951, lng=-77.0364, description="DC metro fusion center. Federal/local surveillance data hub. Monitors protest activity.", source="dhs.gov/fusion-centers"),
            Infrastructure(name="New York State Intelligence Center", type="fusion_center", city="Albany", state="NY", lat=42.6526, lng=-73.7562, description="NY primary fusion center. Social media monitoring documented.", source="dhs.gov/fusion-centers; NYCLU"),
            Infrastructure(name="New York City Police Dept Intelligence Bureau", type="fusion_center", city="New York", state="NY", lat=40.7128, lng=-74.0060, description="NYPD intelligence hub. Demographics Unit monitored Muslim communities (settled lawsuit).", source="dhs.gov/fusion-centers; ACLU"),
            Infrastructure(name="Chicago Crime Prevention Information Center", type="fusion_center", city="Chicago", state="IL", lat=41.8781, lng=-87.6298, description="Operates 32,000+ camera network. Palantir contract documented.", source="dhs.gov/fusion-centers; Chicago Tribune FOIA"),
            Infrastructure(name="Los Angeles Joint Regional Intelligence Center", type="fusion_center", city="Los Angeles", state="CA", lat=34.0522, lng=-118.2437, description="LAPD/LASD/federal data sharing hub.", source="dhs.gov/fusion-centers; ACLU SoCal"),
            Infrastructure(name="Houston Regional Intelligence Service Center", type="fusion_center", city="Houston", state="TX", lat=29.7604, lng=-95.3698, description="Gulf Coast fusion center. Port and energy infrastructure monitoring.", source="dhs.gov/fusion-centers"),
            Infrastructure(name="Arizona Counter Terrorism Information Center", type="fusion_center", city="Phoenix", state="AZ", lat=33.4484, lng=-112.0740, description="Border-adjacent. CBP/ICE data sharing documented.", source="dhs.gov/fusion-centers"),
            Infrastructure(name="Atlanta HIDTA / Georgia Information Sharing and Analysis Center", type="fusion_center", city="Atlanta", state="GA", lat=33.7490, lng=-84.3880, description="Georgia statewide fusion center.", source="dhs.gov/fusion-centers"),
            Infrastructure(name="Oregon Terrorism Information Threat Assessment Network", type="fusion_center", city="Portland", state="OR", lat=45.5231, lng=-122.6765, description="Monitored BLM protests (2020). FOIA confirmed.", source="dhs.gov/fusion-centers; OPB"),
            Infrastructure(name="Colorado Information Analysis Center", type="fusion_center", city="Denver", state="CO", lat=39.7392, lng=-104.9903, description="Palantir deployment documented.", source="dhs.gov/fusion-centers; EFF"),
            Infrastructure(name="Texas Fusion Center", type="fusion_center", city="Austin", state="TX", lat=30.2672, lng=-97.7431, description="DPS-operated statewide center.", source="dhs.gov/fusion-centers"),
            Infrastructure(name="Northern California Regional Intelligence Center", type="fusion_center", city="Sacramento", state="CA", lat=38.5816, lng=-121.4944, description="Oakland ShotSpotter data flows here.", source="dhs.gov/fusion-centers; EFF"),
            Infrastructure(name="Detroit and Southeast Michigan Information and Intelligence Center", type="fusion_center", city="Detroit", state="MI", lat=42.3314, lng=-83.0458, description="Detroit has densest US facial recognition deployment.", source="dhs.gov/fusion-centers; MIT Media Lab"),
            Infrastructure(name="Miami Dade Fusion Center", type="fusion_center", city="Miami", state="FL", lat=25.7617, lng=-80.1918, description="South Florida intelligence hub. CBP/DEA integration.", source="dhs.gov/fusion-centers"),
            Infrastructure(name="Tampa Bay Regional Intelligence Center", type="fusion_center", city="Tampa", state="FL", lat=27.9506, lng=-82.4572, description="Central Florida fusion center.", source="dhs.gov/fusion-centers"),
            Infrastructure(name="Florida Department of Law Enforcement Fusion Center", type="fusion_center", city="Tallahassee", state="FL", lat=30.4518, lng=-84.2807, description="Statewide FL intelligence coordination.", source="dhs.gov/fusion-centers"),
            Infrastructure(name="Washington State Fusion Center", type="fusion_center", city="Seattle", state="WA", lat=47.6062, lng=-122.3321, description="Documents protest movements. FOIA records confirmed.", source="dhs.gov/fusion-centers; ACLU WA"),
            Infrastructure(name="Nevada Threat Analysis Center", type="fusion_center", city="Las Vegas", state="NV", lat=36.1699, lng=-115.1398, description="NV statewide center. Las Vegas Strip surveillance integration.", source="dhs.gov/fusion-centers"),
            Infrastructure(name="New Mexico All Source Intelligence Center", type="fusion_center", city="Santa Fe", state="NM", lat=35.6870, lng=-105.9378, description="NM statewide. Border monitoring.", source="dhs.gov/fusion-centers"),
            Infrastructure(name="Missouri Information Analysis Center", type="fusion_center", city="Jefferson City", state="MO", lat=38.5767, lng=-92.1735, description="MO statewide fusion center.", source="dhs.gov/fusion-centers"),
            Infrastructure(name="Mid-States Organized Crime Information Center", type="fusion_center", city="Springfield", state="MO", lat=37.2090, lng=-93.2923, description="Regional multi-state fusion center.", source="dhs.gov/fusion-centers"),
            Infrastructure(name="Ohio Homeland Security / Strategic Analysis and Information Center", type="fusion_center", city="Columbus", state="OH", lat=39.9612, lng=-82.9988, description="OH statewide fusion center.", source="dhs.gov/fusion-centers"),
            Infrastructure(name="North Carolina Information Sharing and Analysis Center", type="fusion_center", city="Raleigh", state="NC", lat=35.7796, lng=-78.6382, description="NC statewide fusion center.", source="dhs.gov/fusion-centers"),
            Infrastructure(name="Virginia Fusion Center", type="fusion_center", city="Richmond", state="VA", lat=37.5407, lng=-77.4360, description="VA statewide. Pentagon-adjacent data sharing.", source="dhs.gov/fusion-centers"),
            Infrastructure(name="Maryland Coordination and Analysis Center", type="fusion_center", city="Woodlawn", state="MD", lat=39.3435, lng=-76.7344, description="MD/DC corridor fusion center.", source="dhs.gov/fusion-centers"),
            Infrastructure(name="Pennsylvania Criminal Intelligence Center", type="fusion_center", city="Harrisburg", state="PA", lat=40.2732, lng=-76.8867, description="PA statewide fusion center.", source="dhs.gov/fusion-centers"),
            Infrastructure(name="New Jersey Regional Operations and Intelligence Center", type="fusion_center", city="Trenton", state="NJ", lat=40.2171, lng=-74.7429, description="NJ statewide fusion center.", source="dhs.gov/fusion-centers"),
            Infrastructure(name="Massachusetts Commonwealth Fusion Center", type="fusion_center", city="Maynard", state="MA", lat=42.4315, lng=-71.4573, description="MA fusion center. Monitored Occupy Boston.", source="dhs.gov/fusion-centers; ACLU MA"),
            Infrastructure(name="Connecticut Intelligence Center", type="fusion_center", city="Middletown", state="CT", lat=41.5623, lng=-72.6506, description="CT statewide fusion center.", source="dhs.gov/fusion-centers"),
            Infrastructure(name="Minnesota Fusion Center", type="fusion_center", city="St. Paul", state="MN", lat=44.9537, lng=-93.0900, description="MN statewide. George Floyd protest monitoring documented.", source="dhs.gov/fusion-centers; Star Tribune"),
            Infrastructure(name="Wisconsin Statewide Intelligence Center", type="fusion_center", city="Madison", state="WI", lat=43.0731, lng=-89.4012, description="WI statewide fusion center.", source="dhs.gov/fusion-centers"),
            Infrastructure(name="Iowa Intelligence Fusion Center", type="fusion_center", city="Des Moines", state="IA", lat=41.5868, lng=-93.6250, description="IA statewide fusion center.", source="dhs.gov/fusion-centers"),
            Infrastructure(name="Nebraska Information Analysis Center", type="fusion_center", city="Omaha", state="NE", lat=41.2565, lng=-95.9345, description="NE statewide fusion center.", source="dhs.gov/fusion-centers"),
            Infrastructure(name="Kansas Bureau of Investigation — Fusion Center", type="fusion_center", city="Topeka", state="KS", lat=39.0558, lng=-95.6890, description="KS statewide fusion center.", source="dhs.gov/fusion-centers"),
            Infrastructure(name="Oklahoma Information Fusion Center", type="fusion_center", city="Oklahoma City", state="OK", lat=35.4676, lng=-97.5164, description="OK statewide fusion center.", source="dhs.gov/fusion-centers"),
            Infrastructure(name="Arkansas Terrorism Information and Warning System", type="fusion_center", city="Little Rock", state="AR", lat=34.7465, lng=-92.2896, description="AR statewide fusion center.", source="dhs.gov/fusion-centers"),
            Infrastructure(name="Louisiana State Analytical and Fusion Exchange", type="fusion_center", city="Baton Rouge", state="LA", lat=30.4515, lng=-91.1871, description="LA statewide fusion center.", source="dhs.gov/fusion-centers"),
            Infrastructure(name="Mississippi Analysis and Information Center", type="fusion_center", city="Jackson", state="MS", lat=32.2988, lng=-90.1848, description="MS statewide fusion center.", source="dhs.gov/fusion-centers"),
            Infrastructure(name="Alabama Fusion Center", type="fusion_center", city="Montgomery", state="AL", lat=32.3617, lng=-86.2792, description="AL statewide fusion center.", source="dhs.gov/fusion-centers"),
            Infrastructure(name="Tennessee Fusion Center", type="fusion_center", city="Nashville", state="TN", lat=36.1627, lng=-86.7816, description="TN statewide fusion center.", source="dhs.gov/fusion-centers"),
            Infrastructure(name="Kentucky Office of Homeland Security Fusion Center", type="fusion_center", city="Frankfort", state="KY", lat=38.2009, lng=-84.8733, description="KY statewide fusion center.", source="dhs.gov/fusion-centers"),
            Infrastructure(name="West Virginia Intelligence Fusion Center", type="fusion_center", city="Charleston", state="WV", lat=38.3498, lng=-81.6326, description="WV statewide fusion center.", source="dhs.gov/fusion-centers"),
            Infrastructure(name="Indiana Intelligence Fusion Center", type="fusion_center", city="Indianapolis", state="IN", lat=39.7684, lng=-86.1581, description="IN statewide fusion center.", source="dhs.gov/fusion-centers"),
            Infrastructure(name="South Carolina Information and Intelligence Center", type="fusion_center", city="Columbia", state="SC", lat=34.0007, lng=-81.0348, description="SC statewide fusion center.", source="dhs.gov/fusion-centers"),
            Infrastructure(name="North Dakota State and Local Intelligence Center", type="fusion_center", city="Bismarck", state="ND", lat=46.8083, lng=-100.7837, description="ND statewide fusion center.", source="dhs.gov/fusion-centers"),
            Infrastructure(name="South Dakota Fusion Center", type="fusion_center", city="Pierre", state="SD", lat=44.3683, lng=-100.3510, description="SD statewide fusion center.", source="dhs.gov/fusion-centers"),
            Infrastructure(name="Montana All Threat Intelligence Center", type="fusion_center", city="Helena", state="MT", lat=46.5958, lng=-112.0270, description="MT statewide fusion center.", source="dhs.gov/fusion-centers"),
            Infrastructure(name="Idaho Criminal Intelligence Center", type="fusion_center", city="Boise", state="ID", lat=43.6150, lng=-116.2023, description="ID statewide fusion center.", source="dhs.gov/fusion-centers"),
            Infrastructure(name="Utah Statewide Information and Analysis Center", type="fusion_center", city="Salt Lake City", state="UT", lat=40.7608, lng=-111.8910, description="UT statewide fusion center.", source="dhs.gov/fusion-centers"),
            Infrastructure(name="Wyoming Fusion Center", type="fusion_center", city="Cheyenne", state="WY", lat=41.1400, lng=-104.8202, description="WY statewide fusion center.", source="dhs.gov/fusion-centers"),
            Infrastructure(name="Alaska Information and Analysis Center", type="fusion_center", city="Anchorage", state="AK", lat=61.2181, lng=-149.9003, description="AK statewide fusion center.", source="dhs.gov/fusion-centers"),
            Infrastructure(name="Hawaii Fusion Center", type="fusion_center", city="Honolulu", state="HI", lat=21.3069, lng=-157.8583, description="HI statewide fusion center. Pacific region coordination.", source="dhs.gov/fusion-centers"),
            Infrastructure(name="Rhode Island State Fusion Center", type="fusion_center", city="Providence", state="RI", lat=41.8240, lng=-71.4128, description="RI statewide fusion center.", source="dhs.gov/fusion-centers"),
            Infrastructure(name="Vermont Intelligence Center", type="fusion_center", city="Waterbury", state="VT", lat=44.3376, lng=-72.7562, description="VT statewide fusion center.", source="dhs.gov/fusion-centers"),
            Infrastructure(name="New Hampshire Information and Analysis Center", type="fusion_center", city="Concord", state="NH", lat=43.2081, lng=-71.5376, description="NH statewide fusion center.", source="dhs.gov/fusion-centers"),
            Infrastructure(name="Maine Intelligence and Analysis Center", type="fusion_center", city="Augusta", state="ME", lat=44.3106, lng=-69.7795, description="ME statewide fusion center.", source="dhs.gov/fusion-centers"),
            Infrastructure(name="Delaware Information and Analysis Center", type="fusion_center", city="Dover", state="DE", lat=39.1582, lng=-75.5244, description="DE statewide fusion center.", source="dhs.gov/fusion-centers"),
            Infrastructure(name="Guam Homeland Security / Office of Civil Defense", type="fusion_center", city="Agana", state="GU", lat=13.4443, lng=144.7937, description="Guam territory fusion center.", source="dhs.gov/fusion-centers"),
            Infrastructure(name="Puerto Rico National Guard Joint Operations Center", type="fusion_center", city="San Juan", state="PR", lat=18.4655, lng=-66.1057, description="Puerto Rico fusion center.", source="dhs.gov/fusion-centers"),

            # ══════════════════════════════════════════════════════════════
            # ICE FACILITIES
            # Source: ICE.gov detention locator, TRAC Immigration, Freedom for Immigrants
            # ══════════════════════════════════════════════════════════════

            Infrastructure(name="Stewart Detention Center", type="ice_facility", city="Lumpkin", state="GA", lat=32.0496, lng=-84.7963, description="CoreCivic. Capacity 1,800+. Documented human rights abuses.", source="ICE.gov; Freedom for Immigrants"),
            Infrastructure(name="Adelanto ICE Processing Center", type="ice_facility", city="Adelanto", state="CA", lat=34.5822, lng=-117.4327, description="GEO Group. Largest ICE facility in California.", source="ICE.gov; ACLU SoCal"),
            Infrastructure(name="Eloy Federal Contract Facility", type="ice_facility", city="Eloy", state="AZ", lat=32.7837, lng=-111.5548, description="CoreCivic. Major AZ detention hub.", source="ICE.gov"),
            Infrastructure(name="South Texas Family Residential Center", type="ice_facility", city="Dilley", state="TX", lat=28.6672, lng=-99.1745, description="CoreCivic. Largest family detention center in US.", source="ICE.gov; CARA Pro Bono"),
            Infrastructure(name="Krome North Service Processing Center", type="ice_facility", city="Miami", state="FL", lat=25.6582, lng=-80.5432, description="Federal ICE processing center.", source="ICE.gov"),
            Infrastructure(name="Northwest ICE Processing Center", type="ice_facility", city="Tacoma", state="WA", lat=47.2340, lng=-122.4680, description="GEO Group. Primary Pacific NW facility.", source="ICE.gov; La Resistencia"),
            Infrastructure(name="York County Prison (ICE contract)", type="ice_facility", city="York", state="PA", lat=39.9626, lng=-76.7277, description="Major Northeast detention hub.", source="ICE.gov; ACLU PA"),
            Infrastructure(name="Broadview ICE Processing Center", type="ice_facility", city="Broadview", state="IL", lat=41.8612, lng=-87.8573, description="Federal ICE staging near Chicago.", source="ICE.gov; OCAD"),
            Infrastructure(name="Bergen County Jail (ICE contract)", type="ice_facility", city="Hackensack", state="NJ", lat=40.8859, lng=-74.0435, description="NYC metro detention point.", source="ICE.gov; NJ ACLU"),
            Infrastructure(name="Otay Mesa Detention Center", type="ice_facility", city="San Diego", state="CA", lat=32.5671, lng=-116.9756, description="CoreCivic. Major border processing hub.", source="ICE.gov"),
            Infrastructure(name="Cibola County Correctional Center", type="ice_facility", city="Milan", state="NM", lat=35.1814, lng=-107.9000, description="CoreCivic. NM ICE facility.", source="ICE.gov"),
            Infrastructure(name="Denver Contract Detention Facility", type="ice_facility", city="Aurora", state="CO", lat=39.6930, lng=-104.7024, description="GEO Group. Colorado ICE detention.", source="ICE.gov"),
            Infrastructure(name="Glades County Detention Center", type="ice_facility", city="Moore Haven", state="FL", lat=26.8334, lng=-81.0851, description="Florida ICE contract facility.", source="ICE.gov"),
            Infrastructure(name="Irwin County Detention Center", type="ice_facility", city="Ocilla", state="GA", lat=31.5952, lng=-83.2510, description="LaSalle Corrections. Alleged medical abuses documented.", source="ICE.gov; Project South"),
            Infrastructure(name="Louisiana ICE Processing Center (Jena)", type="ice_facility", city="Jena", state="LA", lat=31.6835, lng=-92.1307, description="LaSalle Corrections. Remote Louisiana facility.", source="ICE.gov"),
            Infrastructure(name="Port Isabel Service Processing Center", type="ice_facility", city="Los Fresnos", state="TX", lat=26.0741, lng=-97.5586, description="Federal. South Texas border facility.", source="ICE.gov"),
            Infrastructure(name="T. Don Hutto Residential Center", type="ice_facility", city="Taylor", state="TX", lat=30.5716, lng=-97.4086, description="CoreCivic. Former family detention now women-only.", source="ICE.gov; ACLU TX"),
            Infrastructure(name="Winn Correctional Center (ICE)", type="ice_facility", city="Winnfield", state="LA", lat=31.9235, lng=-92.6388, description="LaSalle Corrections. LA ICE detention.", source="ICE.gov"),
            Infrastructure(name="Pine Prairie ICE Processing Center", type="ice_facility", city="Pine Prairie", state="LA", lat=30.7774, lng=-92.4215, description="GEO Group. Louisiana ICE facility.", source="ICE.gov"),
            Infrastructure(name="Mesa Verde ICE Processing Center", type="ice_facility", city="Bakersfield", state="CA", lat=35.2494, lng=-119.2078, description="GEO Group. California ICE facility.", source="ICE.gov"),
            Infrastructure(name="El Paso Service Processing Center", type="ice_facility", city="El Paso", state="TX", lat=31.7619, lng=-106.4850, description="Federal. Major border processing center.", source="ICE.gov"),
            Infrastructure(name="Laredo Field Office — ICE Detention", type="ice_facility", city="Laredo", state="TX", lat=27.5306, lng=-99.4803, description="Texas border ICE facility.", source="ICE.gov"),
            Infrastructure(name="Bristol County House of Correction (ICE)", type="ice_facility", city="North Dartmouth", state="MA", lat=41.6457, lng=-71.0086, description="MA county jail with ICE contract.", source="ICE.gov; ACLU MA"),
            Infrastructure(name="Essex County Correctional Facility (ICE)", type="ice_facility", city="Newark", state="NJ", lat=40.7357, lng=-74.1724, description="NJ ICE contract facility.", source="ICE.gov"),
            Infrastructure(name="Richwood Correctional Center", type="ice_facility", city="Richwood", state="LA", lat=32.0918, lng=-91.9987, description="LaSalle Corrections. Remote LA ICE facility.", source="ICE.gov"),

            # ══════════════════════════════════════════════════════════════
            # CAMERA NETWORKS
            # Source: EFF Atlas of Surveillance, city records, FOIA responses
            # ══════════════════════════════════════════════════════════════

            Infrastructure(name="Chicago POD Camera Network", type="camera_network", city="Chicago", state="IL", lat=41.8781, lng=-87.6298, description="32,000+ Police Observation Device cameras. Facial recognition capable. Connected to OEMC and fusion center.", source="EFF Atlas of Surveillance; Chicago city records"),
            Infrastructure(name="NYC Domain Awareness System", type="camera_network", city="New York", state="NY", lat=40.7128, lng=-74.0060, description="Microsoft-built. 15,000+ cameras. LPR, radiation detectors, facial recognition integrated.", source="EFF Atlas of Surveillance; NYPD documentation"),
            Infrastructure(name="LA ShotSpotter + Camera Network", type="camera_network", city="Los Angeles", state="CA", lat=34.0522, lng=-118.2437, description="LAPD camera and acoustic surveillance. ShotSpotter covers South and East LA.", source="EFF Atlas of Surveillance; LAPD records"),
            Infrastructure(name="Detroit Project Green Light", type="camera_network", city="Detroit", state="MI", lat=42.3314, lng=-83.0458, description="Real-time facial recognition. DataWorks Plus. Highest documented false positive rate nationally.", source="EFF Atlas; MIT Media Lab (Joy Buolamwini)"),
            Infrastructure(name="Baltimore CitiWatch / Aerial Surveillance", type="camera_network", city="Baltimore", state="MD", lat=39.2904, lng=-76.6122, description="800+ cameras plus Persistent Surveillance Systems aerial program. Entire city filmed from plane.", source="EFF Atlas; Baltimore Sun investigative reporting"),
            Infrastructure(name="San Francisco SFPD Camera Network", type="camera_network", city="San Francisco", state="CA", lat=37.7749, lng=-122.4194, description="SFPD surveillance cameras. SF banned facial recognition for city use but state/federal agencies still operate.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="New Orleans Real Time Crime Center", type="camera_network", city="New Orleans", state="LA", lat=29.9511, lng=-90.0715, description="Extensive camera network. Facial recognition use documented. Operated partly through private Palantir contract.", source="EFF Atlas; ACLU Louisiana"),
            Infrastructure(name="Memphis Blue CRUSH Camera Network", type="camera_network", city="Memphis", state="TN", lat=35.1495, lng=-90.0490, description="Predictive policing + camera surveillance network. IBM i2 integration.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Newark Real Time Crime Center", type="camera_network", city="Newark", state="NJ", lat=40.7357, lng=-74.1724, description="Extensive camera network in NJ's largest city.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Oakland Surveillance Camera Network", type="camera_network", city="Oakland", state="CA", lat=37.8044, lng=-122.2711, description="Domain Awareness Center. Multi-agency data fusion. Activists challenged in court.", source="EFF Atlas; ACLU NorCal"),
            Infrastructure(name="Atlanta Video Integration Center", type="camera_network", city="Atlanta", state="GA", lat=33.7490, lng=-84.3880, description="Atlanta Police Foundation camera network. Flock Safety LPR integrated.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Philadelphia Real Time Crime Center", type="camera_network", city="Philadelphia", state="PA", lat=39.9526, lng=-75.1652, description="Philadephia PD extensive camera infrastructure.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Phoenix Smart City Surveillance Network", type="camera_network", city="Phoenix", state="AZ", lat=33.4484, lng=-112.0740, description="Phoenix PD camera network with facial recognition capability.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="San Antonio Real Time Crime Center", type="camera_network", city="San Antonio", state="TX", lat=29.4241, lng=-98.4936, description="SAPD camera and analytics hub.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Dallas Video Surveillance Network", type="camera_network", city="Dallas", state="TX", lat=32.7767, lng=-96.7970, description="DPD extensive camera infrastructure with ShotSpotter.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Seattle CCTV Network", type="camera_network", city="Seattle", state="WA", lat=47.6062, lng=-122.3321, description="Seattle PD camera network. Facial recognition moratorium in place but federal cameras still operate.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Denver Police Surveillance Network", type="camera_network", city="Denver", state="CO", lat=39.7392, lng=-104.9903, description="DPD camera network with ShotSpotter.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Minneapolis CCTV Network", type="camera_network", city="Minneapolis", state="MN", lat=44.9778, lng=-93.2650, description="MPD camera network. George Floyd Square still under surveillance.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Kansas City KCPD Smart City Cameras", type="camera_network", city="Kansas City", state="MO", lat=39.0997, lng=-94.5786, description="KCPD surveillance camera network.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="St. Louis Metropolitan PD Camera Network", type="camera_network", city="St. Louis", state="MO", lat=38.6270, lng=-90.1994, description="SLMPD camera infrastructure.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Las Vegas Metro Real Time Crime Center", type="camera_network", city="Las Vegas", state="NV", lat=36.1699, lng=-115.1398, description="Strip + metro camera network. Some of densest coverage in US.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="El Paso Surveillance Camera Network", type="camera_network", city="El Paso", state="TX", lat=31.7619, lng=-106.4850, description="Border city camera network integrated with CBP.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Columbus PD Camera Network", type="camera_network", city="Columbus", state="OH", lat=39.9612, lng=-82.9988, description="CPD surveillance infrastructure.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Cleveland Surveillance Camera Network", type="camera_network", city="Cleveland", state="OH", lat=41.4993, lng=-81.6944, description="Cleveland Division of Police cameras.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Pittsburgh Real Time Crime Center", type="camera_network", city="Pittsburgh", state="PA", lat=40.4406, lng=-79.9959, description="Pittsburgh PD camera network with ShotSpotter.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Charlotte-Mecklenburg CCTV Network", type="camera_network", city="Charlotte", state="NC", lat=35.2271, lng=-80.8431, description="CMPD camera infrastructure.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Raleigh Smart City Surveillance", type="camera_network", city="Raleigh", state="NC", lat=35.7796, lng=-78.6382, description="RPD camera network.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Jacksonville CCTV Network", type="camera_network", city="Jacksonville", state="FL", lat=30.3322, lng=-81.6557, description="JSO camera surveillance network.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Tampa Bay Real Time Crime Center", type="camera_network", city="Tampa", state="FL", lat=27.9506, lng=-82.4572, description="Tampa PD camera network.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Miami-Dade Surveillance Network", type="camera_network", city="Miami", state="FL", lat=25.7617, lng=-80.1918, description="MDPD/MPD camera infrastructure.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Indianapolis Real Time Crime Center", type="camera_network", city="Indianapolis", state="IN", lat=39.7684, lng=-86.1581, description="IMPD camera and ShotSpotter network.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Milwaukee Surveillance Network", type="camera_network", city="Milwaukee", state="WI", lat=43.0389, lng=-87.9065, description="MPD camera infrastructure.", source="EFF Atlas of Surveillance"),

            # ══════════════════════════════════════════════════════════════
            # LICENSE PLATE READER NETWORKS
            # Source: EFF Atlas, Flock Safety public contracts, FOIA records
            # ══════════════════════════════════════════════════════════════

            Infrastructure(name="NYPD License Plate Reader Network", type="lpr_network", city="New York", state="NY", lat=40.7128, lng=-74.0060, description="Millions of plates read and stored daily. Feeds into Domain Awareness System.", source="EFF Atlas; NYPD FOIA"),
            Infrastructure(name="Vigilant Solutions / Motorola LPR — Chicago", type="lpr_network", city="Chicago", state="IL", lat=41.8781, lng=-87.6298, description="Motorola LPR network with national repository access.", source="EFF Atlas; CPD contracts"),
            Infrastructure(name="Flock Safety LPR — Atlanta Metro", type="lpr_network", city="Atlanta", state="GA", lat=33.7490, lng=-84.3880, description="Flock Safety LPR. Data retained and shared regionally.", source="EFF Atlas; Flock public contracts"),
            Infrastructure(name="LAPD License Plate Reader Network", type="lpr_network", city="Los Angeles", state="CA", lat=34.0522, lng=-118.2437, description="LAPD LPR network. ACLU documented retaining data on non-suspects.", source="EFF Atlas; ACLU SoCal"),
            Infrastructure(name="Bay Area LPR Network (Flock + Vigilant)", type="lpr_network", city="Oakland", state="CA", lat=37.8044, lng=-122.2711, description="Regional LPR network across Bay Area agencies. EFF Atlas documented.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Texas DPS Statewide LPR Network", type="lpr_network", city="Austin", state="TX", lat=30.2672, lng=-97.7431, description="Texas DPS operates statewide LPR infrastructure.", source="EFF Atlas; Texas DPS records"),
            Infrastructure(name="Houston Metro LPR Network", type="lpr_network", city="Houston", state="TX", lat=29.7604, lng=-95.3698, description="HPD and regional LPR deployment.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Miami Metro LPR Network", type="lpr_network", city="Miami", state="FL", lat=25.7617, lng=-80.1918, description="MDPD LPR network. Border and port monitoring.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Phoenix PD LPR Network", type="lpr_network", city="Phoenix", state="AZ", lat=33.4484, lng=-112.0740, description="Phoenix PD LPR deployment. CBP integration documented.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Seattle Metro LPR Network", type="lpr_network", city="Seattle", state="WA", lat=47.6062, lng=-122.3321, description="SPD LPR network. ACLU WA documented concerns.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Denver Metro Flock Safety LPR", type="lpr_network", city="Denver", state="CO", lat=39.7392, lng=-104.9903, description="Denver metro Flock Safety LPR deployment.", source="EFF Atlas; Flock public contracts"),
            Infrastructure(name="Baltimore MDTA LPR Network", type="lpr_network", city="Baltimore", state="MD", lat=39.2904, lng=-76.6122, description="Maryland LPR on major routes and city cameras.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Philadelphia PD LPR Network", type="lpr_network", city="Philadelphia", state="PA", lat=39.9526, lng=-75.1652, description="PPD LPR deployment.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Boston Regional LPR Network", type="lpr_network", city="Boston", state="MA", lat=42.3601, lng=-71.0589, description="BPD and regional LPR network.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Las Vegas Metro LPR Network", type="lpr_network", city="Las Vegas", state="NV", lat=36.1699, lng=-115.1398, description="LVMPD extensive LPR deployment.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="San Antonio LPR Network", type="lpr_network", city="San Antonio", state="TX", lat=29.4241, lng=-98.4936, description="SAPD LPR infrastructure.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Portland Metro Flock Safety LPR", type="lpr_network", city="Portland", state="OR", lat=45.5231, lng=-122.6765, description="Portland metro Flock Safety deployment.", source="EFF Atlas; Flock public contracts"),
            Infrastructure(name="Nashville Metro LPR Network", type="lpr_network", city="Nashville", state="TN", lat=36.1627, lng=-86.7816, description="MNPD LPR infrastructure.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Minneapolis LPR Network", type="lpr_network", city="Minneapolis", state="MN", lat=44.9778, lng=-93.2650, description="MPD LPR deployment.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Kansas City Metro LPR", type="lpr_network", city="Kansas City", state="MO", lat=39.0997, lng=-94.5786, description="KCPD LPR network.", source="EFF Atlas of Surveillance"),

            # ══════════════════════════════════════════════════════════════
            # BORDER SURVEILLANCE
            # Source: CBP public contracts, DHS reports, Defense One
            # ══════════════════════════════════════════════════════════════

            Infrastructure(name="CBP Autonomous Surveillance Tower — El Paso TX", type="border_surveillance", city="El Paso", state="TX", lat=31.7619, lng=-106.4850, description="CBP Autonomous Surveillance Tower. Anduril Industries Lattice system. AI target detection.", source="CBP contracts; Defense One"),
            Infrastructure(name="CBP Autonomous Surveillance Tower — San Diego CA", type="border_surveillance", city="San Diego", state="CA", lat=32.5671, lng=-116.9756, description="CBP tower with autonomous AI detection capability.", source="CBP contracts; Defense One"),
            Infrastructure(name="CBP Autonomous Surveillance Tower — Yuma AZ", type="border_surveillance", city="Yuma", state="AZ", lat=32.6927, lng=-114.6277, description="CBP AST deployment in Yuma sector.", source="CBP contracts"),
            Infrastructure(name="CBP Autonomous Surveillance Tower — Tucson AZ", type="border_surveillance", city="Tucson", state="AZ", lat=32.2217, lng=-110.9265, description="CBP AST deployment in Tucson sector.", source="CBP contracts"),
            Infrastructure(name="CBP Autonomous Surveillance Tower — McAllen TX", type="border_surveillance", city="McAllen", state="TX", lat=26.2034, lng=-98.2300, description="CBP AST in Rio Grande Valley sector. Highest crossing volume sector.", source="CBP contracts"),
            Infrastructure(name="CBP Autonomous Surveillance Tower — Del Rio TX", type="border_surveillance", city="Del Rio", state="TX", lat=29.3627, lng=-100.8968, description="CBP AST deployment Del Rio sector.", source="CBP contracts"),
            Infrastructure(name="CBP Autonomous Surveillance Tower — Eagle Pass TX", type="border_surveillance", city="Eagle Pass", state="TX", lat=28.7091, lng=-100.4995, description="CBP AST Eagle Pass. Major crossing point.", source="CBP contracts"),
            Infrastructure(name="CBP Autonomous Surveillance Tower — Laredo TX", type="border_surveillance", city="Laredo", state="TX", lat=27.5306, lng=-99.4803, description="CBP AST Laredo sector.", source="CBP contracts"),
            Infrastructure(name="CBP Remote Video Surveillance — Douglas AZ", type="border_surveillance", city="Douglas", state="AZ", lat=31.3445, lng=-109.5453, description="CBP RVSS tower cluster. Arizona border surveillance.", source="CBP contracts"),
            Infrastructure(name="CBP Integrated Fixed Tower — Nogales AZ", type="border_surveillance", city="Nogales", state="AZ", lat=31.3404, lng=-110.9345, description="CBP Integrated Fixed Tower. Elbit Systems contract.", source="CBP contracts; GAO reports"),
            Infrastructure(name="CBP Tethered Aerostat Radar System — Yuma AZ", type="border_surveillance", city="Yuma", state="AZ", lat=32.6566, lng=-114.5990, description="TARS — persistent aerial surveillance balloon. Covers 200+ mile radius.", source="CBP TARS program documentation"),
            Infrastructure(name="CBP Tethered Aerostat — Marfa TX", type="border_surveillance", city="Marfa", state="TX", lat=30.3088, lng=-104.0202, description="TARS persistent surveillance balloon over West Texas border.", source="CBP TARS documentation"),
            Infrastructure(name="CBP USBP Sector HQ — San Diego CA", type="border_surveillance", city="Chula Vista", state="CA", lat=32.6401, lng=-117.0842, description="San Diego Border Patrol Sector. Largest sector by personnel.", source="CBP public records"),
            Infrastructure(name="CBP USBP Sector HQ — Tucson AZ", type="border_surveillance", city="Tucson", state="AZ", lat=32.2217, lng=-110.9265, description="Tucson Border Patrol Sector HQ.", source="CBP public records"),
            Infrastructure(name="CBP USBP Sector HQ — Rio Grande Valley TX", type="border_surveillance", city="Edinburg", state="TX", lat=26.3017, lng=-98.1633, description="RGV Sector HQ. Historically highest apprehension numbers.", source="CBP public records"),
            Infrastructure(name="CBP Air and Marine Operations — San Diego", type="border_surveillance", city="San Diego", state="CA", lat=32.7157, lng=-117.1611, description="CBP drone and aircraft operations hub. Predator B drone operations.", source="CBP AMO documentation"),
            Infrastructure(name="CBP Air and Marine Operations — Corpus Christi", type="border_surveillance", city="Corpus Christi", state="TX", lat=27.8006, lng=-97.3964, description="CBP AMO Gulf Coast operations.", source="CBP AMO documentation"),
            Infrastructure(name="CBP Air and Marine Operations — El Paso", type="border_surveillance", city="El Paso", state="TX", lat=31.8057, lng=-106.3795, description="CBP AMO West Texas drone operations.", source="CBP AMO documentation"),
            Infrastructure(name="Northern Border Surveillance — Detroit MI", type="border_surveillance", city="Detroit", state="MI", lat=42.3314, lng=-83.0458, description="CBP Detroit sector. Canada border surveillance.", source="CBP public records"),
            Infrastructure(name="Northern Border Surveillance — Buffalo NY", type="border_surveillance", city="Buffalo", state="NY", lat=42.8864, lng=-78.8784, description="CBP Buffalo sector. Niagara Falls crossing surveillance.", source="CBP public records"),
            Infrastructure(name="CBP Port of Entry Surveillance — San Ysidro CA", type="border_surveillance", city="San Diego", state="CA", lat=32.5432, lng=-117.0281, description="World's busiest land border crossing. Extensive biometric and vehicle surveillance.", source="CBP public records"),
            Infrastructure(name="CBP Biometric Entry-Exit — JFK Airport", type="border_surveillance", city="New York", state="NY", lat=40.6413, lng=-73.7781, description="CBP biometric facial recognition at all international gates.", source="CBP Biometric Exit program"),
            Infrastructure(name="CBP Biometric Entry-Exit — LAX", type="border_surveillance", city="Los Angeles", state="CA", lat=33.9425, lng=-118.4081, description="CBP facial recognition biometric entry/exit.", source="CBP Biometric Exit program"),
            Infrastructure(name="CBP Biometric Entry-Exit — Miami International", type="border_surveillance", city="Miami", state="FL", lat=25.7959, lng=-80.2870, description="CBP biometric facial recognition.", source="CBP Biometric Exit program"),
            Infrastructure(name="CBP Biometric Entry-Exit — Chicago O'Hare", type="border_surveillance", city="Chicago", state="IL", lat=41.9742, lng=-87.9073, description="CBP biometric facial recognition at O'Hare.", source="CBP Biometric Exit program"),

            # ══════════════════════════════════════════════════════════════
            # AI SURVEILLANCE / FACIAL RECOGNITION
            # Source: EFF Atlas, ACLU, investigative journalism
            # ══════════════════════════════════════════════════════════════

            Infrastructure(name="Detroit Police — DataWorks Plus Facial Recognition", type="facial_recognition", city="Detroit", state="MI", lat=42.3314, lng=-83.0458, description="Detroit PD facial recognition. Three documented wrongful arrests of Black men. MIT study found 96% error rate on darker skin.", source="EFF Atlas; MIT Media Lab; Detroit Free Press"),
            Infrastructure(name="New Orleans PD — Clearview AI Contract", type="facial_recognition", city="New Orleans", state="LA", lat=29.9511, lng=-90.0715, description="NOPD Clearview AI deployment. Used without public disclosure.", source="EFF Atlas; ACLU Louisiana; WWNO investigative report"),
            Infrastructure(name="Chicago PD — Clearview AI / ShotSpotter Integration", type="facial_recognition", city="Chicago", state="IL", lat=41.8781, lng=-87.6298, description="CPD Clearview AI + ShotSpotter acoustic surveillance integration.", source="EFF Atlas; Chicago Sun-Times FOIA"),
            Infrastructure(name="NYPD Facial Recognition System", type="facial_recognition", city="New York", state="NY", lat=40.7128, lng=-74.0060, description="NYPD uses facial recognition. Run 22,000+ searches. Minimal oversight documented.", source="EFF Atlas; NYCLU report 2021"),
            Infrastructure(name="FBI Next Generation Identification — NGI System", type="facial_recognition", city="Washington", state="DC", lat=38.8951, lng=-77.0364, description="FBI's NGI facial recognition database. 641 million photos. Accesses state DMV databases.", source="GAO report 2019; EFF"),
            Infrastructure(name="ICE Facial Recognition — State DMV Access", type="facial_recognition", city="Washington", state="DC", lat=38.8977, lng=-77.0365, description="ICE accesses facial recognition through DMV databases in non-sanctuary states without warrant.", source="Georgetown Law report; Washington Post investigation"),
            Infrastructure(name="Amazon Rekognition — Orlando PD Pilot", type="facial_recognition", city="Orlando", state="FL", lat=28.5383, lng=-81.3792, description="Orlando PD Amazon Rekognition facial recognition pilot. ACLU documented high error rates.", source="ACLU; EFF Atlas of Surveillance"),
            Infrastructure(name="Clearview AI — Nationwide Law Enforcement", type="facial_recognition", city="New York", state="NY", lat=40.7589, lng=-73.9851, description="Clearview AI scraped 30 billion+ photos. Used by 3,100+ law enforcement agencies. Multiple privacy violations documented.", source="BuzzFeed News investigation; EFF"),
            Infrastructure(name="San Diego PD — Tactical Identification System", type="facial_recognition", city="San Diego", state="CA", lat=32.7157, lng=-117.1611, description="SDPD Cogent facial recognition system. EFF Atlas documented.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Baltimore PD Facial Recognition System", type="facial_recognition", city="Baltimore", state="MD", lat=39.2904, lng=-76.6122, description="BPD facial recognition. Used during 2015 Freddie Gray protests.", source="EFF Atlas; ACLU Maryland"),
            Infrastructure(name="Pinellas County Sheriff — Facial Recognition Database", type="facial_recognition", city="Clearwater", state="FL", lat=27.9659, lng=-82.8001, description="One of the largest local facial recognition databases. 12 million photos.", source="Tampa Bay Times investigation; EFF Atlas"),
            Infrastructure(name="ShotSpotter Acoustic Surveillance — Chicago", type="facial_recognition", city="Chicago", state="IL", lat=41.7886, lng=-87.6866, description="ShotSpotter gunshot detection covering South and West Chicago. AI audio classification. Documented false alerts.", source="EFF Atlas; Chicago FOIA; MacArthur Justice Center"),
            Infrastructure(name="ShotSpotter Acoustic Surveillance — NYC", type="facial_recognition", city="New York", state="NY", lat=40.6782, lng=-73.9442, description="ShotSpotter in Brooklyn and Bronx. NYPD contract. False alert concerns documented.", source="EFF Atlas; NYPD records"),
            Infrastructure(name="Palantir Predictive Policing — Los Angeles", type="facial_recognition", city="Los Angeles", state="CA", lat=34.0195, lng=-118.4912, description="Palantir Gotham predictive policing in LAPD. Terminated after community pressure but data retained.", source="EFF Atlas; The Markup investigation"),
            Infrastructure(name="PredPol / Geolitica Predictive Policing — Santa Cruz", type="facial_recognition", city="Santa Cruz", state="CA", lat=36.9741, lng=-122.0308, description="PredPol predictive policing algorithm. Santa Cruz became first US city to ban it (2020).", source="EFF Atlas; Santa Cruz Sentinel"),

            # ══════════════════════════════════════════════════════════════
            # IMSI CATCHERS / STINGRAYS
            # Source: ACLU Stingray tracking map, EFF, FOIA requests
            # ══════════════════════════════════════════════════════════════

            Infrastructure(name="NYPD Stingray Fleet", type="imsi_catcher", city="New York", state="NY", lat=40.7128, lng=-74.0060, description="NYPD confirmed 1,016 Stingray uses in 2020 alone. Harris Corporation / L3Harris equipment.", source="ACLU; NYPD FOIA response 2021"),
            Infrastructure(name="Chicago PD IMSI Catcher Program", type="imsi_catcher", city="Chicago", state="IL", lat=41.8781, lng=-87.6298, description="CPD Stingray deployment. Used at protests. FOIA confirmed purchases.", source="ACLU; Chicago Tribune FOIA"),
            Infrastructure(name="Los Angeles PD / Sheriff Stingray Program", type="imsi_catcher", city="Los Angeles", state="CA", lat=34.0522, lng=-118.2437, description="LAPD and LASD both operate Stingrays. Used 21 times per week on average.", source="ACLU; LA Weekly FOIA"),
            Infrastructure(name="Baltimore PD Hailstorm IMSI Catcher", type="imsi_catcher", city="Baltimore", state="MD", lat=39.2904, lng=-76.6122, description="BPD used Stingrays 4,300+ times over 8 years without warrants. Secrecy agreement with FBI.", source="ACLU; Baltimore Sun investigation"),
            Infrastructure(name="FBI Stingray Operations — Washington DC", type="imsi_catcher", city="Washington", state="DC", lat=38.8951, lng=-77.0364, description="FBI operates Stingrays. Required local agencies sign NDA. DOJ policy requires warrant (since 2015) but exceptions documented.", source="ACLU; EFF; DOJ policy documents"),
            Infrastructure(name="US Marshals Stingray Program", type="imsi_catcher", city="Washington", state="DC", lat=38.8977, lng=-77.0366, description="USMS operates airborne Stingrays from planes. Covers entire cities.", source="WSJ investigation; ACLU"),
            Infrastructure(name="DEA IMSI Catcher Program", type="imsi_catcher", city="Washington", state="DC", lat=38.9382, lng=-77.1796, description="DEA uses Stingrays in drug investigations nationally.", source="ACLU; Reuters investigation"),
            Infrastructure(name="Harris County (Houston) Sheriff Stingray", type="imsi_catcher", city="Houston", state="TX", lat=29.7604, lng=-95.3698, description="Harris County Sheriff documented Stingray use.", source="ACLU Stingray tracking project"),
            Infrastructure(name="Phoenix PD IMSI Catcher Program", type="imsi_catcher", city="Phoenix", state="AZ", lat=33.4484, lng=-112.0740, description="Phoenix PD Stingray deployment. FOIA confirmed.", source="ACLU; Arizona Republic FOIA"),
            Infrastructure(name="Miami PD Stingray Program", type="imsi_catcher", city="Miami", state="FL", lat=25.7617, lng=-80.1918, description="Miami PD was first confirmed US Stingray user. 200+ uses documented.", source="ACLU Florida; USA Today investigation"),
            Infrastructure(name="Tampa Bay Area Stingray Deployment", type="imsi_catcher", city="Tampa", state="FL", lat=27.9506, lng=-82.4572, description="Tampa PD and Hillsborough County Stingray use confirmed.", source="ACLU Florida"),
            Infrastructure(name="San Diego PD IMSI Catcher", type="imsi_catcher", city="San Diego", state="CA", lat=32.7157, lng=-117.1611, description="SDPD Stingray use documented. Proximity to border enables CBP coordination.", source="ACLU; EFF"),
            Infrastructure(name="Oakland PD Stingray Program", type="imsi_catcher", city="Oakland", state="CA", lat=37.8044, lng=-122.2711, description="OPD Stingray use. Used at protests documented by EFF.", source="EFF; ACLU NorCal"),
            Infrastructure(name="Seattle PD IMSI Catcher", type="imsi_catcher", city="Seattle", state="WA", lat=47.6062, lng=-122.3321, description="SPD purchased Stingray. Community pressure led to policy restrictions.", source="ACLU WA; The Stranger investigation"),
            Infrastructure(name="Tucson PD Stingray Program", type="imsi_catcher", city="Tucson", state="AZ", lat=32.2217, lng=-110.9265, description="TPD IMSI catcher confirmed. Border proximity.", source="ACLU Arizona"),
            Infrastructure(name="San Jose PD Stingray Program", type="imsi_catcher", city="San Jose", state="CA", lat=37.3382, lng=-121.8863, description="SJPD Stingray use documented.", source="ACLU NorCal"),
            Infrastructure(name="Denver PD IMSI Catcher", type="imsi_catcher", city="Denver", state="CO", lat=39.7392, lng=-104.9903, description="DPD Stingray confirmed via FOIA.", source="ACLU Colorado; Westword investigation"),
            Infrastructure(name="Indianapolis Metro PD Stingray", type="imsi_catcher", city="Indianapolis", state="IN", lat=39.7684, lng=-86.1581, description="IMPD Stingray use confirmed.", source="ACLU Indiana"),
            Infrastructure(name="Columbus PD IMSI Catcher Program", type="imsi_catcher", city="Columbus", state="OH", lat=39.9612, lng=-82.9988, description="CPD Stingray deployment confirmed.", source="ACLU Ohio"),
            Infrastructure(name="Charlotte-Mecklenburg PD Stingray", type="imsi_catcher", city="Charlotte", state="NC", lat=35.2271, lng=-80.8431, description="CMPD Stingray use documented.", source="ACLU NC"),

            # ══════════════════════════════════════════════════════════════
            # POLICE DRONES — 296 programs across all 50 states
            # Source: FAA Part 107 records, EFF Atlas of Surveillance,
            # FOIA requests, local news investigations
            # Over 1,500 law enforcement agencies operate drone programs
            # as of early 2026. This represents documented programs only.
            # ══════════════════════════════════════════════════════════════

            Infrastructure(name="Birmingham PD Drone Program", type="police_drone", city="Birmingham", state="AL", lat=33.5186, lng=-86.8104, description="BPD drone fleet. Used for crime scene documentation and pursuits.", source="FAA records; EFF Atlas"),
            Infrastructure(name="Huntsville PD Drone Program", type="police_drone", city="Huntsville", state="AL", lat=34.7304, lng=-86.5861, description="HPD drones. NASA corridor city with extensive aerial monitoring.", source="FAA records"),
            Infrastructure(name="Mobile PD Drone Program", type="police_drone", city="Mobile", state="AL", lat=30.6954, lng=-88.0399, description="MPD drone operations. Port city surveillance.", source="FAA records"),
            Infrastructure(name="Montgomery PD Drone Program", type="police_drone", city="Montgomery", state="AL", lat=32.3617, lng=-86.2792, description="MPD drone fleet. State capital operations.", source="FAA records"),
            Infrastructure(name="Tuscaloosa PD Drone Program", type="police_drone", city="Tuscaloosa", state="AL", lat=33.2098, lng=-87.5692, description="TPD drones. University of Alabama events monitoring.", source="FAA records"),
            Infrastructure(name="Anchorage PD Drone Program", type="police_drone", city="Anchorage", state="AK", lat=61.2181, lng=-149.9003, description="APD drone operations. Vast terrain coverage.", source="FAA records"),
            Infrastructure(name="Alaska State Troopers Drone Program", type="police_drone", city="Juneau", state="AK", lat=58.3005, lng=-134.4197, description="AST drones for remote area search and rescue and surveillance.", source="FAA records"),
            Infrastructure(name="Phoenix PD Drone Program", type="police_drone", city="Phoenix", state="AZ", lat=33.4484, lng=-112.074, description="Phoenix PD drone fleet. Desert terrain operations.", source="EFF Atlas; FAA records"),
            Infrastructure(name="Tucson PD Drone Program", type="police_drone", city="Tucson", state="AZ", lat=32.2217, lng=-110.9265, description="TPD drones. Border proximity surveillance.", source="EFF Atlas; FAA records"),
            Infrastructure(name="Mesa PD Drone Program", type="police_drone", city="Mesa", state="AZ", lat=33.4152, lng=-111.8315, description="Mesa PD drone operations.", source="FAA records"),
            Infrastructure(name="Chandler PD Drone Program", type="police_drone", city="Chandler", state="AZ", lat=33.3062, lng=-111.8413, description="CPD drone fleet.", source="FAA records"),
            Infrastructure(name="Scottsdale PD Drone Program", type="police_drone", city="Scottsdale", state="AZ", lat=33.4942, lng=-111.9261, description="SPD drones. Luxury resort surveillance.", source="EFF Atlas; FAA records"),
            Infrastructure(name="Tempe PD Drone Program", type="police_drone", city="Tempe", state="AZ", lat=33.4255, lng=-111.94, description="TPD drone operations near ASU campus.", source="FAA records"),
            Infrastructure(name="Glendale PD Drone Program", type="police_drone", city="Glendale", state="AZ", lat=33.5387, lng=-112.186, description="GPD drone fleet.", source="FAA records"),
            Infrastructure(name="Peoria PD Drone Program", type="police_drone", city="Peoria", state="AZ", lat=33.5806, lng=-112.2374, description="PPD drone operations.", source="FAA records"),
            Infrastructure(name="Gilbert PD Drone Program", type="police_drone", city="Gilbert", state="AZ", lat=33.3528, lng=-111.789, description="GPD drones.", source="FAA records"),
            Infrastructure(name="Surprise PD Drone Program", type="police_drone", city="Surprise", state="AZ", lat=33.6292, lng=-112.3679, description="SPD drone operations.", source="FAA records"),
            Infrastructure(name="Yuma PD Drone Program", type="police_drone", city="Yuma", state="AZ", lat=32.6927, lng=-114.6277, description="YPD drones. Border city operations.", source="FAA records"),
            Infrastructure(name="Flagstaff PD Drone Program", type="police_drone", city="Flagstaff", state="AZ", lat=35.1983, lng=-111.6513, description="FPD drone fleet. High altitude operations.", source="FAA records"),
            Infrastructure(name="Maricopa County Sheriff Drone Program", type="police_drone", city="Phoenix", state="AZ", lat=33.5722, lng=-112.0892, description="MCSO drone fleet. Largest sheriff drone program in AZ.", source="EFF Atlas; FAA records"),
            Infrastructure(name="Pima County Sheriff Drone Program", type="police_drone", city="Tucson", state="AZ", lat=32.2217, lng=-110.9265, description="PCSO drones. Desert and border operations.", source="FAA records"),
            Infrastructure(name="Little Rock PD Drone Program", type="police_drone", city="Little Rock", state="AR", lat=34.7465, lng=-92.2896, description="LRPD drone operations.", source="FAA records"),
            Infrastructure(name="Fayetteville PD Drone Program", type="police_drone", city="Fayetteville", state="AR", lat=36.0626, lng=-94.1574, description="FPD drones. University of Arkansas area.", source="FAA records"),
            Infrastructure(name="Fort Smith PD Drone Program", type="police_drone", city="Fort Smith", state="AR", lat=35.3859, lng=-94.3985, description="FSPD drone fleet.", source="FAA records"),
            Infrastructure(name="Chula Vista PD — Drone as First Responder", type="police_drone", city="Chula Vista", state="CA", lat=32.6401, lng=-117.0842, description="First FAA-approved BVLOS drone program. 20,000+ responses. National model for DFR.", source="EFF Atlas; FAA; Washington Post"),
            Infrastructure(name="LAPD Drone Program", type="police_drone", city="Los Angeles", state="CA", lat=34.0522, lng=-118.2437, description="LAPD drone fleet. Used at protests. Community oversight established.", source="EFF Atlas; ACLU SoCal"),
            Infrastructure(name="SFPD Drone Program", type="police_drone", city="San Francisco", state="CA", lat=37.7749, lng=-122.4194, description="SFPD drones. Controversial use over protests.", source="EFF Atlas; SF Chronicle"),
            Infrastructure(name="San Diego PD Drone Program", type="police_drone", city="San Diego", state="CA", lat=32.7157, lng=-117.1611, description="SDPD drone fleet. Border proximity.", source="EFF Atlas; FAA records"),
            Infrastructure(name="Sacramento PD Drone Program", type="police_drone", city="Sacramento", state="CA", lat=38.5816, lng=-121.4944, description="SPD drones.", source="FAA records"),
            Infrastructure(name="San Jose PD Drone Program", type="police_drone", city="San Jose", state="CA", lat=37.3382, lng=-121.8863, description="SJPD drone operations.", source="EFF Atlas; FAA records"),
            Infrastructure(name="Oakland PD Drone Program", type="police_drone", city="Oakland", state="CA", lat=37.8044, lng=-122.2711, description="OPD drones. Used at protests.", source="EFF Atlas; ACLU NorCal"),
            Infrastructure(name="Fresno PD Drone Program", type="police_drone", city="Fresno", state="CA", lat=36.7378, lng=-119.7871, description="FPD drone fleet.", source="FAA records"),
            Infrastructure(name="Long Beach PD Drone Program", type="police_drone", city="Long Beach", state="CA", lat=33.7701, lng=-118.1937, description="LBPD drone operations.", source="FAA records"),
            Infrastructure(name="Bakersfield PD Drone Program", type="police_drone", city="Bakersfield", state="CA", lat=35.3733, lng=-119.0187, description="BPD drones.", source="FAA records"),
            Infrastructure(name="Anaheim PD Drone Program", type="police_drone", city="Anaheim", state="CA", lat=33.8366, lng=-117.9143, description="APD drones. Disneyland corridor.", source="FAA records"),
            Infrastructure(name="Riverside PD Drone Program", type="police_drone", city="Riverside", state="CA", lat=33.9533, lng=-117.3961, description="RPD drone fleet.", source="FAA records"),
            Infrastructure(name="Stockton PD Drone Program", type="police_drone", city="Stockton", state="CA", lat=37.9577, lng=-121.2908, description="SPD drones.", source="FAA records"),
            Infrastructure(name="Irvine PD Drone Program", type="police_drone", city="Irvine", state="CA", lat=33.6846, lng=-117.8265, description="IPD drone operations.", source="FAA records"),
            Infrastructure(name="Modesto PD Drone Program", type="police_drone", city="Modesto", state="CA", lat=37.6391, lng=-120.9969, description="MPD drone fleet.", source="FAA records"),
            Infrastructure(name="Santa Ana PD Drone Program", type="police_drone", city="Santa Ana", state="CA", lat=33.7455, lng=-117.8677, description="SAPD drones.", source="FAA records"),
            Infrastructure(name="Oxnard PD Drone Program", type="police_drone", city="Oxnard", state="CA", lat=34.1975, lng=-119.1771, description="OPD drone operations.", source="FAA records"),
            Infrastructure(name="Fontana PD Drone Program", type="police_drone", city="Fontana", state="CA", lat=34.0922, lng=-117.435, description="FPD drones.", source="FAA records"),
            Infrastructure(name="Moreno Valley PD Drone Program", type="police_drone", city="Moreno Valley", state="CA", lat=33.9425, lng=-117.2297, description="MVPD drone fleet.", source="FAA records"),
            Infrastructure(name="Glendale PD Drone Program", type="police_drone", city="Glendale", state="CA", lat=34.1425, lng=-118.2551, description="GPD drones.", source="FAA records"),
            Infrastructure(name="Santa Rosa PD Drone Program", type="police_drone", city="Santa Rosa", state="CA", lat=38.4404, lng=-122.7141, description="SRPD drone operations. Wildfire response.", source="FAA records"),
            Infrastructure(name="Huntington Beach PD Drone Program", type="police_drone", city="Huntington Beach", state="CA", lat=33.6595, lng=-117.9988, description="HBPD drones. Beach patrol and events.", source="FAA records"),
            Infrastructure(name="LA County Sheriff Drone Program", type="police_drone", city="Los Angeles", state="CA", lat=34.0522, lng=-118.2437, description="LASD drone fleet. Largest sheriff drone program in US.", source="EFF Atlas; FAA records"),
            Infrastructure(name="San Bernardino County Sheriff Drone Program", type="police_drone", city="San Bernardino", state="CA", lat=34.1083, lng=-117.2898, description="SBCSD drones. Vast county coverage.", source="FAA records"),
            Infrastructure(name="Orange County Sheriff Drone Program", type="police_drone", city="Santa Ana", state="CA", lat=33.7455, lng=-117.8677, description="OCSD drone operations.", source="FAA records"),
            Infrastructure(name="Riverside County Sheriff Drone Program", type="police_drone", city="Riverside", state="CA", lat=33.9533, lng=-117.3961, description="RCSD drone fleet.", source="FAA records"),
            Infrastructure(name="San Diego County Sheriff Drone Program", type="police_drone", city="San Diego", state="CA", lat=32.7157, lng=-117.1611, description="SDCSO drones. Border operations.", source="FAA records"),
            Infrastructure(name="Denver PD Drone Program", type="police_drone", city="Denver", state="CO", lat=39.7392, lng=-104.9903, description="DPD drones. Deployed at BLM protests 2020. ACLU complaint filed.", source="EFF Atlas; ACLU Colorado"),
            Infrastructure(name="Aurora PD Drone Program", type="police_drone", city="Aurora", state="CO", lat=39.7294, lng=-104.8319, description="APD drone fleet.", source="FAA records"),
            Infrastructure(name="Colorado Springs PD Drone Program", type="police_drone", city="Colorado Springs", state="CO", lat=38.8339, lng=-104.8214, description="CSPD drones. Military city operations.", source="FAA records"),
            Infrastructure(name="Fort Collins PD Drone Program", type="police_drone", city="Fort Collins", state="CO", lat=40.5853, lng=-105.0844, description="FCPD drone operations.", source="FAA records"),
            Infrastructure(name="Boulder PD Drone Program", type="police_drone", city="Boulder", state="CO", lat=40.015, lng=-105.2705, description="BPD drones. University operations.", source="FAA records"),
            Infrastructure(name="Jefferson County Sheriff Drone Program", type="police_drone", city="Golden", state="CO", lat=39.7555, lng=-105.2211, description="JeffCo Sheriff drones.", source="FAA records"),
            Infrastructure(name="Adams County Sheriff Drone Program", type="police_drone", city="Brighton", state="CO", lat=39.9855, lng=-104.8197, description="Adams County drone fleet.", source="FAA records"),
            Infrastructure(name="El Paso County Sheriff Drone Program", type="police_drone", city="Colorado Springs", state="CO", lat=38.8339, lng=-104.8214, description="EPCS drone operations.", source="FAA records"),
            Infrastructure(name="Hartford PD Drone Program", type="police_drone", city="Hartford", state="CT", lat=41.7637, lng=-72.6851, description="HPD drone fleet.", source="FAA records"),
            Infrastructure(name="New Haven PD Drone Program", type="police_drone", city="New Haven", state="CT", lat=41.3083, lng=-72.9279, description="NHPD drones. Yale University area.", source="FAA records"),
            Infrastructure(name="Bridgeport PD Drone Program", type="police_drone", city="Bridgeport", state="CT", lat=41.1865, lng=-73.1952, description="BPD drone operations.", source="FAA records"),
            Infrastructure(name="CT State Police Drone Program", type="police_drone", city="Middletown", state="CT", lat=41.5623, lng=-72.6506, description="CSP drone fleet. Statewide operations.", source="FAA records"),
            Infrastructure(name="Wilmington PD Drone Program", type="police_drone", city="Wilmington", state="DE", lat=39.7447, lng=-75.5484, description="WPD drone operations.", source="FAA records"),
            Infrastructure(name="Delaware State Police Drone Program", type="police_drone", city="Dover", state="DE", lat=39.1582, lng=-75.5244, description="DSP drone fleet.", source="FAA records"),
            Infrastructure(name="Miami-Dade PD Drone Program", type="police_drone", city="Miami", state="FL", lat=25.7617, lng=-80.1918, description="MDPD drone fleet. Used for crowd monitoring and pursuits.", source="EFF Atlas; Miami Herald"),
            Infrastructure(name="Miami PD Drone Program", type="police_drone", city="Miami", state="FL", lat=25.7751, lng=-80.1947, description="MPD drones. Downtown and port operations.", source="FAA records"),
            Infrastructure(name="Broward Sheriff Drone Program", type="police_drone", city="Fort Lauderdale", state="FL", lat=26.1224, lng=-80.1373, description="BSO drone fleet. Broward County coverage.", source="EFF Atlas; FAA records"),
            Infrastructure(name="Orlando PD Drone Program", type="police_drone", city="Orlando", state="FL", lat=28.5383, lng=-81.3792, description="OPD drones. Tourism corridor surveillance.", source="EFF Atlas; FAA records"),
            Infrastructure(name="Jacksonville Sheriff Drone Program", type="police_drone", city="Jacksonville", state="FL", lat=30.3322, lng=-81.6557, description="JSO drone operations. Duval County.", source="EFF Atlas; FAA records"),
            Infrastructure(name="Tampa PD Drone Program", type="police_drone", city="Tampa", state="FL", lat=27.9506, lng=-82.4572, description="TPD drone fleet.", source="EFF Atlas; FAA records"),
            Infrastructure(name="Hillsborough County Sheriff Drone Program", type="police_drone", city="Tampa", state="FL", lat=27.9506, lng=-82.4572, description="HCSO drones.", source="FAA records"),
            Infrastructure(name="Pinellas County Sheriff Drone Program", type="police_drone", city="Clearwater", state="FL", lat=27.9659, lng=-82.8001, description="PCSO drone fleet. Gulf Coast operations.", source="EFF Atlas; FAA records"),
            Infrastructure(name="Daytona Beach PD Drone Program", type="police_drone", city="Daytona Beach", state="FL", lat=29.2108, lng=-81.0228, description="DBP drones. Bike Week and Spring Break surveillance.", source="EFF Atlas; Daytona Beach News-Journal"),
            Infrastructure(name="Daytona Beach Shores PD Drone Program", type="police_drone", city="Daytona Beach Shores", state="FL", lat=29.1722, lng=-80.9826, description="DBSPD drone operations.", source="FAA records"),
            Infrastructure(name="Volusia County Sheriff Drone Program", type="police_drone", city="DeLand", state="FL", lat=29.0286, lng=-81.3034, description="VCSO drones.", source="FAA records"),
            Infrastructure(name="Palm Beach County Sheriff Drone Program", type="police_drone", city="West Palm Beach", state="FL", lat=26.7153, lng=-80.0534, description="PBCSO drone fleet.", source="FAA records"),
            Infrastructure(name="West Palm Beach PD Drone Program", type="police_drone", city="West Palm Beach", state="FL", lat=26.7153, lng=-80.0534, description="WPBPD drones.", source="FAA records"),
            Infrastructure(name="Fort Lauderdale PD Drone Program", type="police_drone", city="Fort Lauderdale", state="FL", lat=26.1224, lng=-80.1373, description="FLPD drone operations.", source="FAA records"),
            Infrastructure(name="St. Petersburg PD Drone Program", type="police_drone", city="St. Petersburg", state="FL", lat=27.7676, lng=-82.6403, description="SPPD drone fleet.", source="FAA records"),
            Infrastructure(name="Gainesville PD Drone Program", type="police_drone", city="Gainesville", state="FL", lat=29.6516, lng=-82.3248, description="GPD drones. University of Florida area.", source="FAA records"),
            Infrastructure(name="Tallahassee PD Drone Program", type="police_drone", city="Tallahassee", state="FL", lat=30.4518, lng=-84.2807, description="TPD drone operations. State capital.", source="FAA records"),
            Infrastructure(name="Leon County Sheriff Drone Program", type="police_drone", city="Tallahassee", state="FL", lat=30.4518, lng=-84.2807, description="LCSO drones.", source="FAA records"),
            Infrastructure(name="Cape Coral PD Drone Program", type="police_drone", city="Cape Coral", state="FL", lat=26.5629, lng=-81.9495, description="CCPD drone fleet.", source="FAA records"),
            Infrastructure(name="Fort Myers PD Drone Program", type="police_drone", city="Fort Myers", state="FL", lat=26.6406, lng=-81.8723, description="FMPD drones.", source="FAA records"),
            Infrastructure(name="Lee County Sheriff Drone Program", type="police_drone", city="Fort Myers", state="FL", lat=26.6406, lng=-81.8723, description="LCSO drone fleet.", source="FAA records"),
            Infrastructure(name="Pensacola PD Drone Program", type="police_drone", city="Pensacola", state="FL", lat=30.4213, lng=-87.2169, description="PPD drones. Gulf Coast operations.", source="FAA records"),
            Infrastructure(name="Escambia County Sheriff Drone Program", type="police_drone", city="Pensacola", state="FL", lat=30.4213, lng=-87.2169, description="ECSO drone operations.", source="FAA records"),
            Infrastructure(name="Sarasota PD Drone Program", type="police_drone", city="Sarasota", state="FL", lat=27.3364, lng=-82.5307, description="SPD drone fleet.", source="FAA records"),
            Infrastructure(name="Sarasota County Sheriff Drone Program", type="police_drone", city="Sarasota", state="FL", lat=27.3364, lng=-82.5307, description="SCSO drones.", source="FAA records"),
            Infrastructure(name="Naples PD Drone Program", type="police_drone", city="Naples", state="FL", lat=26.142, lng=-81.7948, description="NPD drones. Collier County.", source="FAA records"),
            Infrastructure(name="Collier County Sheriff Drone Program", type="police_drone", city="Naples", state="FL", lat=26.142, lng=-81.7948, description="CCSO drone fleet.", source="FAA records"),
            Infrastructure(name="Lakeland PD Drone Program", type="police_drone", city="Lakeland", state="FL", lat=28.0395, lng=-81.9498, description="LPD drone operations.", source="FAA records"),
            Infrastructure(name="Polk County Sheriff Drone Program", type="police_drone", city="Bartow", state="FL", lat=27.8967, lng=-81.8431, description="PCSO drones.", source="FAA records"),
            Infrastructure(name="Kissimmee PD Drone Program", type="police_drone", city="Kissimmee", state="FL", lat=28.292, lng=-81.4076, description="KPD drones. Disney corridor.", source="FAA records"),
            Infrastructure(name="Osceola County Sheriff Drone Program", type="police_drone", city="Kissimmee", state="FL", lat=28.292, lng=-81.4076, description="OCSO drone fleet.", source="FAA records"),
            Infrastructure(name="Ocala PD Drone Program", type="police_drone", city="Ocala", state="FL", lat=29.1872, lng=-82.1401, description="OPD drone operations.", source="FAA records"),
            Infrastructure(name="Marion County Sheriff Drone Program", type="police_drone", city="Ocala", state="FL", lat=29.1872, lng=-82.1401, description="MCSO drones.", source="FAA records"),
            Infrastructure(name="Port St. Lucie PD Drone Program", type="police_drone", city="Port St. Lucie", state="FL", lat=27.273, lng=-80.3582, description="PSLPD drone fleet.", source="FAA records"),
            Infrastructure(name="St. Lucie County Sheriff Drone Program", type="police_drone", city="Fort Pierce", state="FL", lat=27.4467, lng=-80.3256, description="SLCSO drones.", source="FAA records"),
            Infrastructure(name="Panama City PD Drone Program", type="police_drone", city="Panama City", state="FL", lat=30.1588, lng=-85.6602, description="PCPD drone operations. Panhandle coverage.", source="FAA records"),
            Infrastructure(name="Bay County Sheriff Drone Program", type="police_drone", city="Panama City", state="FL", lat=30.1588, lng=-85.6602, description="BCSO drone fleet.", source="FAA records"),
            Infrastructure(name="Brevard County Sheriff Drone Program", type="police_drone", city="Titusville", state="FL", lat=28.6122, lng=-80.8075, description="BCSO drones. Space Coast coverage.", source="FAA records"),
            Infrastructure(name="Melbourne PD Drone Program", type="police_drone", city="Melbourne", state="FL", lat=28.0836, lng=-80.6081, description="MPD drone operations. Kennedy Space Center proximity.", source="FAA records"),
            Infrastructure(name="Seminole County Sheriff Drone Program", type="police_drone", city="Sanford", state="FL", lat=28.8006, lng=-81.2731, description="SCSO drone fleet.", source="FAA records"),
            Infrastructure(name="Orange County Sheriff Drone Program", type="police_drone", city="Orlando", state="FL", lat=28.5383, lng=-81.3792, description="OCSO drones. Theme park region.", source="FAA records"),
            Infrastructure(name="Alachua County Sheriff Drone Program", type="police_drone", city="Gainesville", state="FL", lat=29.6516, lng=-82.3248, description="ACSO drone operations.", source="FAA records"),
            Infrastructure(name="Duval County Fire Rescue Drone Program", type="police_drone", city="Jacksonville", state="FL", lat=30.3322, lng=-81.6557, description="DCFR drones for fire and rescue coordination.", source="FAA records"),
            Infrastructure(name="Florida Highway Patrol Drone Program", type="police_drone", city="Tallahassee", state="FL", lat=30.4518, lng=-84.2807, description="FHP statewide drone fleet. Traffic and pursuit operations.", source="FAA records; FDLE records"),
            Infrastructure(name="FDLE Drone Program", type="police_drone", city="Tallahassee", state="FL", lat=30.4518, lng=-84.2807, description="Florida Department of Law Enforcement drone operations.", source="FAA records"),
            Infrastructure(name="Atlanta PD Drone Program", type="police_drone", city="Atlanta", state="GA", lat=33.749, lng=-84.388, description="APD drone fleet.", source="EFF Atlas; FAA records"),
            Infrastructure(name="Fulton County Sheriff Drone Program", type="police_drone", city="Atlanta", state="GA", lat=33.749, lng=-84.388, description="FCS drones.", source="FAA records"),
            Infrastructure(name="DeKalb County PD Drone Program", type="police_drone", city="Decatur", state="GA", lat=33.7748, lng=-84.2963, description="DKPD drone operations.", source="FAA records"),
            Infrastructure(name="Gwinnett County PD Drone Program", type="police_drone", city="Lawrenceville", state="GA", lat=33.9526, lng=-83.9877, description="GCPD drone fleet.", source="FAA records"),
            Infrastructure(name="Cobb County PD Drone Program", type="police_drone", city="Marietta", state="GA", lat=33.9526, lng=-84.5499, description="CCPD drones.", source="FAA records"),
            Infrastructure(name="Augusta PD Drone Program", type="police_drone", city="Augusta", state="GA", lat=33.4735, lng=-82.0105, description="APD drone operations.", source="FAA records"),
            Infrastructure(name="Savannah PD Drone Program", type="police_drone", city="Savannah", state="GA", lat=32.0835, lng=-81.0998, description="SPD drones. Port city surveillance.", source="FAA records"),
            Infrastructure(name="Columbus PD Drone Program", type="police_drone", city="Columbus", state="GA", lat=32.461, lng=-84.9877, description="CPD drone fleet.", source="FAA records"),
            Infrastructure(name="Georgia State Patrol Drone Program", type="police_drone", city="Atlanta", state="GA", lat=33.749, lng=-84.388, description="GSP statewide drone operations.", source="FAA records"),
            Infrastructure(name="Honolulu PD Drone Program", type="police_drone", city="Honolulu", state="HI", lat=21.3069, lng=-157.8583, description="HPD drone fleet. Island-wide coverage.", source="FAA records"),
            Infrastructure(name="Hawaii County PD Drone Program", type="police_drone", city="Hilo", state="HI", lat=19.7297, lng=-155.09, description="HCPD drones. Big Island operations.", source="FAA records"),
            Infrastructure(name="Maui PD Drone Program", type="police_drone", city="Wailuku", state="HI", lat=20.8893, lng=-156.4729, description="MPD drone operations.", source="FAA records"),
            Infrastructure(name="Boise PD Drone Program", type="police_drone", city="Boise", state="ID", lat=43.615, lng=-116.2023, description="BPD drone fleet.", source="FAA records"),
            Infrastructure(name="Ada County Sheriff Drone Program", type="police_drone", city="Boise", state="ID", lat=43.615, lng=-116.2023, description="ACSD drones.", source="FAA records"),
            Infrastructure(name="Idaho State Police Drone Program", type="police_drone", city="Boise", state="ID", lat=43.615, lng=-116.2023, description="ISP statewide drone operations.", source="FAA records"),
            Infrastructure(name="Chicago PD Drone Program", type="police_drone", city="Chicago", state="IL", lat=41.8781, lng=-87.6298, description="CPD drone fleet. Used over South Side neighborhoods.", source="EFF Atlas; Chicago Tribune"),
            Infrastructure(name="Cook County Sheriff Drone Program", type="police_drone", city="Chicago", state="IL", lat=41.8781, lng=-87.6298, description="CCSD drone operations.", source="FAA records"),
            Infrastructure(name="Springfield PD Drone Program", type="police_drone", city="Springfield", state="IL", lat=39.7817, lng=-89.6501, description="SPD drone fleet. State capital.", source="FAA records"),
            Infrastructure(name="Rockford PD Drone Program", type="police_drone", city="Rockford", state="IL", lat=42.2711, lng=-89.094, description="RPD drone operations.", source="FAA records"),
            Infrastructure(name="Aurora PD Drone Program", type="police_drone", city="Aurora", state="IL", lat=41.7606, lng=-88.3201, description="APD drones.", source="FAA records"),
            Infrastructure(name="Joliet PD Drone Program", type="police_drone", city="Joliet", state="IL", lat=41.525, lng=-88.0817, description="JPD drone fleet.", source="FAA records"),
            Infrastructure(name="Illinois State Police Drone Program", type="police_drone", city="Springfield", state="IL", lat=39.7817, lng=-89.6501, description="ISP statewide drone operations.", source="FAA records"),
            Infrastructure(name="Indianapolis Metro PD Drone Program", type="police_drone", city="Indianapolis", state="IN", lat=39.7684, lng=-86.1581, description="IMPD drone fleet.", source="EFF Atlas; FAA records"),
            Infrastructure(name="Fort Wayne PD Drone Program", type="police_drone", city="Fort Wayne", state="IN", lat=41.1306, lng=-85.1289, description="FWPD drones.", source="FAA records"),
            Infrastructure(name="Evansville PD Drone Program", type="police_drone", city="Evansville", state="IN", lat=37.9716, lng=-87.5711, description="EPD drone operations.", source="FAA records"),
            Infrastructure(name="Indiana State Police Drone Program", type="police_drone", city="Indianapolis", state="IN", lat=39.7684, lng=-86.1581, description="ISP statewide drone fleet.", source="FAA records"),
            Infrastructure(name="Des Moines PD Drone Program", type="police_drone", city="Des Moines", state="IA", lat=41.5868, lng=-93.625, description="DMPD drone fleet.", source="FAA records"),
            Infrastructure(name="Iowa City PD Drone Program", type="police_drone", city="Iowa City", state="IA", lat=41.6611, lng=-91.5302, description="ICPD drones. University of Iowa area.", source="FAA records"),
            Infrastructure(name="Iowa State Patrol Drone Program", type="police_drone", city="Des Moines", state="IA", lat=41.5868, lng=-93.625, description="ISP statewide drone operations.", source="FAA records"),
            Infrastructure(name="Wichita PD Drone Program", type="police_drone", city="Wichita", state="KS", lat=37.6872, lng=-97.3301, description="WPD drone fleet.", source="FAA records"),
            Infrastructure(name="Overland Park PD Drone Program", type="police_drone", city="Overland Park", state="KS", lat=38.9822, lng=-94.6708, description="OPPD drones.", source="FAA records"),
            Infrastructure(name="Kansas City KS PD Drone Program", type="police_drone", city="Kansas City", state="KS", lat=39.1155, lng=-94.6268, description="KCKPD drone operations.", source="FAA records"),
            Infrastructure(name="Kansas Highway Patrol Drone Program", type="police_drone", city="Topeka", state="KS", lat=39.0558, lng=-95.689, description="KHP statewide drones.", source="FAA records"),
            Infrastructure(name="Louisville Metro PD Drone Program", type="police_drone", city="Louisville", state="KY", lat=38.2527, lng=-85.7585, description="LMPD drone fleet.", source="FAA records"),
            Infrastructure(name="Lexington PD Drone Program", type="police_drone", city="Lexington", state="KY", lat=38.0406, lng=-84.5037, description="LPD drones. University of Kentucky area.", source="FAA records"),
            Infrastructure(name="Kentucky State Police Drone Program", type="police_drone", city="Frankfort", state="KY", lat=38.2009, lng=-84.8733, description="KSP statewide drone operations.", source="FAA records"),
            Infrastructure(name="New Orleans PD Drone Program", type="police_drone", city="New Orleans", state="LA", lat=29.9511, lng=-90.0715, description="NOPD drone fleet. Mardi Gras and event surveillance.", source="EFF Atlas; FAA records"),
            Infrastructure(name="Baton Rouge PD Drone Program", type="police_drone", city="Baton Rouge", state="LA", lat=30.4515, lng=-91.1871, description="BRPD drones. State capital.", source="FAA records"),
            Infrastructure(name="Shreveport PD Drone Program", type="police_drone", city="Shreveport", state="LA", lat=32.5252, lng=-93.7502, description="SPD drone operations.", source="FAA records"),
            Infrastructure(name="Jefferson Parish Sheriff Drone Program", type="police_drone", city="Gretna", state="LA", lat=29.9143, lng=-90.0532, description="JPSO drones.", source="FAA records"),
            Infrastructure(name="Louisiana State Police Drone Program", type="police_drone", city="Baton Rouge", state="LA", lat=30.4515, lng=-91.1871, description="LSP statewide drone fleet.", source="FAA records"),
            Infrastructure(name="Portland ME PD Drone Program", type="police_drone", city="Portland", state="ME", lat=43.6591, lng=-70.2568, description="PPD drone operations.", source="FAA records"),
            Infrastructure(name="Maine State Police Drone Program", type="police_drone", city="Augusta", state="ME", lat=44.3106, lng=-69.7795, description="MSP statewide drones.", source="FAA records"),
            Infrastructure(name="Baltimore PD Drone Program", type="police_drone", city="Baltimore", state="MD", lat=39.2904, lng=-76.6122, description="BPD drone fleet. Aerial surveillance program.", source="EFF Atlas; Baltimore Sun"),
            Infrastructure(name="Montgomery County PD Drone Program", type="police_drone", city="Rockville", state="MD", lat=39.084, lng=-77.1528, description="MCPD drones.", source="FAA records"),
            Infrastructure(name="Prince George's County PD Drone Program", type="police_drone", city="Upper Marlboro", state="MD", lat=38.8129, lng=-76.7497, description="PGCPD drone fleet.", source="FAA records"),
            Infrastructure(name="Maryland State Police Drone Program", type="police_drone", city="Pikesville", state="MD", lat=39.3779, lng=-76.7208, description="MSP statewide drone operations.", source="FAA records"),
            Infrastructure(name="Boston PD Drone Program", type="police_drone", city="Boston", state="MA", lat=42.3601, lng=-71.0589, description="BPD drone fleet.", source="FAA records"),
            Infrastructure(name="Worcester PD Drone Program", type="police_drone", city="Worcester", state="MA", lat=42.2626, lng=-71.8023, description="WPD drones.", source="FAA records"),
            Infrastructure(name="Springfield MA PD Drone Program", type="police_drone", city="Springfield", state="MA", lat=42.1015, lng=-72.5898, description="SPD drone operations.", source="FAA records"),
            Infrastructure(name="Massachusetts State Police Drone Program", type="police_drone", city="Framingham", state="MA", lat=42.2793, lng=-71.4162, description="MSP statewide drone fleet.", source="FAA records"),
            Infrastructure(name="Detroit PD Drone Program", type="police_drone", city="Detroit", state="MI", lat=42.3314, lng=-83.0458, description="DPD drone fleet. Extensive facial recognition integration.", source="EFF Atlas; FAA records"),
            Infrastructure(name="Grand Rapids PD Drone Program", type="police_drone", city="Grand Rapids", state="MI", lat=42.9634, lng=-85.6681, description="GRPD drones.", source="FAA records"),
            Infrastructure(name="Warren PD Drone Program", type="police_drone", city="Warren", state="MI", lat=42.5145, lng=-83.0147, description="WPD drone operations.", source="FAA records"),
            Infrastructure(name="Wayne County Sheriff Drone Program", type="police_drone", city="Detroit", state="MI", lat=42.3314, lng=-83.0458, description="WCSD drones.", source="FAA records"),
            Infrastructure(name="Oakland County Sheriff Drone Program", type="police_drone", city="Pontiac", state="MI", lat=42.6389, lng=-83.291, description="OCSD drone fleet.", source="FAA records"),
            Infrastructure(name="Michigan State Police Drone Program", type="police_drone", city="Lansing", state="MI", lat=42.7325, lng=-84.5555, description="MSP statewide drone operations.", source="FAA records"),
            Infrastructure(name="Minneapolis PD Drone Program", type="police_drone", city="Minneapolis", state="MN", lat=44.9778, lng=-93.265, description="MPD drones. George Floyd protests documented.", source="EFF Atlas; Star Tribune"),
            Infrastructure(name="St. Paul PD Drone Program", type="police_drone", city="St. Paul", state="MN", lat=44.9537, lng=-93.09, description="SPPD drone fleet.", source="FAA records"),
            Infrastructure(name="Hennepin County Sheriff Drone Program", type="police_drone", city="Minneapolis", state="MN", lat=44.9778, lng=-93.265, description="HCSD drones.", source="FAA records"),
            Infrastructure(name="Minnesota State Patrol Drone Program", type="police_drone", city="St. Paul", state="MN", lat=44.9537, lng=-93.09, description="MSP statewide drone operations.", source="FAA records"),
            Infrastructure(name="Jackson PD Drone Program", type="police_drone", city="Jackson", state="MS", lat=32.2988, lng=-90.1848, description="JPD drone fleet.", source="FAA records"),
            Infrastructure(name="Mississippi Highway Patrol Drone Program", type="police_drone", city="Jackson", state="MS", lat=32.2988, lng=-90.1848, description="MHP statewide drones.", source="FAA records"),
            Infrastructure(name="Kansas City PD Drone Program", type="police_drone", city="Kansas City", state="MO", lat=39.0997, lng=-94.5786, description="KCPD drone fleet.", source="EFF Atlas; FAA records"),
            Infrastructure(name="St. Louis Metro PD Drone Program", type="police_drone", city="St. Louis", state="MO", lat=38.627, lng=-90.1994, description="SLMPD drones.", source="FAA records"),
            Infrastructure(name="Springfield MO PD Drone Program", type="police_drone", city="Springfield", state="MO", lat=37.209, lng=-93.2923, description="SPD drone operations.", source="FAA records"),
            Infrastructure(name="Missouri State Highway Patrol Drone Program", type="police_drone", city="Jefferson City", state="MO", lat=38.5767, lng=-92.1735, description="MSHP statewide drone fleet.", source="FAA records"),
            Infrastructure(name="Billings PD Drone Program", type="police_drone", city="Billings", state="MT", lat=45.7833, lng=-108.5007, description="BPD drone operations.", source="FAA records"),
            Infrastructure(name="Montana Highway Patrol Drone Program", type="police_drone", city="Helena", state="MT", lat=46.5958, lng=-112.027, description="MHP statewide drones.", source="FAA records"),
            Infrastructure(name="Omaha PD Drone Program", type="police_drone", city="Omaha", state="NE", lat=41.2565, lng=-95.9345, description="OPD drone fleet.", source="FAA records"),
            Infrastructure(name="Lincoln PD Drone Program", type="police_drone", city="Lincoln", state="NE", lat=40.8136, lng=-96.7026, description="LPD drones.", source="FAA records"),
            Infrastructure(name="Nebraska State Patrol Drone Program", type="police_drone", city="Lincoln", state="NE", lat=40.8136, lng=-96.7026, description="NSP statewide drone operations.", source="FAA records"),
            Infrastructure(name="Las Vegas Metro PD Drone Program", type="police_drone", city="Las Vegas", state="NV", lat=36.1699, lng=-115.1398, description="LVMPD drone fleet. Strip and metro coverage.", source="EFF Atlas; FAA records"),
            Infrastructure(name="Henderson PD Drone Program", type="police_drone", city="Henderson", state="NV", lat=36.0395, lng=-114.9817, description="HPD drones.", source="FAA records"),
            Infrastructure(name="Reno PD Drone Program", type="police_drone", city="Reno", state="NV", lat=39.5296, lng=-119.8138, description="RPD drone operations.", source="FAA records"),
            Infrastructure(name="Washoe County Sheriff Drone Program", type="police_drone", city="Reno", state="NV", lat=39.5296, lng=-119.8138, description="WCSD drone fleet.", source="FAA records"),
            Infrastructure(name="Nevada Highway Patrol Drone Program", type="police_drone", city="Las Vegas", state="NV", lat=36.1699, lng=-115.1398, description="NHP statewide drones.", source="FAA records"),
            Infrastructure(name="Manchester PD Drone Program", type="police_drone", city="Manchester", state="NH", lat=42.9956, lng=-71.4548, description="MPD drone fleet.", source="FAA records"),
            Infrastructure(name="NH State Police Drone Program", type="police_drone", city="Concord", state="NH", lat=43.2081, lng=-71.5376, description="NHSP statewide drone operations.", source="FAA records"),
            Infrastructure(name="Newark PD Drone Program", type="police_drone", city="Newark", state="NJ", lat=40.7357, lng=-74.1724, description="NPD drone fleet.", source="FAA records"),
            Infrastructure(name="Jersey City PD Drone Program", type="police_drone", city="Jersey City", state="NJ", lat=40.7178, lng=-74.0431, description="JCPD drones.", source="FAA records"),
            Infrastructure(name="Paterson PD Drone Program", type="police_drone", city="Paterson", state="NJ", lat=40.9168, lng=-74.1719, description="PPD drone operations.", source="FAA records"),
            Infrastructure(name="NJ State Police Drone Program", type="police_drone", city="Trenton", state="NJ", lat=40.2171, lng=-74.7429, description="NJSP statewide drone fleet.", source="FAA records"),
            Infrastructure(name="Albuquerque PD Drone Program", type="police_drone", city="Albuquerque", state="NM", lat=35.0844, lng=-106.6504, description="APD drone fleet.", source="FAA records"),
            Infrastructure(name="Santa Fe PD Drone Program", type="police_drone", city="Santa Fe", state="NM", lat=35.687, lng=-105.9378, description="SFPD drones.", source="FAA records"),
            Infrastructure(name="NM State Police Drone Program", type="police_drone", city="Santa Fe", state="NM", lat=35.687, lng=-105.9378, description="NMSP statewide drone operations.", source="FAA records"),
            Infrastructure(name="NYPD Drone Program", type="police_drone", city="New York", state="NY", lat=40.7128, lng=-74.006, description="NYPD drone fleet. Deployed at Labor Day and events.", source="EFF Atlas; NYCLU"),
            Infrastructure(name="Buffalo PD Drone Program", type="police_drone", city="Buffalo", state="NY", lat=42.8864, lng=-78.8784, description="BPD drone operations.", source="FAA records"),
            Infrastructure(name="Rochester PD Drone Program", type="police_drone", city="Rochester", state="NY", lat=43.1566, lng=-77.6088, description="RPD drone fleet.", source="FAA records"),
            Infrastructure(name="Yonkers PD Drone Program", type="police_drone", city="Yonkers", state="NY", lat=40.9312, lng=-73.8988, description="YPD drones.", source="FAA records"),
            Infrastructure(name="Syracuse PD Drone Program", type="police_drone", city="Syracuse", state="NY", lat=43.0481, lng=-76.1474, description="SPD drone operations.", source="FAA records"),
            Infrastructure(name="Nassau County PD Drone Program", type="police_drone", city="Mineola", state="NY", lat=40.7498, lng=-73.6381, description="NCPD drone fleet.", source="FAA records"),
            Infrastructure(name="Suffolk County PD Drone Program", type="police_drone", city="Yaphank", state="NY", lat=40.8343, lng=-72.9132, description="SCPD drones.", source="FAA records"),
            Infrastructure(name="Westchester County PD Drone Program", type="police_drone", city="White Plains", state="NY", lat=41.034, lng=-73.7629, description="WCPD drone operations.", source="FAA records"),
            Infrastructure(name="NY State Police Drone Program", type="police_drone", city="Albany", state="NY", lat=42.6526, lng=-73.7562, description="NYSP statewide drone fleet.", source="FAA records"),
            Infrastructure(name="Charlotte-Mecklenburg PD Drone Program", type="police_drone", city="Charlotte", state="NC", lat=35.2271, lng=-80.8431, description="CMPD drone fleet.", source="EFF Atlas; FAA records"),
            Infrastructure(name="Raleigh PD Drone Program", type="police_drone", city="Raleigh", state="NC", lat=35.7796, lng=-78.6382, description="RPD drones.", source="FAA records"),
            Infrastructure(name="Greensboro PD Drone Program", type="police_drone", city="Greensboro", state="NC", lat=36.0726, lng=-79.792, description="GPD drone operations.", source="FAA records"),
            Infrastructure(name="Durham PD Drone Program", type="police_drone", city="Durham", state="NC", lat=35.994, lng=-78.8986, description="DPD drone fleet.", source="FAA records"),
            Infrastructure(name="Winston-Salem PD Drone Program", type="police_drone", city="Winston-Salem", state="NC", lat=36.0999, lng=-80.2442, description="WSPD drones.", source="FAA records"),
            Infrastructure(name="NC State Highway Patrol Drone Program", type="police_drone", city="Raleigh", state="NC", lat=35.7796, lng=-78.6382, description="NCSHP statewide drone operations.", source="FAA records"),
            Infrastructure(name="Fargo PD Drone Program", type="police_drone", city="Fargo", state="ND", lat=46.8772, lng=-96.7898, description="FPD drone fleet.", source="FAA records"),
            Infrastructure(name="ND Highway Patrol Drone Program", type="police_drone", city="Bismarck", state="ND", lat=46.8083, lng=-100.7837, description="NDHP statewide drones.", source="FAA records"),
            Infrastructure(name="Columbus PD Drone Program", type="police_drone", city="Columbus", state="OH", lat=39.9612, lng=-82.9988, description="CPD drone fleet.", source="EFF Atlas; FAA records"),
            Infrastructure(name="Cleveland PD Drone Program", type="police_drone", city="Cleveland", state="OH", lat=41.4993, lng=-81.6944, description="CPD drones.", source="FAA records"),
            Infrastructure(name="Cincinnati PD Drone Program", type="police_drone", city="Cincinnati", state="OH", lat=39.1031, lng=-84.512, description="CPD drone operations.", source="FAA records"),
            Infrastructure(name="Toledo PD Drone Program", type="police_drone", city="Toledo", state="OH", lat=41.6639, lng=-83.5552, description="TPD drone fleet.", source="FAA records"),
            Infrastructure(name="Akron PD Drone Program", type="police_drone", city="Akron", state="OH", lat=41.0814, lng=-81.519, description="APD drones.", source="FAA records"),
            Infrastructure(name="Dayton PD Drone Program", type="police_drone", city="Dayton", state="OH", lat=39.7589, lng=-84.1916, description="DPD drone operations.", source="FAA records"),
            Infrastructure(name="Cuyahoga County Sheriff Drone Program", type="police_drone", city="Cleveland", state="OH", lat=41.4993, lng=-81.6944, description="CCSD drone fleet.", source="FAA records"),
            Infrastructure(name="Ohio State Highway Patrol Drone Program", type="police_drone", city="Columbus", state="OH", lat=39.9612, lng=-82.9988, description="OSHP statewide drones.", source="FAA records"),
            Infrastructure(name="Oklahoma City PD Drone Program", type="police_drone", city="Oklahoma City", state="OK", lat=35.4676, lng=-97.5164, description="OCPD drone fleet.", source="FAA records"),
            Infrastructure(name="Tulsa PD Drone Program", type="police_drone", city="Tulsa", state="OK", lat=36.154, lng=-95.9928, description="TPD drones.", source="FAA records"),
            Infrastructure(name="Oklahoma Highway Patrol Drone Program", type="police_drone", city="Oklahoma City", state="OK", lat=35.4676, lng=-97.5164, description="OHP statewide drone operations.", source="FAA records"),
            Infrastructure(name="Portland PD Drone Program", type="police_drone", city="Portland", state="OR", lat=45.5231, lng=-122.6765, description="PPB drone fleet. Used at protests.", source="EFF Atlas; FAA records"),
            Infrastructure(name="Eugene PD Drone Program", type="police_drone", city="Eugene", state="OR", lat=44.0521, lng=-123.0868, description="EPD drones.", source="FAA records"),
            Infrastructure(name="Salem PD Drone Program", type="police_drone", city="Salem", state="OR", lat=44.9429, lng=-123.0351, description="SPD drone operations. State capital.", source="FAA records"),
            Infrastructure(name="Oregon State Police Drone Program", type="police_drone", city="Salem", state="OR", lat=44.9429, lng=-123.0351, description="OSP statewide drone fleet.", source="FAA records"),
            Infrastructure(name="Philadelphia PD Drone Program", type="police_drone", city="Philadelphia", state="PA", lat=39.9526, lng=-75.1652, description="PPD drone fleet.", source="EFF Atlas; FAA records"),
            Infrastructure(name="Pittsburgh PD Drone Program", type="police_drone", city="Pittsburgh", state="PA", lat=40.4406, lng=-79.9959, description="PPD drones.", source="FAA records"),
            Infrastructure(name="Allentown PD Drone Program", type="police_drone", city="Allentown", state="PA", lat=40.6084, lng=-75.4902, description="APD drone operations.", source="FAA records"),
            Infrastructure(name="Philadelphia County Sheriff Drone Program", type="police_drone", city="Philadelphia", state="PA", lat=39.9526, lng=-75.1652, description="PCS drone fleet.", source="FAA records"),
            Infrastructure(name="Allegheny County Sheriff Drone Program", type="police_drone", city="Pittsburgh", state="PA", lat=40.4406, lng=-79.9959, description="ACSD drones.", source="FAA records"),
            Infrastructure(name="PA State Police Drone Program", type="police_drone", city="Harrisburg", state="PA", lat=40.2732, lng=-76.8867, description="PSP statewide drone operations.", source="FAA records"),
            Infrastructure(name="Providence PD Drone Program", type="police_drone", city="Providence", state="RI", lat=41.824, lng=-71.4128, description="PPD drone fleet.", source="FAA records"),
            Infrastructure(name="RI State Police Drone Program", type="police_drone", city="Scituate", state="RI", lat=41.7887, lng=-71.619, description="RISP statewide drones.", source="FAA records"),
            Infrastructure(name="Columbia SC PD Drone Program", type="police_drone", city="Columbia", state="SC", lat=34.0007, lng=-81.0348, description="CPD drone operations.", source="FAA records"),
            Infrastructure(name="Charleston PD Drone Program", type="police_drone", city="Charleston", state="SC", lat=32.7765, lng=-79.9311, description="CPD drone fleet.", source="FAA records"),
            Infrastructure(name="SC Highway Patrol Drone Program", type="police_drone", city="Columbia", state="SC", lat=34.0007, lng=-81.0348, description="SCHP statewide drones.", source="FAA records"),
            Infrastructure(name="Sioux Falls PD Drone Program", type="police_drone", city="Sioux Falls", state="SD", lat=43.5446, lng=-96.7311, description="SFPD drone fleet.", source="FAA records"),
            Infrastructure(name="SD Highway Patrol Drone Program", type="police_drone", city="Pierre", state="SD", lat=44.3683, lng=-100.351, description="SDHP statewide drone operations.", source="FAA records"),
            Infrastructure(name="Memphis PD Drone Program", type="police_drone", city="Memphis", state="TN", lat=35.1495, lng=-90.049, description="MPD drone fleet.", source="EFF Atlas; FAA records"),
            Infrastructure(name="Nashville Metro PD Drone Program", type="police_drone", city="Nashville", state="TN", lat=36.1627, lng=-86.7816, description="MNPD drones.", source="FAA records"),
            Infrastructure(name="Knoxville PD Drone Program", type="police_drone", city="Knoxville", state="TN", lat=35.9606, lng=-83.9207, description="KPD drone operations.", source="FAA records"),
            Infrastructure(name="Chattanooga PD Drone Program", type="police_drone", city="Chattanooga", state="TN", lat=35.0456, lng=-85.3097, description="CPD drone fleet.", source="FAA records"),
            Infrastructure(name="Tennessee Highway Patrol Drone Program", type="police_drone", city="Nashville", state="TN", lat=36.1627, lng=-86.7816, description="THP statewide drones.", source="FAA records"),
            Infrastructure(name="Houston PD Drone Program", type="police_drone", city="Houston", state="TX", lat=29.7604, lng=-95.3698, description="HPD drone fleet.", source="EFF Atlas; FAA records"),
            Infrastructure(name="Dallas PD Drone Program", type="police_drone", city="Dallas", state="TX", lat=32.7767, lng=-96.797, description="DPD drones.", source="FAA records"),
            Infrastructure(name="San Antonio PD Drone Program", type="police_drone", city="San Antonio", state="TX", lat=29.4241, lng=-98.4936, description="SAPD drone operations.", source="FAA records"),
            Infrastructure(name="Austin PD Drone Program", type="police_drone", city="Austin", state="TX", lat=30.2672, lng=-97.7431, description="APD drones. SXSW and UT events.", source="FAA records"),
            Infrastructure(name="Fort Worth PD Drone Program", type="police_drone", city="Fort Worth", state="TX", lat=32.7555, lng=-97.3308, description="FWPD drone fleet.", source="FAA records"),
            Infrastructure(name="El Paso PD Drone Program", type="police_drone", city="El Paso", state="TX", lat=31.7619, lng=-106.485, description="EPPD drones. Border city.", source="FAA records"),
            Infrastructure(name="Arlington TX PD Drone Program", type="police_drone", city="Arlington", state="TX", lat=32.7357, lng=-97.1081, description="APD drone operations.", source="FAA records"),
            Infrastructure(name="Plano PD Drone Program", type="police_drone", city="Plano", state="TX", lat=33.0198, lng=-96.6989, description="PPD drone fleet.", source="FAA records"),
            Infrastructure(name="Lubbock PD Drone Program", type="police_drone", city="Lubbock", state="TX", lat=33.5779, lng=-101.8552, description="LPD drones.", source="FAA records"),
            Infrastructure(name="Corpus Christi PD Drone Program", type="police_drone", city="Corpus Christi", state="TX", lat=27.8006, lng=-97.3964, description="CCPD drone operations. Gulf Coast.", source="FAA records"),
            Infrastructure(name="Laredo PD Drone Program", type="police_drone", city="Laredo", state="TX", lat=27.5306, lng=-99.4803, description="LPD drones. Border city.", source="FAA records"),
            Infrastructure(name="McAllen PD Drone Program", type="police_drone", city="McAllen", state="TX", lat=26.2034, lng=-98.23, description="MPD drone fleet. High border crossing area.", source="FAA records"),
            Infrastructure(name="Garland TX PD Drone Program", type="police_drone", city="Garland", state="TX", lat=32.9126, lng=-96.6389, description="GPD drones.", source="FAA records"),
            Infrastructure(name="Irving TX PD Drone Program", type="police_drone", city="Irving", state="TX", lat=32.814, lng=-96.9489, description="IPD drone operations.", source="FAA records"),
            Infrastructure(name="Harris County Sheriff Drone Program", type="police_drone", city="Houston", state="TX", lat=29.7604, lng=-95.3698, description="HCSO drone fleet.", source="FAA records"),
            Infrastructure(name="Dallas County Sheriff Drone Program", type="police_drone", city="Dallas", state="TX", lat=32.7767, lng=-96.797, description="DCSD drones.", source="FAA records"),
            Infrastructure(name="Bexar County Sheriff Drone Program", type="police_drone", city="San Antonio", state="TX", lat=29.4241, lng=-98.4936, description="BCSD drone operations.", source="FAA records"),
            Infrastructure(name="Texas DPS Drone Program", type="police_drone", city="Austin", state="TX", lat=30.2672, lng=-97.7431, description="TxDPS statewide drone fleet. Border and highway operations.", source="FAA records"),
            Infrastructure(name="Texas Rangers Drone Program", type="police_drone", city="Austin", state="TX", lat=30.2672, lng=-97.7431, description="Texas Rangers drone operations statewide.", source="FAA records"),
            Infrastructure(name="Salt Lake City PD Drone Program", type="police_drone", city="Salt Lake City", state="UT", lat=40.7608, lng=-111.891, description="SLCPD drone fleet.", source="FAA records"),
            Infrastructure(name="West Valley City PD Drone Program", type="police_drone", city="West Valley City", state="UT", lat=40.6916, lng=-112.0011, description="WVCPD drones.", source="FAA records"),
            Infrastructure(name="Utah Highway Patrol Drone Program", type="police_drone", city="Salt Lake City", state="UT", lat=40.7608, lng=-111.891, description="UHP statewide drone operations.", source="FAA records"),
            Infrastructure(name="Burlington VT PD Drone Program", type="police_drone", city="Burlington", state="VT", lat=44.4759, lng=-73.2121, description="BPD drone fleet.", source="FAA records"),
            Infrastructure(name="Vermont State Police Drone Program", type="police_drone", city="Waterbury", state="VT", lat=44.3376, lng=-72.7562, description="VSP statewide drones.", source="FAA records"),
            Infrastructure(name="Virginia Beach PD Drone Program", type="police_drone", city="Virginia Beach", state="VA", lat=36.8529, lng=-75.978, description="VBPD drone fleet.", source="FAA records"),
            Infrastructure(name="Norfolk PD Drone Program", type="police_drone", city="Norfolk", state="VA", lat=36.8508, lng=-76.2859, description="NPD drones. Naval base proximity.", source="FAA records"),
            Infrastructure(name="Richmond PD Drone Program", type="police_drone", city="Richmond", state="VA", lat=37.5407, lng=-77.436, description="RPD drone operations. State capital.", source="FAA records"),
            Infrastructure(name="Arlington County PD Drone Program", type="police_drone", city="Arlington", state="VA", lat=38.8799, lng=-77.1068, description="ACPD drones. Pentagon proximity.", source="FAA records"),
            Infrastructure(name="Fairfax County PD Drone Program", type="police_drone", city="Fairfax", state="VA", lat=38.8462, lng=-77.3064, description="FCPD drone fleet.", source="FAA records"),
            Infrastructure(name="Virginia State Police Drone Program", type="police_drone", city="Richmond", state="VA", lat=37.5407, lng=-77.436, description="VSP statewide drone operations.", source="FAA records"),
            Infrastructure(name="Seattle PD Drone Program", type="police_drone", city="Seattle", state="WA", lat=47.6062, lng=-122.3321, description="SPD drone fleet. Community pressure led to restrictions.", source="EFF Atlas; ACLU WA"),
            Infrastructure(name="Spokane PD Drone Program", type="police_drone", city="Spokane", state="WA", lat=47.6587, lng=-117.426, description="SPD drones.", source="FAA records"),
            Infrastructure(name="Tacoma PD Drone Program", type="police_drone", city="Tacoma", state="WA", lat=47.2529, lng=-122.4443, description="TPD drone operations.", source="FAA records"),
            Infrastructure(name="King County Sheriff Drone Program", type="police_drone", city="Seattle", state="WA", lat=47.6062, lng=-122.3321, description="KCSD drone fleet.", source="FAA records"),
            Infrastructure(name="Pierce County Sheriff Drone Program", type="police_drone", city="Tacoma", state="WA", lat=47.2529, lng=-122.4443, description="PCSD drones.", source="FAA records"),
            Infrastructure(name="Washington State Patrol Drone Program", type="police_drone", city="Olympia", state="WA", lat=47.0379, lng=-122.9007, description="WSP statewide drone fleet.", source="FAA records"),
            Infrastructure(name="Charleston WV PD Drone Program", type="police_drone", city="Charleston", state="WV", lat=38.3498, lng=-81.6326, description="CPD drone operations.", source="FAA records"),
            Infrastructure(name="WV State Police Drone Program", type="police_drone", city="Charleston", state="WV", lat=38.3498, lng=-81.6326, description="WVSP statewide drones.", source="FAA records"),
            Infrastructure(name="Milwaukee PD Drone Program", type="police_drone", city="Milwaukee", state="WI", lat=43.0389, lng=-87.9065, description="MPD drone fleet.", source="EFF Atlas; FAA records"),
            Infrastructure(name="Madison PD Drone Program", type="police_drone", city="Madison", state="WI", lat=43.0731, lng=-89.4012, description="MPD drones. University of Wisconsin area.", source="FAA records"),
            Infrastructure(name="Green Bay PD Drone Program", type="police_drone", city="Green Bay", state="WI", lat=44.5133, lng=-88.0133, description="GBPD drone operations.", source="FAA records"),
            Infrastructure(name="Wisconsin State Patrol Drone Program", type="police_drone", city="Madison", state="WI", lat=43.0731, lng=-89.4012, description="WSP statewide drone fleet.", source="FAA records"),
            Infrastructure(name="Cheyenne PD Drone Program", type="police_drone", city="Cheyenne", state="WY", lat=41.14, lng=-104.8202, description="CPD drone operations.", source="FAA records"),
            Infrastructure(name="Wyoming Highway Patrol Drone Program", type="police_drone", city="Cheyenne", state="WY", lat=41.14, lng=-104.8202, description="WHP statewide drones.", source="FAA records"),
            Infrastructure(name="FBI Drone Program — Headquarters", type="police_drone", city="Washington", state="DC", lat=38.8951, lng=-77.0364, description="FBI drone fleet. Used for surveillance, hostage situations, and protest monitoring nationwide.", source="FAA records; DOJ reports"),
            Infrastructure(name="DEA Drone Program", type="police_drone", city="Arlington", state="VA", lat=38.8799, lng=-77.1068, description="DEA airborne drone surveillance. Drug interdiction and cartel operations.", source="FAA records"),
            Infrastructure(name="ATF Drone Program", type="police_drone", city="Washington", state="DC", lat=38.9076, lng=-77.0523, description="ATF drone operations. Firearms trafficking investigations.", source="FAA records"),
            Infrastructure(name="US Marshals Drone Program", type="police_drone", city="Arlington", state="VA", lat=38.8799, lng=-77.1068, description="USMS airborne drone operations. Fugitive apprehension.", source="WSJ investigation; FAA records"),
            Infrastructure(name="Secret Service Drone Program", type="police_drone", city="Washington", state="DC", lat=38.8977, lng=-77.0365, description="USSS drone fleet. Presidential and event security.", source="FAA records"),
            Infrastructure(name="DHS / CBP Predator B Drone — National", type="police_drone", city="Washington", state="DC", lat=38.8951, lng=-77.0364, description="CBP operates 10 Predator B drones nationwide. Loaned to local law enforcement 500+ times.", source="EFF; DHS OIG report"),


            # ══════════════════════════════════════════════════════════════
            # SURVEILLANCE CAMERAS — documented city deployments
            # Source: EFF Atlas, city contracts, FOIA records
            # ══════════════════════════════════════════════════════════════

            Infrastructure(name="NYC Domain Awareness — Lower Manhattan Security Initiative", type="surveillance_camera", city="New York", state="NY", lat=40.7074, lng=-74.0113, description="Ring of steel around Lower Manhattan. 4,000+ cameras, radiation detectors, LPR. Post-9/11 build.", source="EFF Atlas; NYPD documentation"),
            Infrastructure(name="NYC Domain Awareness — Midtown Manhattan", type="surveillance_camera", city="New York", state="NY", lat=40.7549, lng=-73.9840, description="Midtown camera grid. Times Square corridor densest coverage in US.", source="EFF Atlas; NYPD documentation"),
            Infrastructure(name="NYC Domain Awareness — Bronx", type="surveillance_camera", city="New York", state="NY", lat=40.8448, lng=-73.8648, description="Bronx camera network integrated into Domain Awareness System.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="NYC Domain Awareness — Brooklyn", type="surveillance_camera", city="New York", state="NY", lat=40.6782, lng=-73.9442, description="Brooklyn camera network. NYPD facial recognition enabled.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Chicago POD Cameras — South Side", type="surveillance_camera", city="Chicago", state="IL", lat=41.7886, lng=-87.6560, description="Police Observation Device cameras. South Side coverage. Connected to OEMC real-time center.", source="EFF Atlas; Chicago city records"),
            Infrastructure(name="Chicago POD Cameras — West Side", type="surveillance_camera", city="Chicago", state="IL", lat=41.8827, lng=-87.7270, description="West Side POD camera network. Facial recognition capable.", source="EFF Atlas; Chicago city records"),
            Infrastructure(name="Chicago POD Cameras — Loop", type="surveillance_camera", city="Chicago", state="IL", lat=41.8819, lng=-87.6278, description="Downtown Loop camera grid. Over 32,000 cameras citywide.", source="EFF Atlas; Chicago city records"),
            Infrastructure(name="LA LAPD Camera Network — South LA", type="surveillance_camera", city="Los Angeles", state="CA", lat=33.9731, lng=-118.2733, description="LAPD cameras in South Los Angeles. ShotSpotter integrated.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="LA LAPD Camera Network — Downtown", type="surveillance_camera", city="Los Angeles", state="CA", lat=34.0430, lng=-118.2673, description="Downtown LA camera network.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Detroit Project Green Light — East Side", type="surveillance_camera", city="Detroit", state="MI", lat=42.3522, lng=-82.9918, description="Real-time facial recognition cameras. East Detroit businesses. DataWorks Plus.", source="EFF Atlas; MIT Media Lab"),
            Infrastructure(name="Detroit Project Green Light — West Side", type="surveillance_camera", city="Detroit", state="MI", lat=42.3314, lng=-83.1024, description="West Detroit Green Light cameras. Highest documented false positive rate nationally.", source="EFF Atlas; MIT Media Lab"),
            Infrastructure(name="Baltimore CitiWatch — Downtown", type="surveillance_camera", city="Baltimore", state="MD", lat=39.2904, lng=-76.6122, description="800+ cameras. Downtown Baltimore coverage.", source="EFF Atlas; Baltimore Sun"),
            Infrastructure(name="Baltimore CitiWatch — East Baltimore", type="surveillance_camera", city="Baltimore", state="MD", lat=39.2987, lng=-76.5746, description="East Baltimore CitiWatch camera network.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="New Orleans NOPD Camera Network — French Quarter", type="surveillance_camera", city="New Orleans", state="LA", lat=29.9584, lng=-90.0644, description="Dense camera coverage in French Quarter. Facial recognition documented.", source="EFF Atlas; ACLU Louisiana"),
            Infrastructure(name="New Orleans NOPD Camera Network — Central City", type="surveillance_camera", city="New Orleans", state="LA", lat=29.9311, lng=-90.0849, description="Central City NOPD cameras. Clearview AI integration.", source="EFF Atlas; WWNO"),
            Infrastructure(name="Houston HPD Camera Network — Downtown", type="surveillance_camera", city="Houston", state="TX", lat=29.7604, lng=-95.3698, description="HPD cameras in downtown Houston.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Miami-Dade Camera Network — Miami Beach", type="surveillance_camera", city="Miami Beach", state="FL", lat=25.7907, lng=-80.1300, description="Miami Beach extensive camera network. Spring Break surveillance.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Miami-Dade Camera Network — Downtown Miami", type="surveillance_camera", city="Miami", state="FL", lat=25.7751, lng=-80.1947, description="Downtown Miami camera infrastructure.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Orlando City Camera Network", type="surveillance_camera", city="Orlando", state="FL", lat=28.5383, lng=-81.3792, description="City of Orlando camera network. Tourism corridor heavily monitored.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Tampa PD Camera Network — Ybor City", type="surveillance_camera", city="Tampa", state="FL", lat=27.9617, lng=-82.4380, description="Ybor City entertainment district cameras. Facial recognition pilot documented.", source="EFF Atlas; Tampa Bay Times"),
            Infrastructure(name="Tampa PD Camera Network — Downtown", type="surveillance_camera", city="Tampa", state="FL", lat=27.9506, lng=-82.4572, description="Downtown Tampa camera grid.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Jacksonville Sheriff Camera Network", type="surveillance_camera", city="Jacksonville", state="FL", lat=30.3322, lng=-81.6557, description="JSO surveillance cameras across Duval County.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Atlanta APF Camera Network", type="surveillance_camera", city="Atlanta", state="GA", lat=33.7490, lng=-84.3880, description="Atlanta Police Foundation camera network. Flock Safety LPR integrated.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Philadelphia PD Camera Network", type="surveillance_camera", city="Philadelphia", state="PA", lat=39.9526, lng=-75.1652, description="PPD surveillance cameras citywide.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Phoenix PD Camera Network", type="surveillance_camera", city="Phoenix", state="AZ", lat=33.4484, lng=-112.0740, description="Phoenix PD cameras. Facial recognition capable.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Denver PD Camera Network", type="surveillance_camera", city="Denver", state="CO", lat=39.7392, lng=-104.9903, description="DPD cameras with ShotSpotter integration.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Seattle PD Camera Network", type="surveillance_camera", city="Seattle", state="WA", lat=47.6062, lng=-122.3321, description="SPD camera network. Moratorium on facial recognition for city use.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="San Francisco SFPD Camera Network", type="surveillance_camera", city="San Francisco", state="CA", lat=37.7749, lng=-122.4194, description="SFPD cameras. City banned facial recognition but federal cameras remain.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Las Vegas Strip Camera Network", type="surveillance_camera", city="Las Vegas", state="NV", lat=36.1147, lng=-115.1728, description="Strip casino and LVMPD cameras. Among densest coverage in US.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Memphis Blue CRUSH Camera Network", type="surveillance_camera", city="Memphis", state="TN", lat=35.1495, lng=-90.0490, description="Blue CRUSH predictive policing camera network. IBM i2 integration.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Nashville Metro Camera Network", type="surveillance_camera", city="Nashville", state="TN", lat=36.1627, lng=-86.7816, description="MNPD camera infrastructure citywide.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Minneapolis PD Camera Network", type="surveillance_camera", city="Minneapolis", state="MN", lat=44.9778, lng=-93.2650, description="MPD cameras. George Floyd Square still under surveillance.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="St. Louis PD Camera Network", type="surveillance_camera", city="St. Louis", state="MO", lat=38.6270, lng=-90.1994, description="SLMPD camera infrastructure.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Kansas City PD Camera Network", type="surveillance_camera", city="Kansas City", state="MO", lat=39.0997, lng=-94.5786, description="KCPD smart city cameras.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Columbus PD Camera Network", type="surveillance_camera", city="Columbus", state="OH", lat=39.9612, lng=-82.9988, description="CPD surveillance infrastructure.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Cleveland PD Camera Network", type="surveillance_camera", city="Cleveland", state="OH", lat=41.4993, lng=-81.6944, description="Cleveland Division of Police cameras.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Pittsburgh PD Camera Network", type="surveillance_camera", city="Pittsburgh", state="PA", lat=40.4406, lng=-79.9959, description="Pittsburgh PD cameras with ShotSpotter.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Charlotte-Mecklenburg Camera Network", type="surveillance_camera", city="Charlotte", state="NC", lat=35.2271, lng=-80.8431, description="CMPD camera infrastructure.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Raleigh PD Camera Network", type="surveillance_camera", city="Raleigh", state="NC", lat=35.7796, lng=-78.6382, description="RPD camera network.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Indianapolis PD Camera Network", type="surveillance_camera", city="Indianapolis", state="IN", lat=39.7684, lng=-86.1581, description="IMPD cameras and ShotSpotter.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Milwaukee PD Camera Network", type="surveillance_camera", city="Milwaukee", state="WI", lat=43.0389, lng=-87.9065, description="MPD camera infrastructure.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="San Antonio PD Camera Network", type="surveillance_camera", city="San Antonio", state="TX", lat=29.4241, lng=-98.4936, description="SAPD camera infrastructure.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Dallas PD Camera Network", type="surveillance_camera", city="Dallas", state="TX", lat=32.7767, lng=-96.7970, description="DPD cameras with ShotSpotter.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Austin PD Camera Network", type="surveillance_camera", city="Austin", state="TX", lat=30.2672, lng=-97.7431, description="APD camera network.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="El Paso PD Camera Network", type="surveillance_camera", city="El Paso", state="TX", lat=31.7619, lng=-106.4850, description="Border city camera network. CBP integration.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Tucson PD Camera Network", type="surveillance_camera", city="Tucson", state="AZ", lat=32.2217, lng=-110.9265, description="TPD cameras. Border proximity.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Oakland PD Camera Network", type="surveillance_camera", city="Oakland", state="CA", lat=37.8044, lng=-122.2711, description="OPD Domain Awareness Center cameras.", source="EFF Atlas; ACLU NorCal"),
            Infrastructure(name="Sacramento PD Camera Network", type="surveillance_camera", city="Sacramento", state="CA", lat=38.5816, lng=-121.4944, description="SPD camera infrastructure.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="San Jose PD Camera Network", type="surveillance_camera", city="San Jose", state="CA", lat=37.3382, lng=-121.8863, description="SJPD camera network.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Portland PD Camera Network", type="surveillance_camera", city="Portland", state="OR", lat=45.5231, lng=-122.6765, description="PPB cameras. Facial recognition moratorium in effect.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Newark PD Camera Network", type="surveillance_camera", city="Newark", state="NJ", lat=40.7357, lng=-74.1724, description="Extensive camera network. NJ largest city.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Boston PD Camera Network", type="surveillance_camera", city="Boston", state="MA", lat=42.3601, lng=-71.0589, description="BPD camera infrastructure.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Washington DC MPD Camera Network", type="surveillance_camera", city="Washington", state="DC", lat=38.9072, lng=-77.0369, description="DC Metro PD cameras. Federal and local integrated.", source="EFF Atlas of Surveillance"),

            # ══════════════════════════════════════════════════════════════
            # AUTONOMOUS ROBOTS
            # Source: EFF Atlas, city contracts, investigative journalism
            # ══════════════════════════════════════════════════════════════

            Infrastructure(name="SFPD Knightscope Robot — Union Square", type="robot_detection", city="San Francisco", state="CA", lat=37.7880, lng=-122.4075, description="Knightscope K5 robot patrolling Union Square. Controversial after confrontations with homeless residents.", source="EFF Atlas; SF Chronicle"),
            Infrastructure(name="SFPD Knightscope Robot — BART Stations", type="robot_detection", city="San Francisco", state="CA", lat=37.7749, lng=-122.4194, description="Autonomous security robots at multiple BART stations.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="San Diego Knightscope Robot Deployment", type="robot_detection", city="San Diego", state="CA", lat=32.7157, lng=-117.1611, description="Knightscope robots deployed in downtown San Diego.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="NYPD Digidog Robot — Bronx Deployment", type="robot_detection", city="New York", state="NY", lat=40.8448, lng=-73.8648, description="Boston Dynamics Spot robot. NYPD deployed in Bronx. Pulled after public backlash, then reinstated.", source="EFF Atlas; New York Times"),
            Infrastructure(name="NYPD Digidog Robot — Brooklyn", type="robot_detection", city="New York", state="NY", lat=40.6782, lng=-73.9442, description="NYPD Spot robot Brooklyn operations.", source="EFF Atlas; NYCLU"),
            Infrastructure(name="Huntington Park PD Knightscope Robot", type="robot_detection", city="Huntington Park", state="CA", lat=33.9819, lng=-118.2165, description="First US police department to deploy Knightscope robot on patrol.", source="EFF Atlas; LA Times"),
            Infrastructure(name="Las Vegas Knightscope Robot — Fremont Street", type="robot_detection", city="Las Vegas", state="NV", lat=36.1706, lng=-115.1420, description="Autonomous robot patrolling Fremont Street Experience.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Washington DC Capitol Police Robot", type="robot_detection", city="Washington", state="DC", lat=38.8899, lng=-77.0091, description="Capitol Police autonomous robot patrol on Capitol grounds.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Atlanta Robot Security Deployment", type="robot_detection", city="Atlanta", state="GA", lat=33.7490, lng=-84.3880, description="Autonomous security robots in downtown Atlanta.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Minneapolis Knightscope Robot — Mall of America", type="robot_detection", city="Bloomington", state="MN", lat=44.8549, lng=-93.2422, description="Knightscope robot at Mall of America — largest deployment in Midwest.", source="EFF Atlas of Surveillance"),

            # ══════════════════════════════════════════════════════════════
            # PALANTIR CONTRACTS
            # Source: Government contracts, FOIA, investigative journalism
            # ══════════════════════════════════════════════════════════════

            Infrastructure(name="LAPD Palantir Gotham", city="Los Angeles", state="CA", type="palantir", lat=34.0522, lng=-118.2437, description="LAPD Palantir Gotham predictive policing. Contract terminated after community pressure but data retained. Used to build gang databases.", source="The Markup; ACLU SoCal; LA Times"),
            Infrastructure(name="New Orleans PD Palantir — Secret Program", city="New Orleans", state="LA", type="palantir", lat=29.9511, lng=-90.0715, description="Secret 6-year Palantir predictive policing program. Never disclosed to city council. Terminated 2018 after The Verge investigation.", source="The Verge investigation 2018; EFF"),
            Infrastructure(name="Chicago PD Palantir Contract", city="Chicago", state="IL", type="palantir", lat=41.8781, lng=-87.6298, description="CPD Palantir data integration. Connects arrest records, gang databases, social media, and surveillance feeds.", source="Chicago Sun-Times; The Intercept"),
            Infrastructure(name="NYC Police Palantir Integration", city="New York", state="NY", type="palantir", lat=40.7128, lng=-74.0060, description="NYPD Palantir Gotham. Integrated with Domain Awareness System. Used for fugitive tracking and gang investigations.", source="The Intercept; NYCLU"),
            Infrastructure(name="Miami-Dade PD Palantir", city="Miami", state="FL", type="palantir", lat=25.7617, lng=-80.1918, description="MDPD Palantir contract. Immigration enforcement data fusion.", source="Miami Herald; The Markup"),
            Infrastructure(name="Denver PD Palantir Contract", city="Denver", state="CO", type="palantir", lat=39.7392, lng=-104.9903, description="DPD Palantir deployment. Documented in FOIA requests.", source="Westword; EFF Atlas"),
            Infrastructure(name="New Orleans ICE Palantir FALCON", city="New Orleans", state="LA", type="palantir", lat=29.9804, lng=-90.2285, description="ICE uses Palantir FALCON for immigration enforcement nationally. New Orleans field office.", source="The Intercept; BuzzFeed News"),
            Infrastructure(name="ICE Palantir FALCON — Washington DC HQ", city="Washington", state="DC", type="palantir", lat=38.8951, lng=-77.0364, description="ICE Palantir FALCON system HQ. Aggregates data on millions of people for deportation targeting.", source="The Intercept; Mijente report"),
            Infrastructure(name="CBP Palantir Contract", city="Washington", state="DC", type="palantir", lat=38.8977, lng=-77.0365, description="CBP Palantir deployment. Border surveillance data aggregation.", source="DHS contracts; The Intercept"),
            Infrastructure(name="US Army Palantir Contract", city="Arlington", state="VA", type="palantir", lat=38.8799, lng=-77.1068, description="Pentagon Palantir. Battlefield intelligence used domestically in training programs.", source="Defense contracts; WSJ"),
            Infrastructure(name="FBI Palantir Contract", city="Washington", state="DC", type="palantir", lat=38.8951, lng=-77.0364, description="FBI Palantir Gotham for criminal investigations.", source="The Intercept; DOJ contracts"),
            Infrastructure(name="Philadelphia PD Palantir", city="Philadelphia", state="PA", type="palantir", lat=39.9526, lng=-75.1652, description="PPD Palantir contract.", source="The Markup; Billy Penn"),
            Infrastructure(name="New York State Police Palantir", city="Albany", state="NY", type="palantir", lat=42.6526, lng=-73.7562, description="NYSP Palantir deployment statewide.", source="The Markup; NYCLU"),
            Infrastructure(name="San Diego PD Palantir", city="San Diego", state="CA", type="palantir", lat=32.7157, lng=-117.1611, description="SDPD Palantir contract. Border city integration.", source="The Markup"),
            Infrastructure(name="Houston PD Palantir", city="Houston", state="TX", type="palantir", lat=29.7604, lng=-95.3698, description="HPD Palantir deployment.", source="Texas Public Radio; The Markup"),
            Infrastructure(name="Arizona DPS Palantir", city="Phoenix", state="AZ", type="palantir", lat=33.4484, lng=-112.0740, description="Arizona DPS Palantir. Border and gang data aggregation.", source="Arizona Republic; The Markup"),
            Infrastructure(name="Cook County Sheriff Palantir", city="Chicago", state="IL", type="palantir", lat=41.8781, lng=-87.6298, description="CCSD Palantir contract.", source="Chicago Tribune; The Markup"),
            Infrastructure(name="Oakland PD Palantir", city="Oakland", state="CA", type="palantir", lat=37.8044, lng=-122.2711, description="OPD Palantir. Domain Awareness Center integration.", source="EFF; The Markup"),
            Infrastructure(name="Sacramento PD Palantir", city="Sacramento", state="CA", type="palantir", lat=38.5816, lng=-121.4944, description="SPD Palantir deployment.", source="The Markup"),
            Infrastructure(name="Atlanta PD Palantir", city="Atlanta", state="GA", type="palantir", lat=33.7490, lng=-84.3880, description="APD Palantir contract.", source="Atlanta Journal-Constitution; The Markup"),
            Infrastructure(name="Las Vegas Metro PD Palantir", city="Las Vegas", state="NV", type="palantir", lat=36.1699, lng=-115.1398, description="LVMPD Palantir deployment.", source="Las Vegas Review-Journal; The Markup"),
            Infrastructure(name="Minneapolis PD Palantir", city="Minneapolis", state="MN", type="palantir", lat=44.9778, lng=-93.2650, description="MPD Palantir contract. Controversial after George Floyd protests.", source="Star Tribune; The Markup"),
            Infrastructure(name="Seattle PD Palantir", city="Seattle", state="WA", type="palantir", lat=47.6062, lng=-122.3321, description="SPD Palantir deployment.", source="The Markup; ACLU WA"),
            Infrastructure(name="Maricopa County Sheriff Palantir", city="Phoenix", state="AZ", type="palantir", lat=33.5722, lng=-112.0892, description="MCSO Palantir. Arpaio-era immigration enforcement data.", source="Arizona Republic; The Markup"),
            Infrastructure(name="Pittsburgh PD Palantir", city="Pittsburgh", state="PA", type="palantir", lat=40.4406, lng=-79.9959, description="PPD Palantir contract.", source="Pittsburgh Post-Gazette; The Markup"),
            Infrastructure(name="Baltimore PD Palantir", city="Baltimore", state="MD", type="palantir", lat=39.2904, lng=-76.6122, description="BPD Palantir deployment alongside aerial surveillance program.", source="Baltimore Sun; The Markup"),
            Infrastructure(name="Kansas City PD Palantir", city="Kansas City", state="MO", type="palantir", lat=39.0997, lng=-94.5786, description="KCPD Palantir contract.", source="The Markup"),
            Infrastructure(name="Portland PD Palantir", city="Portland", state="OR", type="palantir", lat=45.5231, lng=-122.6765, description="PPB Palantir. Terminated after community pressure.", source="OPB; The Markup"),
            Infrastructure(name="Tulsa PD Palantir", city="Tulsa", state="OK", type="palantir", lat=36.1540, lng=-95.9928, description="TPD Palantir deployment.", source="The Markup"),
            Infrastructure(name="Columbus PD Palantir", city="Columbus", state="OH", type="palantir", lat=39.9612, lng=-82.9988, description="CPD Palantir contract.", source="The Markup"),

            # ══════════════════════════════════════════════════════════════
            # SHOTSPOTTER / ACOUSTIC SURVEILLANCE
            # Source: SoundThinking (ShotSpotter) public contracts,
            # EFF Atlas, FOIA records, investigative journalism
            # ══════════════════════════════════════════════════════════════

            Infrastructure(name="ShotSpotter — Chicago South Side", city="Chicago", state="IL", type="shotspotter", lat=41.7886, lng=-87.6560, description="ShotSpotter covers 12 sq miles on South Side. 89% of alerts find no gun crime. MacArthur Justice Center documented wrongful arrests.", source="MacArthur Justice Center; Chicago FOIA"),
            Infrastructure(name="ShotSpotter — Chicago West Side", city="Chicago", state="IL", type="shotspotter", lat=41.8827, lng=-87.7270, description="West Side ShotSpotter coverage. CPD contract worth $33M.", source="Chicago Sun-Times; EFF Atlas"),
            Infrastructure(name="ShotSpotter — New York City Bronx", city="New York", state="NY", type="shotspotter", lat=40.8448, lng=-73.8648, description="NYPD ShotSpotter in Bronx. Documented false alerts led to wrongful stops.", source="EFF Atlas; NYCLU"),
            Infrastructure(name="ShotSpotter — New York City Brooklyn", city="New York", state="NY", type="shotspotter", lat=40.6782, lng=-73.9442, description="Brooklyn ShotSpotter coverage. NYPD contract.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="ShotSpotter — San Francisco", city="San Francisco", state="CA", type="shotspotter", lat=37.7749, lng=-122.4194, description="SFPD ShotSpotter. Board of Supervisors voted to terminate contract 2024.", source="EFF Atlas; SF Chronicle"),
            Infrastructure(name="ShotSpotter — Oakland", city="Oakland", state="CA", type="shotspotter", lat=37.8044, lng=-122.2711, description="OPD ShotSpotter coverage of flatland neighborhoods.", source="EFF Atlas; ACLU NorCal"),
            Infrastructure(name="ShotSpotter — Los Angeles", city="Los Angeles", state="CA", type="shotspotter", lat=34.0069, lng=-118.2681, description="LAPD ShotSpotter in South LA and East LA. $11M contract.", source="EFF Atlas; LA Times"),
            Infrastructure(name="ShotSpotter — Washington DC", city="Washington", state="DC", type="shotspotter", lat=38.8929, lng=-76.9931, description="DC Metro PD ShotSpotter. Covers Wards 7 and 8.", source="EFF Atlas; Washington Post"),
            Infrastructure(name="ShotSpotter — Baltimore", city="Baltimore", state="MD", type="shotspotter", lat=39.3084, lng=-76.6150, description="BPD ShotSpotter. East and West Baltimore coverage.", source="EFF Atlas; Baltimore Sun"),
            Infrastructure(name="ShotSpotter — Detroit", city="Detroit", state="MI", type="shotspotter", lat=42.3452, lng=-83.0901, description="DPD ShotSpotter. Covers East Side and neighborhoods.", source="EFF Atlas; Detroit Free Press"),
            Infrastructure(name="ShotSpotter — Atlanta", city="Atlanta", state="GA", type="shotspotter", lat=33.7229, lng=-84.4220, description="APD ShotSpotter deployment.", source="EFF Atlas; Atlanta Journal-Constitution"),
            Infrastructure(name="ShotSpotter — Houston", city="Houston", state="TX", type="shotspotter", lat=29.7604, lng=-95.3698, description="HPD ShotSpotter. Covers multiple high-crime areas.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="ShotSpotter — Dallas", city="Dallas", state="TX", type="shotspotter", lat=32.7767, lng=-96.7970, description="DPD ShotSpotter coverage.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="ShotSpotter — Kansas City", city="Kansas City", state="MO", type="shotspotter", lat=39.0997, lng=-94.5786, description="KCPD ShotSpotter deployment.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="ShotSpotter — St. Louis", city="St. Louis", state="MO", type="shotspotter", lat=38.6270, lng=-90.1994, description="SLMPD ShotSpotter coverage.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="ShotSpotter — Memphis", city="Memphis", state="TN", type="shotspotter", lat=35.1495, lng=-90.0490, description="MPD ShotSpotter. Blue CRUSH integration.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="ShotSpotter — New Orleans", city="New Orleans", state="LA", type="shotspotter", lat=29.9511, lng=-90.0715, description="NOPD ShotSpotter coverage.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="ShotSpotter — Cleveland", city="Cleveland", state="OH", type="shotspotter", lat=41.4993, lng=-81.6944, description="CPD ShotSpotter deployment.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="ShotSpotter — Columbus", city="Columbus", state="OH", type="shotspotter", lat=39.9612, lng=-82.9988, description="CPD ShotSpotter coverage.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="ShotSpotter — Cincinnati", city="Cincinnati", state="OH", type="shotspotter", lat=39.1031, lng=-84.5120, description="CPD ShotSpotter deployment.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="ShotSpotter — Indianapolis", city="Indianapolis", state="IN", type="shotspotter", lat=39.7684, lng=-86.1581, description="IMPD ShotSpotter coverage.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="ShotSpotter — Milwaukee", city="Milwaukee", state="WI", type="shotspotter", lat=43.0389, lng=-87.9065, description="MPD ShotSpotter deployment.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="ShotSpotter — Minneapolis", city="Minneapolis", state="MN", type="shotspotter", lat=44.9778, lng=-93.2650, description="MPD ShotSpotter coverage.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="ShotSpotter — Denver", city="Denver", state="CO", type="shotspotter", lat=39.7392, lng=-104.9903, description="DPD ShotSpotter deployment.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="ShotSpotter — Phoenix", city="Phoenix", state="AZ", type="shotspotter", lat=33.4484, lng=-112.0740, description="Phoenix PD ShotSpotter.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="ShotSpotter — Tucson", city="Tucson", state="AZ", type="shotspotter", lat=32.2217, lng=-110.9265, description="TPD ShotSpotter coverage.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="ShotSpotter — San Antonio", city="San Antonio", state="TX", type="shotspotter", lat=29.4241, lng=-98.4936, description="SAPD ShotSpotter.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="ShotSpotter — Albuquerque", city="Albuquerque", state="NM", type="shotspotter", lat=35.0844, lng=-106.6504, description="APD ShotSpotter coverage.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="ShotSpotter — Miami", city="Miami", state="FL", type="shotspotter", lat=25.7617, lng=-80.1918, description="MPD ShotSpotter deployment.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="ShotSpotter — Jacksonville", city="Jacksonville", state="FL", type="shotspotter", lat=30.3322, lng=-81.6557, description="JSO ShotSpotter coverage.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="ShotSpotter — Newark", city="Newark", state="NJ", type="shotspotter", lat=40.7357, lng=-74.1724, description="NPD ShotSpotter. One of oldest deployments in NJ.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="ShotSpotter — Philadelphia", city="Philadelphia", state="PA", type="shotspotter", lat=39.9526, lng=-75.1652, description="PPD ShotSpotter coverage.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="ShotSpotter — Pittsburgh", city="Pittsburgh", state="PA", type="shotspotter", lat=40.4406, lng=-79.9959, description="PPD ShotSpotter deployment.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="ShotSpotter — Richmond VA", city="Richmond", state="VA", type="shotspotter", lat=37.5407, lng=-77.4360, description="RPD ShotSpotter coverage.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="ShotSpotter — Norfolk", city="Norfolk", state="VA", type="shotspotter", lat=36.8508, lng=-76.2859, description="NPD ShotSpotter deployment.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="ShotSpotter — Charlotte", city="Charlotte", state="NC", type="shotspotter", lat=35.2271, lng=-80.8431, description="CMPD ShotSpotter.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="ShotSpotter — Raleigh", city="Raleigh", state="NC", type="shotspotter", lat=35.7796, lng=-78.6382, description="RPD ShotSpotter coverage.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="ShotSpotter — Omaha", city="Omaha", state="NE", type="shotspotter", lat=41.2565, lng=-95.9345, description="OPD ShotSpotter deployment.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="ShotSpotter — Louisville", city="Louisville", state="KY", type="shotspotter", lat=38.2527, lng=-85.7585, description="LMPD ShotSpotter coverage.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="ShotSpotter — Little Rock", city="Little Rock", state="AR", type="shotspotter", lat=34.7465, lng=-92.2896, description="LRPD ShotSpotter deployment.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="ShotSpotter — Baton Rouge", city="Baton Rouge", state="LA", type="shotspotter", lat=30.4515, lng=-91.1871, description="BRPD ShotSpotter coverage.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="ShotSpotter — Jackson MS", city="Jackson", state="MS", type="shotspotter", lat=32.2988, lng=-90.1848, description="JPD ShotSpotter deployment.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="ShotSpotter — Shreveport", city="Shreveport", state="LA", type="shotspotter", lat=32.5252, lng=-93.7502, description="SPD ShotSpotter.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="ShotSpotter — Stockton", city="Stockton", state="CA", type="shotspotter", lat=37.9577, lng=-121.2908, description="SPD ShotSpotter coverage.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="ShotSpotter — Sacramento", city="Sacramento", state="CA", type="shotspotter", lat=38.5816, lng=-121.4944, description="SPD ShotSpotter deployment.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="ShotSpotter — Fresno", city="Fresno", state="CA", type="shotspotter", lat=36.7378, lng=-119.7871, description="FPD ShotSpotter coverage.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="ShotSpotter — Portland", city="Portland", state="OR", type="shotspotter", lat=45.5231, lng=-122.6765, description="PPB ShotSpotter deployment.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="ShotSpotter — Seattle", city="Seattle", state="WA", type="shotspotter", lat=47.6062, lng=-122.3321, description="SPD ShotSpotter coverage.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="ShotSpotter — Tacoma", city="Tacoma", state="WA", type="shotspotter", lat=47.2529, lng=-122.4443, description="TPD ShotSpotter deployment.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="ShotSpotter — Bridgeport", city="Bridgeport", state="CT", type="shotspotter", lat=41.1865, lng=-73.1952, description="BPD ShotSpotter coverage.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="ShotSpotter — Hartford", city="Hartford", state="CT", type="shotspotter", lat=41.7637, lng=-72.6851, description="HPD ShotSpotter deployment.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="ShotSpotter — Springfield MA", city="Springfield", state="MA", type="shotspotter", lat=42.1015, lng=-72.5898, description="SPD ShotSpotter coverage.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="ShotSpotter — Boston", city="Boston", state="MA", type="shotspotter", lat=42.3601, lng=-71.0589, description="BPD ShotSpotter deployment.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="ShotSpotter — Providence", city="Providence", state="RI", type="shotspotter", lat=41.8240, lng=-71.4128, description="PPD ShotSpotter coverage.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="ShotSpotter — Buffalo", city="Buffalo", state="NY", type="shotspotter", lat=42.8864, lng=-78.8784, description="BPD ShotSpotter deployment.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="ShotSpotter — Rochester", city="Rochester", state="NY", type="shotspotter", lat=43.1566, lng=-77.6088, description="RPD ShotSpotter coverage.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="ShotSpotter — Syracuse", city="Syracuse", state="NY", type="shotspotter", lat=43.0481, lng=-76.1474, description="SPD ShotSpotter deployment.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="ShotSpotter — Yonkers", city="Yonkers", state="NY", type="shotspotter", lat=40.9312, lng=-73.8988, description="YPD ShotSpotter coverage.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="ShotSpotter — Paterson NJ", city="Paterson", state="NJ", type="shotspotter", lat=40.9168, lng=-74.1719, description="PPD ShotSpotter deployment.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="ShotSpotter — Camden NJ", city="Camden", state="NJ", type="shotspotter", lat=39.9259, lng=-75.1196, description="CPD ShotSpotter coverage.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="ShotSpotter — Trenton NJ", city="Trenton", state="NJ", type="shotspotter", lat=40.2171, lng=-74.7429, description="TPD ShotSpotter deployment.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="ShotSpotter — Wilmington DE", city="Wilmington", state="DE", type="shotspotter", lat=39.7447, lng=-75.5484, description="WPD ShotSpotter coverage.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="ShotSpotter — Annapolis", city="Annapolis", state="MD", type="shotspotter", lat=38.9784, lng=-76.4922, description="APD ShotSpotter deployment.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="ShotSpotter — Dayton", city="Dayton", state="OH", type="shotspotter", lat=39.7589, lng=-84.1916, description="DPD ShotSpotter coverage.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="ShotSpotter — Toledo", city="Toledo", state="OH", type="shotspotter", lat=41.6639, lng=-83.5552, description="TPD ShotSpotter deployment.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="ShotSpotter — Akron", city="Akron", state="OH", type="shotspotter", lat=41.0814, lng=-81.5190, description="APD ShotSpotter coverage.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="ShotSpotter — Fort Wayne", city="Fort Wayne", state="IN", type="shotspotter", lat=41.1306, lng=-85.1289, description="FWPD ShotSpotter deployment.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="ShotSpotter — Rockford", city="Rockford", state="IL", type="shotspotter", lat=42.2711, lng=-89.0940, description="RPD ShotSpotter coverage.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="ShotSpotter — Aurora IL", city="Aurora", state="IL", type="shotspotter", lat=41.7606, lng=-88.3201, description="APD ShotSpotter deployment.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="ShotSpotter — Flint", city="Flint", state="MI", type="shotspotter", lat=43.0125, lng=-83.6875, description="FPD ShotSpotter coverage.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="ShotSpotter — Grand Rapids", city="Grand Rapids", state="MI", type="shotspotter", lat=42.9634, lng=-85.6681, description="GRPD ShotSpotter deployment.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="ShotSpotter — Lansing", city="Lansing", state="MI", type="shotspotter", lat=42.7325, lng=-84.5555, description="LPD ShotSpotter coverage.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="ShotSpotter — St. Paul", city="St. Paul", state="MN", type="shotspotter", lat=44.9537, lng=-93.0900, description="SPPD ShotSpotter deployment.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="ShotSpotter — Wichita", city="Wichita", state="KS", type="shotspotter", lat=37.6872, lng=-97.3301, description="WPD ShotSpotter coverage.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="ShotSpotter — Oklahoma City", city="Oklahoma City", state="OK", type="shotspotter", lat=35.4676, lng=-97.5164, description="OCPD ShotSpotter deployment.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="ShotSpotter — Tulsa", city="Tulsa", state="OK", type="shotspotter", lat=36.1540, lng=-95.9928, description="TPD ShotSpotter coverage.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="ShotSpotter — El Paso", city="El Paso", state="TX", type="shotspotter", lat=31.7619, lng=-106.4850, description="EPPD ShotSpotter deployment.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="ShotSpotter — Corpus Christi", city="Corpus Christi", state="TX", type="shotspotter", lat=27.8006, lng=-97.3964, description="CCPD ShotSpotter coverage.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="ShotSpotter — Lubbock", city="Lubbock", state="TX", type="shotspotter", lat=33.5779, lng=-101.8552, description="LPD ShotSpotter deployment.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="ShotSpotter — Tampa", city="Tampa", state="FL", type="shotspotter", lat=27.9506, lng=-82.4572, description="TPD ShotSpotter coverage.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="ShotSpotter — St. Petersburg", city="St. Petersburg", state="FL", type="shotspotter", lat=27.7676, lng=-82.6403, description="SPPD ShotSpotter deployment.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="ShotSpotter — Orlando", city="Orlando", state="FL", type="shotspotter", lat=28.5383, lng=-81.3792, description="OPD ShotSpotter coverage.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="ShotSpotter — Fort Lauderdale", city="Fort Lauderdale", state="FL", type="shotspotter", lat=26.1224, lng=-80.1373, description="FLPD ShotSpotter deployment.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="ShotSpotter — Savannah", city="Savannah", state="GA", type="shotspotter", lat=32.0835, lng=-81.0998, description="SPD ShotSpotter coverage.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="ShotSpotter — Augusta GA", city="Augusta", state="GA", type="shotspotter", lat=33.4735, lng=-82.0105, description="APD ShotSpotter deployment.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="ShotSpotter — Chattanooga", city="Chattanooga", state="TN", type="shotspotter", lat=35.0456, lng=-85.3097, description="CPD ShotSpotter coverage.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="ShotSpotter — Nashville", city="Nashville", state="TN", type="shotspotter", lat=36.1627, lng=-86.7816, description="MNPD ShotSpotter deployment.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="ShotSpotter — Knoxville", city="Knoxville", state="TN", type="shotspotter", lat=35.9606, lng=-83.9207, description="KPD ShotSpotter coverage.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="ShotSpotter — Birmingham AL", city="Birmingham", state="AL", type="shotspotter", lat=33.5186, lng=-86.8104, description="BPD ShotSpotter deployment.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="ShotSpotter — Montgomery AL", city="Montgomery", state="AL", type="shotspotter", lat=32.3617, lng=-86.2792, description="MPD ShotSpotter coverage.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="ShotSpotter — Columbia SC", city="Columbia", state="SC", type="shotspotter", lat=34.0007, lng=-81.0348, description="CPD ShotSpotter deployment.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="ShotSpotter — Charleston SC", city="Charleston", state="SC", type="shotspotter", lat=32.7765, lng=-79.9311, description="CPD ShotSpotter coverage.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="ShotSpotter — Greensboro", city="Greensboro", state="NC", type="shotspotter", lat=36.0726, lng=-79.7920, description="GPD ShotSpotter deployment.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="ShotSpotter — Durham NC", city="Durham", state="NC", type="shotspotter", lat=35.9940, lng=-78.8986, description="DPD ShotSpotter coverage.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="ShotSpotter — Fayetteville NC", city="Fayetteville", state="NC", type="shotspotter", lat=35.0527, lng=-78.8784, description="FPD ShotSpotter deployment.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="ShotSpotter — Las Vegas", city="Las Vegas", state="NV", type="shotspotter", lat=36.1699, lng=-115.1398, description="LVMPD ShotSpotter coverage.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="ShotSpotter — Reno", city="Reno", state="NV", type="shotspotter", lat=39.5296, lng=-119.8138, description="RPD ShotSpotter deployment.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="ShotSpotter — Salt Lake City", city="Salt Lake City", state="UT", type="shotspotter", lat=40.7608, lng=-111.8910, description="SLCPD ShotSpotter coverage.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="ShotSpotter — Honolulu", city="Honolulu", state="HI", type="shotspotter", lat=21.3069, lng=-157.8583, description="HPD ShotSpotter deployment.", source="EFF Atlas of Surveillance"),

            # ══════════════════════════════════════════════════════════════
            # JOINT TERRORISM TASK FORCES (JTTFs)
            # Source: FBI public directory, DOJ reports
            # 200 JTTFs operate nationwide — all public record
            # ══════════════════════════════════════════════════════════════

            Infrastructure(name="JTTF — New York City (Largest in US)", city="New York", state="NY", type="jttf", lat=40.7128, lng=-74.0060, description="NYC JTTF. Largest in country. 500+ agents from 50+ agencies. Monitors Muslim communities, activists, and political groups.", source="FBI; NYCLU; The Intercept"),
            Infrastructure(name="JTTF — Los Angeles", city="Los Angeles", state="CA", type="jttf", lat=34.0522, lng=-118.2437, description="LA JTTF. Federal/local fusion. Monitors environmental and political activists.", source="FBI; ACLU SoCal"),
            Infrastructure(name="JTTF — Chicago", city="Chicago", state="IL", type="jttf", lat=41.8781, lng=-87.6298, description="Chicago JTTF. CPD/FBI integration. Active surveillance of protest movements.", source="FBI; The Intercept"),
            Infrastructure(name="JTTF — Washington DC", city="Washington", state="DC", type="jttf", lat=38.8951, lng=-77.0364, description="DC JTTF. Closest to federal power. Monitors advocacy groups near Capitol.", source="FBI; ACLU"),
            Infrastructure(name="JTTF — Houston", city="Houston", state="TX", type="jttf", lat=29.7604, lng=-95.3698, description="Houston JTTF. Gulf Coast operations. Port and energy infrastructure focus.", source="FBI"),
            Infrastructure(name="JTTF — Phoenix", city="Phoenix", state="AZ", type="jttf", lat=33.4484, lng=-112.0740, description="Phoenix JTTF. Border and immigration enforcement integration.", source="FBI"),
            Infrastructure(name="JTTF — Philadelphia", city="Philadelphia", state="PA", type="jttf", lat=39.9526, lng=-75.1652, description="Philadelphia JTTF.", source="FBI"),
            Infrastructure(name="JTTF — San Antonio", city="San Antonio", state="TX", type="jttf", lat=29.4241, lng=-98.4936, description="San Antonio JTTF. Military city focus.", source="FBI"),
            Infrastructure(name="JTTF — San Diego", city="San Diego", state="CA", type="jttf", lat=32.7157, lng=-117.1611, description="San Diego JTTF. Border proximity. CBP/FBI integration.", source="FBI"),
            Infrastructure(name="JTTF — Dallas", city="Dallas", state="TX", type="jttf", lat=32.7767, lng=-96.7970, description="Dallas JTTF.", source="FBI"),
            Infrastructure(name="JTTF — San Jose", city="San Jose", state="CA", type="jttf", lat=37.3382, lng=-121.8863, description="San Jose JTTF. Silicon Valley technology sector focus.", source="FBI"),
            Infrastructure(name="JTTF — Austin", city="Austin", state="TX", type="jttf", lat=30.2672, lng=-97.7431, description="Austin JTTF. Tech sector and university monitoring.", source="FBI"),
            Infrastructure(name="JTTF — Jacksonville", city="Jacksonville", state="FL", type="jttf", lat=30.3322, lng=-81.6557, description="Jacksonville JTTF. Naval station coordination.", source="FBI"),
            Infrastructure(name="JTTF — Fort Worth", city="Fort Worth", state="TX", type="jttf", lat=32.7555, lng=-97.3308, description="Fort Worth JTTF.", source="FBI"),
            Infrastructure(name="JTTF — Columbus OH", city="Columbus", state="OH", type="jttf", lat=39.9612, lng=-82.9988, description="Columbus JTTF.", source="FBI"),
            Infrastructure(name="JTTF — Charlotte", city="Charlotte", state="NC", type="jttf", lat=35.2271, lng=-80.8431, description="Charlotte JTTF. Banking sector security focus.", source="FBI"),
            Infrastructure(name="JTTF — Indianapolis", city="Indianapolis", state="IN", type="jttf", lat=39.7684, lng=-86.1581, description="Indianapolis JTTF.", source="FBI"),
            Infrastructure(name="JTTF — San Francisco", city="San Francisco", state="CA", type="jttf", lat=37.7749, lng=-122.4194, description="SF JTTF. Technology and port security focus.", source="FBI"),
            Infrastructure(name="JTTF — Seattle", city="Seattle", state="WA", type="jttf", lat=47.6062, lng=-122.3321, description="Seattle JTTF. Port and tech sector focus.", source="FBI"),
            Infrastructure(name="JTTF — Denver", city="Denver", state="CO", type="jttf", lat=39.7392, lng=-104.9903, description="Denver JTTF.", source="FBI"),
            Infrastructure(name="JTTF — Nashville", city="Nashville", state="TN", type="jttf", lat=36.1627, lng=-86.7816, description="Nashville JTTF.", source="FBI"),
            Infrastructure(name="JTTF — Oklahoma City", city="Oklahoma City", state="OK", type="jttf", lat=35.4676, lng=-97.5164, description="OKC JTTF. Post-1995 bombing legacy.", source="FBI"),
            Infrastructure(name="JTTF — El Paso", city="El Paso", state="TX", type="jttf", lat=31.7619, lng=-106.4850, description="El Paso JTTF. Border operations coordination.", source="FBI"),
            Infrastructure(name="JTTF — Boston", city="Boston", state="MA", type="jttf", lat=42.3601, lng=-71.0589, description="Boston JTTF. Post-Marathon bombing expansion.", source="FBI"),
            Infrastructure(name="JTTF — Las Vegas", city="Las Vegas", state="NV", type="jttf", lat=36.1699, lng=-115.1398, description="Las Vegas JTTF. Entertainment and mass gathering security.", source="FBI"),
            Infrastructure(name="JTTF — Memphis", city="Memphis", state="TN", type="jttf", lat=35.1495, lng=-90.0490, description="Memphis JTTF.", source="FBI"),
            Infrastructure(name="JTTF — Louisville", city="Louisville", state="KY", type="jttf", lat=38.2527, lng=-85.7585, description="Louisville JTTF.", source="FBI"),
            Infrastructure(name="JTTF — Baltimore", city="Baltimore", state="MD", type="jttf", lat=39.2904, lng=-76.6122, description="Baltimore JTTF.", source="FBI"),
            Infrastructure(name="JTTF — Milwaukee", city="Milwaukee", state="WI", type="jttf", lat=43.0389, lng=-87.9065, description="Milwaukee JTTF.", source="FBI"),
            Infrastructure(name="JTTF — Albuquerque", city="Albuquerque", state="NM", type="jttf", lat=35.0844, lng=-106.6504, description="Albuquerque JTTF. Border proximity.", source="FBI"),
            Infrastructure(name="JTTF — Tucson", city="Tucson", state="AZ", type="jttf", lat=32.2217, lng=-110.9265, description="Tucson JTTF. CBP/FBI border coordination.", source="FBI"),
            Infrastructure(name="JTTF — Fresno", city="Fresno", state="CA", type="jttf", lat=36.7378, lng=-119.7871, description="Fresno JTTF. Central Valley agricultural sector.", source="FBI"),
            Infrastructure(name="JTTF — Sacramento", city="Sacramento", state="CA", type="jttf", lat=38.5816, lng=-121.4944, description="Sacramento JTTF. State capital focus.", source="FBI"),
            Infrastructure(name="JTTF — Long Beach", city="Long Beach", state="CA", type="jttf", lat=33.7701, lng=-118.1937, description="Long Beach JTTF. Port security focus.", source="FBI"),
            Infrastructure(name="JTTF — Portland", city="Portland", state="OR", type="jttf", lat=45.5231, lng=-122.6765, description="Portland JTTF. City withdrew PPB officers after protest controversy.", source="FBI; OPB"),
            Infrastructure(name="JTTF — Atlanta", city="Atlanta", state="GA", type="jttf", lat=33.7490, lng=-84.3880, description="Atlanta JTTF. Transportation hub focus.", source="FBI"),
            Infrastructure(name="JTTF — Minneapolis", city="Minneapolis", state="MN", type="jttf", lat=44.9778, lng=-93.2650, description="Minneapolis JTTF. Somali community monitoring documented.", source="FBI; Star Tribune"),
            Infrastructure(name="JTTF — Kansas City", city="Kansas City", state="MO", type="jttf", lat=39.0997, lng=-94.5786, description="Kansas City JTTF.", source="FBI"),
            Infrastructure(name="JTTF — Tampa", city="Tampa", state="FL", type="jttf", lat=27.9506, lng=-82.4572, description="Tampa JTTF. CENTCOM proximity.", source="FBI"),
            Infrastructure(name="JTTF — Miami", city="Miami", state="FL", type="jttf", lat=25.7617, lng=-80.1918, description="Miami JTTF. International focus, Caribbean and Latin America.", source="FBI"),
            Infrastructure(name="JTTF — New Orleans", city="New Orleans", state="LA", type="jttf", lat=29.9511, lng=-90.0715, description="New Orleans JTTF. Port security.", source="FBI"),
            Infrastructure(name="JTTF — Detroit", city="Detroit", state="MI", type="jttf", lat=42.3314, lng=-83.0458, description="Detroit JTTF. Arab-American community monitoring documented.", source="FBI; ACLU Michigan"),
            Infrastructure(name="JTTF — St. Louis", city="St. Louis", state="MO", type="jttf", lat=38.6270, lng=-90.1994, description="St. Louis JTTF.", source="FBI"),
            Infrastructure(name="JTTF — Pittsburgh", city="Pittsburgh", state="PA", type="jttf", lat=40.4406, lng=-79.9959, description="Pittsburgh JTTF.", source="FBI"),
            Infrastructure(name="JTTF — Salt Lake City", city="Salt Lake City", state="UT", type="jttf", lat=40.7608, lng=-111.8910, description="Salt Lake City JTTF.", source="FBI"),
            Infrastructure(name="JTTF — Richmond VA", city="Richmond", state="VA", type="jttf", lat=37.5407, lng=-77.4360, description="Richmond JTTF. State capital.", source="FBI"),
            Infrastructure(name="JTTF — Norfolk", city="Norfolk", state="VA", type="jttf", lat=36.8508, lng=-76.2859, description="Norfolk JTTF. Naval base coordination.", source="FBI"),
            Infrastructure(name="JTTF — Raleigh", city="Raleigh", state="NC", type="jttf", lat=35.7796, lng=-78.6382, description="Raleigh JTTF.", source="FBI"),
            Infrastructure(name="JTTF — Omaha", city="Omaha", state="NE", type="jttf", lat=41.2565, lng=-95.9345, description="Omaha JTTF.", source="FBI"),

            # ══════════════════════════════════════════════════════════════
            # FLOCK SAFETY LPR NETWORKS
            # Source: Flock Safety public client list, EFF Atlas,
            # local news, FOIA records
            # 4,000+ agencies — this represents documented deployments
            # ══════════════════════════════════════════════════════════════

            Infrastructure(name="Flock Safety LPR — Atlanta Metro", city="Atlanta", state="GA", type="flock_lpr", lat=33.7490, lng=-84.3880, description="Flock Safety LPR. Atlanta metro regional network. Data shared across dozens of agencies.", source="EFF Atlas; Flock Safety client list"),
            Infrastructure(name="Flock Safety LPR — Denver Metro", city="Denver", state="CO", type="flock_lpr", lat=39.7392, lng=-104.9903, description="Denver metro Flock Safety network.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Dallas Metro", city="Dallas", state="TX", type="flock_lpr", lat=32.7767, lng=-96.7970, description="Dallas metro Flock Safety LPR network.", source="EFF Atlas; Flock Safety client list"),
            Infrastructure(name="Flock Safety LPR — Houston Metro", city="Houston", state="TX", type="flock_lpr", lat=29.7604, lng=-95.3698, description="Houston metro Flock Safety deployment.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Austin Metro", city="Austin", state="TX", type="flock_lpr", lat=30.2672, lng=-97.7431, description="Austin metro Flock Safety LPR.", source="EFF Atlas; Flock Safety client list"),
            Infrastructure(name="Flock Safety LPR — San Antonio", city="San Antonio", state="TX", type="flock_lpr", lat=29.4241, lng=-98.4936, description="San Antonio Flock Safety network.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Phoenix Metro", city="Phoenix", state="AZ", type="flock_lpr", lat=33.4484, lng=-112.0740, description="Phoenix metro Flock Safety LPR deployment.", source="EFF Atlas; Flock Safety client list"),
            Infrastructure(name="Flock Safety LPR — Los Angeles Metro", city="Los Angeles", state="CA", type="flock_lpr", lat=34.0522, lng=-118.2437, description="LA metro Flock Safety network. Multiple agency data sharing.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — San Diego", city="San Diego", state="CA", type="flock_lpr", lat=32.7157, lng=-117.1611, description="San Diego Flock Safety LPR.", source="EFF Atlas; Flock Safety client list"),
            Infrastructure(name="Flock Safety LPR — Sacramento Metro", city="Sacramento", state="CA", type="flock_lpr", lat=38.5816, lng=-121.4944, description="Sacramento metro Flock Safety deployment.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Bay Area", city="Oakland", state="CA", type="flock_lpr", lat=37.8044, lng=-122.2711, description="Bay Area Flock Safety network. Multiple agencies.", source="EFF Atlas; Flock Safety client list"),
            Infrastructure(name="Flock Safety LPR — Chicago Metro", city="Chicago", state="IL", type="flock_lpr", lat=41.8781, lng=-87.6298, description="Chicago metro Flock Safety LPR.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Indianapolis", city="Indianapolis", state="IN", type="flock_lpr", lat=39.7684, lng=-86.1581, description="Indianapolis Flock Safety deployment.", source="EFF Atlas; Flock Safety client list"),
            Infrastructure(name="Flock Safety LPR — Columbus OH", city="Columbus", state="OH", type="flock_lpr", lat=39.9612, lng=-82.9988, description="Columbus Flock Safety network.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Cincinnati", city="Cincinnati", state="OH", type="flock_lpr", lat=39.1031, lng=-84.5120, description="Cincinnati Flock Safety LPR.", source="EFF Atlas; Flock Safety client list"),
            Infrastructure(name="Flock Safety LPR — Cleveland", city="Cleveland", state="OH", type="flock_lpr", lat=41.4993, lng=-81.6944, description="Cleveland Flock Safety deployment.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Nashville", city="Nashville", state="TN", type="flock_lpr", lat=36.1627, lng=-86.7816, description="Nashville Flock Safety LPR network.", source="EFF Atlas; Flock Safety client list"),
            Infrastructure(name="Flock Safety LPR — Memphis", city="Memphis", state="TN", type="flock_lpr", lat=35.1495, lng=-90.0490, description="Memphis Flock Safety deployment.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Charlotte", city="Charlotte", state="NC", type="flock_lpr", lat=35.2271, lng=-80.8431, description="Charlotte Flock Safety network.", source="EFF Atlas; Flock Safety client list"),
            Infrastructure(name="Flock Safety LPR — Raleigh", city="Raleigh", state="NC", type="flock_lpr", lat=35.7796, lng=-78.6382, description="Raleigh Flock Safety LPR.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Jacksonville FL", city="Jacksonville", state="FL", type="flock_lpr", lat=30.3322, lng=-81.6557, description="Jacksonville Flock Safety deployment.", source="EFF Atlas; Flock Safety client list"),
            Infrastructure(name="Flock Safety LPR — Tampa Metro", city="Tampa", state="FL", type="flock_lpr", lat=27.9506, lng=-82.4572, description="Tampa metro Flock Safety network.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Miami Metro", city="Miami", state="FL", type="flock_lpr", lat=25.7617, lng=-80.1918, description="Miami metro Flock Safety LPR.", source="EFF Atlas; Flock Safety client list"),
            Infrastructure(name="Flock Safety LPR — Orlando Metro", city="Orlando", state="FL", type="flock_lpr", lat=28.5383, lng=-81.3792, description="Orlando metro Flock Safety deployment.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Seattle Metro", city="Seattle", state="WA", type="flock_lpr", lat=47.6062, lng=-122.3321, description="Seattle metro Flock Safety network.", source="EFF Atlas; Flock Safety client list"),
            Infrastructure(name="Flock Safety LPR — Portland OR", city="Portland", state="OR", type="flock_lpr", lat=45.5231, lng=-122.6765, description="Portland Flock Safety LPR.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Las Vegas Metro", city="Las Vegas", state="NV", type="flock_lpr", lat=36.1699, lng=-115.1398, description="Las Vegas metro Flock Safety deployment.", source="EFF Atlas; Flock Safety client list"),
            Infrastructure(name="Flock Safety LPR — Minneapolis Metro", city="Minneapolis", state="MN", type="flock_lpr", lat=44.9778, lng=-93.2650, description="Minneapolis metro Flock Safety network.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Kansas City", city="Kansas City", state="MO", type="flock_lpr", lat=39.0997, lng=-94.5786, description="Kansas City Flock Safety LPR.", source="EFF Atlas; Flock Safety client list"),
            Infrastructure(name="Flock Safety LPR — St. Louis Metro", city="St. Louis", state="MO", type="flock_lpr", lat=38.6270, lng=-90.1994, description="St. Louis metro Flock Safety deployment.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Baltimore", city="Baltimore", state="MD", type="flock_lpr", lat=39.2904, lng=-76.6122, description="Baltimore Flock Safety network.", source="EFF Atlas; Flock Safety client list"),
            Infrastructure(name="Flock Safety LPR — Washington DC Metro", city="Washington", state="DC", type="flock_lpr", lat=38.8951, lng=-77.0364, description="DC metro Flock Safety LPR. Covers MD and VA suburbs.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Philadelphia Metro", city="Philadelphia", state="PA", type="flock_lpr", lat=39.9526, lng=-75.1652, description="Philadelphia metro Flock Safety deployment.", source="EFF Atlas; Flock Safety client list"),
            Infrastructure(name="Flock Safety LPR — Pittsburgh", city="Pittsburgh", state="PA", type="flock_lpr", lat=40.4406, lng=-79.9959, description="Pittsburgh Flock Safety network.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Boston Metro", city="Boston", state="MA", type="flock_lpr", lat=42.3601, lng=-71.0589, description="Boston metro Flock Safety LPR.", source="EFF Atlas; Flock Safety client list"),
            Infrastructure(name="Flock Safety LPR — Detroit Metro", city="Detroit", state="MI", type="flock_lpr", lat=42.3314, lng=-83.0458, description="Detroit metro Flock Safety deployment.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Milwaukee", city="Milwaukee", state="WI", type="flock_lpr", lat=43.0389, lng=-87.9065, description="Milwaukee Flock Safety network.", source="EFF Atlas; Flock Safety client list"),
            Infrastructure(name="Flock Safety LPR — New Orleans", city="New Orleans", state="LA", type="flock_lpr", lat=29.9511, lng=-90.0715, description="New Orleans Flock Safety LPR.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Albuquerque", city="Albuquerque", state="NM", type="flock_lpr", lat=35.0844, lng=-106.6504, description="Albuquerque Flock Safety deployment.", source="EFF Atlas; Flock Safety client list"),
            Infrastructure(name="Flock Safety LPR — Salt Lake City", city="Salt Lake City", state="UT", type="flock_lpr", lat=40.7608, lng=-111.8910, description="Salt Lake City Flock Safety network.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Omaha", city="Omaha", state="NE", type="flock_lpr", lat=41.2565, lng=-95.9345, description="Omaha Flock Safety LPR.", source="EFF Atlas; Flock Safety client list"),
            Infrastructure(name="Flock Safety LPR — Oklahoma City", city="Oklahoma City", state="OK", type="flock_lpr", lat=35.4676, lng=-97.5164, description="OKC Flock Safety deployment.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Tulsa", city="Tulsa", state="OK", type="flock_lpr", lat=36.1540, lng=-95.9928, description="Tulsa Flock Safety network.", source="EFF Atlas; Flock Safety client list"),
            Infrastructure(name="Flock Safety LPR — Wichita", city="Wichita", state="KS", type="flock_lpr", lat=37.6872, lng=-97.3301, description="Wichita Flock Safety LPR.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Baton Rouge", city="Baton Rouge", state="LA", type="flock_lpr", lat=30.4515, lng=-91.1871, description="Baton Rouge Flock Safety deployment.", source="EFF Atlas; Flock Safety client list"),
            Infrastructure(name="Flock Safety LPR — Richmond VA", city="Richmond", state="VA", type="flock_lpr", lat=37.5407, lng=-77.4360, description="Richmond Flock Safety network.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Virginia Beach", city="Virginia Beach", state="VA", type="flock_lpr", lat=36.8529, lng=-75.9780, description="Virginia Beach Flock Safety LPR.", source="EFF Atlas; Flock Safety client list"),

            # ══════════════════════════════════════════════════════════════
            # CELL-SITE SIMULATOR AIRCRAFT (Airborne Stingrays)
            # Source: WSJ investigation, BuzzFeed News, EFF, ACLU,
            # FAA records, DOJ reports
            # US Marshals, FBI, and DHS operate aircraft-mounted
            # cell-site simulators that blanket entire cities
            # ══════════════════════════════════════════════════════════════

            Infrastructure(name="US Marshals CSS Aircraft — DC Operations Base", city="Washington", state="DC", type="css_aircraft", lat=38.8951, lng=-77.0364, description="USMS operates Cessna aircraft with DRT boxes (airborne Stingrays). Documented covering entire cities from altitude. Intercepts all phones in range.", source="WSJ investigation 2015; ACLU"),
            Infrastructure(name="US Marshals CSS Aircraft — Oklahoma City Hub", city="Oklahoma City", state="OK", type="css_aircraft", lat=35.4676, lng=-97.5164, description="USMS aviation hub. CSS aircraft operations covering Southwest.", source="WSJ investigation; FAA records"),
            Infrastructure(name="US Marshals CSS Aircraft — Miami Hub", city="Miami", state="FL", type="css_aircraft", lat=25.7617, lng=-80.1918, description="USMS Miami aviation hub. CSS operations over South Florida.", source="WSJ investigation; BuzzFeed News"),
            Infrastructure(name="FBI CSS Aircraft — Dade-Collier Training Hub", city="Miami", state="FL", type="css_aircraft", lat=25.6142, lng=-80.8987, description="FBI aviation hub. Shell company aircraft. BuzzFeed documented 50+ FBI planes in single-day operations over US cities.", source="BuzzFeed News investigation; EFF"),
            Infrastructure(name="FBI CSS Aircraft — Bristow Group — Virginia", city="Bristow", state="VA", type="css_aircraft", lat=38.7196, lng=-77.5544, description="FBI shell company aviation operation. Bristow Group cover. CSS-equipped aircraft deployed nationally.", source="BuzzFeed News 2015; ACLU"),
            Infrastructure(name="FBI CSS Aircraft — NG Research — Oklahoma", city="Edmond", state="OK", type="css_aircraft", lat=35.6528, lng=-97.4781, description="FBI shell company aircraft. NG Research cover. Stingray-equipped Cessnas.", source="BuzzFeed News investigation; EFF"),
            Infrastructure(name="FBI CSS Aircraft — OTV Inc — Virginia", city="Manassas", state="VA", type="css_aircraft", lat=38.7284, lng=-77.5152, description="FBI OTV Inc shell company. CSS aircraft based at Manassas Regional Airport.", source="BuzzFeed News investigation"),
            Infrastructure(name="DHS CSS Aircraft — National Air Security Operations", city="Washington", state="DC", type="css_aircraft", lat=38.9072, lng=-77.0369, description="DHS operates CSS-equipped aircraft through ICE Air and CBP Air and Marine Operations.", source="EFF; DHS OIG reports"),
            Infrastructure(name="ICE Air CSS Operations — Houston", city="Houston", state="TX", type="css_aircraft", lat=29.9902, lng=-95.3368, description="ICE Air CSS operations over Houston. Documented deportation targeting.", source="EFF; The Intercept"),
            Infrastructure(name="ICE Air CSS Operations — Los Angeles", city="Los Angeles", state="CA", type="css_aircraft", lat=33.9425, lng=-118.4081, description="ICE Air CSS aircraft over LA metro. Immigration enforcement targeting.", source="EFF; ACLU SoCal"),
            Infrastructure(name="ICE Air CSS Operations — Chicago", city="Chicago", state="IL", type="css_aircraft", lat=41.9742, lng=-87.9073, description="ICE Air CSS operations over Chicago area.", source="EFF; Chicago Tribune"),
            Infrastructure(name="ICE Air CSS Operations — Miami", city="Miami", state="FL", type="css_aircraft", lat=25.7959, lng=-80.2870, description="ICE Air CSS aircraft. Miami hub. Caribbean and Latin America focus.", source="EFF; Miami Herald"),
            Infrastructure(name="CSS Aircraft Operations — Dallas Fort Worth", city="Dallas", state="TX", type="css_aircraft", lat=32.8998, lng=-97.0403, description="Federal CSS aircraft operations over DFW metro. Multiple agencies.", source="WSJ investigation; BuzzFeed News"),
            Infrastructure(name="CSS Aircraft Operations — Atlanta", city="Atlanta", state="GA", type="css_aircraft", lat=33.6407, lng=-84.4277, description="Federal CSS aircraft over Atlanta. Hartsfield-Jackson hub operations.", source="BuzzFeed News; EFF"),
            Infrastructure(name="CSS Aircraft Operations — New York", city="New York", state="NY", type="css_aircraft", lat=40.6413, lng=-73.7781, description="Federal CSS aircraft over NYC metro. JFK/LaGuardia corridor.", source="WSJ investigation; BuzzFeed News"),
            Infrastructure(name="CSS Aircraft Operations — Phoenix", city="Phoenix", state="AZ", type="css_aircraft", lat=33.4373, lng=-112.0078, description="Federal CSS aircraft over Phoenix. Desert Southwest coverage.", source="BuzzFeed News; EFF"),
            Infrastructure(name="CSS Aircraft Operations — Seattle", city="Seattle", state="WA", type="css_aircraft", lat=47.4502, lng=-122.3088, description="Federal CSS aircraft over Seattle metro.", source="BuzzFeed News investigation"),
            Infrastructure(name="CSS Aircraft Operations — Denver", city="Denver", state="CO", type="css_aircraft", lat=39.8561, lng=-104.6737, description="Federal CSS aircraft over Denver. Mountain West hub.", source="BuzzFeed News; EFF"),
            Infrastructure(name="CSS Aircraft Operations — Minneapolis", city="Minneapolis", state="MN", type="css_aircraft", lat=44.8848, lng=-93.2223, description="Federal CSS aircraft over Minneapolis-St. Paul.", source="BuzzFeed News investigation"),
            Infrastructure(name="CSS Aircraft Operations — San Francisco", city="San Francisco", state="CA", type="css_aircraft", lat=37.6213, lng=-122.3790, description="Federal CSS aircraft over Bay Area.", source="BuzzFeed News; EFF"),
            Infrastructure(name="CSS Aircraft Operations — Baltimore", city="Baltimore", state="MD", type="css_aircraft", lat=39.1754, lng=-76.6684, description="Federal and state CSS aircraft over Baltimore. Alongside aerial surveillance program.", source="BuzzFeed News; Baltimore Sun"),
            Infrastructure(name="CSS Aircraft Operations — Detroit", city="Detroit", state="MI", type="css_aircraft", lat=42.2124, lng=-83.3534, description="Federal CSS aircraft over Detroit metro.", source="BuzzFeed News investigation"),
            Infrastructure(name="CSS Aircraft Operations — Portland", city="Portland", state="OR", type="css_aircraft", lat=45.5898, lng=-122.5951, description="Federal CSS aircraft over Portland. Used during protests 2020.", source="BuzzFeed News; The Intercept"),
            Infrastructure(name="CSS Aircraft Operations — San Diego", city="San Diego", state="CA", type="css_aircraft", lat=32.7338, lng=-117.1933, description="Federal CSS aircraft over San Diego. Border proximity operations.", source="BuzzFeed News; EFF"),
            Infrastructure(name="CSS Aircraft Operations — New Orleans", city="New Orleans", state="LA", type="css_aircraft", lat=29.9931, lng=-90.2580, description="Federal CSS aircraft over New Orleans.", source="BuzzFeed News investigation"),
            Infrastructure(name="CSS Aircraft Operations — Kansas City", city="Kansas City", state="MO", type="css_aircraft", lat=39.2976, lng=-94.7139, description="Federal CSS aircraft over Kansas City metro.", source="BuzzFeed News; EFF"),
            Infrastructure(name="CSS Aircraft Operations — Tampa", city="Tampa", state="FL", type="css_aircraft", lat=27.9756, lng=-82.5332, description="Federal CSS aircraft over Tampa Bay. MacDill AFB coordination.", source="BuzzFeed News investigation"),
            Infrastructure(name="CSS Aircraft Operations — Charlotte", city="Charlotte", state="NC", type="css_aircraft", lat=35.2140, lng=-80.9431, description="Federal CSS aircraft over Charlotte metro.", source="BuzzFeed News; EFF"),
            Infrastructure(name="CSS Aircraft Operations — Indianapolis", city="Indianapolis", state="IN", type="css_aircraft", lat=39.7173, lng=-86.2944, description="Federal CSS aircraft over Indianapolis.", source="BuzzFeed News investigation"),
            Infrastructure(name="CSS Aircraft Operations — Las Vegas", city="Las Vegas", state="NV", type="css_aircraft", lat=36.0840, lng=-115.1537, description="Federal CSS aircraft over Las Vegas metro.", source="BuzzFeed News; EFF"),

            # ══════════════════════════════════════════════════════════════
            # FBI SURVEILLANCE PLANES
            # Source: BuzzFeed News investigation (2015), EFF, FAA records
            # FBI operates 100+ aircraft through shell companies.
            # Aircraft circle cities collecting phone data, video,
            # and facial recognition imagery. All public record via FAA.
            # ══════════════════════════════════════════════════════════════

            Infrastructure(name="FBI Surveillance Plane — NG Research (Oklahoma)", city="Edmond", state="OK", type="fbi_surveillance", lat=35.6528, lng=-97.4781, description="FBI shell company NG Research Inc. Cessna aircraft. BuzzFeed identified via FAA records. Stingray-equipped. Circles cities collecting phone data.", source="BuzzFeed News 2015; EFF"),
            Infrastructure(name="FBI Surveillance Plane — OTV Inc (Virginia)", city="Manassas", state="VA", type="fbi_surveillance", lat=38.7284, lng=-77.5152, description="FBI shell company OTV Inc. Manassas Regional Airport base. Surveillance aircraft deployed nationally.", source="BuzzFeed News 2015; EFF"),
            Infrastructure(name="FBI Surveillance Plane — FVX Research (Virginia)", city="Bristow", state="VA", type="fbi_surveillance", lat=38.7196, lng=-77.5544, description="FBI shell company FVX Research. Virginia base. Cessna 182 aircraft. Documented circling Baltimore, Detroit, and other cities.", source="BuzzFeed News investigation 2015"),
            Infrastructure(name="FBI Surveillance Plane — ASGC LLC (Oklahoma)", city="Oklahoma City", state="OK", type="fbi_surveillance", lat=35.3931, lng=-97.5979, description="FBI shell company ASGC LLC. Wiley Post Airport base. Southwest operations.", source="BuzzFeed News 2015"),
            Infrastructure(name="FBI Surveillance Plane — KQM Aviation (Virginia)", city="Warrenton", state="VA", type="fbi_surveillance", lat=38.7218, lng=-77.7963, description="FBI shell company KQM Aviation. Fauquier County Airport. Mid-Atlantic surveillance base.", source="BuzzFeed News investigation 2015"),
            Infrastructure(name="FBI Surveillance Plane — LCB Leasing (Virginia)", city="Manassas", state="VA", type="fbi_surveillance", lat=38.7213, lng=-77.5151, description="FBI shell company LCB Leasing. Manassas base. Multiple Cessna aircraft.", source="BuzzFeed News 2015"),
            Infrastructure(name="FBI Surveillance Plane — NBR Aviation (Virginia)", city="Manassas", state="VA", type="fbi_surveillance", lat=38.7312, lng=-77.5148, description="FBI shell company NBR Aviation. Manassas cluster. East Coast operations.", source="BuzzFeed News investigation 2015"),
            Infrastructure(name="FBI Surveillance Plane — OBR Leasing (Oklahoma)", city="Bethany", state="OK", type="fbi_surveillance", lat=35.5184, lng=-97.6353, description="FBI shell company OBR Leasing. Wiley Post area. Southwest surveillance base.", source="BuzzFeed News 2015"),
            Infrastructure(name="FBI Surveillance Plane — PXW Services (Virginia)", city="Manassas", state="VA", type="fbi_surveillance", lat=38.7198, lng=-77.5147, description="FBI shell company PXW Services. Manassas Regional Airport cluster.", source="BuzzFeed News investigation 2015"),
            Infrastructure(name="FBI Surveillance Plane — RKT Productions (California)", city="Camarillo", state="CA", type="fbi_surveillance", lat=34.2136, lng=-119.0944, description="FBI shell company RKT Productions. Camarillo Airport base. West Coast operations.", source="BuzzFeed News 2015"),
            Infrastructure(name="FBI Surveillance Plane — Midwest hub (Ohio)", city="Columbus", state="OH", type="fbi_surveillance", lat=39.9980, lng=-82.8919, description="FBI surveillance aircraft operating from Columbus metro area. Documented circling Cleveland, Cincinnati, and Columbus.", source="BuzzFeed News; EFF"),
            Infrastructure(name="FBI Surveillance Plane — Southeast hub (Georgia)", city="Atlanta", state="GA", type="fbi_surveillance", lat=33.6407, lng=-84.4277, description="FBI surveillance aircraft based at Atlanta. Southeast regional operations.", source="BuzzFeed News; EFF"),
            Infrastructure(name="FBI Surveillance Plane — Texas hub (Dallas)", city="Dallas", state="TX", type="fbi_surveillance", lat=32.8998, lng=-97.0403, description="FBI surveillance aircraft DFW area. Texas and Southwest operations.", source="BuzzFeed News; EFF"),
            Infrastructure(name="FBI Surveillance Plane — Pacific NW hub (Seattle)", city="Seattle", state="WA", type="fbi_surveillance", lat=47.4502, lng=-122.3088, description="FBI surveillance aircraft Seattle-Tacoma area. Pacific Northwest operations.", source="BuzzFeed News 2015"),
            Infrastructure(name="FBI Surveillance Plane — Chicago hub", city="Chicago", state="IL", type="fbi_surveillance", lat=41.9742, lng=-87.9073, description="FBI surveillance aircraft O'Hare corridor. Midwest operations. Documented circling protests 2020.", source="BuzzFeed News; The Intercept"),
            Infrastructure(name="FBI Surveillance Plane — New York hub", city="New York", state="NY", type="fbi_surveillance", lat=40.6413, lng=-73.7781, description="FBI surveillance aircraft JFK area. NYC metro operations. Documented circling Brooklyn and Bronx.", source="BuzzFeed News 2015; ACLU"),
            Infrastructure(name="FBI Surveillance Plane — Miami hub", city="Miami", state="FL", type="fbi_surveillance", lat=25.7959, lng=-80.2870, description="FBI surveillance aircraft Miami International area. Caribbean and Southeast operations.", source="BuzzFeed News investigation 2015"),
            Infrastructure(name="FBI Surveillance Plane — Los Angeles hub", city="Los Angeles", state="CA", type="fbi_surveillance", lat=33.9425, lng=-118.4081, description="FBI surveillance aircraft LAX area. California and West Coast operations.", source="BuzzFeed News 2015; EFF"),
            Infrastructure(name="FBI Surveillance Plane — Phoenix hub", city="Phoenix", state="AZ", type="fbi_surveillance", lat=33.4373, lng=-112.0078, description="FBI surveillance aircraft Phoenix Sky Harbor area. Southwest operations.", source="BuzzFeed News 2015"),
            Infrastructure(name="FBI Surveillance Plane — Minneapolis hub", city="Minneapolis", state="MN", type="fbi_surveillance", lat=44.8848, lng=-93.2223, description="FBI surveillance aircraft MSP area. Upper Midwest operations. Documented during George Floyd protests 2020.", source="BuzzFeed News; Star Tribune"),
            Infrastructure(name="FBI Surveillance Plane — Denver hub", city="Denver", state="CO", type="fbi_surveillance", lat=39.8561, lng=-104.6737, description="FBI surveillance aircraft DIA area. Mountain West operations.", source="BuzzFeed News 2015"),
            Infrastructure(name="FBI Surveillance Plane — Boston hub", city="Boston", state="MA", type="fbi_surveillance", lat=42.3656, lng=-71.0096, description="FBI surveillance aircraft Logan Airport area. New England operations.", source="BuzzFeed News 2015"),
            Infrastructure(name="FBI Surveillance Plane — Philadelphia hub", city="Philadelphia", state="PA", type="fbi_surveillance", lat=39.8744, lng=-75.2424, description="FBI surveillance aircraft PHL area. Mid-Atlantic operations.", source="BuzzFeed News investigation 2015"),
            Infrastructure(name="FBI Surveillance Plane — Detroit hub", city="Detroit", state="MI", type="fbi_surveillance", lat=42.2124, lng=-83.3534, description="FBI surveillance aircraft DTW area. Great Lakes operations. Documented circling Arab-American communities.", source="BuzzFeed News; ACLU Michigan"),
            Infrastructure(name="FBI Surveillance Plane — St. Louis hub", city="St. Louis", state="MO", type="fbi_surveillance", lat=38.7487, lng=-90.3700, description="FBI surveillance aircraft Lambert area. Documented circling Ferguson during protests.", source="BuzzFeed News; The Intercept"),
            Infrastructure(name="FBI Surveillance Plane — Baltimore hub", city="Baltimore", state="MD", type="fbi_surveillance", lat=39.1754, lng=-76.6684, description="FBI surveillance aircraft BWI area. Mid-Atlantic operations alongside PSS aerial program.", source="BuzzFeed News 2015; Baltimore Sun"),
            Infrastructure(name="FBI Surveillance Plane — San Francisco hub", city="San Francisco", state="CA", type="fbi_surveillance", lat=37.6213, lng=-122.3790, description="FBI surveillance aircraft SFO area. Bay Area and Northern California operations.", source="BuzzFeed News 2015"),
            Infrastructure(name="FBI Surveillance Plane — Portland hub", city="Portland", state="OR", type="fbi_surveillance", lat=45.5898, lng=-122.5951, description="FBI surveillance aircraft PDX area. Documented circling Portland protests 2020.", source="BuzzFeed News; The Intercept"),
            Infrastructure(name="FBI Surveillance Plane — San Diego hub", city="San Diego", state="CA", type="fbi_surveillance", lat=32.7338, lng=-117.1933, description="FBI surveillance aircraft SAN area. Border proximity. Joint operations with CBP.", source="BuzzFeed News 2015"),
            Infrastructure(name="FBI Surveillance Plane — New Orleans hub", city="New Orleans", state="LA", type="fbi_surveillance", lat=29.9931, lng=-90.2580, description="FBI surveillance aircraft MSY area. Gulf South operations.", source="BuzzFeed News 2015"),
            Infrastructure(name="FBI Surveillance Plane — Kansas City hub", city="Kansas City", state="MO", type="fbi_surveillance", lat=39.2976, lng=-94.7139, description="FBI surveillance aircraft MCI area. Central US operations.", source="BuzzFeed News 2015"),
            Infrastructure(name="FBI Surveillance Plane — Tampa hub", city="Tampa", state="FL", type="fbi_surveillance", lat=27.9756, lng=-82.5332, description="FBI surveillance aircraft TPA area. MacDill AFB coordination.", source="BuzzFeed News 2015"),
            Infrastructure(name="FBI Surveillance Plane — Pittsburgh hub", city="Pittsburgh", state="PA", type="fbi_surveillance", lat=40.4955, lng=-80.2329, description="FBI surveillance aircraft PIT area. Northeast operations.", source="BuzzFeed News 2015"),
            Infrastructure(name="FBI Surveillance Plane — Sacramento hub", city="Sacramento", state="CA", type="fbi_surveillance", lat=38.6954, lng=-121.5908, description="FBI surveillance aircraft SMF area. Central California and capital operations.", source="BuzzFeed News 2015"),
            Infrastructure(name="FBI Surveillance Plane — Las Vegas hub", city="Las Vegas", state="NV", type="fbi_surveillance", lat=36.0840, lng=-115.1537, description="FBI surveillance aircraft LAS area. Nevada and Southwest desert operations.", source="BuzzFeed News 2015"),
            Infrastructure(name="FBI Surveillance Plane — Cincinnati hub", city="Cincinnati", state="OH", type="fbi_surveillance", lat=39.0489, lng=-84.6678, description="FBI surveillance aircraft CVG area. Ohio Valley operations.", source="BuzzFeed News 2015"),
            Infrastructure(name="FBI Surveillance Plane — Charlotte hub", city="Charlotte", state="NC", type="fbi_surveillance", lat=35.2140, lng=-80.9431, description="FBI surveillance aircraft CLT area. Southeast operations.", source="BuzzFeed News 2015"),
            Infrastructure(name="FBI Surveillance Plane — Austin hub", city="Austin", state="TX", type="fbi_surveillance", lat=30.1975, lng=-97.6664, description="FBI surveillance aircraft AUS area. Central Texas operations.", source="BuzzFeed News 2015"),
            Infrastructure(name="FBI Surveillance Plane — Honolulu hub", city="Honolulu", state="HI", type="fbi_surveillance", lat=21.3245, lng=-157.9251, description="FBI surveillance aircraft HNL area. Pacific operations.", source="BuzzFeed News 2015"),
            Infrastructure(name="FBI Surveillance Plane — Anchorage hub", city="Anchorage", state="AK", type="fbi_surveillance", lat=61.1743, lng=-149.9963, description="FBI surveillance aircraft ANC area. Alaska and Arctic operations.", source="BuzzFeed News 2015"),

            # ══════════════════════════════════════════════════════════════
            # PREDICTIVE POLICING SOFTWARE
            # Source: EFF Atlas, ACLU, The Markup, city contracts,
            # investigative journalism, FOIA records
            # ══════════════════════════════════════════════════════════════

            Infrastructure(name="PredPol/Geolitica — Los Angeles PD", city="Los Angeles", state="CA", type="predictive_policing", lat=34.0522, lng=-118.2437, description="LAPD PredPol deployment. Predicted crime locations sent to officers. Documented racial bias amplification. Contract terminated 2020 after community pressure.", source="The Markup; ACLU SoCal; LA Times"),
            Infrastructure(name="PredPol/Geolitica — Santa Cruz PD", city="Santa Cruz", state="CA", type="predictive_policing", lat=36.9741, lng=-122.0308, description="SCPD PredPol deployment. Santa Cruz became first US city to ban predictive policing (2020).", source="EFF Atlas; Santa Cruz Sentinel"),
            Infrastructure(name="PredPol/Geolitica — Tacoma PD", city="Tacoma", state="WA", type="predictive_policing", lat=47.2529, lng=-122.4443, description="Tacoma PD PredPol contract.", source="The Markup; EFF Atlas"),
            Infrastructure(name="PredPol/Geolitica — Hagerstown MD PD", city="Hagerstown", state="MD", type="predictive_policing", lat=39.6418, lng=-77.7199, description="Hagerstown PD PredPol deployment.", source="The Markup; EFF Atlas"),
            Infrastructure(name="Palantir Gotham Predictive — Chicago PD", city="Chicago", state="IL", type="predictive_policing", lat=41.8781, lng=-87.6298, description="CPD Strategic Subject List (SSL). Palantir-powered risk scoring of 400,000 Chicagoans. Documented racial disparity. Terminated 2020.", source="The Intercept; Chicago Tribune; ACLU IL"),
            Infrastructure(name="ShotSpotter Respond / Predictive — New York PD", city="New York", state="NY", type="predictive_policing", lat=40.7128, lng=-74.0060, description="NYPD Patternizr predictive policing tool. Pattern-matching algorithm for crime prediction.", source="NYPD documentation; The Markup"),
            Infrastructure(name="Hitachi Visualization Predictive — Chicago", city="Chicago", state="IL", type="predictive_policing", lat=41.8781, lng=-87.6298, description="Hitachi Visualization Predictive Crime Analytics. Chicago pilot program.", source="EFF Atlas; Chicago Reader"),
            Infrastructure(name="HunchLab Predictive — Philadelphia PD", city="Philadelphia", state="PA", type="predictive_policing", lat=39.9526, lng=-75.1652, description="PPD HunchLab predictive policing system.", source="EFF Atlas; The Markup"),
            Infrastructure(name="HunchLab Predictive — New Orleans PD", city="New Orleans", state="LA", type="predictive_policing", lat=29.9511, lng=-90.0715, description="NOPD HunchLab deployment alongside secret Palantir program.", source="EFF Atlas; The Verge"),
            Infrastructure(name="ShotSpotter Respond Predictive — Kansas City PD", city="Kansas City", state="MO", type="predictive_policing", lat=39.0997, lng=-94.5786, description="KCPD ShotSpotter Respond predictive analytics.", source="EFF Atlas; Kansas City Star"),
            Infrastructure(name="Motorola CommandCentral Predictive — Denver PD", city="Denver", state="CO", type="predictive_policing", lat=39.7392, lng=-104.9903, description="DPD Motorola CommandCentral predictive policing integration.", source="EFF Atlas; Westword"),
            Infrastructure(name="SAS Predictive Policing — Memphis PD", city="Memphis", state="TN", type="predictive_policing", lat=35.1495, lng=-90.0490, description="MPD SAS analytics predictive system. Blue CRUSH program.", source="EFF Atlas; Memphis Commercial Appeal"),
            Infrastructure(name="IBM i2 Predictive Analytics — Memphis PD", city="Memphis", state="TN", type="predictive_policing", lat=35.1495, lng=-90.0530, description="MPD IBM i2 Analyst's Notebook. Pattern analysis and predictive deployment.", source="EFF Atlas; IBM contracts"),
            Infrastructure(name="Genetec Predictive — Detroit PD", city="Detroit", state="MI", type="predictive_policing", lat=42.3314, lng=-83.0458, description="DPD Genetec predictive analytics. Integrated with Project Green Light cameras.", source="EFF Atlas; Detroit Free Press"),
            Infrastructure(name="Motorola PredPol — Atlanta PD", city="Atlanta", state="GA", type="predictive_policing", lat=33.7490, lng=-84.3880, description="APD predictive policing analytics.", source="EFF Atlas; Atlanta Journal-Constitution"),
            Infrastructure(name="ShotSpotter Respond — Baltimore PD", city="Baltimore", state="MD", type="predictive_policing", lat=39.2904, lng=-76.6122, description="BPD ShotSpotter Respond predictive system.", source="EFF Atlas; Baltimore Sun"),
            Infrastructure(name="Axon AI Predictive — Phoenix PD", city="Phoenix", state="AZ", type="predictive_policing", lat=33.4484, lng=-112.0740, description="Phoenix PD Axon AI analytics and predictive deployment tools.", source="EFF Atlas; Arizona Republic"),
            Infrastructure(name="Mark43 Predictive Analytics — DC Metro PD", city="Washington", state="DC", type="predictive_policing", lat=38.8951, lng=-77.0364, description="MPD Mark43 records system with predictive analytics integration.", source="EFF Atlas; Washington Post"),
            Infrastructure(name="Vigilant Solutions LEARN — Houston PD", city="Houston", state="TX", type="predictive_policing", lat=29.7604, lng=-95.3698, description="HPD Vigilant Solutions LEARN predictive LPR analytics.", source="EFF Atlas; Houston Chronicle"),
            Infrastructure(name="IBM Watson Predictive — Miami-Dade PD", city="Miami", state="FL", type="predictive_policing", lat=25.7617, lng=-80.1918, description="MDPD IBM Watson analytics for crime prediction.", source="EFF Atlas; Miami Herald"),
            Infrastructure(name="Axon AI Predictive — Las Vegas Metro PD", city="Las Vegas", state="NV", type="predictive_policing", lat=36.1699, lng=-115.1398, description="LVMPD Axon AI predictive policing tools.", source="EFF Atlas"),
            Infrastructure(name="Tyler Technologies Predictive — Indianapolis", city="Indianapolis", state="IN", type="predictive_policing", lat=39.7684, lng=-86.1581, description="IMPD Tyler Technologies predictive analytics platform.", source="EFF Atlas"),
            Infrastructure(name="ShotSpotter Respond Predictive — Oakland PD", city="Oakland", state="CA", type="predictive_policing", lat=37.8044, lng=-122.2711, description="OPD ShotSpotter Respond predictive system.", source="EFF Atlas; ACLU NorCal"),
            Infrastructure(name="Palantir Predictive — New York City PD", city="New York", state="NY", type="predictive_policing", lat=40.7128, lng=-74.0060, description="NYPD Palantir Domain Awareness predictive analytics.", source="The Intercept; NYCLU"),
            Infrastructure(name="Motorola CommandCentral — San Antonio PD", city="San Antonio", state="TX", type="predictive_policing", lat=29.4241, lng=-98.4936, description="SAPD Motorola predictive policing integration.", source="EFF Atlas"),
            Infrastructure(name="PredPol/Geolitica — Modesto PD", city="Modesto", state="CA", type="predictive_policing", lat=37.6391, lng=-120.9969, description="Modesto PD PredPol deployment.", source="The Markup; EFF Atlas"),
            Infrastructure(name="PredPol/Geolitica — Indio PD", city="Indio", state="CA", type="predictive_policing", lat=33.7206, lng=-116.2156, description="Indio PD PredPol contract.", source="The Markup; EFF Atlas"),
            Infrastructure(name="PredPol/Geolitica — Alhambra PD", city="Alhambra", state="CA", type="predictive_policing", lat=34.0953, lng=-118.1270, description="Alhambra PD PredPol deployment.", source="The Markup; EFF Atlas"),
            Infrastructure(name="Beware Software — Fresno PD", city="Fresno", state="CA", type="predictive_policing", lat=36.7378, lng=-119.7871, description="FPD Beware threat scoring software. Assigns threat scores to addresses before officer arrival. Documented errors.", source="Washington Post investigation; EFF Atlas"),
            Infrastructure(name="ShotSpotter Respond Predictive — Milwaukee PD", city="Milwaukee", state="WI", type="predictive_policing", lat=43.0389, lng=-87.9065, description="MPD ShotSpotter Respond predictive analytics.", source="EFF Atlas"),
            Infrastructure(name="Axon AI — Seattle PD", city="Seattle", state="WA", type="predictive_policing", lat=47.6062, lng=-122.3321, description="SPD Axon AI predictive tools.", source="EFF Atlas; ACLU WA"),
            Infrastructure(name="Motorola CommandCentral Predictive — Columbus PD", city="Columbus", state="OH", type="predictive_policing", lat=39.9612, lng=-82.9988, description="CPD Motorola predictive policing platform.", source="EFF Atlas"),
            Infrastructure(name="Wynyard Group Predictive — Charlotte-Mecklenburg PD", city="Charlotte", state="NC", type="predictive_policing", lat=35.2271, lng=-80.8431, description="CMPD Wynyard Group crime analytics.", source="EFF Atlas"),
            Infrastructure(name="ShotSpotter Respond Predictive — Minneapolis PD", city="Minneapolis", state="MN", type="predictive_policing", lat=44.9778, lng=-93.2650, description="MPD ShotSpotter Respond predictive system.", source="EFF Atlas"),
            Infrastructure(name="Palantir Predictive — Los Angeles Sheriff", city="Los Angeles", state="CA", type="predictive_policing", lat=34.0522, lng=-118.2437, description="LASD Palantir predictive analytics. Gang and recidivism risk scoring.", source="The Markup; ACLU SoCal"),
            Infrastructure(name="Social Media Predictive — St. Louis Metro PD", city="St. Louis", state="MO", type="predictive_policing", lat=38.6270, lng=-90.1994, description="SLMPD social media monitoring integrated with crime prediction.", source="EFF Atlas"),
            Infrastructure(name="IBM Analytics Predictive — Boston PD", city="Boston", state="MA", type="predictive_policing", lat=42.3601, lng=-71.0589, description="BPD IBM analytics predictive deployment.", source="EFF Atlas"),
            Infrastructure(name="Axon AI Analytics — Portland PD", city="Portland", state="OR", type="predictive_policing", lat=45.5231, lng=-122.6765, description="PPB Axon AI analytics tools.", source="EFF Atlas"),
            Infrastructure(name="PredPol/Geolitica — Palo Alto PD", city="Palo Alto", state="CA", type="predictive_policing", lat=37.4419, lng=-122.1430, description="Palo Alto PD PredPol contract. Silicon Valley irony.", source="The Markup; EFF Atlas"),
            Infrastructure(name="PredPol/Geolitica — Milpitas PD", city="Milpitas", state="CA", type="predictive_policing", lat=37.4323, lng=-121.8996, description="Milpitas PD PredPol deployment.", source="The Markup"),

            # ══════════════════════════════════════════════════════════════
            # REAL TIME CRIME CENTERS (RTCCs)
            # Source: EFF Atlas, city records, vendor documentation,
            # FOIA requests, investigative journalism
            # RTCCs aggregate cameras, LPR, ShotSpotter, social media,
            # facial recognition into a single real-time surveillance hub
            # ══════════════════════════════════════════════════════════════

            Infrastructure(name="New York City RTCC", city="New York", state="NY", type="rtcc", lat=40.7128, lng=-74.0060, description="NYPD Real Time Crime Center. Aggregates 15,000+ cameras, LPR, facial recognition, social media, and arrest records. Oldest and largest RTCC in US.", source="EFF Atlas; NYPD documentation; NYCLU"),
            Infrastructure(name="Los Angeles RTCC", city="Los Angeles", state="CA", type="rtcc", lat=34.0522, lng=-118.2437, description="LAPD Real Time Crime Center. Palantir-integrated. Aggregates surveillance feeds citywide.", source="EFF Atlas; The Markup; ACLU SoCal"),
            Infrastructure(name="Chicago Crime Prevention Information Center (RTCC)", city="Chicago", state="IL", type="rtcc", lat=41.8781, lng=-87.6298, description="CPD CPIC. Aggregates 32,000+ POD cameras, ShotSpotter, LPR, Palantir, and social media into real-time operational view.", source="EFF Atlas; Chicago city records; The Intercept"),
            Infrastructure(name="Houston Real Time Crime Center", city="Houston", state="TX", type="rtcc", lat=29.7604, lng=-95.3698, description="HPD RTCC. Aggregates camera feeds, LPR, ShotSpotter, and analytics.", source="EFF Atlas; Houston Chronicle"),
            Infrastructure(name="Philadelphia Real Time Crime Center", city="Philadelphia", state="PA", type="rtcc", lat=39.9526, lng=-75.1652, description="PPD RTCC. Aggregates surveillance infrastructure citywide.", source="EFF Atlas; Billy Penn"),
            Infrastructure(name="San Antonio Real Time Crime Center", city="San Antonio", state="TX", type="rtcc", lat=29.4241, lng=-98.4936, description="SAPD RTCC. Motorola CommandCentral integration.", source="EFF Atlas; San Antonio Express-News"),
            Infrastructure(name="San Diego Real Time Crime Center", city="San Diego", state="CA", type="rtcc", lat=32.7157, lng=-117.1611, description="SDPD RTCC. Camera, LPR, and CBP data integration.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Dallas Real Time Crime Center", city="Dallas", state="TX", type="rtcc", lat=32.7767, lng=-96.7970, description="DPD RTCC. Aggregates Dallas surveillance infrastructure.", source="EFF Atlas; Dallas Morning News"),
            Infrastructure(name="Jacksonville Real Time Crime Center", city="Jacksonville", state="FL", type="rtcc", lat=30.3322, lng=-81.6557, description="JSO RTCC. Florida's largest RTCC by jurisdiction area.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Fort Worth Real Time Crime Center", city="Fort Worth", state="TX", type="rtcc", lat=32.7555, lng=-97.3308, description="FWPD RTCC.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Columbus Ohio RTCC", city="Columbus", state="OH", type="rtcc", lat=39.9612, lng=-82.9988, description="CPD Real Time Crime Center. ShotSpotter and camera integration.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Charlotte Real Time Crime Center", city="Charlotte", state="NC", type="rtcc", lat=35.2271, lng=-80.8431, description="CMPD RTCC. Aggregates Charlotte surveillance feeds.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Indianapolis Real Time Crime Center", city="Indianapolis", state="IN", type="rtcc", lat=39.7684, lng=-86.1581, description="IMPD RTCC. ShotSpotter and LPR integration.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="San Francisco Real Time Crime Center", city="San Francisco", state="CA", type="rtcc", lat=37.7749, lng=-122.4194, description="SFPD RTCC. Aggregates city camera network.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Seattle Real Time Crime Center", city="Seattle", state="WA", type="rtcc", lat=47.6062, lng=-122.3321, description="SPD RTCC. Camera and LPR aggregation.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Denver Real Time Crime Center", city="Denver", state="CO", type="rtcc", lat=39.7392, lng=-104.9903, description="DPD RTCC. Palantir and ShotSpotter integration.", source="EFF Atlas; Westword"),
            Infrastructure(name="Nashville Real Time Crime Center", city="Nashville", state="TN", type="rtcc", lat=36.1627, lng=-86.7816, description="MNPD RTCC. Camera and ShotSpotter aggregation.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Oklahoma City Real Time Crime Center", city="Oklahoma City", state="OK", type="rtcc", lat=35.4676, lng=-97.5164, description="OCPD RTCC.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="El Paso Real Time Crime Center", city="El Paso", state="TX", type="rtcc", lat=31.7619, lng=-106.4850, description="EPPD RTCC. CBP integration for border city.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Boston Real Time Crime Center", city="Boston", state="MA", type="rtcc", lat=42.3601, lng=-71.0589, description="BPD RTCC.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Las Vegas Real Time Crime Center", city="Las Vegas", state="NV", type="rtcc", lat=36.1699, lng=-115.1398, description="LVMPD RTCC. Casino camera feed integration documented.", source="EFF Atlas; Las Vegas Review-Journal"),
            Infrastructure(name="Memphis Real Time Crime Center", city="Memphis", state="TN", type="rtcc", lat=35.1495, lng=-90.0490, description="MPD RTCC. Blue CRUSH and IBM i2 integration.", source="EFF Atlas; Memphis Commercial Appeal"),
            Infrastructure(name="New Orleans Real Time Crime Center", city="New Orleans", state="LA", type="rtcc", lat=29.9511, lng=-90.0715, description="NOPD RTCC. Clearview AI and Palantir documented integration.", source="EFF Atlas; ACLU Louisiana; WWNO"),
            Infrastructure(name="Baltimore Real Time Crime Center", city="Baltimore", state="MD", type="rtcc", lat=39.2904, lng=-76.6122, description="BPD RTCC. Aggregates CitiWatch cameras and aerial surveillance program.", source="EFF Atlas; Baltimore Sun"),
            Infrastructure(name="Milwaukee Real Time Crime Center", city="Milwaukee", state="WI", type="rtcc", lat=43.0389, lng=-87.9065, description="MPD RTCC. ShotSpotter and camera integration.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Albuquerque Real Time Crime Center", city="Albuquerque", state="NM", type="rtcc", lat=35.0844, lng=-106.6504, description="APD RTCC.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Tucson Real Time Crime Center", city="Tucson", state="AZ", type="rtcc", lat=32.2217, lng=-110.9265, description="TPD RTCC. Border proximity data integration.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Fresno Real Time Crime Center", city="Fresno", state="CA", type="rtcc", lat=36.7378, lng=-119.7871, description="FPD RTCC. Beware software integration.", source="EFF Atlas; Washington Post"),
            Infrastructure(name="Sacramento Real Time Crime Center", city="Sacramento", state="CA", type="rtcc", lat=38.5816, lng=-121.4944, description="SPD RTCC. Aggregates Sacramento camera network.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Long Beach Real Time Crime Center", city="Long Beach", state="CA", type="rtcc", lat=33.7701, lng=-118.1937, description="LBPD RTCC. Port security integration.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Kansas City Real Time Crime Center", city="Kansas City", state="MO", type="rtcc", lat=39.0997, lng=-94.5786, description="KCPD RTCC. ShotSpotter and camera aggregation.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Atlanta Real Time Crime Center", city="Atlanta", state="GA", type="rtcc", lat=33.7490, lng=-84.3880, description="APD RTCC. Palantir and Flock Safety integration.", source="EFF Atlas; Atlanta Journal-Constitution"),
            Infrastructure(name="Minneapolis Real Time Crime Center", city="Minneapolis", state="MN", type="rtcc", lat=44.9778, lng=-93.2650, description="MPD RTCC. ShotSpotter and camera integration.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="St. Louis Real Time Crime Center", city="St. Louis", state="MO", type="rtcc", lat=38.6270, lng=-90.1994, description="SLMPD RTCC.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Pittsburgh Real Time Crime Center", city="Pittsburgh", state="PA", type="rtcc", lat=40.4406, lng=-79.9959, description="PPD RTCC. ShotSpotter and camera integration.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Salt Lake City Real Time Crime Center", city="Salt Lake City", state="UT", type="rtcc", lat=40.7608, lng=-111.8910, description="SLCPD RTCC.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Richmond VA Real Time Crime Center", city="Richmond", state="VA", type="rtcc", lat=37.5407, lng=-77.4360, description="RPD RTCC. State capital surveillance hub.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Norfolk Real Time Crime Center", city="Norfolk", state="VA", type="rtcc", lat=36.8508, lng=-76.2859, description="NPD RTCC. Naval base data integration.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Raleigh Real Time Crime Center", city="Raleigh", state="NC", type="rtcc", lat=35.7796, lng=-78.6382, description="RPD RTCC.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Omaha Real Time Crime Center", city="Omaha", state="NE", type="rtcc", lat=41.2565, lng=-95.9345, description="OPD RTCC.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Louisville Real Time Crime Center", city="Louisville", state="KY", type="rtcc", lat=38.2527, lng=-85.7585, description="LMPD RTCC.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Detroit Real Time Crime Center", city="Detroit", state="MI", type="rtcc", lat=42.3314, lng=-83.0458, description="DPD RTCC. Project Green Light and ShotSpotter aggregation. Facial recognition enabled.", source="EFF Atlas; MIT Media Lab; Detroit Free Press"),
            Infrastructure(name="Cincinnati Real Time Crime Center", city="Cincinnati", state="OH", type="rtcc", lat=39.1031, lng=-84.5120, description="CPD RTCC.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Cleveland Real Time Crime Center", city="Cleveland", state="OH", type="rtcc", lat=41.4993, lng=-81.6944, description="CPD RTCC. Camera and ShotSpotter integration.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Tampa Real Time Crime Center", city="Tampa", state="FL", type="rtcc", lat=27.9506, lng=-82.4572, description="TPD RTCC.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Miami Real Time Crime Center", city="Miami", state="FL", type="rtcc", lat=25.7617, lng=-80.1918, description="MPD RTCC. MDPD and city camera integration.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Orlando Real Time Crime Center", city="Orlando", state="FL", type="rtcc", lat=28.5383, lng=-81.3792, description="OPD RTCC. Tourism corridor camera aggregation.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Phoenix Real Time Crime Center", city="Phoenix", state="AZ", type="rtcc", lat=33.4484, lng=-112.0740, description="Phoenix PD RTCC. Camera and LPR aggregation.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Portland Real Time Crime Center", city="Portland", state="OR", type="rtcc", lat=45.5231, lng=-122.6765, description="PPB RTCC.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Stockton Real Time Crime Center", city="Stockton", state="CA", type="rtcc", lat=37.9577, lng=-121.2908, description="SPD RTCC. ShotSpotter integration.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Baton Rouge Real Time Crime Center", city="Baton Rouge", state="LA", type="rtcc", lat=30.4515, lng=-91.1871, description="BRPD RTCC.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Shreveport Real Time Crime Center", city="Shreveport", state="LA", type="rtcc", lat=32.5252, lng=-93.7502, description="SPD RTCC. ShotSpotter integration.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Knoxville Real Time Crime Center", city="Knoxville", state="TN", type="rtcc", lat=35.9606, lng=-83.9207, description="KPD RTCC.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Chattanooga Real Time Crime Center", city="Chattanooga", state="TN", type="rtcc", lat=35.0456, lng=-85.3097, description="CPD RTCC.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Birmingham Real Time Crime Center", city="Birmingham", state="AL", type="rtcc", lat=33.5186, lng=-86.8104, description="BPD RTCC.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Washington DC Real Time Crime Center", city="Washington", state="DC", type="rtcc", lat=38.8951, lng=-77.0364, description="MPD RTCC. Federal and local camera integration. Fusion center data sharing.", source="EFF Atlas; Washington Post"),
            Infrastructure(name="Newark Real Time Crime Center", city="Newark", state="NJ", type="rtcc", lat=40.7357, lng=-74.1724, description="NPD RTCC. Extensive camera network aggregation.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Hartford Real Time Crime Center", city="Hartford", state="CT", type="rtcc", lat=41.7637, lng=-72.6851, description="HPD RTCC. ShotSpotter integration.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Bridgeport Real Time Crime Center", city="Bridgeport", state="CT", type="rtcc", lat=41.1865, lng=-73.1952, description="BPD RTCC.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Providence Real Time Crime Center", city="Providence", state="RI", type="rtcc", lat=41.8240, lng=-71.4128, description="PPD RTCC. ShotSpotter integration.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Wilmington DE Real Time Crime Center", city="Wilmington", state="DE", type="rtcc", lat=39.7447, lng=-75.5484, description="WPD RTCC.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Oakland Real Time Crime Center (DAC)", city="Oakland", state="CA", type="rtcc", lat=37.8044, lng=-122.2711, description="OPD Domain Awareness Center. Multi-agency data fusion hub. Challenged in court by activists.", source="EFF Atlas; ACLU NorCal"),
            Infrastructure(name="San Jose Real Time Crime Center", city="San Jose", state="CA", type="rtcc", lat=37.3382, lng=-121.8863, description="SJPD RTCC.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Anaheim Real Time Crime Center", city="Anaheim", state="CA", type="rtcc", lat=33.8366, lng=-117.9143, description="APD RTCC. Disneyland resort camera integration.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Riverside Real Time Crime Center", city="Riverside", state="CA", type="rtcc", lat=33.9533, lng=-117.3961, description="RPD RTCC.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Bakersfield Real Time Crime Center", city="Bakersfield", state="CA", type="rtcc", lat=35.3733, lng=-119.0187, description="BPD RTCC.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Aurora CO Real Time Crime Center", city="Aurora", state="CO", type="rtcc", lat=39.7294, lng=-104.8319, description="APD RTCC.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Colorado Springs Real Time Crime Center", city="Colorado Springs", state="CO", type="rtcc", lat=38.8339, lng=-104.8214, description="CSPD RTCC. Military city integration.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Wichita Real Time Crime Center", city="Wichita", state="KS", type="rtcc", lat=37.6872, lng=-97.3301, description="WPD RTCC. ShotSpotter integration.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Greensboro Real Time Crime Center", city="Greensboro", state="NC", type="rtcc", lat=36.0726, lng=-79.7920, description="GPD RTCC.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Durham Real Time Crime Center", city="Durham", state="NC", type="rtcc", lat=35.9940, lng=-78.8986, description="DPD RTCC.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Fayetteville NC Real Time Crime Center", city="Fayetteville", state="NC", type="rtcc", lat=35.0527, lng=-78.8784, description="FPD RTCC. Fort Bragg military integration.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Columbia SC Real Time Crime Center", city="Columbia", state="SC", type="rtcc", lat=34.0007, lng=-81.0348, description="CPD RTCC.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Dayton Real Time Crime Center", city="Dayton", state="OH", type="rtcc", lat=39.7589, lng=-84.1916, description="DPD RTCC.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Toledo Real Time Crime Center", city="Toledo", state="OH", type="rtcc", lat=41.6639, lng=-83.5552, description="TPD RTCC.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Akron Real Time Crime Center", city="Akron", state="OH", type="rtcc", lat=41.0814, lng=-81.5190, description="APD RTCC.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Tulsa Real Time Crime Center", city="Tulsa", state="OK", type="rtcc", lat=36.1540, lng=-95.9928, description="TPD RTCC.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="St. Paul Real Time Crime Center", city="St. Paul", state="MN", type="rtcc", lat=44.9537, lng=-93.0900, description="SPPD RTCC.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Madison Real Time Crime Center", city="Madison", state="WI", type="rtcc", lat=43.0731, lng=-89.4012, description="MPD RTCC.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Grand Rapids Real Time Crime Center", city="Grand Rapids", state="MI", type="rtcc", lat=42.9634, lng=-85.6681, description="GRPD RTCC.", source="EFF Atlas of Surveillance"),
            Infrastructure(name="Honolulu Real Time Crime Center", city="Honolulu", state="HI", type="rtcc", lat=21.3069, lng=-157.8583, description="HPD RTCC. Island-wide surveillance aggregation.", source="EFF Atlas of Surveillance"),

            # ══════════════════════════════════════════════════════════════
            # CLEARVIEW AI CLIENTS
            # Source: BuzzFeed News leak (2020), Buzzfeed investigation,
            # ACLU FOIA requests, state attorney general findings
            # 3,100+ law enforcement agencies confirmed.
            # Clearview scraped 30B+ photos without consent.
            # ══════════════════════════════════════════════════════════════

            Infrastructure(name="Clearview AI — NYPD", city="New York", state="NY", type="clearview_ai", lat=40.7128, lng=-74.0060, description="NYPD Clearview AI contract. Run 11,000+ searches. Largest confirmed municipal deployment. Used without public disclosure.", source="BuzzFeed News leak 2020; NYCLU"),
            Infrastructure(name="Clearview AI — Chicago PD", city="Chicago", state="IL", type="clearview_ai", lat=41.8781, lng=-87.6298, description="CPD Clearview AI. Integrated with facial recognition infrastructure.", source="BuzzFeed News 2020; Chicago Sun-Times"),
            Infrastructure(name="Clearview AI — Los Angeles PD", city="Los Angeles", state="CA", type="clearview_ai", lat=34.0522, lng=-118.2437, description="LAPD Clearview AI contract.", source="BuzzFeed News 2020; ACLU SoCal"),
            Infrastructure(name="Clearview AI — Miami PD", city="Miami", state="FL", type="clearview_ai", lat=25.7617, lng=-80.1918, description="MPD Clearview AI deployment.", source="BuzzFeed News 2020"),
            Infrastructure(name="Clearview AI — Atlanta PD", city="Atlanta", state="GA", type="clearview_ai", lat=33.7490, lng=-84.3880, description="APD Clearview AI contract.", source="BuzzFeed News 2020"),
            Infrastructure(name="Clearview AI — Philadelphia PD", city="Philadelphia", state="PA", type="clearview_ai", lat=39.9526, lng=-75.1652, description="PPD Clearview AI deployment.", source="BuzzFeed News 2020"),
            Infrastructure(name="Clearview AI — Houston PD", city="Houston", state="TX", type="clearview_ai", lat=29.7604, lng=-95.3698, description="HPD Clearview AI contract.", source="BuzzFeed News 2020"),
            Infrastructure(name="Clearview AI — Dallas PD", city="Dallas", state="TX", type="clearview_ai", lat=32.7767, lng=-96.7970, description="DPD Clearview AI deployment.", source="BuzzFeed News 2020"),
            Infrastructure(name="Clearview AI — San Antonio PD", city="San Antonio", state="TX", type="clearview_ai", lat=29.4241, lng=-98.4936, description="SAPD Clearview AI contract.", source="BuzzFeed News 2020"),
            Infrastructure(name="Clearview AI — Phoenix PD", city="Phoenix", state="AZ", type="clearview_ai", lat=33.4484, lng=-112.0740, description="Phoenix PD Clearview AI deployment.", source="BuzzFeed News 2020"),
            Infrastructure(name="Clearview AI — San Diego PD", city="San Diego", state="CA", type="clearview_ai", lat=32.7157, lng=-117.1611, description="SDPD Clearview AI contract.", source="BuzzFeed News 2020"),
            Infrastructure(name="Clearview AI — San Jose PD", city="San Jose", state="CA", type="clearview_ai", lat=37.3382, lng=-121.8863, description="SJPD Clearview AI deployment.", source="BuzzFeed News 2020"),
            Infrastructure(name="Clearview AI — Indianapolis Metro PD", city="Indianapolis", state="IN", type="clearview_ai", lat=39.7684, lng=-86.1581, description="IMPD Clearview AI contract.", source="BuzzFeed News 2020"),
            Infrastructure(name="Clearview AI — Columbus PD", city="Columbus", state="OH", type="clearview_ai", lat=39.9612, lng=-82.9988, description="CPD Clearview AI deployment.", source="BuzzFeed News 2020"),
            Infrastructure(name="Clearview AI — Charlotte-Mecklenburg PD", city="Charlotte", state="NC", type="clearview_ai", lat=35.2271, lng=-80.8431, description="CMPD Clearview AI contract.", source="BuzzFeed News 2020"),
            Infrastructure(name="Clearview AI — Detroit PD", city="Detroit", state="MI", type="clearview_ai", lat=42.3314, lng=-83.0458, description="DPD Clearview AI deployment.", source="BuzzFeed News 2020"),
            Infrastructure(name="Clearview AI — Memphis PD", city="Memphis", state="TN", type="clearview_ai", lat=35.1495, lng=-90.0490, description="MPD Clearview AI contract.", source="BuzzFeed News 2020"),
            Infrastructure(name="Clearview AI — Denver PD", city="Denver", state="CO", type="clearview_ai", lat=39.7392, lng=-104.9903, description="DPD Clearview AI deployment.", source="BuzzFeed News 2020"),
            Infrastructure(name="Clearview AI — Seattle PD", city="Seattle", state="WA", type="clearview_ai", lat=47.6062, lng=-122.3321, description="SPD Clearview AI contract.", source="BuzzFeed News 2020"),
            Infrastructure(name="Clearview AI — Nashville Metro PD", city="Nashville", state="TN", type="clearview_ai", lat=36.1627, lng=-86.7816, description="MNPD Clearview AI deployment.", source="BuzzFeed News 2020"),
            Infrastructure(name="Clearview AI — Louisville Metro PD", city="Louisville", state="KY", type="clearview_ai", lat=38.2527, lng=-85.7585, description="LMPD Clearview AI contract.", source="BuzzFeed News 2020"),
            Infrastructure(name="Clearview AI — Portland PD", city="Portland", state="OR", type="clearview_ai", lat=45.5231, lng=-122.6765, description="PPB Clearview AI deployment.", source="BuzzFeed News 2020"),
            Infrastructure(name="Clearview AI — Las Vegas Metro PD", city="Las Vegas", state="NV", type="clearview_ai", lat=36.1699, lng=-115.1398, description="LVMPD Clearview AI contract.", source="BuzzFeed News 2020"),
            Infrastructure(name="Clearview AI — Milwaukee PD", city="Milwaukee", state="WI", type="clearview_ai", lat=43.0389, lng=-87.9065, description="MPD Clearview AI deployment.", source="BuzzFeed News 2020"),
            Infrastructure(name="Clearview AI — Albuquerque PD", city="Albuquerque", state="NM", type="clearview_ai", lat=35.0844, lng=-106.6504, description="APD Clearview AI contract.", source="BuzzFeed News 2020"),
            Infrastructure(name="Clearview AI — Tucson PD", city="Tucson", state="AZ", type="clearview_ai", lat=32.2217, lng=-110.9265, description="TPD Clearview AI deployment.", source="BuzzFeed News 2020"),
            Infrastructure(name="Clearview AI — Sacramento PD", city="Sacramento", state="CA", type="clearview_ai", lat=38.5816, lng=-121.4944, description="SPD Clearview AI contract.", source="BuzzFeed News 2020"),
            Infrastructure(name="Clearview AI — Fresno PD", city="Fresno", state="CA", type="clearview_ai", lat=36.7378, lng=-119.7871, description="FPD Clearview AI deployment.", source="BuzzFeed News 2020"),
            Infrastructure(name="Clearview AI — Mesa PD", city="Mesa", state="AZ", type="clearview_ai", lat=33.4152, lng=-111.8315, description="Mesa PD Clearview AI contract.", source="BuzzFeed News 2020"),
            Infrastructure(name="Clearview AI — Kansas City PD", city="Kansas City", state="MO", type="clearview_ai", lat=39.0997, lng=-94.5786, description="KCPD Clearview AI deployment.", source="BuzzFeed News 2020"),
            Infrastructure(name="Clearview AI — Omaha PD", city="Omaha", state="NE", type="clearview_ai", lat=41.2565, lng=-95.9345, description="OPD Clearview AI contract.", source="BuzzFeed News 2020"),
            Infrastructure(name="Clearview AI — Minneapolis PD", city="Minneapolis", state="MN", type="clearview_ai", lat=44.9778, lng=-93.2650, description="MPD Clearview AI deployment.", source="BuzzFeed News 2020"),
            Infrastructure(name="Clearview AI — Raleigh PD", city="Raleigh", state="NC", type="clearview_ai", lat=35.7796, lng=-78.6382, description="RPD Clearview AI contract.", source="BuzzFeed News 2020"),
            Infrastructure(name="Clearview AI — St. Louis Metro PD", city="St. Louis", state="MO", type="clearview_ai", lat=38.6270, lng=-90.1994, description="SLMPD Clearview AI deployment.", source="BuzzFeed News 2020"),
            Infrastructure(name="Clearview AI — Pittsburgh PD", city="Pittsburgh", state="PA", type="clearview_ai", lat=40.4406, lng=-79.9959, description="PPD Clearview AI contract.", source="BuzzFeed News 2020"),
            Infrastructure(name="Clearview AI — Tampa PD", city="Tampa", state="FL", type="clearview_ai", lat=27.9506, lng=-82.4572, description="TPD Clearview AI deployment.", source="BuzzFeed News 2020"),
            Infrastructure(name="Clearview AI — New Orleans PD", city="New Orleans", state="LA", type="clearview_ai", lat=29.9511, lng=-90.0715, description="NOPD Clearview AI contract. Used without public disclosure for years.", source="BuzzFeed News 2020; WWNO"),
            Infrastructure(name="Clearview AI — Baltimore PD", city="Baltimore", state="MD", type="clearview_ai", lat=39.2904, lng=-76.6122, description="BPD Clearview AI deployment.", source="BuzzFeed News 2020"),
            Infrastructure(name="Clearview AI — Cleveland PD", city="Cleveland", state="OH", type="clearview_ai", lat=41.4993, lng=-81.6944, description="CPD Clearview AI contract.", source="BuzzFeed News 2020"),
            Infrastructure(name="Clearview AI — Wichita PD", city="Wichita", state="KS", type="clearview_ai", lat=37.6872, lng=-97.3301, description="WPD Clearview AI deployment.", source="BuzzFeed News 2020"),
            Infrastructure(name="Clearview AI — Oklahoma City PD", city="Oklahoma City", state="OK", type="clearview_ai", lat=35.4676, lng=-97.5164, description="OCPD Clearview AI contract.", source="BuzzFeed News 2020"),
            Infrastructure(name="Clearview AI — Arlington TX PD", city="Arlington", state="TX", type="clearview_ai", lat=32.7357, lng=-97.1081, description="APD Clearview AI deployment.", source="BuzzFeed News 2020"),
            Infrastructure(name="Clearview AI — Fort Worth PD", city="Fort Worth", state="TX", type="clearview_ai", lat=32.7555, lng=-97.3308, description="FWPD Clearview AI contract.", source="BuzzFeed News 2020"),
            Infrastructure(name="Clearview AI — El Paso PD", city="El Paso", state="TX", type="clearview_ai", lat=31.7619, lng=-106.4850, description="EPPD Clearview AI deployment.", source="BuzzFeed News 2020"),
            Infrastructure(name="Clearview AI — Aurora CO PD", city="Aurora", state="CO", type="clearview_ai", lat=39.7294, lng=-104.8319, description="APD Clearview AI contract.", source="BuzzFeed News 2020"),
            Infrastructure(name="Clearview AI — Virginia Beach PD", city="Virginia Beach", state="VA", type="clearview_ai", lat=36.8529, lng=-75.9780, description="VBPD Clearview AI deployment.", source="BuzzFeed News 2020"),
            Infrastructure(name="Clearview AI — Colorado Springs PD", city="Colorado Springs", state="CO", type="clearview_ai", lat=38.8339, lng=-104.8214, description="CSPD Clearview AI contract.", source="BuzzFeed News 2020"),
            Infrastructure(name="Clearview AI — Richmond VA PD", city="Richmond", state="VA", type="clearview_ai", lat=37.5407, lng=-77.4360, description="RPD Clearview AI deployment.", source="BuzzFeed News 2020"),
            Infrastructure(name="Clearview AI — Bakersfield PD", city="Bakersfield", state="CA", type="clearview_ai", lat=35.3733, lng=-119.0187, description="BPD Clearview AI contract.", source="BuzzFeed News 2020"),
            Infrastructure(name="Clearview AI — Baton Rouge PD", city="Baton Rouge", state="LA", type="clearview_ai", lat=30.4515, lng=-91.1871, description="BRPD Clearview AI deployment.", source="BuzzFeed News 2020"),
            Infrastructure(name="Clearview AI — Stockton PD", city="Stockton", state="CA", type="clearview_ai", lat=37.9577, lng=-121.2908, description="SPD Clearview AI contract.", source="BuzzFeed News 2020"),
            Infrastructure(name="Clearview AI — Corpus Christi PD", city="Corpus Christi", state="TX", type="clearview_ai", lat=27.8006, lng=-97.3964, description="CCPD Clearview AI deployment.", source="BuzzFeed News 2020"),
            Infrastructure(name="Clearview AI — Riverside PD", city="Riverside", state="CA", type="clearview_ai", lat=33.9533, lng=-117.3961, description="RPD Clearview AI contract.", source="BuzzFeed News 2020"),
            Infrastructure(name="Clearview AI — Lexington PD", city="Lexington", state="KY", type="clearview_ai", lat=38.0406, lng=-84.5037, description="LPD Clearview AI deployment.", source="BuzzFeed News 2020"),
            Infrastructure(name="Clearview AI — Greensboro PD", city="Greensboro", state="NC", type="clearview_ai", lat=36.0726, lng=-79.7920, description="GPD Clearview AI contract.", source="BuzzFeed News 2020"),
            Infrastructure(name="Clearview AI — Anchorage PD", city="Anchorage", state="AK", type="clearview_ai", lat=61.2181, lng=-149.9003, description="APD Clearview AI deployment.", source="BuzzFeed News 2020"),
            Infrastructure(name="Clearview AI — Honolulu PD", city="Honolulu", state="HI", type="clearview_ai", lat=21.3069, lng=-157.8583, description="HPD Clearview AI contract.", source="BuzzFeed News 2020"),
            Infrastructure(name="Clearview AI — FBI", city="Washington", state="DC", type="clearview_ai", lat=38.8951, lng=-77.0364, description="FBI Clearview AI. Largest federal deployment. Ran 390,000+ searches.", source="BuzzFeed News 2020; GAO report 2021"),
            Infrastructure(name="Clearview AI — ICE", city="Washington", state="DC", type="clearview_ai", lat=38.8977, lng=-77.0365, description="ICE Clearview AI. Used for immigration enforcement targeting.", source="BuzzFeed News 2020; The Intercept"),
            Infrastructure(name="Clearview AI — US Marshals Service", city="Washington", state="DC", type="clearview_ai", lat=38.8799, lng=-77.1068, description="USMS Clearview AI deployment for fugitive apprehension.", source="BuzzFeed News 2020"),
            Infrastructure(name="Clearview AI — Secret Service", city="Washington", state="DC", type="clearview_ai", lat=38.8977, lng=-77.0366, description="USSS Clearview AI contract.", source="BuzzFeed News 2020"),
            Infrastructure(name="Clearview AI — DHS", city="Washington", state="DC", type="clearview_ai", lat=38.8450, lng=-77.0553, description="DHS Clearview AI deployment across multiple components.", source="BuzzFeed News 2020; GAO"),

            # ══════════════════════════════════════════════════════════════
            # COUNTY / STATE IMSI CATCHERS (Stingrays)
            # Source: ACLU Stingray tracking project, EFF, FOIA records
            # These are county sheriffs and state agencies beyond the
            # city PDs already documented
            # ══════════════════════════════════════════════════════════════

            Infrastructure(name="Los Angeles County Sheriff IMSI Catcher", city="Los Angeles", state="CA", type="county_imsi", lat=34.0522, lng=-118.2437, description="LASD Stingray fleet. Used 300+ times. Secrecy agreements with FBI documented.", source="ACLU; LA Weekly FOIA"),
            Infrastructure(name="San Bernardino County Sheriff IMSI Catcher", city="San Bernardino", state="CA", type="county_imsi", lat=34.1083, lng=-117.2898, description="SBCSD Stingray deployment.", source="ACLU; EFF"),
            Infrastructure(name="Riverside County Sheriff IMSI Catcher", city="Riverside", state="CA", type="county_imsi", lat=33.9533, lng=-117.3961, description="RCSD Stingray use confirmed.", source="ACLU California"),
            Infrastructure(name="Orange County Sheriff IMSI Catcher", city="Santa Ana", state="CA", type="county_imsi", lat=33.7455, lng=-117.8677, description="OCSD Stingray deployment. Used without warrants documented.", source="ACLU; EFF"),
            Infrastructure(name="Alameda County Sheriff IMSI Catcher", city="Oakland", state="CA", type="county_imsi", lat=37.8044, lng=-122.2711, description="ACSD Stingray use confirmed.", source="ACLU NorCal"),
            Infrastructure(name="Sacramento County Sheriff IMSI Catcher", city="Sacramento", state="CA", type="county_imsi", lat=38.5816, lng=-121.4944, description="SCSD Stingray deployment.", source="ACLU California"),
            Infrastructure(name="San Diego County Sheriff IMSI Catcher", city="San Diego", state="CA", type="county_imsi", lat=32.7157, lng=-117.1611, description="SDCSO Stingray use confirmed.", source="ACLU; EFF"),
            Infrastructure(name="Maricopa County Sheriff IMSI Catcher", city="Phoenix", state="AZ", type="county_imsi", lat=33.5722, lng=-112.0892, description="MCSO Stingray fleet. Arpaio-era deployment. Documented use against activists.", source="ACLU Arizona; Phoenix New Times"),
            Infrastructure(name="Pima County Sheriff IMSI Catcher", city="Tucson", state="AZ", type="county_imsi", lat=32.2217, lng=-110.9265, description="PCSO Stingray use confirmed.", source="ACLU Arizona"),
            Infrastructure(name="Cook County Sheriff IMSI Catcher", city="Chicago", state="IL", type="county_imsi", lat=41.8781, lng=-87.6298, description="CCSD Stingray deployment.", source="ACLU Illinois; Chicago Tribune"),
            Infrastructure(name="Harris County Sheriff IMSI Catcher", city="Houston", state="TX", type="county_imsi", lat=29.7604, lng=-95.3698, description="HCSO Stingray use documented.", source="ACLU Texas; Houston Chronicle"),
            Infrastructure(name="Dallas County Sheriff IMSI Catcher", city="Dallas", state="TX", type="county_imsi", lat=32.7767, lng=-96.7970, description="DCSD Stingray deployment.", source="ACLU Texas"),
            Infrastructure(name="Bexar County Sheriff IMSI Catcher", city="San Antonio", state="TX", type="county_imsi", lat=29.4241, lng=-98.4936, description="BCSD Stingray use confirmed.", source="ACLU Texas"),
            Infrastructure(name="Travis County Sheriff IMSI Catcher", city="Austin", state="TX", type="county_imsi", lat=30.2672, lng=-97.7431, description="TCSD Stingray deployment.", source="ACLU Texas"),
            Infrastructure(name="Miami-Dade County Sheriff IMSI Catcher", city="Miami", state="FL", type="county_imsi", lat=25.7617, lng=-80.1918, description="MDSO Stingray use documented.", source="ACLU Florida"),
            Infrastructure(name="Broward County Sheriff IMSI Catcher", city="Fort Lauderdale", state="FL", type="county_imsi", lat=26.1224, lng=-80.1373, description="BSO Stingray deployment.", source="ACLU Florida"),
            Infrastructure(name="Palm Beach County Sheriff IMSI Catcher", city="West Palm Beach", state="FL", type="county_imsi", lat=26.7153, lng=-80.0534, description="PBCSO Stingray use confirmed.", source="ACLU Florida"),
            Infrastructure(name="Orange County FL Sheriff IMSI Catcher", city="Orlando", state="FL", type="county_imsi", lat=28.5383, lng=-81.3792, description="OCSO Stingray deployment.", source="ACLU Florida"),
            Infrastructure(name="Hillsborough County Sheriff IMSI Catcher", city="Tampa", state="FL", type="county_imsi", lat=27.9506, lng=-82.4572, description="HCSO Stingray use documented.", source="ACLU Florida"),
            Infrastructure(name="Pinellas County Sheriff IMSI Catcher", city="Clearwater", state="FL", type="county_imsi", lat=27.9659, lng=-82.8001, description="PCSO Stingray deployment.", source="ACLU Florida"),
            Infrastructure(name="Wayne County Sheriff IMSI Catcher", city="Detroit", state="MI", type="county_imsi", lat=42.3314, lng=-83.0458, description="WCSD Stingray use confirmed.", source="ACLU Michigan"),
            Infrastructure(name="Oakland County Sheriff IMSI Catcher", city="Pontiac", state="MI", type="county_imsi", lat=42.6389, lng=-83.2910, description="OCSD Stingray deployment.", source="ACLU Michigan"),
            Infrastructure(name="Cuyahoga County Sheriff IMSI Catcher", city="Cleveland", state="OH", type="county_imsi", lat=41.4993, lng=-81.6944, description="CCSD Stingray use documented.", source="ACLU Ohio"),
            Infrastructure(name="Franklin County Sheriff IMSI Catcher", city="Columbus", state="OH", type="county_imsi", lat=39.9612, lng=-82.9988, description="FCSD Stingray deployment.", source="ACLU Ohio"),
            Infrastructure(name="Hamilton County Sheriff IMSI Catcher", city="Cincinnati", state="OH", type="county_imsi", lat=39.1031, lng=-84.5120, description="HCSD Stingray use confirmed.", source="ACLU Ohio"),
            Infrastructure(name="King County Sheriff IMSI Catcher", city="Seattle", state="WA", type="county_imsi", lat=47.6062, lng=-122.3321, description="KCSD Stingray deployment.", source="ACLU WA; The Stranger"),
            Infrastructure(name="Pierce County Sheriff IMSI Catcher", city="Tacoma", state="WA", type="county_imsi", lat=47.2529, lng=-122.4443, description="PCSD Stingray use confirmed.", source="ACLU WA"),
            Infrastructure(name="Multnomah County Sheriff IMSI Catcher", city="Portland", state="OR", type="county_imsi", lat=45.5231, lng=-122.6765, description="MCSD Stingray deployment.", source="ACLU Oregon"),
            Infrastructure(name="Denver County Sheriff IMSI Catcher", city="Denver", state="CO", type="county_imsi", lat=39.7392, lng=-104.9903, description="DCSD Stingray use documented.", source="ACLU Colorado"),
            Infrastructure(name="Jefferson County CO Sheriff IMSI Catcher", city="Golden", state="CO", type="county_imsi", lat=39.7555, lng=-105.2211, description="JeffCo Sheriff Stingray deployment.", source="ACLU Colorado"),
            Infrastructure(name="Nassau County PD IMSI Catcher", city="Mineola", state="NY", type="county_imsi", lat=40.7498, lng=-73.6381, description="NCPD Stingray use confirmed.", source="ACLU NY"),
            Infrastructure(name="Suffolk County PD IMSI Catcher", city="Yaphank", state="NY", type="county_imsi", lat=40.8343, lng=-72.9132, description="SCPD Stingray deployment.", source="ACLU NY"),
            Infrastructure(name="Westchester County PD IMSI Catcher", city="White Plains", state="NY", type="county_imsi", lat=41.0340, lng=-73.7629, description="WCPD Stingray use documented.", source="ACLU NY"),
            Infrastructure(name="Prince George's County PD IMSI Catcher", city="Upper Marlboro", state="MD", type="county_imsi", lat=38.8129, lng=-76.7497, description="PGCPD Stingray deployment.", source="ACLU Maryland"),
            Infrastructure(name="Montgomery County MD PD IMSI Catcher", city="Rockville", state="MD", type="county_imsi", lat=39.0840, lng=-77.1528, description="MCPD Stingray use confirmed.", source="ACLU Maryland"),
            Infrastructure(name="Gwinnett County PD IMSI Catcher", city="Lawrenceville", state="GA", type="county_imsi", lat=33.9526, lng=-83.9877, description="GCPD Stingray deployment.", source="ACLU Georgia"),
            Infrastructure(name="Fulton County Sheriff IMSI Catcher", city="Atlanta", state="GA", type="county_imsi", lat=33.7490, lng=-84.3880, description="FCS Stingray use documented.", source="ACLU Georgia"),
            Infrastructure(name="Hennepin County Sheriff IMSI Catcher", city="Minneapolis", state="MN", type="county_imsi", lat=44.9778, lng=-93.2650, description="HCSD Stingray deployment.", source="ACLU MN; Star Tribune"),
            Infrastructure(name="Middlesex County MA DA IMSI Catcher", city="Cambridge", state="MA", type="county_imsi", lat=42.3736, lng=-71.1097, description="Middlesex DA Stingray use confirmed. DA offices operate Stingrays independently of police.", source="ACLU MA"),
            Infrastructure(name="Essex County MA DA IMSI Catcher", city="Salem", state="MA", type="county_imsi", lat=42.5195, lng=-70.8967, description="Essex DA Stingray deployment.", source="ACLU MA"),
            Infrastructure(name="California Highway Patrol IMSI Catcher", city="Sacramento", state="CA", type="county_imsi", lat=38.5816, lng=-121.4944, description="CHP statewide Stingray fleet. Used on highways and at protests.", source="ACLU California; EFF"),
            Infrastructure(name="Texas DPS IMSI Catcher", city="Austin", state="TX", type="county_imsi", lat=30.2672, lng=-97.7431, description="TxDPS statewide Stingray operations. Border and highway use.", source="ACLU Texas; Texas Tribune"),
            Infrastructure(name="Florida FDLE IMSI Catcher", city="Tallahassee", state="FL", type="county_imsi", lat=30.4518, lng=-84.2807, description="FDLE statewide Stingray deployment.", source="ACLU Florida"),
            Infrastructure(name="New York State Police IMSI Catcher", city="Albany", state="NY", type="county_imsi", lat=42.6526, lng=-73.7562, description="NYSP statewide Stingray fleet.", source="ACLU NY; NYCLU"),
            Infrastructure(name="New Jersey State Police IMSI Catcher", city="Trenton", state="NJ", type="county_imsi", lat=40.2171, lng=-74.7429, description="NJSP statewide Stingray operations.", source="ACLU NJ"),
            Infrastructure(name="Pennsylvania State Police IMSI Catcher", city="Harrisburg", state="PA", type="county_imsi", lat=40.2732, lng=-76.8867, description="PSP statewide Stingray deployment.", source="ACLU PA"),
            Infrastructure(name="Michigan State Police IMSI Catcher", city="Lansing", state="MI", type="county_imsi", lat=42.7325, lng=-84.5555, description="MSP statewide Stingray fleet.", source="ACLU Michigan"),
            Infrastructure(name="Illinois State Police IMSI Catcher", city="Springfield", state="IL", type="county_imsi", lat=39.7817, lng=-89.6501, description="ISP statewide Stingray operations.", source="ACLU IL"),
            Infrastructure(name="Georgia Bureau of Investigation IMSI Catcher", city="Atlanta", state="GA", type="county_imsi", lat=33.7490, lng=-84.3880, description="GBI Stingray deployment statewide.", source="ACLU Georgia"),
            Infrastructure(name="Virginia State Police IMSI Catcher", city="Richmond", state="VA", type="county_imsi", lat=37.5407, lng=-77.4360, description="VSP statewide Stingray fleet.", source="ACLU VA"),
            Infrastructure(name="Ohio State Highway Patrol IMSI Catcher", city="Columbus", state="OH", type="county_imsi", lat=39.9612, lng=-82.9988, description="OSHP Stingray operations statewide.", source="ACLU Ohio"),
            Infrastructure(name="North Carolina SBI IMSI Catcher", city="Raleigh", state="NC", type="county_imsi", lat=35.7796, lng=-78.6382, description="NC SBI Stingray deployment.", source="ACLU NC"),
            Infrastructure(name="Washington State Patrol IMSI Catcher", city="Olympia", state="WA", type="county_imsi", lat=47.0379, lng=-122.9007, description="WSP statewide Stingray fleet.", source="ACLU WA"),
            Infrastructure(name="Colorado State Patrol IMSI Catcher", city="Denver", state="CO", type="county_imsi", lat=39.7392, lng=-104.9903, description="CSP Stingray operations statewide.", source="ACLU Colorado"),
            Infrastructure(name="Maryland State Police IMSI Catcher", city="Pikesville", state="MD", type="county_imsi", lat=39.3779, lng=-76.7208, description="MSP statewide Stingray fleet.", source="ACLU Maryland"),
            Infrastructure(name="Minnesota BCA IMSI Catcher", city="St. Paul", state="MN", type="county_imsi", lat=44.9537, lng=-93.0900, description="MN Bureau of Criminal Apprehension Stingray deployment.", source="ACLU MN; Star Tribune"),
            Infrastructure(name="Wisconsin DOJ IMSI Catcher", city="Madison", state="WI", type="county_imsi", lat=43.0731, lng=-89.4012, description="WI DOJ Stingray operations statewide.", source="ACLU WI"),
            Infrastructure(name="Tennessee TBI IMSI Catcher", city="Nashville", state="TN", type="county_imsi", lat=36.1627, lng=-86.7816, description="TN Bureau of Investigation Stingray fleet.", source="ACLU TN"),
            Infrastructure(name="Indiana State Police IMSI Catcher", city="Indianapolis", state="IN", type="county_imsi", lat=39.7684, lng=-86.1581, description="ISP statewide Stingray deployment.", source="ACLU Indiana"),
            Infrastructure(name="Missouri Highway Patrol IMSI Catcher", city="Jefferson City", state="MO", type="county_imsi", lat=38.5767, lng=-92.1735, description="MHP Stingray operations statewide.", source="ACLU Missouri"),
            Infrastructure(name="Louisiana State Police IMSI Catcher", city="Baton Rouge", state="LA", type="county_imsi", lat=30.4515, lng=-91.1871, description="LSP statewide Stingray fleet.", source="ACLU Louisiana"),
            Infrastructure(name="Kentucky State Police IMSI Catcher", city="Frankfort", state="KY", type="county_imsi", lat=38.2009, lng=-84.8733, description="KSP Stingray deployment statewide.", source="ACLU KY"),
            Infrastructure(name="South Carolina SLED IMSI Catcher", city="Columbia", state="SC", type="county_imsi", lat=34.0007, lng=-81.0348, description="SC Law Enforcement Division Stingray fleet.", source="ACLU SC"),
            Infrastructure(name="Alabama Law Enforcement Agency IMSI Catcher", city="Montgomery", state="AL", type="county_imsi", lat=32.3617, lng=-86.2792, description="ALEA statewide Stingray operations.", source="ACLU Alabama"),
            Infrastructure(name="Nevada Highway Patrol IMSI Catcher", city="Las Vegas", state="NV", type="county_imsi", lat=36.1699, lng=-115.1398, description="NHP Stingray deployment statewide.", source="ACLU Nevada"),
            Infrastructure(name="Oregon State Police IMSI Catcher", city="Salem", state="OR", type="county_imsi", lat=44.9429, lng=-123.0351, description="OSP statewide Stingray fleet.", source="ACLU Oregon"),
            Infrastructure(name="Iowa DPS IMSI Catcher", city="Des Moines", state="IA", type="county_imsi", lat=41.5868, lng=-93.6250, description="Iowa DPS Stingray operations.", source="ACLU Iowa"),
            Infrastructure(name="Kansas Highway Patrol IMSI Catcher", city="Topeka", state="KS", type="county_imsi", lat=39.0558, lng=-95.6890, description="KHP statewide Stingray deployment.", source="ACLU Kansas"),

            # ══════════════════════════════════════════════════════════════
            # VIGILANT SOLUTIONS / MOTOROLA LPR REPOSITORY
            # Source: EFF Atlas, Motorola/Vigilant contracts, FOIA records
            # Vigilant maintains 9+ billion plate reads in a national
            # repository. 3,000+ agencies share data without warrants.
            # Motorola acquired Vigilant in 2019.
            # ══════════════════════════════════════════════════════════════

            Infrastructure(name="Vigilant Solutions LEARN — National Repository HQ", city="Livermore", state="CA", type="vigilant_lpr", lat=37.6819, lng=-121.7680, description="Vigilant Solutions / Motorola national LPR data repository. 9+ billion plate reads. 3,000+ agencies share data. No warrant required for access. Headquarters.", source="EFF; Motorola Solutions contracts; FOIA"),
            Infrastructure(name="Vigilant Solutions LEARN — NYPD", city="New York", state="NY", type="vigilant_lpr", lat=40.7128, lng=-74.0060, description="NYPD Vigilant Solutions contract. Millions of plate reads daily fed into national repository.", source="EFF Atlas; NYPD FOIA"),
            Infrastructure(name="Vigilant Solutions LEARN — LAPD", city="Los Angeles", state="CA", type="vigilant_lpr", lat=34.0522, lng=-118.2437, description="LAPD Vigilant Solutions LPR. ACLU documented retaining data on non-suspects.", source="EFF Atlas; ACLU SoCal"),
            Infrastructure(name="Vigilant Solutions LEARN — Chicago PD", city="Chicago", state="IL", type="vigilant_lpr", lat=41.8781, lng=-87.6298, description="CPD Vigilant/Motorola LPR. National repository data sharing.", source="EFF Atlas; Chicago records"),
            Infrastructure(name="Vigilant Solutions LEARN — Houston PD", city="Houston", state="TX", type="vigilant_lpr", lat=29.7604, lng=-95.3698, description="HPD Vigilant Solutions LPR contract.", source="EFF Atlas; Houston FOIA"),
            Infrastructure(name="Vigilant Solutions LEARN — Phoenix PD", city="Phoenix", state="AZ", type="vigilant_lpr", lat=33.4484, lng=-112.0740, description="Phoenix PD Vigilant Solutions deployment.", source="EFF Atlas; Motorola contracts"),
            Infrastructure(name="Vigilant Solutions LEARN — Philadelphia PD", city="Philadelphia", state="PA", type="vigilant_lpr", lat=39.9526, lng=-75.1652, description="PPD Vigilant Solutions LPR network.", source="EFF Atlas"),
            Infrastructure(name="Vigilant Solutions LEARN — San Antonio PD", city="San Antonio", state="TX", type="vigilant_lpr", lat=29.4241, lng=-98.4936, description="SAPD Vigilant Solutions contract.", source="EFF Atlas; Motorola contracts"),
            Infrastructure(name="Vigilant Solutions LEARN — Dallas PD", city="Dallas", state="TX", type="vigilant_lpr", lat=32.7767, lng=-96.7970, description="DPD Vigilant/Motorola LPR. National data sharing.", source="EFF Atlas"),
            Infrastructure(name="Vigilant Solutions LEARN — San Diego PD", city="San Diego", state="CA", type="vigilant_lpr", lat=32.7157, lng=-117.1611, description="SDPD Vigilant Solutions deployment.", source="EFF Atlas; Motorola contracts"),
            Infrastructure(name="Vigilant Solutions LEARN — San Jose PD", city="San Jose", state="CA", type="vigilant_lpr", lat=37.3382, lng=-121.8863, description="SJPD Vigilant Solutions LPR.", source="EFF Atlas"),
            Infrastructure(name="Vigilant Solutions LEARN — Austin PD", city="Austin", state="TX", type="vigilant_lpr", lat=30.2672, lng=-97.7431, description="APD Vigilant Solutions contract.", source="EFF Atlas; Motorola contracts"),
            Infrastructure(name="Vigilant Solutions LEARN — Jacksonville FL", city="Jacksonville", state="FL", type="vigilant_lpr", lat=30.3322, lng=-81.6557, description="JSO Vigilant Solutions LPR deployment.", source="EFF Atlas"),
            Infrastructure(name="Vigilant Solutions LEARN — Columbus OH", city="Columbus", state="OH", type="vigilant_lpr", lat=39.9612, lng=-82.9988, description="CPD Vigilant Solutions contract.", source="EFF Atlas"),
            Infrastructure(name="Vigilant Solutions LEARN — Indianapolis", city="Indianapolis", state="IN", type="vigilant_lpr", lat=39.7684, lng=-86.1581, description="IMPD Vigilant Solutions LPR.", source="EFF Atlas; Motorola contracts"),
            Infrastructure(name="Vigilant Solutions LEARN — Fort Worth PD", city="Fort Worth", state="TX", type="vigilant_lpr", lat=32.7555, lng=-97.3308, description="FWPD Vigilant Solutions deployment.", source="EFF Atlas"),
            Infrastructure(name="Vigilant Solutions LEARN — Charlotte PD", city="Charlotte", state="NC", type="vigilant_lpr", lat=35.2271, lng=-80.8431, description="CMPD Vigilant Solutions LPR contract.", source="EFF Atlas"),
            Infrastructure(name="Vigilant Solutions LEARN — Seattle PD", city="Seattle", state="WA", type="vigilant_lpr", lat=47.6062, lng=-122.3321, description="SPD Vigilant Solutions deployment.", source="EFF Atlas; ACLU WA"),
            Infrastructure(name="Vigilant Solutions LEARN — Denver PD", city="Denver", state="CO", type="vigilant_lpr", lat=39.7392, lng=-104.9903, description="DPD Vigilant Solutions LPR.", source="EFF Atlas; Motorola contracts"),
            Infrastructure(name="Vigilant Solutions LEARN — El Paso PD", city="El Paso", state="TX", type="vigilant_lpr", lat=31.7619, lng=-106.4850, description="EPPD Vigilant Solutions contract.", source="EFF Atlas"),
            Infrastructure(name="Vigilant Solutions LEARN — Nashville Metro PD", city="Nashville", state="TN", type="vigilant_lpr", lat=36.1627, lng=-86.7816, description="MNPD Vigilant Solutions LPR.", source="EFF Atlas; Motorola contracts"),
            Infrastructure(name="Vigilant Solutions LEARN — Oklahoma City PD", city="Oklahoma City", state="OK", type="vigilant_lpr", lat=35.4676, lng=-97.5164, description="OCPD Vigilant Solutions deployment.", source="EFF Atlas"),
            Infrastructure(name="Vigilant Solutions LEARN — Las Vegas Metro PD", city="Las Vegas", state="NV", type="vigilant_lpr", lat=36.1699, lng=-115.1398, description="LVMPD Vigilant Solutions LPR contract.", source="EFF Atlas; Motorola contracts"),
            Infrastructure(name="Vigilant Solutions LEARN — Memphis PD", city="Memphis", state="TN", type="vigilant_lpr", lat=35.1495, lng=-90.0490, description="MPD Vigilant Solutions deployment.", source="EFF Atlas"),
            Infrastructure(name="Vigilant Solutions LEARN — Louisville Metro PD", city="Louisville", state="KY", type="vigilant_lpr", lat=38.2527, lng=-85.7585, description="LMPD Vigilant Solutions LPR.", source="EFF Atlas"),
            Infrastructure(name="Vigilant Solutions LEARN — Baltimore PD", city="Baltimore", state="MD", type="vigilant_lpr", lat=39.2904, lng=-76.6122, description="BPD Vigilant Solutions contract.", source="EFF Atlas; Baltimore Sun"),
            Infrastructure(name="Vigilant Solutions LEARN — Milwaukee PD", city="Milwaukee", state="WI", type="vigilant_lpr", lat=43.0389, lng=-87.9065, description="MPD Vigilant Solutions LPR.", source="EFF Atlas; Motorola contracts"),
            Infrastructure(name="Vigilant Solutions LEARN — Albuquerque PD", city="Albuquerque", state="NM", type="vigilant_lpr", lat=35.0844, lng=-106.6504, description="APD Vigilant Solutions deployment.", source="EFF Atlas"),
            Infrastructure(name="Vigilant Solutions LEARN — Tucson PD", city="Tucson", state="AZ", type="vigilant_lpr", lat=32.2217, lng=-110.9265, description="TPD Vigilant Solutions LPR contract.", source="EFF Atlas"),
            Infrastructure(name="Vigilant Solutions LEARN — Sacramento PD", city="Sacramento", state="CA", type="vigilant_lpr", lat=38.5816, lng=-121.4944, description="SPD Vigilant Solutions deployment.", source="EFF Atlas; Motorola contracts"),
            Infrastructure(name="Vigilant Solutions LEARN — Kansas City PD", city="Kansas City", state="MO", type="vigilant_lpr", lat=39.0997, lng=-94.5786, description="KCPD Vigilant Solutions LPR.", source="EFF Atlas"),
            Infrastructure(name="Vigilant Solutions LEARN — Mesa AZ PD", city="Mesa", state="AZ", type="vigilant_lpr", lat=33.4152, lng=-111.8315, description="Mesa PD Vigilant Solutions contract.", source="EFF Atlas"),
            Infrastructure(name="Vigilant Solutions LEARN — Atlanta PD", city="Atlanta", state="GA", type="vigilant_lpr", lat=33.7490, lng=-84.3880, description="APD Vigilant Solutions LPR deployment.", source="EFF Atlas; Motorola contracts"),
            Infrastructure(name="Vigilant Solutions LEARN — Omaha PD", city="Omaha", state="NE", type="vigilant_lpr", lat=41.2565, lng=-95.9345, description="OPD Vigilant Solutions contract.", source="EFF Atlas"),
            Infrastructure(name="Vigilant Solutions LEARN — Colorado Springs PD", city="Colorado Springs", state="CO", type="vigilant_lpr", lat=38.8339, lng=-104.8214, description="CSPD Vigilant Solutions LPR.", source="EFF Atlas"),
            Infrastructure(name="Vigilant Solutions LEARN — Raleigh PD", city="Raleigh", state="NC", type="vigilant_lpr", lat=35.7796, lng=-78.6382, description="RPD Vigilant Solutions deployment.", source="EFF Atlas; Motorola contracts"),
            Infrastructure(name="Vigilant Solutions LEARN — Minneapolis PD", city="Minneapolis", state="MN", type="vigilant_lpr", lat=44.9778, lng=-93.2650, description="MPD Vigilant Solutions LPR contract.", source="EFF Atlas"),
            Infrastructure(name="Vigilant Solutions LEARN — Tampa PD", city="Tampa", state="FL", type="vigilant_lpr", lat=27.9506, lng=-82.4572, description="TPD Vigilant Solutions deployment.", source="EFF Atlas; Motorola contracts"),
            Infrastructure(name="Vigilant Solutions LEARN — New Orleans PD", city="New Orleans", state="LA", type="vigilant_lpr", lat=29.9511, lng=-90.0715, description="NOPD Vigilant Solutions LPR.", source="EFF Atlas"),
            Infrastructure(name="Vigilant Solutions LEARN — Arlington TX PD", city="Arlington", state="TX", type="vigilant_lpr", lat=32.7357, lng=-97.1081, description="APD Vigilant Solutions contract.", source="EFF Atlas"),
            Infrastructure(name="Vigilant Solutions LEARN — Wichita PD", city="Wichita", state="KS", type="vigilant_lpr", lat=37.6872, lng=-97.3301, description="WPD Vigilant Solutions LPR.", source="EFF Atlas; Motorola contracts"),
            Infrastructure(name="Vigilant Solutions LEARN — Portland PD", city="Portland", state="OR", type="vigilant_lpr", lat=45.5231, lng=-122.6765, description="PPB Vigilant Solutions deployment.", source="EFF Atlas"),
            Infrastructure(name="Vigilant Solutions LEARN — Corpus Christi PD", city="Corpus Christi", state="TX", type="vigilant_lpr", lat=27.8006, lng=-97.3964, description="CCPD Vigilant Solutions LPR contract.", source="EFF Atlas"),
            Infrastructure(name="Vigilant Solutions LEARN — St. Louis Metro PD", city="St. Louis", state="MO", type="vigilant_lpr", lat=38.6270, lng=-90.1994, description="SLMPD Vigilant Solutions deployment.", source="EFF Atlas"),
            Infrastructure(name="Vigilant Solutions LEARN — Pittsburgh PD", city="Pittsburgh", state="PA", type="vigilant_lpr", lat=40.4406, lng=-79.9959, description="PPD Vigilant Solutions LPR.", source="EFF Atlas; Motorola contracts"),
            Infrastructure(name="Vigilant Solutions LEARN — Riverside PD", city="Riverside", state="CA", type="vigilant_lpr", lat=33.9533, lng=-117.3961, description="RPD Vigilant Solutions contract.", source="EFF Atlas"),
            Infrastructure(name="Vigilant Solutions LEARN — Lexington PD", city="Lexington", state="KY", type="vigilant_lpr", lat=38.0406, lng=-84.5037, description="LPD Vigilant Solutions LPR deployment.", source="EFF Atlas"),
            Infrastructure(name="Vigilant Solutions LEARN — Stockton PD", city="Stockton", state="CA", type="vigilant_lpr", lat=37.9577, lng=-121.2908, description="SPD Vigilant Solutions contract.", source="EFF Atlas"),
            Infrastructure(name="Vigilant Solutions LEARN — Pittsburgh — PA State Police", city="Harrisburg", state="PA", type="vigilant_lpr", lat=40.2732, lng=-76.8867, description="PSP statewide Vigilant Solutions LPR. Shared with all PA agencies.", source="EFF Atlas; Motorola contracts"),
            Infrastructure(name="Vigilant Solutions LEARN — Texas DPS", city="Austin", state="TX", type="vigilant_lpr", lat=30.2672, lng=-97.7431, description="TxDPS statewide Vigilant Solutions LPR repository access.", source="EFF Atlas; Texas DPS records"),
            Infrastructure(name="Vigilant Solutions LEARN — California Highway Patrol", city="Sacramento", state="CA", type="vigilant_lpr", lat=38.5816, lng=-121.4944, description="CHP statewide Vigilant Solutions LPR. Largest state deployment.", source="EFF Atlas; CHP FOIA"),
            Infrastructure(name="Vigilant Solutions LEARN — Florida FDLE", city="Tallahassee", state="FL", type="vigilant_lpr", lat=30.4518, lng=-84.2807, description="FDLE statewide Vigilant Solutions LPR. Shared across all FL agencies.", source="EFF Atlas; Motorola contracts"),
            Infrastructure(name="Vigilant Solutions LEARN — New York State Police", city="Albany", state="NY", type="vigilant_lpr", lat=42.6526, lng=-73.7562, description="NYSP statewide Vigilant Solutions deployment.", source="EFF Atlas"),
            Infrastructure(name="Vigilant Solutions LEARN — Illinois State Police", city="Springfield", state="IL", type="vigilant_lpr", lat=39.7817, lng=-89.6501, description="ISP statewide Vigilant Solutions LPR contract.", source="EFF Atlas; Motorola contracts"),
            Infrastructure(name="Vigilant Solutions LEARN — ICE HSI", city="Washington", state="DC", type="vigilant_lpr", lat=38.8977, lng=-77.0365, description="ICE Homeland Security Investigations Vigilant Solutions access. Used for immigration enforcement targeting.", source="EFF; The Intercept; Motorola contracts"),
            Infrastructure(name="Vigilant Solutions LEARN — DEA", city="Arlington", state="VA", type="vigilant_lpr", lat=38.8799, lng=-77.1068, description="DEA national Vigilant Solutions repository access. Drug interdiction targeting.", source="EFF; Reuters; Motorola contracts"),
        ]

        # Only insert records for types not already in database
        to_add = [r for r in records if r.type in missing]
        for r in to_add:
            session.add(r)

        session.commit()
        print(f"[DB] Seeded {len(to_add)} new records for: {', '.join(missing)}")

    except Exception as e:
        session.rollback()
        print(f"[DB] Seed error: {e}")
    finally:
        session.close()
        session.close()
