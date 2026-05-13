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
            'dhs_cisa', 'federal_building', 'joint_ops',
            'port_surveillance', 'school_surveillance',
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

            # ══════════════════════════════════════════════════════════════
            # NEIGHBORHOOD / PRECINCT LEVEL — CHICAGO
            # Source: CPD records, Chicago city data portal, EFF Atlas,
            # MacArthur Justice Center, Chicago Tribune FOIA
            # ══════════════════════════════════════════════════════════════

            # Chicago ShotSpotter — by neighborhood
            Infrastructure(name="ShotSpotter — Chicago Englewood", city="Chicago", state="IL", type="shotspotter", lat=41.7790, lng=-87.6470, description="ShotSpotter coverage in Englewood neighborhood. One of highest density deployments in city.", source="MacArthur Justice Center; CPD records"),
            Infrastructure(name="ShotSpotter — Chicago Austin", city="Chicago", state="IL", type="shotspotter", lat=41.8950, lng=-87.7640, description="ShotSpotter in Austin neighborhood, West Side Chicago.", source="MacArthur Justice Center; CPD records"),
            Infrastructure(name="ShotSpotter — Chicago Garfield Park", city="Chicago", state="IL", type="shotspotter", lat=41.8800, lng=-87.7230, description="ShotSpotter coverage in East and West Garfield Park.", source="MacArthur Justice Center; CPD records"),
            Infrastructure(name="ShotSpotter — Chicago Humboldt Park", city="Chicago", state="IL", type="shotspotter", lat=41.9000, lng=-87.7200, description="ShotSpotter in Humboldt Park neighborhood.", source="MacArthur Justice Center; CPD records"),
            Infrastructure(name="ShotSpotter — Chicago North Lawndale", city="Chicago", state="IL", type="shotspotter", lat=41.8620, lng=-87.7190, description="ShotSpotter coverage in North Lawndale.", source="MacArthur Justice Center; CPD records"),
            Infrastructure(name="ShotSpotter — Chicago Roseland", city="Chicago", state="IL", type="shotspotter", lat=41.6900, lng=-87.6280, description="ShotSpotter in Roseland neighborhood, Far South Side.", source="MacArthur Justice Center; CPD records"),
            Infrastructure(name="ShotSpotter — Chicago Woodlawn", city="Chicago", state="IL", type="shotspotter", lat=41.7730, lng=-87.5990, description="ShotSpotter coverage in Woodlawn.", source="MacArthur Justice Center; CPD records"),
            Infrastructure(name="ShotSpotter — Chicago Auburn Gresham", city="Chicago", state="IL", type="shotspotter", lat=41.7440, lng=-87.6560, description="ShotSpotter in Auburn Gresham neighborhood.", source="MacArthur Justice Center; CPD records"),
            Infrastructure(name="ShotSpotter — Chicago South Shore", city="Chicago", state="IL", type="shotspotter", lat=41.7610, lng=-87.5780, description="ShotSpotter coverage in South Shore.", source="MacArthur Justice Center; CPD records"),
            Infrastructure(name="ShotSpotter — Chicago Pullman", city="Chicago", state="IL", type="shotspotter", lat=41.7060, lng=-87.6080, description="ShotSpotter in Pullman neighborhood.", source="MacArthur Justice Center; CPD records"),
            Infrastructure(name="ShotSpotter — Chicago West Pullman", city="Chicago", state="IL", type="shotspotter", lat=41.6890, lng=-87.6450, description="ShotSpotter coverage in West Pullman.", source="MacArthur Justice Center; CPD records"),
            Infrastructure(name="ShotSpotter — Chicago Morgan Park", city="Chicago", state="IL", type="shotspotter", lat=41.7000, lng=-87.6680, description="ShotSpotter in Morgan Park neighborhood.", source="MacArthur Justice Center; CPD records"),

            # Chicago POD Cameras — by ward/district
            Infrastructure(name="Chicago POD Cameras — District 1 (Central)", city="Chicago", state="IL", type="surveillance_camera", lat=41.8756, lng=-87.6244, description="CPD District 1 POD camera network. Loop and Grant Park coverage.", source="Chicago city data portal; EFF Atlas"),
            Infrastructure(name="Chicago POD Cameras — District 2 (Wentworth)", city="Chicago", state="IL", type="surveillance_camera", lat=41.8340, lng=-87.6320, description="CPD District 2 POD cameras. South Loop and Chinatown area.", source="Chicago city data portal"),
            Infrastructure(name="Chicago POD Cameras — District 3 (Grand Crossing)", city="Chicago", state="IL", type="surveillance_camera", lat=41.7590, lng=-87.6020, description="CPD District 3 POD camera network. Grand Crossing coverage.", source="Chicago city data portal"),
            Infrastructure(name="Chicago POD Cameras — District 4 (South Chicago)", city="Chicago", state="IL", type="surveillance_camera", lat=41.7420, lng=-87.5680, description="CPD District 4 POD cameras. South Chicago neighborhood.", source="Chicago city data portal"),
            Infrastructure(name="Chicago POD Cameras — District 5 (Calumet)", city="Chicago", state="IL", type="surveillance_camera", lat=41.7120, lng=-87.5980, description="CPD District 5 POD network. Far South Side.", source="Chicago city data portal"),
            Infrastructure(name="Chicago POD Cameras — District 6 (Gresham)", city="Chicago", state="IL", type="surveillance_camera", lat=41.7480, lng=-87.6570, description="CPD District 6 POD cameras. Gresham area.", source="Chicago city data portal"),
            Infrastructure(name="Chicago POD Cameras — District 7 (Englewood)", city="Chicago", state="IL", type="surveillance_camera", lat=41.7790, lng=-87.6470, description="CPD District 7 POD network. Englewood — highest camera density on South Side.", source="Chicago city data portal; EFF Atlas"),
            Infrastructure(name="Chicago POD Cameras — District 8 (Chicago Lawn)", city="Chicago", state="IL", type="surveillance_camera", lat=41.7720, lng=-87.6940, description="CPD District 8 POD cameras. Chicago Lawn area.", source="Chicago city data portal"),
            Infrastructure(name="Chicago POD Cameras — District 9 (Deering)", city="Chicago", state="IL", type="surveillance_camera", lat=41.8130, lng=-87.6580, description="CPD District 9 POD network. Bridgeport and Canaryville.", source="Chicago city data portal"),
            Infrastructure(name="Chicago POD Cameras — District 10 (Ogden)", city="Chicago", state="IL", type="surveillance_camera", lat=41.8600, lng=-87.7100, description="CPD District 10 POD cameras. Lawndale area.", source="Chicago city data portal"),
            Infrastructure(name="Chicago POD Cameras — District 11 (Harrison)", city="Chicago", state="IL", type="surveillance_camera", lat=41.8730, lng=-87.7350, description="CPD District 11 POD network. West Garfield Park — densest West Side coverage.", source="Chicago city data portal; EFF Atlas"),
            Infrastructure(name="Chicago POD Cameras — District 12 (Monroe)", city="Chicago", state="IL", type="surveillance_camera", lat=41.8780, lng=-87.6690, description="CPD District 12 POD cameras. Near West Side.", source="Chicago city data portal"),
            Infrastructure(name="Chicago POD Cameras — District 14 (Shakespeare)", city="Chicago", state="IL", type="surveillance_camera", lat=41.9180, lng=-87.6980, description="CPD District 14 POD network. Wicker Park area.", source="Chicago city data portal"),
            Infrastructure(name="Chicago POD Cameras — District 15 (Austin)", city="Chicago", state="IL", type="surveillance_camera", lat=41.8950, lng=-87.7640, description="CPD District 15 POD cameras. Austin neighborhood.", source="Chicago city data portal"),
            Infrastructure(name="Chicago POD Cameras — District 16 (Jefferson Park)", city="Chicago", state="IL", type="surveillance_camera", lat=41.9710, lng=-87.7680, description="CPD District 16 POD network. Northwest side.", source="Chicago city data portal"),
            Infrastructure(name="Chicago POD Cameras — District 17 (Albany Park)", city="Chicago", state="IL", type="surveillance_camera", lat=41.9690, lng=-87.7230, description="CPD District 17 POD cameras. Albany Park area.", source="Chicago city data portal"),
            Infrastructure(name="Chicago POD Cameras — District 18 (Near North)", city="Chicago", state="IL", type="surveillance_camera", lat=41.9060, lng=-87.6360, description="CPD District 18 POD network. Gold Coast and River North.", source="Chicago city data portal"),
            Infrastructure(name="Chicago POD Cameras — District 19 (Town Hall)", city="Chicago", state="IL", type="surveillance_camera", lat=41.9440, lng=-87.6550, description="CPD District 19 POD cameras. Lakeview area.", source="Chicago city data portal"),
            Infrastructure(name="Chicago POD Cameras — District 20 (Lincoln)", city="Chicago", state="IL", type="surveillance_camera", lat=41.9760, lng=-87.6800, description="CPD District 20 POD network. Lincoln Square area.", source="Chicago city data portal"),
            Infrastructure(name="Chicago POD Cameras — District 22 (Morgan Park)", city="Chicago", state="IL", type="surveillance_camera", lat=41.7000, lng=-87.6680, description="CPD District 22 POD cameras. Morgan Park and Beverly.", source="Chicago city data portal"),
            Infrastructure(name="Chicago POD Cameras — District 24 (Rogers Park)", city="Chicago", state="IL", type="surveillance_camera", lat=42.0060, lng=-87.6700, description="CPD District 24 POD network. Rogers Park — northernmost district.", source="Chicago city data portal"),
            Infrastructure(name="Chicago POD Cameras — District 25 (Grand Central)", city="Chicago", state="IL", type="surveillance_camera", lat=41.8490, lng=-87.7100, description="CPD District 25 POD cameras. Little Village area.", source="Chicago city data portal"),

            # ══════════════════════════════════════════════════════════════
            # NEIGHBORHOOD / PRECINCT LEVEL — NEW YORK CITY
            # Source: NYPD records, NYCLU, domain awareness documentation
            # ══════════════════════════════════════════════════════════════

            # NYPD Precincts — camera and surveillance nodes
            Infrastructure(name="NYPD 40th Precinct — South Bronx Surveillance", city="New York", state="NY", type="surveillance_camera", lat=40.8120, lng=-73.9270, description="40th Precinct surveillance cameras. South Bronx. Highest crime designation area.", source="NYPD; NYCLU"),
            Infrastructure(name="NYPD 41st Precinct — Longwood Bronx Surveillance", city="New York", state="NY", type="surveillance_camera", lat=40.8210, lng=-73.9000, description="41st Precinct camera network. Longwood neighborhood Bronx.", source="NYPD; NYCLU"),
            Infrastructure(name="NYPD 42nd Precinct — Morrisania Surveillance", city="New York", state="NY", type="surveillance_camera", lat=40.8330, lng=-73.9140, description="42nd Precinct surveillance. Morrisania, Bronx.", source="NYPD; NYCLU"),
            Infrastructure(name="NYPD 44th Precinct — Concourse Bronx Surveillance", city="New York", state="NY", type="surveillance_camera", lat=40.8460, lng=-73.9230, description="44th Precinct cameras. Grand Concourse area, Bronx.", source="NYPD; NYCLU"),
            Infrastructure(name="NYPD 46th Precinct — Morris Heights Surveillance", city="New York", state="NY", type="surveillance_camera", lat=40.8530, lng=-73.9190, description="46th Precinct camera network. Morris Heights, Bronx.", source="NYPD; NYCLU"),
            Infrastructure(name="NYPD 48th Precinct — Belmont Bronx Surveillance", city="New York", state="NY", type="surveillance_camera", lat=40.8590, lng=-73.8890, description="48th Precinct surveillance. Belmont neighborhood, Bronx.", source="NYPD; NYCLU"),
            Infrastructure(name="NYPD 52nd Precinct — Fordham Bronx Surveillance", city="New York", state="NY", type="surveillance_camera", lat=40.8680, lng=-73.8990, description="52nd Precinct cameras. Fordham Road area, Bronx.", source="NYPD; NYCLU"),
            Infrastructure(name="NYPD 67th Precinct — Flatbush Brooklyn Surveillance", city="New York", state="NY", type="surveillance_camera", lat=40.6380, lng=-73.9440, description="67th Precinct camera network. Flatbush, Brooklyn.", source="NYPD; NYCLU"),
            Infrastructure(name="NYPD 70th Precinct — Flatbush South Surveillance", city="New York", state="NY", type="surveillance_camera", lat=40.6280, lng=-73.9620, description="70th Precinct surveillance. South Flatbush.", source="NYPD; NYCLU"),
            Infrastructure(name="NYPD 71st Precinct — Crown Heights Surveillance", city="New York", state="NY", type="surveillance_camera", lat=40.6620, lng=-73.9450, description="71st Precinct cameras. Crown Heights, Brooklyn.", source="NYPD; NYCLU"),
            Infrastructure(name="NYPD 73rd Precinct — Brownsville Surveillance", city="New York", state="NY", type="surveillance_camera", lat=40.6620, lng=-73.9110, description="73rd Precinct camera network. Brownsville — densest coverage in Brooklyn.", source="NYPD; NYCLU"),
            Infrastructure(name="NYPD 75th Precinct — East New York Surveillance", city="New York", state="NY", type="surveillance_camera", lat=40.6630, lng=-73.8820, description="75th Precinct surveillance. East New York, Brooklyn.", source="NYPD; NYCLU"),
            Infrastructure(name="NYPD 77th Precinct — Crown Heights North Surveillance", city="New York", state="NY", type="surveillance_camera", lat=40.6720, lng=-73.9440, description="77th Precinct cameras. Crown Heights North.", source="NYPD; NYCLU"),
            Infrastructure(name="NYPD 79th Precinct — Bedford-Stuyvesant Surveillance", city="New York", state="NY", type="surveillance_camera", lat=40.6870, lng=-73.9440, description="79th Precinct camera network. Bed-Stuy, Brooklyn.", source="NYPD; NYCLU"),
            Infrastructure(name="NYPD 81st Precinct — Bushwick Surveillance", city="New York", state="NY", type="surveillance_camera", lat=40.6940, lng=-73.9200, description="81st Precinct surveillance. Bushwick, Brooklyn.", source="NYPD; NYCLU"),
            Infrastructure(name="NYPD 83rd Precinct — Bushwick North Surveillance", city="New York", state="NY", type="surveillance_camera", lat=40.7020, lng=-73.9260, description="83rd Precinct cameras. North Bushwick.", source="NYPD; NYCLU"),
            Infrastructure(name="NYPD 103rd Precinct — Jamaica Queens Surveillance", city="New York", state="NY", type="surveillance_camera", lat=40.7000, lng=-73.7920, description="103rd Precinct camera network. Jamaica, Queens.", source="NYPD; NYCLU"),
            Infrastructure(name="NYPD 105th Precinct — Queens Village Surveillance", city="New York", state="NY", type="surveillance_camera", lat=40.7210, lng=-73.7460, description="105th Precinct surveillance. Queens Village.", source="NYPD; NYCLU"),
            Infrastructure(name="NYPD 113th Precinct — St. Albans Queens Surveillance", city="New York", state="NY", type="surveillance_camera", lat=40.6820, lng=-73.7710, description="113th Precinct cameras. St. Albans, Queens.", source="NYPD; NYCLU"),

            # NYC ShotSpotter nodes
            Infrastructure(name="ShotSpotter — NYC East New York Brooklyn", city="New York", state="NY", type="shotspotter", lat=40.6630, lng=-73.8820, description="ShotSpotter sensor coverage in East New York, Brooklyn.", source="NYPD records; NYCLU"),
            Infrastructure(name="ShotSpotter — NYC Brownsville Brooklyn", city="New York", state="NY", type="shotspotter", lat=40.6620, lng=-73.9110, description="ShotSpotter in Brownsville neighborhood.", source="NYPD records; NYCLU"),
            Infrastructure(name="ShotSpotter — NYC South Bronx", city="New York", state="NY", type="shotspotter", lat=40.8120, lng=-73.9270, description="ShotSpotter acoustic sensors in South Bronx.", source="NYPD records; NYCLU"),
            Infrastructure(name="ShotSpotter — NYC Morrisania Bronx", city="New York", state="NY", type="shotspotter", lat=40.8330, lng=-73.9140, description="ShotSpotter in Morrisania, Bronx.", source="NYPD records; NYCLU"),
            Infrastructure(name="ShotSpotter — NYC Jamaica Queens", city="New York", state="NY", type="shotspotter", lat=40.7000, lng=-73.7920, description="ShotSpotter coverage in Jamaica, Queens.", source="NYPD records; NYCLU"),
            Infrastructure(name="ShotSpotter — NYC Harlem Manhattan", city="New York", state="NY", type="shotspotter", lat=40.8116, lng=-73.9465, description="ShotSpotter acoustic sensors in Harlem.", source="NYPD records; NYCLU"),
            Infrastructure(name="ShotSpotter — NYC Bedford-Stuyvesant Brooklyn", city="New York", state="NY", type="shotspotter", lat=40.6870, lng=-73.9440, description="ShotSpotter in Bed-Stuy, Brooklyn.", source="NYPD records; NYCLU"),
            Infrastructure(name="ShotSpotter — NYC Crown Heights Brooklyn", city="New York", state="NY", type="shotspotter", lat=40.6660, lng=-73.9450, description="ShotSpotter coverage in Crown Heights.", source="NYPD records; NYCLU"),

            # ══════════════════════════════════════════════════════════════
            # NEIGHBORHOOD / PRECINCT LEVEL — LOS ANGELES
            # Source: LAPD records, EFF Atlas, ACLU SoCal
            # ══════════════════════════════════════════════════════════════

            Infrastructure(name="LAPD 77th Street Division Surveillance", city="Los Angeles", state="CA", type="surveillance_camera", lat=33.9970, lng=-118.2970, description="LAPD 77th Street Division cameras and ShotSpotter. South Central LA.", source="LAPD records; EFF Atlas"),
            Infrastructure(name="LAPD Southwest Division Surveillance", city="Los Angeles", state="CA", type="surveillance_camera", lat=34.0140, lng=-118.3140, description="LAPD Southwest Division camera network. Crenshaw corridor.", source="LAPD records; EFF Atlas"),
            Infrastructure(name="LAPD Southeast Division Surveillance", city="Los Angeles", state="CA", type="surveillance_camera", lat=33.9730, lng=-118.2480, description="LAPD Southeast Division surveillance. Watts and Compton adjacent.", source="LAPD records; EFF Atlas"),
            Infrastructure(name="LAPD Newton Division Surveillance", city="Los Angeles", state="CA", type="surveillance_camera", lat=34.0130, lng=-118.2540, description="LAPD Newton Division cameras. Historic South Central.", source="LAPD records; EFF Atlas"),
            Infrastructure(name="LAPD Harbor Division Surveillance", city="Los Angeles", state="CA", type="surveillance_camera", lat=33.7810, lng=-118.2920, description="LAPD Harbor Division camera network. San Pedro and Watts.", source="LAPD records; EFF Atlas"),
            Infrastructure(name="LAPD Hollenbeck Division Surveillance", city="Los Angeles", state="CA", type="surveillance_camera", lat=34.0540, lng=-118.2010, description="LAPD Hollenbeck Division cameras. East LA and Boyle Heights.", source="LAPD records; EFF Atlas"),
            Infrastructure(name="LAPD Rampart Division Surveillance", city="Los Angeles", state="CA", type="surveillance_camera", lat=34.0740, lng=-118.2780, description="LAPD Rampart Division camera network. Westlake and Koreatown.", source="LAPD records; EFF Atlas"),
            Infrastructure(name="LAPD Mission Division Surveillance", city="Los Angeles", state="CA", type="surveillance_camera", lat=34.2720, lng=-118.4340, description="LAPD Mission Division cameras. Pacoima and San Fernando Valley.", source="LAPD records; EFF Atlas"),
            Infrastructure(name="ShotSpotter — LA Watts", city="Los Angeles", state="CA", type="shotspotter", lat=33.9440, lng=-118.2380, description="ShotSpotter in Watts neighborhood. Dense acoustic sensor coverage.", source="LAPD records; EFF Atlas"),
            Infrastructure(name="ShotSpotter — LA Compton", city="Compton", state="CA", type="shotspotter", lat=33.8958, lng=-118.2201, description="ShotSpotter coverage in Compton.", source="LASD records; EFF Atlas"),
            Infrastructure(name="ShotSpotter — LA South Central", city="Los Angeles", state="CA", type="shotspotter", lat=33.9997, lng=-118.2730, description="ShotSpotter in South Central LA.", source="LAPD records; EFF Atlas"),
            Infrastructure(name="ShotSpotter — LA Inglewood", city="Inglewood", state="CA", type="shotspotter", lat=33.9617, lng=-118.3531, description="ShotSpotter in Inglewood.", source="IPD records; EFF Atlas"),
            Infrastructure(name="ShotSpotter — LA East Los Angeles", city="Los Angeles", state="CA", type="shotspotter", lat=34.0239, lng=-118.1717, description="ShotSpotter coverage in East LA.", source="LASD records; EFF Atlas"),

            # ══════════════════════════════════════════════════════════════
            # NEIGHBORHOOD / PRECINCT LEVEL — HOUSTON
            # Source: HPD records, EFF Atlas
            # ══════════════════════════════════════════════════════════════

            Infrastructure(name="HPD Central Division Surveillance", city="Houston", state="TX", type="surveillance_camera", lat=29.7604, lng=-95.3698, description="HPD Central Division camera network. Downtown Houston.", source="HPD records; EFF Atlas"),
            Infrastructure(name="HPD Northeast Division Surveillance", city="Houston", state="TX", type="surveillance_camera", lat=29.8150, lng=-95.3120, description="HPD Northeast Division cameras.", source="HPD records; EFF Atlas"),
            Infrastructure(name="HPD North Division Surveillance", city="Houston", state="TX", type="surveillance_camera", lat=29.8450, lng=-95.3980, description="HPD North Division camera network.", source="HPD records; EFF Atlas"),
            Infrastructure(name="HPD Northwest Division Surveillance", city="Houston", state="TX", type="surveillance_camera", lat=29.8320, lng=-95.5140, description="HPD Northwest Division cameras.", source="HPD records; EFF Atlas"),
            Infrastructure(name="HPD West Division Surveillance", city="Houston", state="TX", type="surveillance_camera", lat=29.7500, lng=-95.5100, description="HPD West Division camera network.", source="HPD records; EFF Atlas"),
            Infrastructure(name="HPD Southwest Division Surveillance", city="Houston", state="TX", type="surveillance_camera", lat=29.6900, lng=-95.5000, description="HPD Southwest Division cameras.", source="HPD records; EFF Atlas"),
            Infrastructure(name="HPD South Division Surveillance", city="Houston", state="TX", type="surveillance_camera", lat=29.6730, lng=-95.3890, description="HPD South Division camera network.", source="HPD records; EFF Atlas"),
            Infrastructure(name="HPD Southeast Division Surveillance", city="Houston", state="TX", type="surveillance_camera", lat=29.7010, lng=-95.2940, description="HPD Southeast Division cameras.", source="HPD records; EFF Atlas"),
            Infrastructure(name="HPD Midwest Division Surveillance", city="Houston", state="TX", type="surveillance_camera", lat=29.7800, lng=-95.4500, description="HPD Midwest Division camera network.", source="HPD records; EFF Atlas"),
            Infrastructure(name="ShotSpotter — Houston Third Ward", city="Houston", state="TX", type="shotspotter", lat=29.7370, lng=-95.3570, description="ShotSpotter in Third Ward, Houston.", source="HPD records; EFF Atlas"),
            Infrastructure(name="ShotSpotter — Houston Fifth Ward", city="Houston", state="TX", type="shotspotter", lat=29.7760, lng=-95.3390, description="ShotSpotter coverage in Fifth Ward.", source="HPD records; EFF Atlas"),
            Infrastructure(name="ShotSpotter — Houston Sunnyside", city="Houston", state="TX", type="shotspotter", lat=29.6710, lng=-95.3850, description="ShotSpotter in Sunnyside neighborhood.", source="HPD records; EFF Atlas"),
            Infrastructure(name="ShotSpotter — Houston Acres Homes", city="Houston", state="TX", type="shotspotter", lat=29.8650, lng=-95.4190, description="ShotSpotter coverage in Acres Homes.", source="HPD records; EFF Atlas"),

            # ══════════════════════════════════════════════════════════════
            # NEIGHBORHOOD / PRECINCT LEVEL — BALTIMORE
            # Source: BPD records, Baltimore Sun, EFF Atlas
            # ══════════════════════════════════════════════════════════════

            Infrastructure(name="BPD Eastern District Surveillance", city="Baltimore", state="MD", type="surveillance_camera", lat=39.2990, lng=-76.5810, description="BPD Eastern District CitiWatch cameras. East Baltimore.", source="BPD records; Baltimore Sun"),
            Infrastructure(name="BPD Western District Surveillance", city="Baltimore", state="MD", type="surveillance_camera", lat=39.2970, lng=-76.6490, description="BPD Western District cameras. West Baltimore.", source="BPD records; Baltimore Sun"),
            Infrastructure(name="BPD Southern District Surveillance", city="Baltimore", state="MD", type="surveillance_camera", lat=39.2690, lng=-76.6220, description="BPD Southern District CitiWatch network.", source="BPD records; Baltimore Sun"),
            Infrastructure(name="BPD Northern District Surveillance", city="Baltimore", state="MD", type="surveillance_camera", lat=39.3340, lng=-76.6380, description="BPD Northern District cameras.", source="BPD records; Baltimore Sun"),
            Infrastructure(name="BPD Northeastern District Surveillance", city="Baltimore", state="MD", type="surveillance_camera", lat=39.3350, lng=-76.5680, description="BPD Northeastern District camera network.", source="BPD records; Baltimore Sun"),
            Infrastructure(name="BPD Northwestern District Surveillance", city="Baltimore", state="MD", type="surveillance_camera", lat=39.3230, lng=-76.6750, description="BPD Northwestern District cameras.", source="BPD records; Baltimore Sun"),
            Infrastructure(name="BPD Southeastern District Surveillance", city="Baltimore", state="MD", type="surveillance_camera", lat=39.2800, lng=-76.5680, description="BPD Southeastern District CitiWatch.", source="BPD records; Baltimore Sun"),
            Infrastructure(name="ShotSpotter — Baltimore East Baltimore", city="Baltimore", state="MD", type="shotspotter", lat=39.2987, lng=-76.5746, description="ShotSpotter in East Baltimore neighborhoods.", source="BPD records; Baltimore Sun"),
            Infrastructure(name="ShotSpotter — Baltimore West Baltimore", city="Baltimore", state="MD", type="shotspotter", lat=39.2970, lng=-76.6490, description="ShotSpotter coverage in West Baltimore.", source="BPD records; Baltimore Sun"),
            Infrastructure(name="ShotSpotter — Baltimore Cherry Hill", city="Baltimore", state="MD", type="shotspotter", lat=39.2490, lng=-76.6210, description="ShotSpotter in Cherry Hill neighborhood.", source="BPD records; Baltimore Sun"),
            Infrastructure(name="PSS Aerial Surveillance — Baltimore Coverage Zone 1", city="Baltimore", state="MD", type="surveillance_camera", lat=39.3100, lng=-76.6200, description="Persistent Surveillance Systems aerial camera. Filmed entire Baltimore from plane. Zone 1 coverage.", source="Baltimore Sun investigative report; ACLU Maryland"),
            Infrastructure(name="PSS Aerial Surveillance — Baltimore Coverage Zone 2", city="Baltimore", state="MD", type="surveillance_camera", lat=39.2800, lng=-76.5900, description="PSS aerial surveillance Zone 2. East Baltimore coverage.", source="Baltimore Sun; ACLU Maryland"),

            # ══════════════════════════════════════════════════════════════
            # NEIGHBORHOOD LEVEL — DETROIT
            # Source: DPD records, MIT Media Lab, EFF Atlas
            # ══════════════════════════════════════════════════════════════

            Infrastructure(name="Detroit Project Green Light — East Side Node", city="Detroit", state="MI", type="surveillance_camera", lat=42.3522, lng=-82.9918, description="Project Green Light real-time facial recognition camera. East Detroit businesses. DataWorks Plus.", source="EFF Atlas; MIT Media Lab"),
            Infrastructure(name="Detroit Project Green Light — West Side Node", city="Detroit", state="MI", type="surveillance_camera", lat=42.3314, lng=-83.1024, description="Project Green Light cameras. West Detroit. Highest false positive rate nationally.", source="EFF Atlas; MIT Media Lab"),
            Infrastructure(name="Detroit Project Green Light — Northwest Node", city="Detroit", state="MI", type="surveillance_camera", lat=42.3890, lng=-83.1100, description="Project Green Light. Northwest Detroit coverage.", source="EFF Atlas; DPD records"),
            Infrastructure(name="Detroit Project Green Light — Northeast Node", city="Detroit", state="MI", type="surveillance_camera", lat=42.3950, lng=-83.0200, description="Project Green Light. Northeast Detroit.", source="EFF Atlas; DPD records"),
            Infrastructure(name="Detroit Project Green Light — Southwest Node", city="Detroit", state="MI", type="surveillance_camera", lat=42.3100, lng=-83.1200, description="Project Green Light cameras. Southwest Detroit.", source="EFF Atlas; DPD records"),
            Infrastructure(name="Detroit Project Green Light — Downtown Node", city="Detroit", state="MI", type="surveillance_camera", lat=42.3314, lng=-83.0458, description="Project Green Light. Downtown Detroit dense coverage.", source="EFF Atlas; DPD records"),
            Infrastructure(name="ShotSpotter — Detroit East Side", city="Detroit", state="MI", type="shotspotter", lat=42.3522, lng=-82.9918, description="ShotSpotter acoustic coverage. East Detroit.", source="DPD records; EFF Atlas"),
            Infrastructure(name="ShotSpotter — Detroit West Side", city="Detroit", state="MI", type="shotspotter", lat=42.3314, lng=-83.1024, description="ShotSpotter coverage. West Detroit.", source="DPD records; EFF Atlas"),
            Infrastructure(name="ShotSpotter — Detroit Northwest", city="Detroit", state="MI", type="shotspotter", lat=42.3890, lng=-83.1100, description="ShotSpotter in Northwest Detroit.", source="DPD records; EFF Atlas"),

            # ══════════════════════════════════════════════════════════════
            # SMALLER CITIES — DOCUMENTED PROGRAMS NOT YET SEEDED
            # Source: EFF Atlas of Surveillance
            # ══════════════════════════════════════════════════════════════

            Infrastructure(name="ShotSpotter — Compton CA", city="Compton", state="CA", type="shotspotter", lat=33.8958, lng=-118.2201, description="LASD ShotSpotter in Compton.", source="EFF Atlas"),
            Infrastructure(name="ShotSpotter — Salinas CA", city="Salinas", state="CA", type="shotspotter", lat=36.6777, lng=-121.6555, description="Salinas PD ShotSpotter. One of first CA deployments.", source="EFF Atlas"),
            Infrastructure(name="ShotSpotter — Richmond CA", city="Richmond", state="CA", type="shotspotter", lat=37.9358, lng=-122.3477, description="Richmond PD ShotSpotter coverage.", source="EFF Atlas"),
            Infrastructure(name="ShotSpotter — East Palo Alto CA", city="East Palo Alto", state="CA", type="shotspotter", lat=37.4688, lng=-122.1411, description="East Palo Alto PD ShotSpotter.", source="EFF Atlas"),
            Infrastructure(name="ShotSpotter — Vallejo CA", city="Vallejo", state="CA", type="shotspotter", lat=38.1041, lng=-122.2566, description="Vallejo PD ShotSpotter deployment.", source="EFF Atlas"),
            Infrastructure(name="ShotSpotter — Pomona CA", city="Pomona", state="CA", type="shotspotter", lat=34.0553, lng=-117.7500, description="Pomona PD ShotSpotter coverage.", source="EFF Atlas"),
            Infrastructure(name="ShotSpotter — San Bernardino CA", city="San Bernardino", state="CA", type="shotspotter", lat=34.1083, lng=-117.2898, description="SBPD ShotSpotter deployment.", source="EFF Atlas"),
            Infrastructure(name="ShotSpotter — Victorville CA", city="Victorville", state="CA", type="shotspotter", lat=34.5362, lng=-117.2928, description="Victorville PD ShotSpotter.", source="EFF Atlas"),
            Infrastructure(name="ShotSpotter — Antioch CA", city="Antioch", state="CA", type="shotspotter", lat=38.0049, lng=-121.8058, description="Antioch PD ShotSpotter coverage.", source="EFF Atlas"),
            Infrastructure(name="ShotSpotter — Hayward CA", city="Hayward", state="CA", type="shotspotter", lat=37.6688, lng=-122.0808, description="Hayward PD ShotSpotter.", source="EFF Atlas"),
            Infrastructure(name="ShotSpotter — Peoria IL", city="Peoria", state="IL", type="shotspotter", lat=40.6936, lng=-89.5890, description="Peoria PD ShotSpotter deployment.", source="EFF Atlas"),
            Infrastructure(name="ShotSpotter — East St. Louis IL", city="East St. Louis", state="IL", type="shotspotter", lat=38.6245, lng=-90.1540, description="East St. Louis PD ShotSpotter coverage.", source="EFF Atlas"),
            Infrastructure(name="ShotSpotter — Gary IN", city="Gary", state="IN", type="shotspotter", lat=41.5934, lng=-87.3465, description="Gary PD ShotSpotter deployment.", source="EFF Atlas"),
            Infrastructure(name="ShotSpotter — South Bend IN", city="South Bend", state="IN", type="shotspotter", lat=41.6764, lng=-86.2520, description="South Bend PD ShotSpotter.", source="EFF Atlas"),
            Infrastructure(name="ShotSpotter — Muncie IN", city="Muncie", state="IN", type="shotspotter", lat=40.1934, lng=-85.3864, description="Muncie PD ShotSpotter coverage.", source="EFF Atlas"),
            Infrastructure(name="ShotSpotter — Flint MI", city="Flint", state="MI", type="shotspotter", lat=43.0125, lng=-83.6875, description="Flint PD ShotSpotter deployment.", source="EFF Atlas"),
            Infrastructure(name="ShotSpotter — Saginaw MI", city="Saginaw", state="MI", type="shotspotter", lat=43.4195, lng=-83.9508, description="Saginaw PD ShotSpotter.", source="EFF Atlas"),
            Infrastructure(name="ShotSpotter — Pontiac MI", city="Pontiac", state="MI", type="shotspotter", lat=42.6389, lng=-83.2910, description="Pontiac PD ShotSpotter coverage.", source="EFF Atlas"),
            Infrastructure(name="ShotSpotter — Macon GA", city="Macon", state="GA", type="shotspotter", lat=32.8407, lng=-83.6324, description="Macon PD ShotSpotter deployment.", source="EFF Atlas"),
            Infrastructure(name="ShotSpotter — Columbus GA", city="Columbus", state="GA", type="shotspotter", lat=32.4610, lng=-84.9877, description="Columbus GA PD ShotSpotter.", source="EFF Atlas"),
            Infrastructure(name="ShotSpotter — Albany GA", city="Albany", state="GA", type="shotspotter", lat=31.5785, lng=-84.1557, description="Albany GA PD ShotSpotter coverage.", source="EFF Atlas"),
            Infrastructure(name="ShotSpotter — Wilmington NC", city="Wilmington", state="NC", type="shotspotter", lat=34.2257, lng=-77.9447, description="Wilmington NC PD ShotSpotter.", source="EFF Atlas"),
            Infrastructure(name="ShotSpotter — High Point NC", city="High Point", state="NC", type="shotspotter", lat=35.9557, lng=-80.0053, description="High Point PD ShotSpotter deployment.", source="EFF Atlas"),
            Infrastructure(name="ShotSpotter — Rocky Mount NC", city="Rocky Mount", state="NC", type="shotspotter", lat=35.9382, lng=-77.7905, description="Rocky Mount PD ShotSpotter.", source="EFF Atlas"),
            Infrastructure(name="ShotSpotter — Harrisburg PA", city="Harrisburg", state="PA", type="shotspotter", lat=40.2732, lng=-76.8867, description="Harrisburg PA PD ShotSpotter coverage.", source="EFF Atlas"),
            Infrastructure(name="ShotSpotter — Reading PA", city="Reading", state="PA", type="shotspotter", lat=40.3356, lng=-75.9269, description="Reading PD ShotSpotter deployment.", source="EFF Atlas"),
            Infrastructure(name="ShotSpotter — Chester PA", city="Chester", state="PA", type="shotspotter", lat=39.8493, lng=-75.3557, description="Chester PA PD ShotSpotter.", source="EFF Atlas"),
            Infrastructure(name="ShotSpotter — Allentown PA", city="Allentown", state="PA", type="shotspotter", lat=40.6084, lng=-75.4902, description="Allentown PD ShotSpotter coverage.", source="EFF Atlas"),
            Infrastructure(name="ShotSpotter — Scranton PA", city="Scranton", state="PA", type="shotspotter", lat=41.4090, lng=-75.6624, description="Scranton PD ShotSpotter deployment.", source="EFF Atlas"),
            Infrastructure(name="ShotSpotter — Erie PA", city="Erie", state="PA", type="shotspotter", lat=42.1292, lng=-80.0851, description="Erie PA PD ShotSpotter.", source="EFF Atlas"),
            Infrastructure(name="ShotSpotter — Springfield MA", city="Springfield", state="MA", type="shotspotter", lat=42.1015, lng=-72.5898, description="Springfield MA PD ShotSpotter coverage.", source="EFF Atlas"),
            Infrastructure(name="ShotSpotter — Brockton MA", city="Brockton", state="MA", type="shotspotter", lat=42.0834, lng=-71.0184, description="Brockton PD ShotSpotter deployment.", source="EFF Atlas"),
            Infrastructure(name="ShotSpotter — Fall River MA", city="Fall River", state="MA", type="shotspotter", lat=41.7015, lng=-71.1550, description="Fall River PD ShotSpotter.", source="EFF Atlas"),
            Infrastructure(name="ShotSpotter — New Bedford MA", city="New Bedford", state="MA", type="shotspotter", lat=41.6362, lng=-70.9342, description="New Bedford PD ShotSpotter coverage.", source="EFF Atlas"),
            Infrastructure(name="ShotSpotter — Lowell MA", city="Lowell", state="MA", type="shotspotter", lat=42.6334, lng=-71.3162, description="Lowell PD ShotSpotter deployment.", source="EFF Atlas"),
            Infrastructure(name="ShotSpotter — Lawrence MA", city="Lawrence", state="MA", type="shotspotter", lat=42.7070, lng=-71.1631, description="Lawrence MA PD ShotSpotter.", source="EFF Atlas"),
            Infrastructure(name="ShotSpotter — Holyoke MA", city="Holyoke", state="MA", type="shotspotter", lat=42.2042, lng=-72.6162, description="Holyoke PD ShotSpotter coverage.", source="EFF Atlas"),
            Infrastructure(name="ShotSpotter — Worcester MA", city="Worcester", state="MA", type="shotspotter", lat=42.2626, lng=-71.8023, description="Worcester PD ShotSpotter deployment.", source="EFF Atlas"),
            Infrastructure(name="ShotSpotter — Waterbury CT", city="Waterbury", state="CT", type="shotspotter", lat=41.5582, lng=-73.0515, description="Waterbury PD ShotSpotter.", source="EFF Atlas"),
            Infrastructure(name="ShotSpotter — New Haven CT", city="New Haven", state="CT", type="shotspotter", lat=41.3083, lng=-72.9279, description="New Haven PD ShotSpotter coverage.", source="EFF Atlas"),
            Infrastructure(name="ShotSpotter — Hamden CT", city="Hamden", state="CT", type="shotspotter", lat=41.3959, lng=-72.8968, description="Hamden PD ShotSpotter deployment.", source="EFF Atlas"),
            Infrastructure(name="ShotSpotter — East Hartford CT", city="East Hartford", state="CT", type="shotspotter", lat=41.7823, lng=-72.6121, description="East Hartford PD ShotSpotter.", source="EFF Atlas"),
            Infrastructure(name="ShotSpotter — Portsmouth VA", city="Portsmouth", state="VA", type="shotspotter", lat=36.8354, lng=-76.2983, description="Portsmouth VA PD ShotSpotter coverage.", source="EFF Atlas"),
            Infrastructure(name="ShotSpotter — Petersburg VA", city="Petersburg", state="VA", type="shotspotter", lat=37.2279, lng=-77.4019, description="Petersburg VA PD ShotSpotter.", source="EFF Atlas"),
            Infrastructure(name="ShotSpotter — Newport News VA", city="Newport News", state="VA", type="shotspotter", lat=37.0871, lng=-76.4730, description="Newport News PD ShotSpotter deployment.", source="EFF Atlas"),
            Infrastructure(name="ShotSpotter — Hampton VA", city="Hampton", state="VA", type="shotspotter", lat=37.0299, lng=-76.3452, description="Hampton VA PD ShotSpotter.", source="EFF Atlas"),
            Infrastructure(name="ShotSpotter — Fort Wayne IN", city="Fort Wayne", state="IN", type="shotspotter", lat=41.1306, lng=-85.1289, description="Fort Wayne PD ShotSpotter coverage.", source="EFF Atlas"),
            Infrastructure(name="ShotSpotter — Evansville IN", city="Evansville", state="IN", type="shotspotter", lat=37.9716, lng=-87.5711, description="Evansville PD ShotSpotter deployment.", source="EFF Atlas"),
            Infrastructure(name="ShotSpotter — Terre Haute IN", city="Terre Haute", state="IN", type="shotspotter", lat=39.4667, lng=-87.4139, description="Terre Haute PD ShotSpotter.", source="EFF Atlas"),
            Infrastructure(name="ShotSpotter — Columbus MS", city="Columbus", state="MS", type="shotspotter", lat=33.4957, lng=-88.4273, description="Columbus MS PD ShotSpotter coverage.", source="EFF Atlas"),
            Infrastructure(name="ShotSpotter — Meridian MS", city="Meridian", state="MS", type="shotspotter", lat=32.3643, lng=-88.7037, description="Meridian PD ShotSpotter deployment.", source="EFF Atlas"),
            Infrastructure(name="ShotSpotter — Hattiesburg MS", city="Hattiesburg", state="MS", type="shotspotter", lat=31.3271, lng=-89.2903, description="Hattiesburg PD ShotSpotter.", source="EFF Atlas"),
            Infrastructure(name="ShotSpotter — Pine Bluff AR", city="Pine Bluff", state="AR", type="shotspotter", lat=34.2284, lng=-92.0032, description="Pine Bluff PD ShotSpotter coverage.", source="EFF Atlas"),
            Infrastructure(name="ShotSpotter — Monroe LA", city="Monroe", state="LA", type="shotspotter", lat=32.5093, lng=-92.1193, description="Monroe LA PD ShotSpotter deployment.", source="EFF Atlas"),
            Infrastructure(name="ShotSpotter — Alexandria LA", city="Alexandria", state="LA", type="shotspotter", lat=31.3113, lng=-92.4451, description="Alexandria LA PD ShotSpotter.", source="EFF Atlas"),
            Infrastructure(name="ShotSpotter — Lake Charles LA", city="Lake Charles", state="LA", type="shotspotter", lat=30.2266, lng=-93.2174, description="Lake Charles PD ShotSpotter coverage.", source="EFF Atlas"),
            Infrastructure(name="ShotSpotter — Mobile AL", city="Mobile", state="AL", type="shotspotter", lat=30.6954, lng=-88.0399, description="Mobile PD ShotSpotter deployment.", source="EFF Atlas"),
            Infrastructure(name="ShotSpotter — Huntsville AL", city="Huntsville", state="AL", type="shotspotter", lat=34.7304, lng=-86.5861, description="Huntsville PD ShotSpotter.", source="EFF Atlas"),
            Infrastructure(name="ShotSpotter — Tuscaloosa AL", city="Tuscaloosa", state="AL", type="shotspotter", lat=33.2098, lng=-87.5692, description="Tuscaloosa PD ShotSpotter coverage.", source="EFF Atlas"),
            Infrastructure(name="ShotSpotter — Decatur AL", city="Decatur", state="AL", type="shotspotter", lat=34.6059, lng=-86.9833, description="Decatur AL PD ShotSpotter.", source="EFF Atlas"),
            Infrastructure(name="ShotSpotter — Muskogee OK", city="Muskogee", state="OK", type="shotspotter", lat=35.7479, lng=-95.3697, description="Muskogee PD ShotSpotter deployment.", source="EFF Atlas"),
            Infrastructure(name="ShotSpotter — Lawton OK", city="Lawton", state="OK", type="shotspotter", lat=34.6036, lng=-98.3959, description="Lawton PD ShotSpotter coverage.", source="EFF Atlas"),
            Infrastructure(name="ShotSpotter — Pueblo CO", city="Pueblo", state="CO", type="shotspotter", lat=38.2544, lng=-104.6091, description="Pueblo PD ShotSpotter.", source="EFF Atlas"),
            Infrastructure(name="ShotSpotter — Ogden UT", city="Ogden", state="UT", type="shotspotter", lat=41.2230, lng=-111.9738, description="Ogden PD ShotSpotter deployment.", source="EFF Atlas"),
            Infrastructure(name="ShotSpotter — Provo UT", city="Provo", state="UT", type="shotspotter", lat=40.2338, lng=-111.6585, description="Provo PD ShotSpotter coverage.", source="EFF Atlas"),
            Infrastructure(name="ShotSpotter — Spokane WA", city="Spokane", state="WA", type="shotspotter", lat=47.6587, lng=-117.4260, description="Spokane PD ShotSpotter deployment.", source="EFF Atlas"),
            Infrastructure(name="ShotSpotter — Yakima WA", city="Yakima", state="WA", type="shotspotter", lat=46.6021, lng=-120.5059, description="Yakima PD ShotSpotter.", source="EFF Atlas"),
            Infrastructure(name="ShotSpotter — Boise ID", city="Boise", state="ID", type="shotspotter", lat=43.6150, lng=-116.2023, description="Boise PD ShotSpotter coverage.", source="EFF Atlas"),
            Infrastructure(name="ShotSpotter — Billings MT", city="Billings", state="MT", type="shotspotter", lat=45.7833, lng=-108.5007, description="Billings PD ShotSpotter deployment.", source="EFF Atlas"),
            Infrastructure(name="ShotSpotter — Fargo ND", city="Fargo", state="ND", type="shotspotter", lat=46.8772, lng=-96.7898, description="Fargo PD ShotSpotter.", source="EFF Atlas"),
            Infrastructure(name="ShotSpotter — Sioux Falls SD", city="Sioux Falls", state="SD", type="shotspotter", lat=43.5446, lng=-96.7311, description="Sioux Falls PD ShotSpotter coverage.", source="EFF Atlas"),
            Infrastructure(name="ShotSpotter — Rapid City SD", city="Rapid City", state="SD", type="shotspotter", lat=44.0805, lng=-103.2310, description="Rapid City PD ShotSpotter.", source="EFF Atlas"),
            Infrastructure(name="ShotSpotter — Bismarck ND", city="Bismarck", state="ND", type="shotspotter", lat=46.8083, lng=-100.7837, description="Bismarck PD ShotSpotter deployment.", source="EFF Atlas"),

            # ══════════════════════════════════════════════════════════════
            # NEIGHBORHOOD LEVEL — PHILADELPHIA
            # Source: PPD records, EFF Atlas, The Markup
            # ══════════════════════════════════════════════════════════════

            Infrastructure(name="PPD 22nd District Surveillance — North Philly", city="Philadelphia", state="PA", type="surveillance_camera", lat=39.9920, lng=-75.1580, description="PPD 22nd District cameras. North Philadelphia.", source="PPD records; EFF Atlas"),
            Infrastructure(name="PPD 25th District Surveillance — Kensington", city="Philadelphia", state="PA", type="surveillance_camera", lat=39.9990, lng=-75.1260, description="PPD 25th District cameras. Kensington neighborhood.", source="PPD records; EFF Atlas"),
            Infrastructure(name="PPD 35th District Surveillance — Germantown", city="Philadelphia", state="PA", type="surveillance_camera", lat=40.0330, lng=-75.1710, description="PPD 35th District camera network. Germantown.", source="PPD records; EFF Atlas"),
            Infrastructure(name="PPD 39th District Surveillance — West Philly", city="Philadelphia", state="PA", type="surveillance_camera", lat=39.9680, lng=-75.2290, description="PPD 39th District cameras. West Philadelphia.", source="PPD records; EFF Atlas"),
            Infrastructure(name="PPD 12th District Surveillance — South Philly", city="Philadelphia", state="PA", type="surveillance_camera", lat=39.9270, lng=-75.1580, description="PPD 12th District camera network. South Philadelphia.", source="PPD records; EFF Atlas"),
            Infrastructure(name="PPD 19th District Surveillance — West Philly South", city="Philadelphia", state="PA", type="surveillance_camera", lat=39.9500, lng=-75.2410, description="PPD 19th District cameras. Southwest Philadelphia.", source="PPD records; EFF Atlas"),
            Infrastructure(name="ShotSpotter — Philadelphia North Philly", city="Philadelphia", state="PA", type="shotspotter", lat=39.9920, lng=-75.1580, description="ShotSpotter coverage in North Philadelphia.", source="PPD records; EFF Atlas"),
            Infrastructure(name="ShotSpotter — Philadelphia Kensington", city="Philadelphia", state="PA", type="shotspotter", lat=39.9990, lng=-75.1260, description="ShotSpotter in Kensington neighborhood.", source="PPD records; EFF Atlas"),
            Infrastructure(name="ShotSpotter — Philadelphia West Philadelphia", city="Philadelphia", state="PA", type="shotspotter", lat=39.9680, lng=-75.2290, description="ShotSpotter coverage in West Philadelphia.", source="PPD records; EFF Atlas"),
            Infrastructure(name="ShotSpotter — Philadelphia Germantown", city="Philadelphia", state="PA", type="shotspotter", lat=40.0330, lng=-75.1710, description="ShotSpotter in Germantown.", source="PPD records; EFF Atlas"),

            # ══════════════════════════════════════════════════════════════
            # NEIGHBORHOOD LEVEL — ATLANTA
            # Source: APD records, EFF Atlas
            # ══════════════════════════════════════════════════════════════

            Infrastructure(name="APD Zone 1 Surveillance — Northwest Atlanta", city="Atlanta", state="GA", type="surveillance_camera", lat=33.7820, lng=-84.4230, description="APD Zone 1 cameras. Northwest Atlanta.", source="APD records; EFF Atlas"),
            Infrastructure(name="APD Zone 3 Surveillance — Southwest Atlanta", city="Atlanta", state="GA", type="surveillance_camera", lat=33.7090, lng=-84.4460, description="APD Zone 3 camera network. Southwest Atlanta.", source="APD records; EFF Atlas"),
            Infrastructure(name="APD Zone 4 Surveillance — Southeast Atlanta", city="Atlanta", state="GA", type="surveillance_camera", lat=33.7130, lng=-84.3820, description="APD Zone 4 cameras. Southeast Atlanta.", source="APD records; EFF Atlas"),
            Infrastructure(name="APD Zone 5 Surveillance — Downtown Atlanta", city="Atlanta", state="GA", type="surveillance_camera", lat=33.7490, lng=-84.3880, description="APD Zone 5 camera network. Downtown and Midtown.", source="APD records; EFF Atlas"),
            Infrastructure(name="APD Zone 6 Surveillance — East Atlanta", city="Atlanta", state="GA", type="surveillance_camera", lat=33.7340, lng=-84.3380, description="APD Zone 6 cameras. East Atlanta and Ormewood Park.", source="APD records; EFF Atlas"),
            Infrastructure(name="ShotSpotter — Atlanta Vine City", city="Atlanta", state="GA", type="shotspotter", lat=33.7590, lng=-84.4180, description="ShotSpotter in Vine City neighborhood.", source="APD records; EFF Atlas"),
            Infrastructure(name="ShotSpotter — Atlanta Pittsburgh neighborhood", city="Atlanta", state="GA", type="shotspotter", lat=33.7180, lng=-84.4050, description="ShotSpotter in Pittsburgh neighborhood, SW Atlanta.", source="APD records; EFF Atlas"),
            Infrastructure(name="ShotSpotter — Atlanta Bankhead", city="Atlanta", state="GA", type="shotspotter", lat=33.7730, lng=-84.4590, description="ShotSpotter coverage in Bankhead area.", source="APD records; EFF Atlas"),
            Infrastructure(name="Flock Safety LPR — Atlanta Fulton County intersections", city="Atlanta", state="GA", type="flock_lpr", lat=33.7490, lng=-84.4150, description="Flock Safety cameras at key Fulton County intersections. Real-time plate reads.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Atlanta DeKalb County intersections", city="Atlanta", state="GA", type="flock_lpr", lat=33.7748, lng=-84.2963, description="Flock Safety LPR in DeKalb County. Regional data sharing.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Atlanta Gwinnett County intersections", city="Atlanta", state="GA", type="flock_lpr", lat=33.9526, lng=-83.9877, description="Flock Safety cameras in Gwinnett County.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Atlanta Cobb County intersections", city="Atlanta", state="GA", type="flock_lpr", lat=33.9526, lng=-84.5499, description="Flock Safety LPR in Cobb County.", source="EFF Atlas; Flock Safety contracts"),

            # ══════════════════════════════════════════════════════════════
            # NEIGHBORHOOD LEVEL — NEW ORLEANS
            # Source: NOPD records, EFF Atlas, ACLU Louisiana
            # ══════════════════════════════════════════════════════════════

            Infrastructure(name="NOPD 1st District Surveillance — French Quarter", city="New Orleans", state="LA", type="surveillance_camera", lat=29.9584, lng=-90.0644, description="NOPD 1st District cameras. French Quarter — densest coverage in city.", source="NOPD records; EFF Atlas"),
            Infrastructure(name="NOPD 2nd District Surveillance — Uptown", city="New Orleans", state="LA", type="surveillance_camera", lat=29.9255, lng=-90.1030, description="NOPD 2nd District camera network. Uptown neighborhood.", source="NOPD records; EFF Atlas"),
            Infrastructure(name="NOPD 3rd District Surveillance — Gentilly", city="New Orleans", state="LA", type="surveillance_camera", lat=30.0050, lng=-90.0460, description="NOPD 3rd District cameras. Gentilly neighborhood.", source="NOPD records; EFF Atlas"),
            Infrastructure(name="NOPD 4th District Surveillance — Algiers", city="New Orleans", state="LA", type="surveillance_camera", lat=29.9290, lng=-90.0640, description="NOPD 4th District camera network. Algiers Point.", source="NOPD records; EFF Atlas"),
            Infrastructure(name="NOPD 5th District Surveillance — Lower Ninth Ward", city="New Orleans", state="LA", type="surveillance_camera", lat=29.9710, lng=-89.9990, description="NOPD 5th District cameras. Lower Ninth Ward.", source="NOPD records; EFF Atlas"),
            Infrastructure(name="NOPD 6th District Surveillance — Central City", city="New Orleans", state="LA", type="surveillance_camera", lat=29.9311, lng=-90.0849, description="NOPD 6th District camera network. Central City neighborhood.", source="NOPD records; EFF Atlas"),
            Infrastructure(name="NOPD 7th District Surveillance — New Orleans East", city="New Orleans", state="LA", type="surveillance_camera", lat=30.0160, lng=-89.9510, description="NOPD 7th District cameras. New Orleans East.", source="NOPD records; EFF Atlas"),
            Infrastructure(name="NOPD 8th District Surveillance — CBD", city="New Orleans", state="LA", type="surveillance_camera", lat=29.9501, lng=-90.0715, description="NOPD 8th District camera network. Central Business District.", source="NOPD records; EFF Atlas"),
            Infrastructure(name="ShotSpotter — New Orleans Seventh Ward", city="New Orleans", state="LA", type="shotspotter", lat=29.9690, lng=-90.0560, description="ShotSpotter coverage in Seventh Ward.", source="NOPD records; EFF Atlas"),
            Infrastructure(name="ShotSpotter — New Orleans Treme", city="New Orleans", state="LA", type="shotspotter", lat=29.9630, lng=-90.0680, description="ShotSpotter in Treme neighborhood.", source="NOPD records; EFF Atlas"),
            Infrastructure(name="ShotSpotter — New Orleans Central City", city="New Orleans", state="LA", type="shotspotter", lat=29.9311, lng=-90.0849, description="ShotSpotter coverage in Central City.", source="NOPD records; EFF Atlas"),
            Infrastructure(name="ShotSpotter — New Orleans Lower Ninth Ward", city="New Orleans", state="LA", type="shotspotter", lat=29.9710, lng=-89.9990, description="ShotSpotter in Lower Ninth Ward.", source="NOPD records; EFF Atlas"),

            # ══════════════════════════════════════════════════════════════
            # FLOCK SAFETY — ADDITIONAL SUBURBAN/SMALLER CITY DEPLOYMENTS
            # Source: Flock Safety public contracts, EFF Atlas
            # ══════════════════════════════════════════════════════════════

            Infrastructure(name="Flock Safety LPR — Alpharetta GA", city="Alpharetta", state="GA", type="flock_lpr", lat=34.0754, lng=-84.2941, description="Alpharetta PD Flock Safety deployment. Suburban Atlanta.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Sandy Springs GA", city="Sandy Springs", state="GA", type="flock_lpr", lat=33.9304, lng=-84.3733, description="Sandy Springs PD Flock Safety LPR.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Marietta GA", city="Marietta", state="GA", type="flock_lpr", lat=33.9526, lng=-84.5499, description="Marietta GA PD Flock Safety deployment.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Roswell GA", city="Roswell", state="GA", type="flock_lpr", lat=34.0232, lng=-84.3616, description="Roswell GA PD Flock Safety LPR.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Peachtree City GA", city="Peachtree City", state="GA", type="flock_lpr", lat=33.3965, lng=-84.5963, description="Peachtree City PD Flock Safety cameras.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Frisco TX", city="Frisco", state="TX", type="flock_lpr", lat=33.1507, lng=-96.8236, description="Frisco TX PD Flock Safety LPR network.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — McKinney TX", city="McKinney", state="TX", type="flock_lpr", lat=33.1972, lng=-96.6397, description="McKinney TX PD Flock Safety deployment.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Allen TX", city="Allen", state="TX", type="flock_lpr", lat=33.1032, lng=-96.6706, description="Allen TX PD Flock Safety LPR.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Round Rock TX", city="Round Rock", state="TX", type="flock_lpr", lat=30.5083, lng=-97.6789, description="Round Rock TX PD Flock Safety cameras.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Cedar Park TX", city="Cedar Park", state="TX", type="flock_lpr", lat=30.5052, lng=-97.8203, description="Cedar Park TX PD Flock Safety LPR.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Leander TX", city="Leander", state="TX", type="flock_lpr", lat=30.5788, lng=-97.8531, description="Leander TX PD Flock Safety deployment.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Pflugerville TX", city="Pflugerville", state="TX", type="flock_lpr", lat=30.4393, lng=-97.6200, description="Pflugerville TX PD Flock Safety LPR.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Chandler AZ", city="Chandler", state="AZ", type="flock_lpr", lat=33.3062, lng=-111.8413, description="Chandler AZ PD Flock Safety cameras.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Gilbert AZ", city="Gilbert", state="AZ", type="flock_lpr", lat=33.3528, lng=-111.7890, description="Gilbert AZ PD Flock Safety LPR.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Tempe AZ", city="Tempe", state="AZ", type="flock_lpr", lat=33.4255, lng=-111.9400, description="Tempe AZ PD Flock Safety deployment.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Scottsdale AZ", city="Scottsdale", state="AZ", type="flock_lpr", lat=33.4942, lng=-111.9261, description="Scottsdale AZ PD Flock Safety LPR.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Peoria AZ", city="Peoria", state="AZ", type="flock_lpr", lat=33.5806, lng=-112.2374, description="Peoria AZ PD Flock Safety cameras.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Surprise AZ", city="Surprise", state="AZ", type="flock_lpr", lat=33.6292, lng=-112.3679, description="Surprise AZ PD Flock Safety LPR.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Naperville IL", city="Naperville", state="IL", type="flock_lpr", lat=41.7508, lng=-88.1535, description="Naperville IL PD Flock Safety deployment.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Aurora IL", city="Aurora", state="IL", type="flock_lpr", lat=41.7606, lng=-88.3201, description="Aurora IL PD Flock Safety LPR.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Joliet IL", city="Joliet", state="IL", type="flock_lpr", lat=41.5250, lng=-88.0817, description="Joliet IL PD Flock Safety cameras.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Schaumburg IL", city="Schaumburg", state="IL", type="flock_lpr", lat=42.0334, lng=-88.0834, description="Schaumburg IL PD Flock Safety LPR.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Elgin IL", city="Elgin", state="IL", type="flock_lpr", lat=42.0354, lng=-88.2826, description="Elgin IL PD Flock Safety deployment.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Waukegan IL", city="Waukegan", state="IL", type="flock_lpr", lat=42.3636, lng=-87.8448, description="Waukegan IL PD Flock Safety LPR.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Henderson NV", city="Henderson", state="NV", type="flock_lpr", lat=36.0395, lng=-114.9817, description="Henderson NV PD Flock Safety cameras.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — North Las Vegas NV", city="North Las Vegas", state="NV", type="flock_lpr", lat=36.1989, lng=-115.1175, description="North Las Vegas PD Flock Safety LPR.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Summerlin NV", city="Las Vegas", state="NV", type="flock_lpr", lat=36.1750, lng=-115.3280, description="Flock Safety cameras in Summerlin area, Las Vegas.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Chesapeake VA", city="Chesapeake", state="VA", type="flock_lpr", lat=36.7682, lng=-76.2875, description="Chesapeake VA PD Flock Safety deployment.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Suffolk VA", city="Suffolk", state="VA", type="flock_lpr", lat=36.7282, lng=-76.5836, description="Suffolk VA PD Flock Safety LPR.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Hampton VA", city="Hampton", state="VA", type="flock_lpr", lat=37.0299, lng=-76.3452, description="Hampton VA PD Flock Safety cameras.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Roanoke VA", city="Roanoke", state="VA", type="flock_lpr", lat=37.2710, lng=-79.9414, description="Roanoke VA PD Flock Safety LPR.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Fayetteville NC", city="Fayetteville", state="NC", type="flock_lpr", lat=35.0527, lng=-78.8784, description="Fayetteville NC PD Flock Safety deployment.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Wilmington NC", city="Wilmington", state="NC", type="flock_lpr", lat=34.2257, lng=-77.9447, description="Wilmington NC PD Flock Safety LPR.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — High Point NC", city="High Point", state="NC", type="flock_lpr", lat=35.9557, lng=-80.0053, description="High Point NC PD Flock Safety cameras.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Concord NC", city="Concord", state="NC", type="flock_lpr", lat=35.4088, lng=-80.5795, description="Concord NC PD Flock Safety LPR.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Cary NC", city="Cary", state="NC", type="flock_lpr", lat=35.7915, lng=-78.7811, description="Cary NC PD Flock Safety deployment.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Durham NC", city="Durham", state="NC", type="flock_lpr", lat=35.9940, lng=-78.8986, description="Durham NC PD Flock Safety LPR.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Clarksville TN", city="Clarksville", state="TN", type="flock_lpr", lat=36.5298, lng=-87.3595, description="Clarksville TN PD Flock Safety deployment.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Murfreesboro TN", city="Murfreesboro", state="TN", type="flock_lpr", lat=35.8456, lng=-86.3903, description="Murfreesboro TN PD Flock Safety LPR.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Franklin TN", city="Franklin", state="TN", type="flock_lpr", lat=35.9251, lng=-86.8689, description="Franklin TN PD Flock Safety cameras.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Brentwood TN", city="Brentwood", state="TN", type="flock_lpr", lat=36.0331, lng=-86.7828, description="Brentwood TN PD Flock Safety LPR.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Huntsville AL", city="Huntsville", state="AL", type="flock_lpr", lat=34.7304, lng=-86.5861, description="Huntsville AL PD Flock Safety deployment.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Mobile AL", city="Mobile", state="AL", type="flock_lpr", lat=30.6954, lng=-88.0399, description="Mobile AL PD Flock Safety LPR.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Pensacola FL", city="Pensacola", state="FL", type="flock_lpr", lat=30.4213, lng=-87.2169, description="Pensacola FL PD Flock Safety cameras.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Tallahassee FL", city="Tallahassee", state="FL", type="flock_lpr", lat=30.4518, lng=-84.2807, description="Tallahassee FL PD Flock Safety LPR.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Gainesville FL", city="Gainesville", state="FL", type="flock_lpr", lat=29.6516, lng=-82.3248, description="Gainesville FL PD Flock Safety deployment.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Cape Coral FL", city="Cape Coral", state="FL", type="flock_lpr", lat=26.5629, lng=-81.9495, description="Cape Coral FL PD Flock Safety LPR.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Port St. Lucie FL", city="Port St. Lucie", state="FL", type="flock_lpr", lat=27.2730, lng=-80.3582, description="Port St. Lucie FL PD Flock Safety cameras.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Miramar FL", city="Miramar", state="FL", type="flock_lpr", lat=25.9860, lng=-80.2331, description="Miramar FL PD Flock Safety LPR.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Coral Springs FL", city="Coral Springs", state="FL", type="flock_lpr", lat=26.2707, lng=-80.2706, description="Coral Springs FL PD Flock Safety deployment.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Pembroke Pines FL", city="Pembroke Pines", state="FL", type="flock_lpr", lat=26.0128, lng=-80.2962, description="Pembroke Pines FL PD Flock Safety LPR.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Hollywood FL", city="Hollywood", state="FL", type="flock_lpr", lat=26.0112, lng=-80.1495, description="Hollywood FL PD Flock Safety cameras.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Pompano Beach FL", city="Pompano Beach", state="FL", type="flock_lpr", lat=26.2379, lng=-80.1248, description="Pompano Beach FL PD Flock Safety LPR.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Boca Raton FL", city="Boca Raton", state="FL", type="flock_lpr", lat=26.3683, lng=-80.1289, description="Boca Raton FL PD Flock Safety deployment.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Clearwater FL", city="Clearwater", state="FL", type="flock_lpr", lat=27.9659, lng=-82.8001, description="Clearwater FL PD Flock Safety LPR.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Lakeland FL", city="Lakeland", state="FL", type="flock_lpr", lat=28.0395, lng=-81.9498, description="Lakeland FL PD Flock Safety cameras.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Daytona Beach FL", city="Daytona Beach", state="FL", type="flock_lpr", lat=29.2108, lng=-81.0228, description="Daytona Beach FL PD Flock Safety LPR.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Kissimmee FL", city="Kissimmee", state="FL", type="flock_lpr", lat=28.2920, lng=-81.4076, description="Kissimmee FL PD Flock Safety deployment.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Ocala FL", city="Ocala", state="FL", type="flock_lpr", lat=29.1872, lng=-82.1401, description="Ocala FL PD Flock Safety LPR.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Sarasota FL", city="Sarasota", state="FL", type="flock_lpr", lat=27.3364, lng=-82.5307, description="Sarasota FL PD Flock Safety cameras.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Fort Myers FL", city="Fort Myers", state="FL", type="flock_lpr", lat=26.6406, lng=-81.8723, description="Fort Myers FL PD Flock Safety LPR.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Naples FL", city="Naples", state="FL", type="flock_lpr", lat=26.1420, lng=-81.7948, description="Naples FL PD Flock Safety deployment.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Overland Park KS", city="Overland Park", state="KS", type="flock_lpr", lat=38.9822, lng=-94.6708, description="Overland Park KS PD Flock Safety LPR.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Olathe KS", city="Olathe", state="KS", type="flock_lpr", lat=38.8814, lng=-94.8191, description="Olathe KS PD Flock Safety cameras.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Shawnee KS", city="Shawnee", state="KS", type="flock_lpr", lat=39.0228, lng=-94.7154, description="Shawnee KS PD Flock Safety LPR.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Lenexa KS", city="Lenexa", state="KS", type="flock_lpr", lat=38.9536, lng=-94.7336, description="Lenexa KS PD Flock Safety deployment.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Lee's Summit MO", city="Lee's Summit", state="MO", type="flock_lpr", lat=38.9108, lng=-94.3822, description="Lee's Summit MO PD Flock Safety LPR.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Independence MO", city="Independence", state="MO", type="flock_lpr", lat=39.0911, lng=-94.4155, description="Independence MO PD Flock Safety cameras.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Columbia MO", city="Columbia", state="MO", type="flock_lpr", lat=38.9517, lng=-92.3341, description="Columbia MO PD Flock Safety LPR.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Springfield MO", city="Springfield", state="MO", type="flock_lpr", lat=37.2090, lng=-93.2923, description="Springfield MO PD Flock Safety deployment.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Lexington KY", city="Lexington", state="KY", type="flock_lpr", lat=38.0406, lng=-84.5037, description="Lexington KY PD Flock Safety LPR.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Bowling Green KY", city="Bowling Green", state="KY", type="flock_lpr", lat=36.9685, lng=-86.4808, description="Bowling Green KY PD Flock Safety cameras.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Evansville IN", city="Evansville", state="IN", type="flock_lpr", lat=37.9716, lng=-87.5711, description="Evansville IN PD Flock Safety LPR.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — South Bend IN", city="South Bend", state="IN", type="flock_lpr", lat=41.6764, lng=-86.2520, description="South Bend IN PD Flock Safety deployment.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Carmel IN", city="Carmel", state="IN", type="flock_lpr", lat=39.9784, lng=-86.1180, description="Carmel IN PD Flock Safety LPR.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Fishers IN", city="Fishers", state="IN", type="flock_lpr", lat=39.9567, lng=-86.0134, description="Fishers IN PD Flock Safety cameras.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Ann Arbor MI", city="Ann Arbor", state="MI", type="flock_lpr", lat=42.2808, lng=-83.7430, description="Ann Arbor MI PD Flock Safety LPR.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Lansing MI", city="Lansing", state="MI", type="flock_lpr", lat=42.7325, lng=-84.5555, description="Lansing MI PD Flock Safety deployment.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Flint MI", city="Flint", state="MI", type="flock_lpr", lat=43.0125, lng=-83.6875, description="Flint MI PD Flock Safety LPR.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Dearborn MI", city="Dearborn", state="MI", type="flock_lpr", lat=42.3223, lng=-83.1763, description="Dearborn MI PD Flock Safety cameras.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Sterling Heights MI", city="Sterling Heights", state="MI", type="flock_lpr", lat=42.5803, lng=-83.0302, description="Sterling Heights MI PD Flock Safety LPR.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Rochester Hills MI", city="Rochester Hills", state="MI", type="flock_lpr", lat=42.6584, lng=-83.1499, description="Rochester Hills MI PD Flock Safety deployment.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Akron OH", city="Akron", state="OH", type="flock_lpr", lat=41.0814, lng=-81.5190, description="Akron OH PD Flock Safety LPR.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Dayton OH", city="Dayton", state="OH", type="flock_lpr", lat=39.7589, lng=-84.1916, description="Dayton OH PD Flock Safety cameras.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Toledo OH", city="Toledo", state="OH", type="flock_lpr", lat=41.6639, lng=-83.5552, description="Toledo OH PD Flock Safety deployment.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Parma OH", city="Parma", state="OH", type="flock_lpr", lat=41.3845, lng=-81.7229, description="Parma OH PD Flock Safety LPR.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Youngstown OH", city="Youngstown", state="OH", type="flock_lpr", lat=41.0998, lng=-80.6495, description="Youngstown OH PD Flock Safety cameras.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Spokane WA", city="Spokane", state="WA", type="flock_lpr", lat=47.6587, lng=-117.4260, description="Spokane WA PD Flock Safety LPR.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Bellevue WA", city="Bellevue", state="WA", type="flock_lpr", lat=47.6101, lng=-122.2015, description="Bellevue WA PD Flock Safety deployment.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Kirkland WA", city="Kirkland", state="WA", type="flock_lpr", lat=47.6815, lng=-122.2087, description="Kirkland WA PD Flock Safety LPR.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Renton WA", city="Renton", state="WA", type="flock_lpr", lat=47.4829, lng=-122.2171, description="Renton WA PD Flock Safety cameras.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Kent WA", city="Kent", state="WA", type="flock_lpr", lat=47.3809, lng=-122.2348, description="Kent WA PD Flock Safety LPR.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Eugene OR", city="Eugene", state="OR", type="flock_lpr", lat=44.0521, lng=-123.0868, description="Eugene OR PD Flock Safety deployment.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Salem OR", city="Salem", state="OR", type="flock_lpr", lat=44.9429, lng=-123.0351, description="Salem OR PD Flock Safety LPR.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Beaverton OR", city="Beaverton", state="OR", type="flock_lpr", lat=45.4871, lng=-122.8037, description="Beaverton OR PD Flock Safety cameras.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Gresham OR", city="Gresham", state="OR", type="flock_lpr", lat=45.5051, lng=-122.4302, description="Gresham OR PD Flock Safety LPR.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Boise ID", city="Boise", state="ID", type="flock_lpr", lat=43.6150, lng=-116.2023, description="Boise ID PD Flock Safety deployment.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Meridian ID", city="Meridian", state="ID", type="flock_lpr", lat=43.6121, lng=-116.3915, description="Meridian ID PD Flock Safety LPR.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Nampa ID", city="Nampa", state="ID", type="flock_lpr", lat=43.5407, lng=-116.5635, description="Nampa ID PD Flock Safety cameras.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Billings MT", city="Billings", state="MT", type="flock_lpr", lat=45.7833, lng=-108.5007, description="Billings MT PD Flock Safety LPR.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Missoula MT", city="Missoula", state="MT", type="flock_lpr", lat=46.8721, lng=-113.9940, description="Missoula MT PD Flock Safety deployment.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Fargo ND", city="Fargo", state="ND", type="flock_lpr", lat=46.8772, lng=-96.7898, description="Fargo ND PD Flock Safety LPR.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Sioux Falls SD", city="Sioux Falls", state="SD", type="flock_lpr", lat=43.5446, lng=-96.7311, description="Sioux Falls SD PD Flock Safety cameras.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Lincoln NE", city="Lincoln", state="NE", type="flock_lpr", lat=40.8136, lng=-96.7026, description="Lincoln NE PD Flock Safety LPR.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Des Moines IA", city="Des Moines", state="IA", type="flock_lpr", lat=41.5868, lng=-93.6250, description="Des Moines IA PD Flock Safety deployment.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Cedar Rapids IA", city="Cedar Rapids", state="IA", type="flock_lpr", lat=41.9779, lng=-91.6656, description="Cedar Rapids IA PD Flock Safety LPR.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Madison WI", city="Madison", state="WI", type="flock_lpr", lat=43.0731, lng=-89.4012, description="Madison WI PD Flock Safety cameras.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Green Bay WI", city="Green Bay", state="WI", type="flock_lpr", lat=44.5133, lng=-88.0133, description="Green Bay WI PD Flock Safety LPR.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Kenosha WI", city="Kenosha", state="WI", type="flock_lpr", lat=42.5847, lng=-87.8212, description="Kenosha WI PD Flock Safety deployment.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Racine WI", city="Racine", state="WI", type="flock_lpr", lat=42.7261, lng=-87.7829, description="Racine WI PD Flock Safety LPR.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Manchester NH", city="Manchester", state="NH", type="flock_lpr", lat=42.9956, lng=-71.4548, description="Manchester NH PD Flock Safety cameras.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Nashua NH", city="Nashua", state="NH", type="flock_lpr", lat=42.7654, lng=-71.4676, description="Nashua NH PD Flock Safety LPR.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Burlington VT", city="Burlington", state="VT", type="flock_lpr", lat=44.4759, lng=-73.2121, description="Burlington VT PD Flock Safety deployment.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Portland ME", city="Portland", state="ME", type="flock_lpr", lat=43.6591, lng=-70.2568, description="Portland ME PD Flock Safety LPR.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Anchorage AK", city="Anchorage", state="AK", type="flock_lpr", lat=61.2181, lng=-149.9003, description="Anchorage AK PD Flock Safety cameras.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Honolulu HI", city="Honolulu", state="HI", type="flock_lpr", lat=21.3069, lng=-157.8583, description="Honolulu HI PD Flock Safety LPR.", source="EFF Atlas; Flock Safety contracts"),

            # ══════════════════════════════════════════════════════════════
            # ADDITIONAL RTCC — SMALLER CITIES
            # Source: EFF Atlas, city records
            # ══════════════════════════════════════════════════════════════

            Infrastructure(name="Compton CA Real Time Crime Center", city="Compton", state="CA", type="rtcc", lat=33.8958, lng=-118.2201, description="Compton PD RTCC. ShotSpotter and camera integration.", source="EFF Atlas"),
            Infrastructure(name="Salinas CA Real Time Crime Center", city="Salinas", state="CA", type="rtcc", lat=36.6777, lng=-121.6555, description="Salinas PD RTCC.", source="EFF Atlas"),
            Infrastructure(name="Vallejo CA Real Time Crime Center", city="Vallejo", state="CA", type="rtcc", lat=38.1041, lng=-122.2566, description="Vallejo PD RTCC.", source="EFF Atlas"),
            Infrastructure(name="Richmond CA Real Time Crime Center", city="Richmond", state="CA", type="rtcc", lat=37.9358, lng=-122.3477, description="Richmond CA PD RTCC.", source="EFF Atlas"),
            Infrastructure(name="Gary IN Real Time Crime Center", city="Gary", state="IN", type="rtcc", lat=41.5934, lng=-87.3465, description="Gary PD RTCC. ShotSpotter integration.", source="EFF Atlas"),
            Infrastructure(name="South Bend IN Real Time Crime Center", city="South Bend", state="IN", type="rtcc", lat=41.6764, lng=-86.2520, description="South Bend PD RTCC.", source="EFF Atlas"),
            Infrastructure(name="Flint MI Real Time Crime Center", city="Flint", state="MI", type="rtcc", lat=43.0125, lng=-83.6875, description="Flint PD RTCC.", source="EFF Atlas"),
            Infrastructure(name="Macon GA Real Time Crime Center", city="Macon", state="GA", type="rtcc", lat=32.8407, lng=-83.6324, description="Macon PD RTCC.", source="EFF Atlas"),
            Infrastructure(name="Savannah GA Real Time Crime Center", city="Savannah", state="GA", type="rtcc", lat=32.0835, lng=-81.0998, description="Savannah PD RTCC. Port city surveillance.", source="EFF Atlas"),
            Infrastructure(name="Augusta GA Real Time Crime Center", city="Augusta", state="GA", type="rtcc", lat=33.4735, lng=-82.0105, description="Augusta PD RTCC.", source="EFF Atlas"),
            Infrastructure(name="Montgomery AL Real Time Crime Center", city="Montgomery", state="AL", type="rtcc", lat=32.3617, lng=-86.2792, description="Montgomery PD RTCC.", source="EFF Atlas"),
            Infrastructure(name="Mobile AL Real Time Crime Center", city="Mobile", state="AL", type="rtcc", lat=30.6954, lng=-88.0399, description="Mobile PD RTCC. Port city surveillance.", source="EFF Atlas"),
            Infrastructure(name="Jackson MS Real Time Crime Center", city="Jackson", state="MS", type="rtcc", lat=32.2988, lng=-90.1848, description="Jackson MS PD RTCC.", source="EFF Atlas"),
            Infrastructure(name="Little Rock AR Real Time Crime Center", city="Little Rock", state="AR", type="rtcc", lat=34.7465, lng=-92.2896, description="Little Rock PD RTCC.", source="EFF Atlas"),
            Infrastructure(name="Shreveport LA Real Time Crime Center", city="Shreveport", state="LA", type="rtcc", lat=32.5252, lng=-93.7502, description="Shreveport PD RTCC.", source="EFF Atlas"),
            Infrastructure(name="Lubbock TX Real Time Crime Center", city="Lubbock", state="TX", type="rtcc", lat=33.5779, lng=-101.8552, description="Lubbock PD RTCC.", source="EFF Atlas"),
            Infrastructure(name="Corpus Christi TX Real Time Crime Center", city="Corpus Christi", state="TX", type="rtcc", lat=27.8006, lng=-97.3964, description="CCPD RTCC. Port surveillance.", source="EFF Atlas"),
            Infrastructure(name="Laredo TX Real Time Crime Center", city="Laredo", state="TX", type="rtcc", lat=27.5306, lng=-99.4803, description="Laredo PD RTCC. Border city surveillance.", source="EFF Atlas"),
            Infrastructure(name="McAllen TX Real Time Crime Center", city="McAllen", state="TX", type="rtcc", lat=26.2034, lng=-98.2300, description="McAllen PD RTCC. High border crossing area.", source="EFF Atlas"),
            Infrastructure(name="El Paso TX Real Time Crime Center", city="El Paso", state="TX", type="rtcc", lat=31.7619, lng=-106.4850, description="EPPD RTCC. Border city CBP integration.", source="EFF Atlas"),
            Infrastructure(name="Spokane WA Real Time Crime Center", city="Spokane", state="WA", type="rtcc", lat=47.6587, lng=-117.4260, description="Spokane PD RTCC.", source="EFF Atlas"),
            Infrastructure(name="Tacoma WA Real Time Crime Center", city="Tacoma", state="WA", type="rtcc", lat=47.2529, lng=-122.4443, description="Tacoma PD RTCC.", source="EFF Atlas"),
            Infrastructure(name="Anchorage AK Real Time Crime Center", city="Anchorage", state="AK", type="rtcc", lat=61.2181, lng=-149.9003, description="APD RTCC. Alaska statewide data.", source="EFF Atlas"),

            # ══════════════════════════════════════════════════════════════
            # NEIGHBORHOOD LEVEL — DALLAS / FORT WORTH METRO
            # Source: DPD records, EFF Atlas
            # ══════════════════════════════════════════════════════════════

            Infrastructure(name="DPD Central Division Surveillance", city="Dallas", state="TX", type="surveillance_camera", lat=32.7767, lng=-96.7970, description="DPD Central Division cameras. Downtown Dallas.", source="DPD records; EFF Atlas"),
            Infrastructure(name="DPD South Central Division Surveillance", city="Dallas", state="TX", type="surveillance_camera", lat=32.7360, lng=-96.7970, description="DPD South Central Division camera network.", source="DPD records; EFF Atlas"),
            Infrastructure(name="DPD Southeast Division Surveillance", city="Dallas", state="TX", type="surveillance_camera", lat=32.7350, lng=-96.7360, description="DPD Southeast Division cameras.", source="DPD records; EFF Atlas"),
            Infrastructure(name="DPD Southwest Division Surveillance", city="Dallas", state="TX", type="surveillance_camera", lat=32.7130, lng=-96.8700, description="DPD Southwest Division camera network.", source="DPD records; EFF Atlas"),
            Infrastructure(name="DPD Northwest Division Surveillance", city="Dallas", state="TX", type="surveillance_camera", lat=32.8460, lng=-96.8780, description="DPD Northwest Division cameras.", source="DPD records; EFF Atlas"),
            Infrastructure(name="DPD Northeast Division Surveillance", city="Dallas", state="TX", type="surveillance_camera", lat=32.8560, lng=-96.7310, description="DPD Northeast Division camera network.", source="DPD records; EFF Atlas"),
            Infrastructure(name="ShotSpotter — Dallas South Dallas", city="Dallas", state="TX", type="shotspotter", lat=32.7350, lng=-96.7970, description="ShotSpotter in South Dallas neighborhoods.", source="DPD records; EFF Atlas"),
            Infrastructure(name="ShotSpotter — Dallas West Dallas", city="Dallas", state="TX", type="shotspotter", lat=32.7890, lng=-96.8470, description="ShotSpotter coverage in West Dallas.", source="DPD records; EFF Atlas"),
            Infrastructure(name="ShotSpotter — Dallas Oak Cliff", city="Dallas", state="TX", type="shotspotter", lat=32.7200, lng=-96.8350, description="ShotSpotter in Oak Cliff neighborhood.", source="DPD records; EFF Atlas"),
            Infrastructure(name="ShotSpotter — Fort Worth Stop Six", city="Fort Worth", state="TX", type="shotspotter", lat=32.7250, lng=-97.2700, description="ShotSpotter in Stop Six neighborhood, Fort Worth.", source="FWPD records; EFF Atlas"),
            Infrastructure(name="ShotSpotter — Fort Worth Como", city="Fort Worth", state="TX", type="shotspotter", lat=32.7580, lng=-97.4060, description="ShotSpotter coverage in Como neighborhood.", source="FWPD records; EFF Atlas"),
            Infrastructure(name="Flock Safety LPR — Dallas North Dallas", city="Dallas", state="TX", type="flock_lpr", lat=32.8980, lng=-96.7680, description="Flock Safety LPR cameras in North Dallas.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Dallas East Dallas", city="Dallas", state="TX", type="flock_lpr", lat=32.8100, lng=-96.7050, description="Flock Safety cameras in East Dallas.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Dallas Plano suburbs", city="Plano", state="TX", type="flock_lpr", lat=33.0198, lng=-96.6989, description="Flock Safety LPR network in Plano.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Dallas Irving suburbs", city="Irving", state="TX", type="flock_lpr", lat=32.8140, lng=-96.9489, description="Flock Safety cameras in Irving.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Dallas Garland suburbs", city="Garland", state="TX", type="flock_lpr", lat=32.9126, lng=-96.6389, description="Flock Safety LPR in Garland.", source="EFF Atlas; Flock Safety contracts"),

            # ══════════════════════════════════════════════════════════════
            # NEIGHBORHOOD LEVEL — SAN ANTONIO
            # Source: SAPD records, EFF Atlas
            # ══════════════════════════════════════════════════════════════

            Infrastructure(name="SAPD Central Division Surveillance", city="San Antonio", state="TX", type="surveillance_camera", lat=29.4241, lng=-98.4936, description="SAPD Central Division cameras. Downtown San Antonio.", source="SAPD records; EFF Atlas"),
            Infrastructure(name="SAPD South Division Surveillance", city="San Antonio", state="TX", type="surveillance_camera", lat=29.3810, lng=-98.4810, description="SAPD South Division camera network.", source="SAPD records; EFF Atlas"),
            Infrastructure(name="SAPD West Division Surveillance", city="San Antonio", state="TX", type="surveillance_camera", lat=29.4240, lng=-98.5610, description="SAPD West Division cameras.", source="SAPD records; EFF Atlas"),
            Infrastructure(name="SAPD East Division Surveillance", city="San Antonio", state="TX", type="surveillance_camera", lat=29.4260, lng=-98.4260, description="SAPD East Division camera network.", source="SAPD records; EFF Atlas"),
            Infrastructure(name="ShotSpotter — San Antonio East Side", city="San Antonio", state="TX", type="shotspotter", lat=29.4260, lng=-98.4260, description="ShotSpotter on San Antonio East Side.", source="SAPD records; EFF Atlas"),
            Infrastructure(name="ShotSpotter — San Antonio South Side", city="San Antonio", state="TX", type="shotspotter", lat=29.3810, lng=-98.4810, description="ShotSpotter coverage on South Side.", source="SAPD records; EFF Atlas"),
            Infrastructure(name="ShotSpotter — San Antonio West Side", city="San Antonio", state="TX", type="shotspotter", lat=29.4240, lng=-98.5610, description="ShotSpotter on West Side neighborhoods.", source="SAPD records; EFF Atlas"),

            # ══════════════════════════════════════════════════════════════
            # NEIGHBORHOOD LEVEL — MIAMI / DADE COUNTY
            # Source: MDPD / MPD records, EFF Atlas
            # ══════════════════════════════════════════════════════════════

            Infrastructure(name="Miami PD Overtown Surveillance", city="Miami", state="FL", type="surveillance_camera", lat=25.7870, lng=-80.2050, description="MPD cameras in Overtown neighborhood.", source="MPD records; EFF Atlas"),
            Infrastructure(name="Miami PD Little Havana Surveillance", city="Miami", state="FL", type="surveillance_camera", lat=25.7690, lng=-80.2270, description="MPD camera network in Little Havana.", source="MPD records; EFF Atlas"),
            Infrastructure(name="Miami PD Liberty City Surveillance", city="Miami", state="FL", type="surveillance_camera", lat=25.8310, lng=-80.2220, description="MPD cameras in Liberty City.", source="MPD records; EFF Atlas"),
            Infrastructure(name="Miami PD Wynwood Surveillance", city="Miami", state="FL", type="surveillance_camera", lat=25.8000, lng=-80.1990, description="MPD camera network in Wynwood arts district.", source="MPD records; EFF Atlas"),
            Infrastructure(name="Miami PD Allapattah Surveillance", city="Miami", state="FL", type="surveillance_camera", lat=25.8070, lng=-80.2220, description="MPD cameras in Allapattah neighborhood.", source="MPD records; EFF Atlas"),
            Infrastructure(name="MDPD Opa-locka Surveillance", city="Opa-locka", state="FL", type="surveillance_camera", lat=25.9015, lng=-80.2497, description="MDPD cameras in Opa-locka. High surveillance density.", source="MDPD records; EFF Atlas"),
            Infrastructure(name="MDPD Hialeah Surveillance Network", city="Hialeah", state="FL", type="surveillance_camera", lat=25.8576, lng=-80.2781, description="Hialeah PD camera network. Dense Cuban-American community surveillance.", source="HPD records; EFF Atlas"),
            Infrastructure(name="ShotSpotter — Miami Liberty City", city="Miami", state="FL", type="shotspotter", lat=25.8310, lng=-80.2220, description="ShotSpotter in Liberty City.", source="MPD records; EFF Atlas"),
            Infrastructure(name="ShotSpotter — Miami Overtown", city="Miami", state="FL", type="shotspotter", lat=25.7870, lng=-80.2050, description="ShotSpotter coverage in Overtown.", source="MPD records; EFF Atlas"),
            Infrastructure(name="ShotSpotter — Miami Carol City", city="Miami Gardens", state="FL", type="shotspotter", lat=25.9420, lng=-80.2450, description="ShotSpotter in Carol City / Miami Gardens.", source="MGPD records; EFF Atlas"),
            Infrastructure(name="Flock Safety LPR — Miami Doral", city="Doral", state="FL", type="flock_lpr", lat=25.8195, lng=-80.3548, description="Flock Safety cameras in Doral.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Miami Aventura", city="Aventura", state="FL", type="flock_lpr", lat=25.9565, lng=-80.1393, description="Flock Safety LPR in Aventura.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Miami Coral Gables", city="Coral Gables", state="FL", type="flock_lpr", lat=25.7215, lng=-80.2684, description="Coral Gables PD Flock Safety cameras.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Miami South Miami", city="South Miami", state="FL", type="flock_lpr", lat=25.7076, lng=-80.2912, description="South Miami PD Flock Safety LPR.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Miami Homestead", city="Homestead", state="FL", type="flock_lpr", lat=25.4687, lng=-80.4776, description="Homestead FL PD Flock Safety cameras.", source="EFF Atlas; Flock Safety contracts"),

            # ══════════════════════════════════════════════════════════════
            # ADDITIONAL CLEARVIEW AI — SMALLER AGENCIES
            # Source: BuzzFeed News 2020 leak
            # ══════════════════════════════════════════════════════════════

            Infrastructure(name="Clearview AI — Broward County Sheriff FL", city="Fort Lauderdale", state="FL", type="clearview_ai", lat=26.1224, lng=-80.1373, description="BSO Clearview AI deployment.", source="BuzzFeed News 2020"),
            Infrastructure(name="Clearview AI — Palm Beach County Sheriff FL", city="West Palm Beach", state="FL", type="clearview_ai", lat=26.7153, lng=-80.0534, description="PBCSO Clearview AI contract.", source="BuzzFeed News 2020"),
            Infrastructure(name="Clearview AI — Orange County Sheriff FL", city="Orlando", state="FL", type="clearview_ai", lat=28.5383, lng=-81.3792, description="OCSO Clearview AI deployment.", source="BuzzFeed News 2020"),
            Infrastructure(name="Clearview AI — Pinellas County Sheriff FL", city="Clearwater", state="FL", type="clearview_ai", lat=27.9659, lng=-82.8001, description="PCSO Clearview AI use. 12 million photo database.", source="BuzzFeed News 2020; Tampa Bay Times"),
            Infrastructure(name="Clearview AI — Gwinnett County PD GA", city="Lawrenceville", state="GA", type="clearview_ai", lat=33.9526, lng=-83.9877, description="GCPD Clearview AI contract.", source="BuzzFeed News 2020"),
            Infrastructure(name="Clearview AI — DeKalb County PD GA", city="Decatur", state="GA", type="clearview_ai", lat=33.7748, lng=-84.2963, description="DKPD Clearview AI deployment.", source="BuzzFeed News 2020"),
            Infrastructure(name="Clearview AI — Maricopa County Sheriff AZ", city="Phoenix", state="AZ", type="clearview_ai", lat=33.5722, lng=-112.0892, description="MCSO Clearview AI use.", source="BuzzFeed News 2020"),
            Infrastructure(name="Clearview AI — Harris County Sheriff TX", city="Houston", state="TX", type="clearview_ai", lat=29.7604, lng=-95.3698, description="HCSO Clearview AI contract.", source="BuzzFeed News 2020"),
            Infrastructure(name="Clearview AI — Travis County Sheriff TX", city="Austin", state="TX", type="clearview_ai", lat=30.2672, lng=-97.7431, description="TCSO Clearview AI deployment.", source="BuzzFeed News 2020"),
            Infrastructure(name="Clearview AI — Bexar County Sheriff TX", city="San Antonio", state="TX", type="clearview_ai", lat=29.4241, lng=-98.4936, description="BCSO Clearview AI use.", source="BuzzFeed News 2020"),
            Infrastructure(name="Clearview AI — King County Sheriff WA", city="Seattle", state="WA", type="clearview_ai", lat=47.6062, lng=-122.3321, description="KCSD Clearview AI contract.", source="BuzzFeed News 2020"),
            Infrastructure(name="Clearview AI — Cook County Sheriff IL", city="Chicago", state="IL", type="clearview_ai", lat=41.8781, lng=-87.6298, description="CCSD Clearview AI deployment.", source="BuzzFeed News 2020"),
            Infrastructure(name="Clearview AI — Wayne County Sheriff MI", city="Detroit", state="MI", type="clearview_ai", lat=42.3314, lng=-83.0458, description="WCSD Clearview AI use.", source="BuzzFeed News 2020"),
            Infrastructure(name="Clearview AI — Cuyahoga County Sheriff OH", city="Cleveland", state="OH", type="clearview_ai", lat=41.4993, lng=-81.6944, description="CCSD Clearview AI contract.", source="BuzzFeed News 2020"),
            Infrastructure(name="Clearview AI — Hennepin County Sheriff MN", city="Minneapolis", state="MN", type="clearview_ai", lat=44.9778, lng=-93.2650, description="HCSD Clearview AI deployment.", source="BuzzFeed News 2020"),
            Infrastructure(name="Clearview AI — Multnomah County Sheriff OR", city="Portland", state="OR", type="clearview_ai", lat=45.5231, lng=-122.6765, description="MCSD Clearview AI use.", source="BuzzFeed News 2020"),
            Infrastructure(name="Clearview AI — Nassau County PD NY", city="Mineola", state="NY", type="clearview_ai", lat=40.7498, lng=-73.6381, description="NCPD Clearview AI contract.", source="BuzzFeed News 2020"),
            Infrastructure(name="Clearview AI — Suffolk County PD NY", city="Yaphank", state="NY", type="clearview_ai", lat=40.8343, lng=-72.9132, description="SCPD Clearview AI deployment.", source="BuzzFeed News 2020"),
            Infrastructure(name="Clearview AI — Westchester County PD NY", city="White Plains", state="NY", type="clearview_ai", lat=41.0340, lng=-73.7629, description="WCPD Clearview AI use.", source="BuzzFeed News 2020"),
            Infrastructure(name="Clearview AI — Broward County FL School Board Police", city="Fort Lauderdale", state="FL", type="clearview_ai", lat=26.1224, lng=-80.1373, description="School Board Police Clearview AI. Used in schools.", source="BuzzFeed News 2020"),
            Infrastructure(name="Clearview AI — Homeland Security Investigations NY", city="New York", state="NY", type="clearview_ai", lat=40.7128, lng=-74.0060, description="HSI New York Clearview AI contract.", source="BuzzFeed News 2020"),
            Infrastructure(name="Clearview AI — Customs and Border Protection Nationwide", city="Washington", state="DC", type="clearview_ai", lat=38.8977, lng=-77.0365, description="CBP nationwide Clearview AI deployment. All ports of entry.", source="BuzzFeed News 2020; GAO"),
            Infrastructure(name="Clearview AI — Pentagon Force Protection Agency", city="Arlington", state="VA", type="clearview_ai", lat=38.8719, lng=-77.0563, description="PFPA Clearview AI for Pentagon security.", source="BuzzFeed News 2020"),
            Infrastructure(name="Clearview AI — Army Criminal Investigation Command", city="Quantico", state="VA", type="clearview_ai", lat=38.5232, lng=-77.3947, description="Army CID Clearview AI contract.", source="BuzzFeed News 2020"),
            Infrastructure(name="Clearview AI — Naval Criminal Investigative Service", city="Quantico", state="VA", type="clearview_ai", lat=38.5187, lng=-77.4280, description="NCIS Clearview AI deployment.", source="BuzzFeed News 2020"),
            Infrastructure(name="Clearview AI — Air Force Office of Special Investigations", city="Andrews AFB", state="MD", type="clearview_ai", lat=38.8108, lng=-76.8666, description="AFOSI Clearview AI use.", source="BuzzFeed News 2020"),

            # ══════════════════════════════════════════════════════════════
            # ADDITIONAL PALANTIR CONTRACTS
            # Source: The Markup, government contracts, investigative journalism
            # ══════════════════════════════════════════════════════════════

            Infrastructure(name="Palantir — Maricopa County Sheriff AZ", city="Phoenix", state="AZ", type="palantir", lat=33.5722, lng=-112.0892, description="MCSO Palantir contract. Immigration and gang data.", source="The Markup; Arizona Republic"),
            Infrastructure(name="Palantir — New York State Intelligence Center", city="Albany", state="NY", type="palantir", lat=42.6526, lng=-73.7562, description="NY Fusion Center Palantir deployment.", source="The Markup; NYCLU"),
            Infrastructure(name="Palantir — ICE ERO National", city="Washington", state="DC", type="palantir", lat=38.8977, lng=-77.0365, description="ICE Enforcement and Removal Operations Palantir FALCON nationwide.", source="The Intercept; Mijente report"),
            Infrastructure(name="Palantir — CBP AMO National", city="Washington", state="DC", type="palantir", lat=38.8951, lng=-77.0364, description="CBP Air and Marine Operations Palantir deployment.", source="DHS contracts"),
            Infrastructure(name="Palantir — US Special Operations Command", city="Tampa", state="FL", type="palantir", lat=28.2275, lng=-82.5204, description="USSOCOM Palantir Gotham. Military intelligence — domestic training use documented.", source="Defense contracts; The Intercept"),
            Infrastructure(name="Palantir — National Geospatial-Intelligence Agency", city="Springfield", state="VA", type="palantir", lat=38.7697, lng=-77.1453, description="NGA Palantir deployment. Satellite and location data.", source="Defense contracts"),
            Infrastructure(name="Palantir — Drug Enforcement Administration National", city="Arlington", state="VA", type="palantir", lat=38.8799, lng=-77.1068, description="DEA Palantir DICE (Drug Intelligence Coordination Enterprise). Nationwide.", source="The Intercept; Reuters"),
            Infrastructure(name="Palantir — San Jose PD CA", city="San Jose", state="CA", type="palantir", lat=37.3382, lng=-121.8863, description="SJPD Palantir contract.", source="The Markup"),
            Infrastructure(name="Palantir — Anaheim PD CA", city="Anaheim", state="CA", type="palantir", lat=33.8366, lng=-117.9143, description="APD Palantir deployment.", source="The Markup"),
            Infrastructure(name="Palantir — Contra Costa County Sheriff CA", city="Martinez", state="CA", type="palantir", lat=37.9935, lng=-122.1341, description="CCSD Palantir contract.", source="The Markup"),
            Infrastructure(name="Palantir — Nashville Metro PD TN", city="Nashville", state="TN", type="palantir", lat=36.1627, lng=-86.7816, description="MNPD Palantir deployment.", source="The Markup"),
            Infrastructure(name="Palantir — Cincinnati PD OH", city="Cincinnati", state="OH", type="palantir", lat=39.1031, lng=-84.5120, description="CPD Palantir contract.", source="The Markup"),
            Infrastructure(name="Palantir — Albuquerque PD NM", city="Albuquerque", state="NM", type="palantir", lat=35.0844, lng=-106.6504, description="APD Palantir deployment.", source="The Markup"),
            Infrastructure(name="Palantir — Sacramento PD CA", city="Sacramento", state="CA", type="palantir", lat=38.5816, lng=-121.4944, description="SPD Palantir contract.", source="The Markup"),

            # ══════════════════════════════════════════════════════════════
            # ADDITIONAL PREDICTIVE POLICING
            # Source: EFF Atlas, The Markup, city contracts
            # ══════════════════════════════════════════════════════════════

            Infrastructure(name="PredPol/Geolitica — Long Beach PD CA", city="Long Beach", state="CA", type="predictive_policing", lat=33.7701, lng=-118.1937, description="Long Beach PD PredPol contract.", source="The Markup; EFF Atlas"),
            Infrastructure(name="PredPol/Geolitica — Norcross GA PD", city="Norcross", state="GA", type="predictive_policing", lat=33.9412, lng=-84.2135, description="Norcross GA PD PredPol deployment.", source="The Markup; EFF Atlas"),
            Infrastructure(name="ShotSpotter Respond Predictive — Fort Wayne IN", city="Fort Wayne", state="IN", type="predictive_policing", lat=41.1306, lng=-85.1289, description="Fort Wayne PD ShotSpotter Respond predictive analytics.", source="EFF Atlas"),
            Infrastructure(name="Axon AI Predictive — Tampa PD FL", city="Tampa", state="FL", type="predictive_policing", lat=27.9506, lng=-82.4572, description="Tampa PD Axon AI predictive tools.", source="EFF Atlas"),
            Infrastructure(name="Motorola CommandCentral Predictive — Memphis PD TN", city="Memphis", state="TN", type="predictive_policing", lat=35.1495, lng=-90.0490, description="MPD Motorola CommandCentral predictive policing.", source="EFF Atlas"),
            Infrastructure(name="Vigilant Solutions Predictive — Houston PD TX", city="Houston", state="TX", type="predictive_policing", lat=29.7604, lng=-95.3698, description="HPD Vigilant Solutions predictive LPR analytics.", source="EFF Atlas"),
            Infrastructure(name="PredPol/Geolitica — Burbank PD CA", city="Burbank", state="CA", type="predictive_policing", lat=34.1808, lng=-118.3090, description="Burbank PD PredPol contract.", source="The Markup; EFF Atlas"),
            Infrastructure(name="PredPol/Geolitica — Glendale PD CA", city="Glendale", state="CA", type="predictive_policing", lat=34.1425, lng=-118.2551, description="Glendale CA PD PredPol deployment.", source="The Markup; EFF Atlas"),
            Infrastructure(name="PredPol/Geolitica — Pasadena PD CA", city="Pasadena", state="CA", type="predictive_policing", lat=34.1478, lng=-118.1445, description="Pasadena PD PredPol contract.", source="The Markup; EFF Atlas"),
            Infrastructure(name="IBM i2 Predictive — Chicago PD IL", city="Chicago", state="IL", type="predictive_policing", lat=41.8781, lng=-87.6298, description="CPD IBM i2 Analyst's Notebook predictive pattern analysis.", source="EFF Atlas; The Intercept"),
            Infrastructure(name="SAS Predictive Analytics — Shreveport PD LA", city="Shreveport", state="LA", type="predictive_policing", lat=32.5252, lng=-93.7502, description="Shreveport PD SAS predictive policing platform.", source="EFF Atlas"),
            Infrastructure(name="Wynyard Group Analytics — New Zealand/US — Kansas City", city="Kansas City", state="MO", type="predictive_policing", lat=39.0997, lng=-94.5786, description="KCPD Wynyard crime analytics deployment.", source="EFF Atlas"),
            Infrastructure(name="Axon AI Predictive — San Antonio PD TX", city="San Antonio", state="TX", type="predictive_policing", lat=29.4241, lng=-98.4936, description="SAPD Axon AI predictive tools.", source="EFF Atlas"),
            Infrastructure(name="Motorola CommandCentral Predictive — Detroit PD MI", city="Detroit", state="MI", type="predictive_policing", lat=42.3314, lng=-83.0458, description="DPD Motorola predictive policing platform.", source="EFF Atlas"),

            # ══════════════════════════════════════════════════════════════
            # VIGILANT SOLUTIONS — ADDITIONAL AGENCIES
            # Source: EFF Atlas, Motorola contracts, FOIA
            # ══════════════════════════════════════════════════════════════

            Infrastructure(name="Vigilant Solutions LEARN — Broward County Sheriff FL", city="Fort Lauderdale", state="FL", type="vigilant_lpr", lat=26.1224, lng=-80.1373, description="BSO Vigilant Solutions LPR network.", source="EFF Atlas; Motorola contracts"),
            Infrastructure(name="Vigilant Solutions LEARN — Palm Beach County Sheriff FL", city="West Palm Beach", state="FL", type="vigilant_lpr", lat=26.7153, lng=-80.0534, description="PBCSO Vigilant Solutions deployment.", source="EFF Atlas"),
            Infrastructure(name="Vigilant Solutions LEARN — Orange County Sheriff FL", city="Orlando", state="FL", type="vigilant_lpr", lat=28.5383, lng=-81.3792, description="OCSO Vigilant Solutions LPR.", source="EFF Atlas; Motorola contracts"),
            Infrastructure(name="Vigilant Solutions LEARN — Maricopa County Sheriff AZ", city="Phoenix", state="AZ", type="vigilant_lpr", lat=33.5722, lng=-112.0892, description="MCSO Vigilant Solutions network.", source="EFF Atlas"),
            Infrastructure(name="Vigilant Solutions LEARN — Harris County Sheriff TX", city="Houston", state="TX", type="vigilant_lpr", lat=29.7604, lng=-95.3698, description="HCSO Vigilant Solutions LPR.", source="EFF Atlas; Motorola contracts"),
            Infrastructure(name="Vigilant Solutions LEARN — Cook County Sheriff IL", city="Chicago", state="IL", type="vigilant_lpr", lat=41.8781, lng=-87.6298, description="CCSD Vigilant Solutions deployment.", source="EFF Atlas"),
            Infrastructure(name="Vigilant Solutions LEARN — King County Sheriff WA", city="Seattle", state="WA", type="vigilant_lpr", lat=47.6062, lng=-122.3321, description="KCSD Vigilant Solutions LPR.", source="EFF Atlas; Motorola contracts"),
            Infrastructure(name="Vigilant Solutions LEARN — Hennepin County Sheriff MN", city="Minneapolis", state="MN", type="vigilant_lpr", lat=44.9778, lng=-93.2650, description="HCSD Vigilant Solutions network.", source="EFF Atlas"),
            Infrastructure(name="Vigilant Solutions LEARN — Gwinnett County PD GA", city="Lawrenceville", state="GA", type="vigilant_lpr", lat=33.9526, lng=-83.9877, description="GCPD Vigilant Solutions LPR.", source="EFF Atlas; Motorola contracts"),
            Infrastructure(name="Vigilant Solutions LEARN — Cuyahoga County Sheriff OH", city="Cleveland", state="OH", type="vigilant_lpr", lat=41.4993, lng=-81.6944, description="CCSD Vigilant Solutions deployment.", source="EFF Atlas"),
            Infrastructure(name="Vigilant Solutions LEARN — Nassau County PD NY", city="Mineola", state="NY", type="vigilant_lpr", lat=40.7498, lng=-73.6381, description="NCPD Vigilant Solutions LPR.", source="EFF Atlas; Motorola contracts"),
            Infrastructure(name="Vigilant Solutions LEARN — Suffolk County PD NY", city="Yaphank", state="NY", type="vigilant_lpr", lat=40.8343, lng=-72.9132, description="SCPD Vigilant Solutions network.", source="EFF Atlas"),
            Infrastructure(name="Vigilant Solutions LEARN — Contra Costa County CA", city="Martinez", state="CA", type="vigilant_lpr", lat=37.9935, lng=-122.1341, description="Contra Costa County Vigilant Solutions LPR.", source="EFF Atlas; Motorola contracts"),
            Infrastructure(name="Vigilant Solutions LEARN — San Mateo County CA", city="Redwood City", state="CA", type="vigilant_lpr", lat=37.4852, lng=-122.2364, description="San Mateo County Vigilant Solutions deployment.", source="EFF Atlas"),
            Infrastructure(name="Vigilant Solutions LEARN — Santa Clara County CA", city="San Jose", state="CA", type="vigilant_lpr", lat=37.3382, lng=-121.8863, description="Santa Clara County Vigilant Solutions LPR.", source="EFF Atlas; Motorola contracts"),
            Infrastructure(name="Vigilant Solutions LEARN — Ventura County Sheriff CA", city="Ventura", state="CA", type="vigilant_lpr", lat=34.2747, lng=-119.2290, description="VCSD Vigilant Solutions network.", source="EFF Atlas"),
            Infrastructure(name="Vigilant Solutions LEARN — Fresno County Sheriff CA", city="Fresno", state="CA", type="vigilant_lpr", lat=36.7378, lng=-119.7871, description="Fresno County Sheriff Vigilant Solutions LPR.", source="EFF Atlas; Motorola contracts"),
            Infrastructure(name="Vigilant Solutions LEARN — Kern County Sheriff CA", city="Bakersfield", state="CA", type="vigilant_lpr", lat=35.3733, lng=-119.0187, description="Kern County Sheriff Vigilant Solutions deployment.", source="EFF Atlas"),
            Infrastructure(name="Vigilant Solutions LEARN — Wayne County Sheriff MI", city="Detroit", state="MI", type="vigilant_lpr", lat=42.3314, lng=-83.0458, description="WCSD Vigilant Solutions LPR.", source="EFF Atlas; Motorola contracts"),
            Infrastructure(name="Vigilant Solutions LEARN — Broward County FL School District PD", city="Fort Lauderdale", state="FL", type="vigilant_lpr", lat=26.1224, lng=-80.1373, description="Broward School District PD Vigilant Solutions. Used near schools.", source="EFF Atlas"),

            # ══════════════════════════════════════════════════════════════
            # NEIGHBORHOOD LEVEL — MINNEAPOLIS / ST. PAUL
            # Source: MPD records, Star Tribune, EFF Atlas
            # ══════════════════════════════════════════════════════════════

            Infrastructure(name="MPD 1st Precinct Surveillance — Downtown Minneapolis", city="Minneapolis", state="MN", type="surveillance_camera", lat=44.9778, lng=-93.2650, description="MPD 1st Precinct cameras. Downtown Minneapolis.", source="MPD records; Star Tribune"),
            Infrastructure(name="MPD 3rd Precinct Surveillance — South Minneapolis", city="Minneapolis", state="MN", type="surveillance_camera", lat=44.9380, lng=-93.2490, description="MPD 3rd Precinct cameras. South Minneapolis. George Floyd Square in coverage area.", source="MPD records; Star Tribune"),
            Infrastructure(name="MPD 4th Precinct Surveillance — North Minneapolis", city="Minneapolis", state="MN", type="surveillance_camera", lat=44.9990, lng=-93.3020, description="MPD 4th Precinct camera network. North Minneapolis.", source="MPD records; Star Tribune"),
            Infrastructure(name="MPD 5th Precinct Surveillance — Southwest Minneapolis", city="Minneapolis", state="MN", type="surveillance_camera", lat=44.9270, lng=-93.3130, description="MPD 5th Precinct cameras. Southwest Minneapolis.", source="MPD records; Star Tribune"),
            Infrastructure(name="ShotSpotter — Minneapolis North Side", city="Minneapolis", state="MN", type="shotspotter", lat=44.9990, lng=-93.3020, description="ShotSpotter coverage on Minneapolis North Side.", source="MPD records; Star Tribune"),
            Infrastructure(name="ShotSpotter — Minneapolis South Side", city="Minneapolis", state="MN", type="shotspotter", lat=44.9380, lng=-93.2490, description="ShotSpotter in South Minneapolis neighborhoods.", source="MPD records; Star Tribune"),
            Infrastructure(name="ShotSpotter — Minneapolis Near North", city="Minneapolis", state="MN", type="shotspotter", lat=44.9870, lng=-93.2890, description="ShotSpotter in Near North neighborhood.", source="MPD records; Star Tribune"),
            Infrastructure(name="SPPD Eastern District Surveillance", city="St. Paul", state="MN", type="surveillance_camera", lat=44.9537, lng=-93.0380, description="St. Paul PD Eastern District cameras.", source="SPPD records; EFF Atlas"),
            Infrastructure(name="SPPD Western District Surveillance", city="St. Paul", state="MN", type="surveillance_camera", lat=44.9537, lng=-93.1400, description="St. Paul PD Western District camera network.", source="SPPD records; EFF Atlas"),
            Infrastructure(name="ShotSpotter — St. Paul Frogtown", city="St. Paul", state="MN", type="shotspotter", lat=44.9570, lng=-93.1300, description="ShotSpotter in Frogtown neighborhood, St. Paul.", source="SPPD records; EFF Atlas"),
            Infrastructure(name="ShotSpotter — St. Paul East Side", city="St. Paul", state="MN", type="shotspotter", lat=44.9450, lng=-93.0380, description="ShotSpotter coverage on St. Paul East Side.", source="SPPD records; EFF Atlas"),

            # ══════════════════════════════════════════════════════════════
            # NEIGHBORHOOD LEVEL — CLEVELAND / COLUMBUS / CINCINNATI
            # Source: PD records, EFF Atlas
            # ══════════════════════════════════════════════════════════════

            Infrastructure(name="Cleveland PD 1st District Surveillance", city="Cleveland", state="OH", type="surveillance_camera", lat=41.4993, lng=-81.6944, description="Cleveland PD 1st District cameras. Downtown.", source="CPD records; EFF Atlas"),
            Infrastructure(name="Cleveland PD 2nd District Surveillance — West Side", city="Cleveland", state="OH", type="surveillance_camera", lat=41.4820, lng=-81.7420, description="Cleveland PD 2nd District cameras. West Side.", source="CPD records; EFF Atlas"),
            Infrastructure(name="Cleveland PD 3rd District Surveillance — East Side", city="Cleveland", state="OH", type="surveillance_camera", lat=41.4960, lng=-81.6380, description="Cleveland PD 3rd District camera network. East Side.", source="CPD records; EFF Atlas"),
            Infrastructure(name="Cleveland PD 4th District Surveillance — East Cleveland", city="Cleveland", state="OH", type="surveillance_camera", lat=41.5230, lng=-81.5990, description="Cleveland PD 4th District cameras.", source="CPD records; EFF Atlas"),
            Infrastructure(name="Cleveland PD 5th District Surveillance — Far East", city="Cleveland", state="OH", type="surveillance_camera", lat=41.5140, lng=-81.5690, description="Cleveland PD 5th District camera network.", source="CPD records; EFF Atlas"),
            Infrastructure(name="ShotSpotter — Cleveland Central", city="Cleveland", state="OH", type="shotspotter", lat=41.4993, lng=-81.6944, description="ShotSpotter in Central Cleveland.", source="CPD records; EFF Atlas"),
            Infrastructure(name="ShotSpotter — Cleveland East Side", city="Cleveland", state="OH", type="shotspotter", lat=41.4960, lng=-81.6380, description="ShotSpotter on Cleveland East Side.", source="CPD records; EFF Atlas"),
            Infrastructure(name="ShotSpotter — Cleveland Glenville", city="Cleveland", state="OH", type="shotspotter", lat=41.5360, lng=-81.6280, description="ShotSpotter in Glenville neighborhood.", source="CPD records; EFF Atlas"),
            Infrastructure(name="Columbus PD Zone 1 Surveillance — Downtown", city="Columbus", state="OH", type="surveillance_camera", lat=39.9612, lng=-82.9988, description="Columbus PD Zone 1 cameras. Downtown Columbus.", source="CPD records; EFF Atlas"),
            Infrastructure(name="Columbus PD Zone 2 Surveillance — South Columbus", city="Columbus", state="OH", type="surveillance_camera", lat=39.9260, lng=-82.9990, description="Columbus PD Zone 2 camera network.", source="CPD records; EFF Atlas"),
            Infrastructure(name="Columbus PD Zone 3 Surveillance — East Columbus", city="Columbus", state="OH", type="surveillance_camera", lat=39.9640, lng=-82.9430, description="Columbus PD Zone 3 cameras.", source="CPD records; EFF Atlas"),
            Infrastructure(name="ShotSpotter — Columbus Near East Side", city="Columbus", state="OH", type="shotspotter", lat=39.9640, lng=-82.9430, description="ShotSpotter on Columbus Near East Side.", source="CPD records; EFF Atlas"),
            Infrastructure(name="ShotSpotter — Columbus South Side", city="Columbus", state="OH", type="shotspotter", lat=39.9260, lng=-82.9990, description="ShotSpotter on Columbus South Side.", source="CPD records; EFF Atlas"),
            Infrastructure(name="Cincinnati PD District 1 Surveillance — Downtown", city="Cincinnati", state="OH", type="surveillance_camera", lat=39.1031, lng=-84.5120, description="Cincinnati PD District 1 cameras. Downtown.", source="CPD records; EFF Atlas"),
            Infrastructure(name="Cincinnati PD District 3 Surveillance — West End", city="Cincinnati", state="OH", type="surveillance_camera", lat=39.1100, lng=-84.5350, description="Cincinnati PD District 3 camera network. West End.", source="CPD records; EFF Atlas"),
            Infrastructure(name="Cincinnati PD District 5 Surveillance — Avondale", city="Cincinnati", state="OH", type="surveillance_camera", lat=39.1320, lng=-84.4890, description="Cincinnati PD District 5 cameras. Avondale neighborhood.", source="CPD records; EFF Atlas"),
            Infrastructure(name="ShotSpotter — Cincinnati Over-the-Rhine", city="Cincinnati", state="OH", type="shotspotter", lat=39.1110, lng=-84.5170, description="ShotSpotter in Over-the-Rhine neighborhood.", source="CPD records; EFF Atlas"),
            Infrastructure(name="ShotSpotter — Cincinnati West End", city="Cincinnati", state="OH", type="shotspotter", lat=39.1100, lng=-84.5350, description="ShotSpotter in West End Cincinnati.", source="CPD records; EFF Atlas"),
            Infrastructure(name="ShotSpotter — Cincinnati Avondale", city="Cincinnati", state="OH", type="shotspotter", lat=39.1320, lng=-84.4890, description="ShotSpotter in Avondale neighborhood.", source="CPD records; EFF Atlas"),

            # ══════════════════════════════════════════════════════════════
            # NEIGHBORHOOD LEVEL — KANSAS CITY / ST. LOUIS
            # Source: PD records, EFF Atlas
            # ══════════════════════════════════════════════════════════════

            Infrastructure(name="KCPD Central Patrol Division Surveillance", city="Kansas City", state="MO", type="surveillance_camera", lat=39.0997, lng=-94.5786, description="KCPD Central Patrol cameras. Downtown KC.", source="KCPD records; EFF Atlas"),
            Infrastructure(name="KCPD South Patrol Division Surveillance", city="Kansas City", state="MO", type="surveillance_camera", lat=39.0460, lng=-94.5710, description="KCPD South Patrol camera network.", source="KCPD records; EFF Atlas"),
            Infrastructure(name="KCPD East Patrol Division Surveillance", city="Kansas City", state="MO", type="surveillance_camera", lat=39.0970, lng=-94.5090, description="KCPD East Patrol cameras.", source="KCPD records; EFF Atlas"),
            Infrastructure(name="KCPD North Patrol Division Surveillance", city="Kansas City", state="MO", type="surveillance_camera", lat=39.1530, lng=-94.5760, description="KCPD North Patrol camera network.", source="KCPD records; EFF Atlas"),
            Infrastructure(name="ShotSpotter — Kansas City East Side", city="Kansas City", state="MO", type="shotspotter", lat=39.0970, lng=-94.5090, description="ShotSpotter on Kansas City East Side.", source="KCPD records; EFF Atlas"),
            Infrastructure(name="ShotSpotter — Kansas City Northeast", city="Kansas City", state="MO", type="shotspotter", lat=39.1180, lng=-94.5390, description="ShotSpotter in Kansas City Northeast.", source="KCPD records; EFF Atlas"),
            Infrastructure(name="ShotSpotter — Kansas City Eastside Linwood", city="Kansas City", state="MO", type="shotspotter", lat=39.0880, lng=-94.5370, description="ShotSpotter in Linwood area, Kansas City.", source="KCPD records; EFF Atlas"),
            Infrastructure(name="SLMPD 1st District Surveillance — Downtown St. Louis", city="St. Louis", state="MO", type="surveillance_camera", lat=38.6270, lng=-90.1994, description="SLMPD 1st District cameras. Downtown St. Louis.", source="SLMPD records; EFF Atlas"),
            Infrastructure(name="SLMPD 3rd District Surveillance — Cherokee", city="St. Louis", state="MO", type="surveillance_camera", lat=38.6020, lng=-90.2260, description="SLMPD 3rd District camera network. Cherokee Street area.", source="SLMPD records; EFF Atlas"),
            Infrastructure(name="SLMPD 4th District Surveillance — North St. Louis", city="St. Louis", state="MO", type="surveillance_camera", lat=38.6590, lng=-90.2130, description="SLMPD 4th District cameras. North St. Louis.", source="SLMPD records; EFF Atlas"),
            Infrastructure(name="SLMPD 5th District Surveillance — Gravois Park", city="St. Louis", state="MO", type="surveillance_camera", lat=38.6100, lng=-90.2360, description="SLMPD 5th District camera network.", source="SLMPD records; EFF Atlas"),
            Infrastructure(name="SLMPD 6th District Surveillance — Carondelet", city="St. Louis", state="MO", type="surveillance_camera", lat=38.5760, lng=-90.2380, description="SLMPD 6th District cameras. Carondelet neighborhood.", source="SLMPD records; EFF Atlas"),
            Infrastructure(name="ShotSpotter — St. Louis Walnut Park", city="St. Louis", state="MO", type="shotspotter", lat=38.6700, lng=-90.2390, description="ShotSpotter in Walnut Park neighborhood.", source="SLMPD records; EFF Atlas"),
            Infrastructure(name="ShotSpotter — St. Louis Wells-Goodfellow", city="St. Louis", state="MO", type="shotspotter", lat=38.6540, lng=-90.2620, description="ShotSpotter in Wells-Goodfellow area.", source="SLMPD records; EFF Atlas"),
            Infrastructure(name="ShotSpotter — St. Louis Dutchtown", city="St. Louis", state="MO", type="shotspotter", lat=38.5930, lng=-90.2350, description="ShotSpotter in Dutchtown neighborhood.", source="SLMPD records; EFF Atlas"),
            Infrastructure(name="ShotSpotter — St. Louis O'Fallon Park", city="St. Louis", state="MO", type="shotspotter", lat=38.6640, lng=-90.1990, description="ShotSpotter in O'Fallon Park area.", source="SLMPD records; EFF Atlas"),

            # ══════════════════════════════════════════════════════════════
            # ADDITIONAL BORDER SURVEILLANCE — INTERIOR CHECKPOINTS
            # Source: CBP public records, ACLU
            # ══════════════════════════════════════════════════════════════

            Infrastructure(name="CBP Interior Checkpoint — I-19 Arizona", city="Tubac", state="AZ", type="border_surveillance", lat=31.6891, lng=-111.0485, description="CBP permanent interior checkpoint on I-19. 25 miles north of border. All vehicles stopped.", source="CBP public records; ACLU"),
            Infrastructure(name="CBP Interior Checkpoint — I-8 California", city="Pine Valley", state="CA", type="border_surveillance", lat=32.8282, lng=-116.5279, description="CBP permanent interior checkpoint on I-8. East San Diego County.", source="CBP public records; ACLU"),
            Infrastructure(name="CBP Interior Checkpoint — Highway 77 Arizona", city="Three Points", state="AZ", type="border_surveillance", lat=32.0418, lng=-111.3415, description="CBP checkpoint on Highway 77. Tucson sector.", source="CBP public records"),
            Infrastructure(name="CBP Interior Checkpoint — I-10 New Mexico", city="Las Cruces", state="NM", type="border_surveillance", lat=32.3199, lng=-106.7637, description="CBP permanent interior checkpoint on I-10. New Mexico.", source="CBP public records; ACLU"),
            Infrastructure(name="CBP Interior Checkpoint — Highway 90 Texas", city="Marfa", state="TX", type="border_surveillance", lat=30.3088, lng=-104.0202, description="CBP checkpoint on Highway 90. West Texas Big Bend sector.", source="CBP public records"),
            Infrastructure(name="CBP Interior Checkpoint — Highway 281 Texas", city="Falfurrias", state="TX", type="border_surveillance", lat=27.2256, lng=-98.1431, description="CBP checkpoint on Highway 281. Brooks County TX. Busiest inland checkpoint nationally.", source="CBP public records; Texas Tribune"),
            Infrastructure(name="CBP Interior Checkpoint — Highway 385 Texas", city="Uvalde", state="TX", type="border_surveillance", lat=29.2097, lng=-99.7862, description="CBP checkpoint on Highway 385. Southwest Texas.", source="CBP public records"),
            Infrastructure(name="CBP Interior Checkpoint — I-35 Texas", city="Laredo", state="TX", type="border_surveillance", lat=27.7163, lng=-99.5075, description="CBP checkpoint on I-35 north of Laredo.", source="CBP public records; ACLU"),
            Infrastructure(name="CBP Marine Vessel Surveillance — Rio Grande Valley", city="McAllen", state="TX", type="border_surveillance", lat=26.1500, lng=-97.9900, description="CBP marine vessel surveillance on Rio Grande. Camera and sensor arrays.", source="CBP public records"),
            Infrastructure(name="CBP Marine Vessel Surveillance — San Diego Bay", city="San Diego", state="CA", type="border_surveillance", lat=32.7157, lng=-117.1611, description="CBP marine surveillance in San Diego Bay.", source="CBP public records"),
            Infrastructure(name="CBP Remote Video Surveillance — Big Bend TX", city="Presidio", state="TX", type="border_surveillance", lat=29.5608, lng=-104.3677, description="CBP RVSS towers in Big Bend sector. Remote desert surveillance.", source="CBP public records"),
            Infrastructure(name="CBP Remote Video Surveillance — Ajo AZ", city="Ajo", state="AZ", type="border_surveillance", lat=32.3718, lng=-112.8610, description="CBP RVSS towers in Ajo corridor. Arizona Sonoran Desert.", source="CBP public records"),
            Infrastructure(name="CBP Remote Video Surveillance — Lajas Puerto Rico", city="Lajas", state="PR", type="border_surveillance", lat=17.9942, lng=-67.0597, description="CBP surveillance towers in southwest Puerto Rico coastal zone.", source="CBP public records"),
            Infrastructure(name="CBP Integrated Fixed Tower — Sasabe AZ", city="Sasabe", state="AZ", type="border_surveillance", lat=31.4752, lng=-111.5415, description="CBP IFT Elbit Systems tower. Sasabe corridor. AI detection.", source="CBP contracts; GAO reports"),
            Infrastructure(name="CBP Integrated Fixed Tower — Lukeville AZ", city="Lukeville", state="AZ", type="border_surveillance", lat=31.8885, lng=-112.8192, description="CBP IFT tower. Lukeville port of entry corridor.", source="CBP contracts"),

            # ══════════════════════════════════════════════════════════════
            # ADDITIONAL ICE FACILITIES
            # Source: ICE.gov, Freedom for Immigrants, TRAC
            # ══════════════════════════════════════════════════════════════

            Infrastructure(name="ICE Processing Center — Prairieland Detention TX", city="Alvarado", state="TX", type="ice_facility", lat=32.4068, lng=-97.2139, description="LaSalle Corrections. Texas ICE facility.", source="ICE.gov; Freedom for Immigrants"),
            Infrastructure(name="ICE Processing Center — Limestone County TX", city="Mexia", state="TX", type="ice_facility", lat=31.6796, lng=-96.4822, description="LaSalle Corrections. Central Texas ICE detention.", source="ICE.gov"),
            Infrastructure(name="ICE Processing Center — Houston Contract Detention", city="Houston", state="TX", type="ice_facility", lat=29.6600, lng=-95.2790, description="GEO Group. Houston area ICE processing.", source="ICE.gov"),
            Infrastructure(name="ICE Processing Center — Montgomery County TX", city="Conroe", state="TX", type="ice_facility", lat=30.3119, lng=-95.4560, description="Montgomery County contract detention.", source="ICE.gov"),
            Infrastructure(name="ICE Processing Center — Joe Corley TX", city="Conroe", state="TX", type="ice_facility", lat=30.3280, lng=-95.4680, description="GEO Group Joe Corley Detention. Texas ICE facility.", source="ICE.gov"),
            Infrastructure(name="ICE Processing Center — Jackson Parish LA", city="Jonesboro", state="LA", type="ice_facility", lat=32.2446, lng=-92.7143, description="LaSalle Corrections. Louisiana ICE detention.", source="ICE.gov"),
            Infrastructure(name="ICE Processing Center — LaSalle ICE Processing Center LA", city="Jena", state="LA", type="ice_facility", lat=31.6835, lng=-92.1307, description="LaSalle Corrections. Central Louisiana.", source="ICE.gov"),
            Infrastructure(name="ICE Processing Center — River Correctional LA", city="Ferriday", state="LA", type="ice_facility", lat=31.6329, lng=-91.5551, description="LaSalle Corrections. Louisiana ICE contract.", source="ICE.gov"),
            Infrastructure(name="ICE Processing Center — Tensas Parish LA", city="Waterproof", state="LA", type="ice_facility", lat=31.8060, lng=-91.3876, description="LaSalle Corrections. Remote Louisiana ICE facility.", source="ICE.gov"),
            Infrastructure(name="ICE Processing Center — Baker County FL", city="MacClenny", state="FL", type="ice_facility", lat=30.2783, lng=-82.1279, description="Baker County contract detention. Florida.", source="ICE.gov"),
            Infrastructure(name="ICE Processing Center — Clay County FL", city="Fleming Island", state="FL", type="ice_facility", lat=30.0896, lng=-81.7140, description="Clay County jail ICE contract.", source="ICE.gov"),
            Infrastructure(name="ICE Processing Center — Geo Aurora CO", city="Aurora", state="CO", type="ice_facility", lat=39.6930, lng=-104.7024, description="GEO Group. Colorado ICE detention. Previously sued over labor practices.", source="ICE.gov; ACLU Colorado"),
            Infrastructure(name="ICE Processing Center — Henderson Detention NV", city="Henderson", state="NV", type="ice_facility", lat=36.0395, lng=-114.9817, description="Nevada ICE contract detention.", source="ICE.gov"),
            Infrastructure(name="ICE Processing Center — Nye County NV", city="Pahrump", state="NV", type="ice_facility", lat=36.2083, lng=-115.9845, description="Nye County jail ICE contract.", source="ICE.gov"),
            Infrastructure(name="ICE Processing Center — Tacoma Northwest WA", city="Tacoma", state="WA", type="ice_facility", lat=47.2340, lng=-122.4680, description="GEO Group. Northwest ICE Processing. Primary Pacific NW detention hub.", source="ICE.gov; La Resistencia"),
            Infrastructure(name="ICE Processing Center — Northwest Detention Expansion WA", city="Tacoma", state="WA", type="ice_facility", lat=47.2360, lng=-122.4660, description="GEO Group expansion facility adjacent to main Tacoma center.", source="ICE.gov"),
            Infrastructure(name="ICE Processing Center — Richland County SC", city="Columbia", state="SC", type="ice_facility", lat=34.0007, lng=-81.0348, description="Richland County jail ICE contract. South Carolina.", source="ICE.gov"),
            Infrastructure(name="ICE Processing Center — Stewart County TN", city="Dover", state="TN", type="ice_facility", lat=36.4885, lng=-87.8389, description="Stewart County jail ICE contract.", source="ICE.gov"),
            Infrastructure(name="ICE Processing Center — Boone County KY", city="Burlington", state="KY", type="ice_facility", lat=38.9881, lng=-84.7319, description="Boone County jail ICE contract. Northern Kentucky.", source="ICE.gov"),
            Infrastructure(name="ICE Processing Center — Geauga County OH", city="Chardon", state="OH", type="ice_facility", lat=41.5803, lng=-81.2020, description="Geauga County jail ICE contract.", source="ICE.gov"),
            Infrastructure(name="ICE Processing Center — Seneca County OH", city="Tiffin", state="OH", type="ice_facility", lat=41.1145, lng=-83.1779, description="Seneca County jail ICE contract.", source="ICE.gov"),
            Infrastructure(name="ICE Processing Center — Morrow County OH", city="Mount Gilead", state="OH", type="ice_facility", lat=40.5487, lng=-82.8249, description="Morrow County jail ICE contract.", source="ICE.gov"),

            # ══════════════════════════════════════════════════════════════
            # ADDITIONAL FUSION CENTERS — SATELLITE OFFICES
            # Source: DHS, state records
            # ══════════════════════════════════════════════════════════════

            Infrastructure(name="Texas Fusion Center — Houston Regional", city="Houston", state="TX", type="fusion_center", lat=29.7604, lng=-95.3698, description="Texas DPS regional fusion center. Gulf Coast operations.", source="DHS; Texas DPS"),
            Infrastructure(name="Texas Fusion Center — San Antonio Regional", city="San Antonio", state="TX", type="fusion_center", lat=29.4241, lng=-98.4936, description="Texas DPS San Antonio regional fusion node.", source="DHS; Texas DPS"),
            Infrastructure(name="Texas Fusion Center — El Paso Regional", city="El Paso", state="TX", type="fusion_center", lat=31.7619, lng=-106.4850, description="Texas DPS El Paso regional fusion center. Border operations.", source="DHS; Texas DPS"),
            Infrastructure(name="Texas Fusion Center — Lubbock Regional", city="Lubbock", state="TX", type="fusion_center", lat=33.5779, lng=-101.8552, description="Texas DPS Lubbock regional fusion node.", source="DHS; Texas DPS"),
            Infrastructure(name="Texas Fusion Center — Waco Regional", city="Waco", state="TX", type="fusion_center", lat=31.5493, lng=-97.1467, description="Texas DPS Waco regional fusion center.", source="DHS; Texas DPS"),
            Infrastructure(name="Texas Fusion Center — McAllen Regional", city="McAllen", state="TX", type="fusion_center", lat=26.2034, lng=-98.2300, description="Texas DPS McAllen regional. High border crossing area.", source="DHS; Texas DPS"),
            Infrastructure(name="Texas Fusion Center — Laredo Regional", city="Laredo", state="TX", type="fusion_center", lat=27.5306, lng=-99.4803, description="Texas DPS Laredo regional fusion node. Border operations.", source="DHS; Texas DPS"),
            Infrastructure(name="Florida Fusion Center — Miami Regional", city="Miami", state="FL", type="fusion_center", lat=25.7617, lng=-80.1918, description="FDLE Miami regional fusion center.", source="DHS; FDLE"),
            Infrastructure(name="Florida Fusion Center — Tampa Regional", city="Tampa", state="FL", type="fusion_center", lat=27.9506, lng=-82.4572, description="FDLE Tampa Bay regional fusion node.", source="DHS; FDLE"),
            Infrastructure(name="Florida Fusion Center — Orlando Regional", city="Orlando", state="FL", type="fusion_center", lat=28.5383, lng=-81.3792, description="FDLE Orlando regional fusion center.", source="DHS; FDLE"),
            Infrastructure(name="Florida Fusion Center — Jacksonville Regional", city="Jacksonville", state="FL", type="fusion_center", lat=30.3322, lng=-81.6557, description="FDLE Jacksonville regional fusion node.", source="DHS; FDLE"),
            Infrastructure(name="California Fusion Center — Los Angeles Regional", city="Los Angeles", state="CA", type="fusion_center", lat=34.0522, lng=-118.2437, description="JRIC Los Angeles regional fusion center.", source="DHS; California OES"),
            Infrastructure(name="California Fusion Center — San Diego Regional", city="San Diego", state="CA", type="fusion_center", lat=32.7157, lng=-117.1611, description="San Diego LECC regional fusion center. Border proximity.", source="DHS; California OES"),
            Infrastructure(name="California Fusion Center — Bay Area Regional", city="Oakland", state="CA", type="fusion_center", lat=37.8044, lng=-122.2711, description="Bay Area UASI fusion node. Multi-agency.", source="DHS; California OES"),
            Infrastructure(name="California Fusion Center — Fresno Regional", city="Fresno", state="CA", type="fusion_center", lat=36.7378, lng=-119.7871, description="Central California fusion node.", source="DHS; California OES"),
            Infrastructure(name="New York Fusion Center — NYC Regional", city="New York", state="NY", type="fusion_center", lat=40.7128, lng=-74.0060, description="NYPD Intelligence Bureau fusion node. Feeds into NYSIC.", source="DHS; NYPD"),
            Infrastructure(name="New York Fusion Center — Buffalo Regional", city="Buffalo", state="NY", type="fusion_center", lat=42.8864, lng=-78.8784, description="Western New York fusion node. Canadian border proximity.", source="DHS; NYSIC"),
            Infrastructure(name="Illinois Fusion Center — Chicago Regional", city="Chicago", state="IL", type="fusion_center", lat=41.8781, lng=-87.6298, description="CPIC Chicago regional fusion node. Multi-agency.", source="DHS; ISP"),
            Infrastructure(name="North Carolina Fusion Center — Charlotte Regional", city="Charlotte", state="NC", type="fusion_center", lat=35.2271, lng=-80.8431, description="NCSIAC Charlotte regional node.", source="DHS; NCSIAC"),
            Infrastructure(name="Georgia Fusion Center — Atlanta Regional", city="Atlanta", state="GA", type="fusion_center", lat=33.7490, lng=-84.3880, description="GISAC Atlanta regional fusion node.", source="DHS; GBI"),
            Infrastructure(name="Washington Fusion Center — Seattle Regional", city="Seattle", state="WA", type="fusion_center", lat=47.6062, lng=-122.3321, description="WSFC Seattle regional node.", source="DHS; WSP"),
            Infrastructure(name="Ohio Fusion Center — Cleveland Regional", city="Cleveland", state="OH", type="fusion_center", lat=41.4993, lng=-81.6944, description="Ohio SAIC Cleveland regional fusion node.", source="DHS; Ohio SAIC"),
            Infrastructure(name="Ohio Fusion Center — Cincinnati Regional", city="Cincinnati", state="OH", type="fusion_center", lat=39.1031, lng=-84.5120, description="Ohio SAIC Cincinnati regional node.", source="DHS; Ohio SAIC"),
            Infrastructure(name="Michigan Fusion Center — Detroit Regional", city="Detroit", state="MI", type="fusion_center", lat=42.3314, lng=-83.0458, description="DSEMIIC Detroit regional fusion node.", source="DHS; MSP"),
            Infrastructure(name="Pennsylvania Fusion Center — Philadelphia Regional", city="Philadelphia", state="PA", type="fusion_center", lat=39.9526, lng=-75.1652, description="PCIC Philadelphia regional node.", source="DHS; PSP"),
            Infrastructure(name="Pennsylvania Fusion Center — Pittsburgh Regional", city="Pittsburgh", state="PA", type="fusion_center", lat=40.4406, lng=-79.9959, description="PCIC Pittsburgh regional fusion node.", source="DHS; PSP"),
            Infrastructure(name="New Jersey Fusion Center — Newark Regional", city="Newark", state="NJ", type="fusion_center", lat=40.7357, lng=-74.1724, description="ROIC Newark regional node.", source="DHS; NJSP"),
            Infrastructure(name="Maryland Fusion Center — Baltimore Regional", city="Baltimore", state="MD", type="fusion_center", lat=39.2904, lng=-76.6122, description="MCAC Baltimore regional fusion node.", source="DHS; MSP"),
            Infrastructure(name="Virginia Fusion Center — Northern Virginia Regional", city="Fairfax", state="VA", type="fusion_center", lat=38.8462, lng=-77.3064, description="VFC Northern Virginia node. Pentagon proximity.", source="DHS; VSP"),
            Infrastructure(name="Missouri Fusion Center — Kansas City Regional", city="Kansas City", state="MO", type="fusion_center", lat=39.0997, lng=-94.5786, description="MIAC Kansas City regional node.", source="DHS; MHP"),
            Infrastructure(name="Colorado Fusion Center — Colorado Springs Regional", city="Colorado Springs", state="CO", type="fusion_center", lat=38.8339, lng=-104.8214, description="CIAC Colorado Springs regional node. Military city.", source="DHS; CSP"),
            Infrastructure(name="Arizona Fusion Center — Tucson Regional", city="Tucson", state="AZ", type="fusion_center", lat=32.2217, lng=-110.9265, description="ACTIC Tucson regional fusion node. Border operations.", source="DHS; DPS"),
            Infrastructure(name="Arizona Fusion Center — Yuma Regional", city="Yuma", state="AZ", type="fusion_center", lat=32.6927, lng=-114.6277, description="ACTIC Yuma regional node. Border city.", source="DHS; DPS"),
            Infrastructure(name="New Mexico Fusion Center — Las Cruces Regional", city="Las Cruces", state="NM", type="fusion_center", lat=32.3199, lng=-106.7637, description="NMASIAC Las Cruces regional node. Border proximity.", source="DHS; NMSP"),

            # ══════════════════════════════════════════════════════════════
            # NEIGHBORHOOD LEVEL — SEATTLE / TACOMA
            # Source: SPD records, EFF Atlas, ACLU WA
            # ══════════════════════════════════════════════════════════════

            Infrastructure(name="SPD East Precinct Surveillance — Capitol Hill", city="Seattle", state="WA", type="surveillance_camera", lat=47.6205, lng=-122.3212, description="SPD East Precinct cameras. Capitol Hill. Dense coverage during 2020 protests.", source="SPD records; ACLU WA"),
            Infrastructure(name="SPD South Precinct Surveillance — Rainier Valley", city="Seattle", state="WA", type="surveillance_camera", lat=47.5537, lng=-122.2989, description="SPD South Precinct cameras. Rainier Valley neighborhood.", source="SPD records; EFF Atlas"),
            Infrastructure(name="SPD Southwest Precinct Surveillance — West Seattle", city="Seattle", state="WA", type="surveillance_camera", lat=47.5636, lng=-122.3857, description="SPD Southwest Precinct camera network.", source="SPD records; EFF Atlas"),
            Infrastructure(name="SPD North Precinct Surveillance — North Seattle", city="Seattle", state="WA", type="surveillance_camera", lat=47.7035, lng=-122.3261, description="SPD North Precinct cameras. North Seattle.", source="SPD records; EFF Atlas"),
            Infrastructure(name="SPD West Precinct Surveillance — Downtown", city="Seattle", state="WA", type="surveillance_camera", lat=47.6062, lng=-122.3321, description="SPD West Precinct cameras. Downtown Seattle.", source="SPD records; EFF Atlas"),
            Infrastructure(name="ShotSpotter — Seattle Rainier Beach", city="Seattle", state="WA", type="shotspotter", lat=47.5230, lng=-122.2660, description="ShotSpotter in Rainier Beach neighborhood.", source="SPD records; EFF Atlas"),
            Infrastructure(name="ShotSpotter — Seattle South Park", city="Seattle", state="WA", type="shotspotter", lat=47.5280, lng=-122.3370, description="ShotSpotter coverage in South Park.", source="SPD records; EFF Atlas"),
            Infrastructure(name="Flock Safety LPR — Seattle Beacon Hill", city="Seattle", state="WA", type="flock_lpr", lat=47.5668, lng=-122.3030, description="Flock Safety LPR cameras in Beacon Hill.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Tacoma PD South End Surveillance", city="Tacoma", state="WA", type="surveillance_camera", lat=47.2100, lng=-122.4520, description="Tacoma PD cameras in South End neighborhoods.", source="TPD records; EFF Atlas"),
            Infrastructure(name="ShotSpotter — Tacoma Hilltop", city="Tacoma", state="WA", type="shotspotter", lat=47.2580, lng=-122.4630, description="ShotSpotter in Hilltop neighborhood, Tacoma.", source="TPD records; EFF Atlas"),
            Infrastructure(name="ShotSpotter — Tacoma East Side", city="Tacoma", state="WA", type="shotspotter", lat=47.2440, lng=-122.4020, description="ShotSpotter on Tacoma East Side.", source="TPD records; EFF Atlas"),

            # ══════════════════════════════════════════════════════════════
            # NEIGHBORHOOD LEVEL — DENVER / COLORADO SPRINGS
            # Source: DPD records, EFF Atlas, ACLU Colorado
            # ══════════════════════════════════════════════════════════════

            Infrastructure(name="DPD District 1 Surveillance — Downtown Denver", city="Denver", state="CO", type="surveillance_camera", lat=39.7392, lng=-104.9903, description="DPD District 1 cameras. Downtown Denver.", source="DPD records; EFF Atlas"),
            Infrastructure(name="DPD District 2 Surveillance — Northeast Denver", city="Denver", state="CO", type="surveillance_camera", lat=39.7840, lng=-104.9390, description="DPD District 2 camera network. Northeast Denver.", source="DPD records; EFF Atlas"),
            Infrastructure(name="DPD District 3 Surveillance — Southeast Denver", city="Denver", state="CO", type="surveillance_camera", lat=39.7050, lng=-104.9290, description="DPD District 3 cameras. Southeast Denver.", source="DPD records; EFF Atlas"),
            Infrastructure(name="DPD District 4 Surveillance — Southwest Denver", city="Denver", state="CO", type="surveillance_camera", lat=39.7010, lng=-105.0240, description="DPD District 4 camera network. Southwest Denver.", source="DPD records; EFF Atlas"),
            Infrastructure(name="DPD District 5 Surveillance — Northwest Denver", city="Denver", state="CO", type="surveillance_camera", lat=39.7770, lng=-105.0380, description="DPD District 5 cameras. Northwest Denver.", source="DPD records; EFF Atlas"),
            Infrastructure(name="DPD District 6 Surveillance — West Denver", city="Denver", state="CO", type="surveillance_camera", lat=39.7390, lng=-105.0340, description="DPD District 6 camera network. West Denver.", source="DPD records; EFF Atlas"),
            Infrastructure(name="ShotSpotter — Denver Montbello", city="Denver", state="CO", type="shotspotter", lat=39.8050, lng=-104.8870, description="ShotSpotter in Montbello neighborhood.", source="DPD records; EFF Atlas"),
            Infrastructure(name="ShotSpotter — Denver Globeville", city="Denver", state="CO", type="shotspotter", lat=39.7870, lng=-104.9800, description="ShotSpotter in Globeville neighborhood.", source="DPD records; EFF Atlas"),
            Infrastructure(name="ShotSpotter — Denver Elyria-Swansea", city="Denver", state="CO", type="shotspotter", lat=39.7770, lng=-104.9620, description="ShotSpotter in Elyria-Swansea neighborhoods.", source="DPD records; EFF Atlas"),
            Infrastructure(name="Colorado Springs PD Division 1 Surveillance", city="Colorado Springs", state="CO", type="surveillance_camera", lat=38.8339, lng=-104.8214, description="CSPD Division 1 cameras. Downtown Colorado Springs.", source="CSPD records; EFF Atlas"),
            Infrastructure(name="Colorado Springs PD Division 2 Surveillance — East", city="Colorado Springs", state="CO", type="surveillance_camera", lat=38.8420, lng=-104.7640, description="CSPD Division 2 camera network. East Colorado Springs.", source="CSPD records; EFF Atlas"),
            Infrastructure(name="ShotSpotter — Colorado Springs East Side", city="Colorado Springs", state="CO", type="shotspotter", lat=38.8420, lng=-104.7640, description="ShotSpotter on Colorado Springs East Side.", source="CSPD records; EFF Atlas"),

            # ══════════════════════════════════════════════════════════════
            # NEIGHBORHOOD LEVEL — LAS VEGAS METRO
            # Source: LVMPD records, EFF Atlas
            # ══════════════════════════════════════════════════════════════

            Infrastructure(name="LVMPD Area Command Downtown Surveillance", city="Las Vegas", state="NV", type="surveillance_camera", lat=36.1699, lng=-115.1398, description="LVMPD Downtown Area Command cameras. Strip and Fremont.", source="LVMPD records; EFF Atlas"),
            Infrastructure(name="LVMPD Area Command Northeast Surveillance", city="Las Vegas", state="NV", type="surveillance_camera", lat=36.2110, lng=-115.0820, description="LVMPD Northeast Area Command camera network.", source="LVMPD records; EFF Atlas"),
            Infrastructure(name="LVMPD Area Command Southeast Surveillance", city="Las Vegas", state="NV", type="surveillance_camera", lat=36.1040, lng=-115.0750, description="LVMPD Southeast Area Command cameras.", source="LVMPD records; EFF Atlas"),
            Infrastructure(name="LVMPD Area Command Northwest Surveillance", city="Las Vegas", state="NV", type="surveillance_camera", lat=36.2370, lng=-115.2100, description="LVMPD Northwest Area Command camera network.", source="LVMPD records; EFF Atlas"),
            Infrastructure(name="LVMPD Area Command Southwest Surveillance", city="Las Vegas", state="NV", type="surveillance_camera", lat=36.0800, lng=-115.2350, description="LVMPD Southwest Area Command cameras.", source="LVMPD records; EFF Atlas"),
            Infrastructure(name="ShotSpotter — Las Vegas East Las Vegas", city="Las Vegas", state="NV", type="shotspotter", lat=36.1630, lng=-115.0760, description="ShotSpotter in East Las Vegas.", source="LVMPD records; EFF Atlas"),
            Infrastructure(name="ShotSpotter — Las Vegas North Las Vegas", city="North Las Vegas", state="NV", type="shotspotter", lat=36.1989, lng=-115.1175, description="ShotSpotter in North Las Vegas.", source="NLVPD records; EFF Atlas"),
            Infrastructure(name="Flock Safety LPR — Las Vegas Summerlin", city="Las Vegas", state="NV", type="flock_lpr", lat=36.1750, lng=-115.3280, description="Flock Safety LPR in Summerlin area.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Las Vegas Henderson suburbs", city="Henderson", state="NV", type="flock_lpr", lat=36.0395, lng=-114.9817, description="Flock Safety cameras in Henderson.", source="EFF Atlas; Flock Safety contracts"),
            Infrastructure(name="Flock Safety LPR — Las Vegas Green Valley", city="Henderson", state="NV", type="flock_lpr", lat=36.0100, lng=-115.0610, description="Flock Safety LPR in Green Valley area.", source="EFF Atlas; Flock Safety contracts"),

            # ══════════════════════════════════════════════════════════════
            # NEIGHBORHOOD LEVEL — NASHVILLE / MEMPHIS / KNOXVILLE
            # Source: PD records, EFF Atlas
            # ══════════════════════════════════════════════════════════════

            Infrastructure(name="MNPD Central Precinct Surveillance — Downtown Nashville", city="Nashville", state="TN", type="surveillance_camera", lat=36.1627, lng=-86.7816, description="MNPD Central Precinct cameras. Downtown Nashville.", source="MNPD records; EFF Atlas"),
            Infrastructure(name="MNPD East Precinct Surveillance", city="Nashville", state="TN", type="surveillance_camera", lat=36.1750, lng=-86.7330, description="MNPD East Precinct camera network.", source="MNPD records; EFF Atlas"),
            Infrastructure(name="MNPD North Precinct Surveillance", city="Nashville", state="TN", type="surveillance_camera", lat=36.2060, lng=-86.7860, description="MNPD North Precinct cameras.", source="MNPD records; EFF Atlas"),
            Infrastructure(name="MNPD South Precinct Surveillance", city="Nashville", state="TN", type="surveillance_camera", lat=36.1190, lng=-86.7730, description="MNPD South Precinct camera network.", source="MNPD records; EFF Atlas"),
            Infrastructure(name="MNPD West Precinct Surveillance", city="Nashville", state="TN", type="surveillance_camera", lat=36.1560, lng=-86.8290, description="MNPD West Precinct cameras.", source="MNPD records; EFF Atlas"),
            Infrastructure(name="ShotSpotter — Nashville North Nashville", city="Nashville", state="TN", type="shotspotter", lat=36.2060, lng=-86.7860, description="ShotSpotter in North Nashville.", source="MNPD records; EFF Atlas"),
            Infrastructure(name="ShotSpotter — Nashville East Nashville", city="Nashville", state="TN", type="shotspotter", lat=36.1750, lng=-86.7330, description="ShotSpotter coverage in East Nashville.", source="MNPD records; EFF Atlas"),
            Infrastructure(name="MPD Raines Road Precinct Surveillance — South Memphis", city="Memphis", state="TN", type="surveillance_camera", lat=35.0370, lng=-90.0490, description="Memphis PD South Memphis cameras. Blue CRUSH coverage.", source="MPD records; EFF Atlas"),
            Infrastructure(name="MPD Tillman Cove Precinct Surveillance — North Memphis", city="Memphis", state="TN", type="surveillance_camera", lat=35.1980, lng=-90.0490, description="Memphis PD North Memphis camera network.", source="MPD records; EFF Atlas"),
            Infrastructure(name="MPD Airways Precinct Surveillance — East Memphis", city="Memphis", state="TN", type="surveillance_camera", lat=35.1350, lng=-89.9440, description="Memphis PD East Memphis cameras.", source="MPD records; EFF Atlas"),
            Infrastructure(name="ShotSpotter — Memphis Orange Mound", city="Memphis", state="TN", type="shotspotter", lat=35.1120, lng=-89.9870, description="ShotSpotter in Orange Mound neighborhood.", source="MPD records; EFF Atlas"),
            Infrastructure(name="ShotSpotter — Memphis Whitehaven", city="Memphis", state="TN", type="shotspotter", lat=35.0200, lng=-90.0200, description="ShotSpotter coverage in Whitehaven.", source="MPD records; EFF Atlas"),
            Infrastructure(name="ShotSpotter — Memphis Frayser", city="Memphis", state="TN", type="shotspotter", lat=35.2120, lng=-90.0470, description="ShotSpotter in Frayser neighborhood.", source="MPD records; EFF Atlas"),
            Infrastructure(name="ShotSpotter — Memphis South Memphis", city="Memphis", state="TN", type="shotspotter", lat=35.0990, lng=-90.0490, description="ShotSpotter in South Memphis.", source="MPD records; EFF Atlas"),
            Infrastructure(name="KPD Central Precinct Surveillance — Downtown Knoxville", city="Knoxville", state="TN", type="surveillance_camera", lat=35.9606, lng=-83.9207, description="Knoxville PD Central Precinct cameras.", source="KPD records; EFF Atlas"),
            Infrastructure(name="ShotSpotter — Knoxville Mechanicsville", city="Knoxville", state="TN", type="shotspotter", lat=35.9780, lng=-83.9450, description="ShotSpotter in Mechanicsville neighborhood.", source="KPD records; EFF Atlas"),

            # ══════════════════════════════════════════════════════════════
            # NEIGHBORHOOD LEVEL — LOUISVILLE / INDIANAPOLIS
            # Source: PD records, EFF Atlas
            # ══════════════════════════════════════════════════════════════

            Infrastructure(name="LMPD 1st Division Surveillance — Downtown Louisville", city="Louisville", state="KY", type="surveillance_camera", lat=38.2527, lng=-85.7585, description="LMPD 1st Division cameras. Downtown Louisville.", source="LMPD records; EFF Atlas"),
            Infrastructure(name="LMPD 2nd Division Surveillance — West Louisville", city="Louisville", state="KY", type="surveillance_camera", lat=38.2530, lng=-85.8090, description="LMPD 2nd Division camera network. West Louisville.", source="LMPD records; EFF Atlas"),
            Infrastructure(name="LMPD 4th Division Surveillance — South Louisville", city="Louisville", state="KY", type="surveillance_camera", lat=38.2020, lng=-85.7510, description="LMPD 4th Division cameras. South Louisville.", source="LMPD records; EFF Atlas"),
            Infrastructure(name="ShotSpotter — Louisville Russell neighborhood", city="Louisville", state="KY", type="shotspotter", lat=38.2480, lng=-85.7870, description="ShotSpotter in Russell neighborhood. West Louisville.", source="LMPD records; EFF Atlas"),
            Infrastructure(name="ShotSpotter — Louisville Shively", city="Louisville", state="KY", type="shotspotter", lat=38.2010, lng=-85.8220, description="ShotSpotter in Shively area.", source="LMPD records; EFF Atlas"),
            Infrastructure(name="ShotSpotter — Louisville California neighborhood", city="Louisville", state="KY", type="shotspotter", lat=38.2560, lng=-85.7820, description="ShotSpotter in California neighborhood.", source="LMPD records; EFF Atlas"),
            Infrastructure(name="IMPD North District Surveillance", city="Indianapolis", state="IN", type="surveillance_camera", lat=39.8350, lng=-86.1580, description="IMPD North District cameras.", source="IMPD records; EFF Atlas"),
            Infrastructure(name="IMPD East District Surveillance", city="Indianapolis", state="IN", type="surveillance_camera", lat=39.7700, lng=-86.0990, description="IMPD East District camera network.", source="IMPD records; EFF Atlas"),
            Infrastructure(name="IMPD South District Surveillance", city="Indianapolis", state="IN", type="surveillance_camera", lat=39.6940, lng=-86.1580, description="IMPD South District cameras.", source="IMPD records; EFF Atlas"),
            Infrastructure(name="IMPD Northwest District Surveillance", city="Indianapolis", state="IN", type="surveillance_camera", lat=39.8210, lng=-86.2430, description="IMPD Northwest District camera network.", source="IMPD records; EFF Atlas"),
            Infrastructure(name="ShotSpotter — Indianapolis East 38th Street", city="Indianapolis", state="IN", type="shotspotter", lat=39.8040, lng=-86.0990, description="ShotSpotter along East 38th Street corridor.", source="IMPD records; EFF Atlas"),
            Infrastructure(name="ShotSpotter — Indianapolis Near Eastside", city="Indianapolis", state="IN", type="shotspotter", lat=39.7700, lng=-86.0990, description="ShotSpotter on Indianapolis Near Eastside.", source="IMPD records; EFF Atlas"),
            Infrastructure(name="ShotSpotter — Indianapolis Near Northside", city="Indianapolis", state="IN", type="shotspotter", lat=39.7980, lng=-86.1580, description="ShotSpotter on Indianapolis Near Northside.", source="IMPD records; EFF Atlas"),

            # ══════════════════════════════════════════════════════════════
            # ADDITIONAL CAMERA NETWORKS — SMALLER CITIES
            # Source: EFF Atlas, city records
            # ══════════════════════════════════════════════════════════════

            Infrastructure(name="Compton CA Camera Network", city="Compton", state="CA", type="surveillance_camera", lat=33.8958, lng=-118.2201, description="Compton PD and LASD camera network.", source="EFF Atlas"),
            Infrastructure(name="Inglewood CA Camera Network", city="Inglewood", state="CA", type="surveillance_camera", lat=33.9617, lng=-118.3531, description="Inglewood PD camera infrastructure.", source="EFF Atlas"),
            Infrastructure(name="Long Beach CA Camera Network — North", city="Long Beach", state="CA", type="surveillance_camera", lat=33.8350, lng=-118.1750, description="LBPD camera network North Long Beach.", source="EFF Atlas"),
            Infrastructure(name="Long Beach CA Camera Network — Central", city="Long Beach", state="CA", type="surveillance_camera", lat=33.7880, lng=-118.1780, description="LBPD camera network Central Long Beach.", source="EFF Atlas"),
            Infrastructure(name="Stockton CA Camera Network", city="Stockton", state="CA", type="surveillance_camera", lat=37.9577, lng=-121.2908, description="Stockton PD camera infrastructure.", source="EFF Atlas"),
            Infrastructure(name="Fresno CA Camera Network — Southwest", city="Fresno", state="CA", type="surveillance_camera", lat=36.7080, lng=-119.8080, description="Fresno PD cameras in Southwest Fresno.", source="EFF Atlas"),
            Infrastructure(name="Fresno CA Camera Network — Central", city="Fresno", state="CA", type="surveillance_camera", lat=36.7378, lng=-119.7871, description="Fresno PD central camera network.", source="EFF Atlas"),
            Infrastructure(name="Richmond VA Camera Network — East End", city="Richmond", state="VA", type="surveillance_camera", lat=37.5407, lng=-77.4060, description="Richmond PD East End cameras.", source="EFF Atlas"),
            Infrastructure(name="Richmond VA Camera Network — South Side", city="Richmond", state="VA", type="surveillance_camera", lat=37.5110, lng=-77.4360, description="Richmond PD South Side camera network.", source="EFF Atlas"),
            Infrastructure(name="Hartford CT Camera Network", city="Hartford", state="CT", type="surveillance_camera", lat=41.7637, lng=-72.6851, description="Hartford PD camera infrastructure.", source="EFF Atlas"),
            Infrastructure(name="Bridgeport CT Camera Network", city="Bridgeport", state="CT", type="surveillance_camera", lat=41.1865, lng=-73.1952, description="Bridgeport PD camera network.", source="EFF Atlas"),
            Infrastructure(name="New Haven CT Camera Network", city="New Haven", state="CT", type="surveillance_camera", lat=41.3083, lng=-72.9279, description="New Haven PD camera infrastructure.", source="EFF Atlas"),
            Infrastructure(name="Springfield MA Camera Network", city="Springfield", state="MA", type="surveillance_camera", lat=42.1015, lng=-72.5898, description="Springfield MA PD camera network.", source="EFF Atlas"),
            Infrastructure(name="Worcester MA Camera Network", city="Worcester", state="MA", type="surveillance_camera", lat=42.2626, lng=-71.8023, description="Worcester PD camera infrastructure.", source="EFF Atlas"),
            Infrastructure(name="Providence RI Camera Network", city="Providence", state="RI", type="surveillance_camera", lat=41.8240, lng=-71.4128, description="Providence PD camera network.", source="EFF Atlas"),
            Infrastructure(name="Paterson NJ Camera Network", city="Paterson", state="NJ", type="surveillance_camera", lat=40.9168, lng=-74.1719, description="Paterson PD camera infrastructure.", source="EFF Atlas"),
            Infrastructure(name="Camden NJ Camera Network", city="Camden", state="NJ", type="surveillance_camera", lat=39.9259, lng=-75.1196, description="Camden County Metro PD camera network.", source="EFF Atlas"),
            Infrastructure(name="Trenton NJ Camera Network", city="Trenton", state="NJ", type="surveillance_camera", lat=40.2171, lng=-74.7429, description="Trenton PD camera infrastructure.", source="EFF Atlas"),
            Infrastructure(name="Gary IN Camera Network", city="Gary", state="IN", type="surveillance_camera", lat=41.5934, lng=-87.3465, description="Gary PD camera network.", source="EFF Atlas"),
            Infrastructure(name="Rockford IL Camera Network", city="Rockford", state="IL", type="surveillance_camera", lat=42.2711, lng=-89.0940, description="Rockford PD camera infrastructure.", source="EFF Atlas"),
            Infrastructure(name="Peoria IL Camera Network", city="Peoria", state="IL", type="surveillance_camera", lat=40.6936, lng=-89.5890, description="Peoria PD camera network.", source="EFF Atlas"),
            Infrastructure(name="East St. Louis IL Camera Network", city="East St. Louis", state="IL", type="surveillance_camera", lat=38.6245, lng=-90.1540, description="East St. Louis PD camera infrastructure.", source="EFF Atlas"),
            Infrastructure(name="Flint MI Camera Network", city="Flint", state="MI", type="surveillance_camera", lat=43.0125, lng=-83.6875, description="Flint PD camera network.", source="EFF Atlas"),
            Infrastructure(name="Saginaw MI Camera Network", city="Saginaw", state="MI", type="surveillance_camera", lat=43.4195, lng=-83.9508, description="Saginaw PD camera infrastructure.", source="EFF Atlas"),
            Infrastructure(name="Dayton OH Camera Network", city="Dayton", state="OH", type="surveillance_camera", lat=39.7589, lng=-84.1916, description="Dayton PD camera network.", source="EFF Atlas"),
            Infrastructure(name="Toledo OH Camera Network", city="Toledo", state="OH", type="surveillance_camera", lat=41.6639, lng=-83.5552, description="Toledo PD camera infrastructure.", source="EFF Atlas"),
            Infrastructure(name="Akron OH Camera Network", city="Akron", state="OH", type="surveillance_camera", lat=41.0814, lng=-81.5190, description="Akron PD camera network.", source="EFF Atlas"),
            Infrastructure(name="Youngstown OH Camera Network", city="Youngstown", state="OH", type="surveillance_camera", lat=41.0998, lng=-80.6495, description="Youngstown PD camera infrastructure.", source="EFF Atlas"),
            Infrastructure(name="Savannah GA Camera Network", city="Savannah", state="GA", type="surveillance_camera", lat=32.0835, lng=-81.0998, description="Savannah PD camera network.", source="EFF Atlas"),
            Infrastructure(name="Augusta GA Camera Network", city="Augusta", state="GA", type="surveillance_camera", lat=33.4735, lng=-82.0105, description="Augusta PD camera infrastructure.", source="EFF Atlas"),
            Infrastructure(name="Macon GA Camera Network", city="Macon", state="GA", type="surveillance_camera", lat=32.8407, lng=-83.6324, description="Macon PD camera network.", source="EFF Atlas"),
            Infrastructure(name="Columbus GA Camera Network", city="Columbus", state="GA", type="surveillance_camera", lat=32.4610, lng=-84.9877, description="Columbus GA PD camera infrastructure.", source="EFF Atlas"),
            Infrastructure(name="Mobile AL Camera Network", city="Mobile", state="AL", type="surveillance_camera", lat=30.6954, lng=-88.0399, description="Mobile PD camera network.", source="EFF Atlas"),
            Infrastructure(name="Huntsville AL Camera Network", city="Huntsville", state="AL", type="surveillance_camera", lat=34.7304, lng=-86.5861, description="Huntsville PD camera infrastructure.", source="EFF Atlas"),
            Infrastructure(name="Montgomery AL Camera Network", city="Montgomery", state="AL", type="surveillance_camera", lat=32.3617, lng=-86.2792, description="Montgomery PD camera network.", source="EFF Atlas"),
            Infrastructure(name="Jackson MS Camera Network", city="Jackson", state="MS", type="surveillance_camera", lat=32.2988, lng=-90.1848, description="Jackson PD camera infrastructure.", source="EFF Atlas"),
            Infrastructure(name="Little Rock AR Camera Network", city="Little Rock", state="AR", type="surveillance_camera", lat=34.7465, lng=-92.2896, description="Little Rock PD camera network.", source="EFF Atlas"),
            Infrastructure(name="Shreveport LA Camera Network", city="Shreveport", state="LA", type="surveillance_camera", lat=32.5252, lng=-93.7502, description="Shreveport PD camera infrastructure.", source="EFF Atlas"),
            Infrastructure(name="Baton Rouge LA Camera Network", city="Baton Rouge", state="LA", type="surveillance_camera", lat=30.4515, lng=-91.1871, description="Baton Rouge PD camera network.", source="EFF Atlas"),
            Infrastructure(name="Lubbock TX Camera Network", city="Lubbock", state="TX", type="surveillance_camera", lat=33.5779, lng=-101.8552, description="Lubbock PD camera infrastructure.", source="EFF Atlas"),
            Infrastructure(name="Corpus Christi TX Camera Network", city="Corpus Christi", state="TX", type="surveillance_camera", lat=27.8006, lng=-97.3964, description="Corpus Christi PD camera network.", source="EFF Atlas"),
            Infrastructure(name="Laredo TX Camera Network", city="Laredo", state="TX", type="surveillance_camera", lat=27.5306, lng=-99.4803, description="Laredo PD camera infrastructure. Border city.", source="EFF Atlas"),
            Infrastructure(name="McAllen TX Camera Network", city="McAllen", state="TX", type="surveillance_camera", lat=26.2034, lng=-98.2300, description="McAllen PD camera network. Border city.", source="EFF Atlas"),
            Infrastructure(name="Amarillo TX Camera Network", city="Amarillo", state="TX", type="surveillance_camera", lat=35.2220, lng=-101.8313, description="Amarillo PD camera infrastructure.", source="EFF Atlas"),
            Infrastructure(name="Beaumont TX Camera Network", city="Beaumont", state="TX", type="surveillance_camera", lat=30.0860, lng=-94.1018, description="Beaumont PD camera network.", source="EFF Atlas"),
            Infrastructure(name="Wichita Falls TX Camera Network", city="Wichita Falls", state="TX", type="surveillance_camera", lat=33.9137, lng=-98.4934, description="Wichita Falls PD camera infrastructure.", source="EFF Atlas"),
            Infrastructure(name="Albuquerque NM Camera Network — South Valley", city="Albuquerque", state="NM", type="surveillance_camera", lat=35.0340, lng=-106.6860, description="APD South Valley camera network.", source="EFF Atlas"),
            Infrastructure(name="Albuquerque NM Camera Network — East Downtown", city="Albuquerque", state="NM", type="surveillance_camera", lat=35.0844, lng=-106.6404, description="APD East Downtown cameras. Higher crime area.", source="EFF Atlas"),
            Infrastructure(name="Tucson AZ Camera Network — South Tucson", city="Tucson", state="AZ", type="surveillance_camera", lat=32.2000, lng=-110.9700, description="Tucson PD South Tucson cameras.", source="EFF Atlas"),
            Infrastructure(name="Tucson AZ Camera Network — Midtown", city="Tucson", state="AZ", type="surveillance_camera", lat=32.2217, lng=-110.9265, description="Tucson PD Midtown camera network.", source="EFF Atlas"),
            Infrastructure(name="Reno NV Camera Network", city="Reno", state="NV", type="surveillance_camera", lat=39.5296, lng=-119.8138, description="Reno PD camera infrastructure.", source="EFF Atlas"),
            Infrastructure(name="Spokane WA Camera Network", city="Spokane", state="WA", type="surveillance_camera", lat=47.6587, lng=-117.4260, description="Spokane PD camera network.", source="EFF Atlas"),
            Infrastructure(name="Boise ID Camera Network", city="Boise", state="ID", type="surveillance_camera", lat=43.6150, lng=-116.2023, description="Boise PD camera infrastructure.", source="EFF Atlas"),
            Infrastructure(name="Salt Lake City UT Camera Network", city="Salt Lake City", state="UT", type="surveillance_camera", lat=40.7608, lng=-111.8910, description="SLC PD camera network.", source="EFF Atlas"),
            Infrastructure(name="Anchorage AK Camera Network", city="Anchorage", state="AK", type="surveillance_camera", lat=61.2181, lng=-149.9003, description="Anchorage PD camera infrastructure.", source="EFF Atlas"),
            Infrastructure(name="Honolulu HI Camera Network", city="Honolulu", state="HI", type="surveillance_camera", lat=21.3069, lng=-157.8583, description="Honolulu PD camera network.", source="EFF Atlas"),

            # ══════════════════════════════════════════════════════════════
            # ADDITIONAL LPR NETWORKS — SUBURBAN AND SMALLER CITIES
            # Source: EFF Atlas, Motorola contracts, city records
            # ══════════════════════════════════════════════════════════════

            Infrastructure(name="Vigilant Solutions LEARN — Compton CA", city="Compton", state="CA", type="vigilant_lpr", lat=33.8958, lng=-118.2201, description="LASD Compton station Vigilant Solutions LPR.", source="EFF Atlas; Motorola contracts"),
            Infrastructure(name="Vigilant Solutions LEARN — Long Beach PD CA", city="Long Beach", state="CA", type="vigilant_lpr", lat=33.7701, lng=-118.1937, description="LBPD Vigilant Solutions LPR network.", source="EFF Atlas; Motorola contracts"),
            Infrastructure(name="Vigilant Solutions LEARN — Anaheim PD CA", city="Anaheim", state="CA", type="vigilant_lpr", lat=33.8366, lng=-117.9143, description="APD Vigilant Solutions deployment.", source="EFF Atlas"),
            Infrastructure(name="Vigilant Solutions LEARN — Glendale PD CA", city="Glendale", state="CA", type="vigilant_lpr", lat=34.1425, lng=-118.2551, description="Glendale CA PD Vigilant Solutions LPR.", source="EFF Atlas; Motorola contracts"),
            Infrastructure(name="Vigilant Solutions LEARN — Pasadena PD CA", city="Pasadena", state="CA", type="vigilant_lpr", lat=34.1478, lng=-118.1445, description="Pasadena PD Vigilant Solutions network.", source="EFF Atlas"),
            Infrastructure(name="Vigilant Solutions LEARN — Burbank PD CA", city="Burbank", state="CA", type="vigilant_lpr", lat=34.1808, lng=-118.3090, description="Burbank PD Vigilant Solutions LPR.", source="EFF Atlas; Motorola contracts"),
            Infrastructure(name="Vigilant Solutions LEARN — Torrance PD CA", city="Torrance", state="CA", type="vigilant_lpr", lat=33.8358, lng=-118.3406, description="Torrance PD Vigilant Solutions deployment.", source="EFF Atlas"),
            Infrastructure(name="Vigilant Solutions LEARN — El Monte PD CA", city="El Monte", state="CA", type="vigilant_lpr", lat=34.0686, lng=-118.0276, description="El Monte PD Vigilant Solutions LPR.", source="EFF Atlas; Motorola contracts"),
            Infrastructure(name="Vigilant Solutions LEARN — Pomona PD CA", city="Pomona", state="CA", type="vigilant_lpr", lat=34.0553, lng=-117.7500, description="Pomona PD Vigilant Solutions network.", source="EFF Atlas"),
            Infrastructure(name="Vigilant Solutions LEARN — Ontario PD CA", city="Ontario", state="CA", type="vigilant_lpr", lat=34.0633, lng=-117.6509, description="Ontario CA PD Vigilant Solutions LPR.", source="EFF Atlas; Motorola contracts"),
            Infrastructure(name="Vigilant Solutions LEARN — Chula Vista PD CA", city="Chula Vista", state="CA", type="vigilant_lpr", lat=32.6401, lng=-117.0842, description="Chula Vista PD Vigilant Solutions deployment.", source="EFF Atlas"),
            Infrastructure(name="Vigilant Solutions LEARN — Escondido PD CA", city="Escondido", state="CA", type="vigilant_lpr", lat=33.1192, lng=-117.0864, description="Escondido PD Vigilant Solutions LPR.", source="EFF Atlas; Motorola contracts"),
            Infrastructure(name="Vigilant Solutions LEARN — El Cajon PD CA", city="El Cajon", state="CA", type="vigilant_lpr", lat=32.7948, lng=-116.9625, description="El Cajon PD Vigilant Solutions network.", source="EFF Atlas"),
            Infrastructure(name="Vigilant Solutions LEARN — Hayward PD CA", city="Hayward", state="CA", type="vigilant_lpr", lat=37.6688, lng=-122.0808, description="Hayward PD Vigilant Solutions LPR.", source="EFF Atlas; Motorola contracts"),
            Infrastructure(name="Vigilant Solutions LEARN — Fremont PD CA", city="Fremont", state="CA", type="vigilant_lpr", lat=37.5485, lng=-121.9886, description="Fremont PD Vigilant Solutions deployment.", source="EFF Atlas"),
            Infrastructure(name="Vigilant Solutions LEARN — Sunnyvale DPS CA", city="Sunnyvale", state="CA", type="vigilant_lpr", lat=37.3688, lng=-122.0363, description="Sunnyvale DPS Vigilant Solutions LPR.", source="EFF Atlas; Motorola contracts"),
            Infrastructure(name="Vigilant Solutions LEARN — Santa Clara PD CA", city="Santa Clara", state="CA", type="vigilant_lpr", lat=37.3541, lng=-121.9552, description="Santa Clara PD Vigilant Solutions network.", source="EFF Atlas"),
            Infrastructure(name="Vigilant Solutions LEARN — Richmond PD CA", city="Richmond", state="CA", type="vigilant_lpr", lat=37.9358, lng=-122.3477, description="Richmond CA PD Vigilant Solutions LPR.", source="EFF Atlas; Motorola contracts"),
            Infrastructure(name="Vigilant Solutions LEARN — Vallejo PD CA", city="Vallejo", state="CA", type="vigilant_lpr", lat=38.1041, lng=-122.2566, description="Vallejo PD Vigilant Solutions deployment.", source="EFF Atlas"),
            Infrastructure(name="Vigilant Solutions LEARN — Concord PD CA", city="Concord", state="CA", type="vigilant_lpr", lat=37.9780, lng=-122.0311, description="Concord CA PD Vigilant Solutions LPR.", source="EFF Atlas; Motorola contracts"),
            Infrastructure(name="Vigilant Solutions LEARN — Antioch PD CA", city="Antioch", state="CA", type="vigilant_lpr", lat=38.0049, lng=-121.8058, description="Antioch PD Vigilant Solutions network.", source="EFF Atlas"),
            Infrastructure(name="Vigilant Solutions LEARN — Modesto PD CA", city="Modesto", state="CA", type="vigilant_lpr", lat=37.6391, lng=-120.9969, description="Modesto PD Vigilant Solutions LPR.", source="EFF Atlas; Motorola contracts"),
            Infrastructure(name="Vigilant Solutions LEARN — Salinas PD CA", city="Salinas", state="CA", type="vigilant_lpr", lat=36.6777, lng=-121.6555, description="Salinas PD Vigilant Solutions deployment.", source="EFF Atlas"),
            Infrastructure(name="Vigilant Solutions LEARN — Oxnard PD CA", city="Oxnard", state="CA", type="vigilant_lpr", lat=34.1975, lng=-119.1771, description="Oxnard PD Vigilant Solutions LPR.", source="EFF Atlas; Motorola contracts"),
            Infrastructure(name="Vigilant Solutions LEARN — Santa Barbara PD CA", city="Santa Barbara", state="CA", type="vigilant_lpr", lat=34.4208, lng=-119.6982, description="Santa Barbara PD Vigilant Solutions network.", source="EFF Atlas"),
            Infrastructure(name="Vigilant Solutions LEARN — Visalia PD CA", city="Visalia", state="CA", type="vigilant_lpr", lat=36.3302, lng=-119.2921, description="Visalia PD Vigilant Solutions LPR.", source="EFF Atlas; Motorola contracts"),
            Infrastructure(name="Vigilant Solutions LEARN — Bakersfield PD CA", city="Bakersfield", state="CA", type="vigilant_lpr", lat=35.3733, lng=-119.0187, description="Bakersfield PD Vigilant Solutions deployment.", source="EFF Atlas"),
            Infrastructure(name="Vigilant Solutions LEARN — Rialto PD CA", city="Rialto", state="CA", type="vigilant_lpr", lat=34.1064, lng=-117.3703, description="Rialto PD Vigilant Solutions LPR. Early drone program city.", source="EFF Atlas; Motorola contracts"),
            Infrastructure(name="Vigilant Solutions LEARN — Victorville PD CA", city="Victorville", state="CA", type="vigilant_lpr", lat=34.5362, lng=-117.2928, description="Victorville PD Vigilant Solutions network.", source="EFF Atlas"),
            Infrastructure(name="Vigilant Solutions LEARN — Fort Worth PD TX", city="Fort Worth", state="TX", type="vigilant_lpr", lat=32.7555, lng=-97.3308, description="Fort Worth PD Vigilant Solutions LPR.", source="EFF Atlas; Motorola contracts"),
            Infrastructure(name="Vigilant Solutions LEARN — Arlington TX PD", city="Arlington", state="TX", type="vigilant_lpr", lat=32.7357, lng=-97.1081, description="Arlington TX PD Vigilant Solutions deployment.", source="EFF Atlas"),
            Infrastructure(name="Vigilant Solutions LEARN — Plano TX PD", city="Plano", state="TX", type="vigilant_lpr", lat=33.0198, lng=-96.6989, description="Plano TX PD Vigilant Solutions LPR.", source="EFF Atlas; Motorola contracts"),
            Infrastructure(name="Vigilant Solutions LEARN — Irving TX PD", city="Irving", state="TX", type="vigilant_lpr", lat=32.8140, lng=-96.9489, description="Irving TX PD Vigilant Solutions network.", source="EFF Atlas"),
            Infrastructure(name="Vigilant Solutions LEARN — Garland TX PD", city="Garland", state="TX", type="vigilant_lpr", lat=32.9126, lng=-96.6389, description="Garland TX PD Vigilant Solutions LPR.", source="EFF Atlas; Motorola contracts"),
            Infrastructure(name="Vigilant Solutions LEARN — Frisco TX PD", city="Frisco", state="TX", type="vigilant_lpr", lat=33.1507, lng=-96.8236, description="Frisco TX PD Vigilant Solutions deployment.", source="EFF Atlas"),
            Infrastructure(name="Vigilant Solutions LEARN — McKinney TX PD", city="McKinney", state="TX", type="vigilant_lpr", lat=33.1972, lng=-96.6397, description="McKinney TX PD Vigilant Solutions LPR.", source="EFF Atlas; Motorola contracts"),
            Infrastructure(name="Vigilant Solutions LEARN — Laredo TX PD", city="Laredo", state="TX", type="vigilant_lpr", lat=27.5306, lng=-99.4803, description="Laredo PD Vigilant Solutions network. Border city.", source="EFF Atlas"),
            Infrastructure(name="Vigilant Solutions LEARN — McAllen TX PD", city="McAllen", state="TX", type="vigilant_lpr", lat=26.2034, lng=-98.2300, description="McAllen TX PD Vigilant Solutions LPR. Border city.", source="EFF Atlas; Motorola contracts"),
            Infrastructure(name="Vigilant Solutions LEARN — Amarillo TX PD", city="Amarillo", state="TX", type="vigilant_lpr", lat=35.2220, lng=-101.8313, description="Amarillo TX PD Vigilant Solutions deployment.", source="EFF Atlas"),
            Infrastructure(name="Vigilant Solutions LEARN — Beaumont TX PD", city="Beaumont", state="TX", type="vigilant_lpr", lat=30.0860, lng=-94.1018, description="Beaumont TX PD Vigilant Solutions LPR.", source="EFF Atlas; Motorola contracts"),
            Infrastructure(name="Vigilant Solutions LEARN — Chandler AZ PD", city="Chandler", state="AZ", type="vigilant_lpr", lat=33.3062, lng=-111.8413, description="Chandler AZ PD Vigilant Solutions network.", source="EFF Atlas"),
            Infrastructure(name="Vigilant Solutions LEARN — Gilbert AZ PD", city="Gilbert", state="AZ", type="vigilant_lpr", lat=33.3528, lng=-111.7890, description="Gilbert AZ PD Vigilant Solutions LPR.", source="EFF Atlas; Motorola contracts"),
            Infrastructure(name="Vigilant Solutions LEARN — Tempe AZ PD", city="Tempe", state="AZ", type="vigilant_lpr", lat=33.4255, lng=-111.9400, description="Tempe AZ PD Vigilant Solutions deployment.", source="EFF Atlas"),
            Infrastructure(name="Vigilant Solutions LEARN — Glendale AZ PD", city="Glendale", state="AZ", type="vigilant_lpr", lat=33.5387, lng=-112.1860, description="Glendale AZ PD Vigilant Solutions LPR.", source="EFF Atlas; Motorola contracts"),
            Infrastructure(name="Vigilant Solutions LEARN — Mesa AZ PD", city="Mesa", state="AZ", type="vigilant_lpr", lat=33.4152, lng=-111.8315, description="Mesa AZ PD Vigilant Solutions network.", source="EFF Atlas"),
            Infrastructure(name="Vigilant Solutions LEARN — Scottsdale AZ PD", city="Scottsdale", state="AZ", type="vigilant_lpr", lat=33.4942, lng=-111.9261, description="Scottsdale AZ PD Vigilant Solutions LPR.", source="EFF Atlas; Motorola contracts"),
            Infrastructure(name="Vigilant Solutions LEARN — Yuma AZ PD", city="Yuma", state="AZ", type="vigilant_lpr", lat=32.6927, lng=-114.6277, description="Yuma AZ PD Vigilant Solutions deployment. Border city.", source="EFF Atlas"),
            Infrastructure(name="Vigilant Solutions LEARN — Henderson NV PD", city="Henderson", state="NV", type="vigilant_lpr", lat=36.0395, lng=-114.9817, description="Henderson NV PD Vigilant Solutions LPR.", source="EFF Atlas; Motorola contracts"),
            Infrastructure(name="Vigilant Solutions LEARN — Reno PD NV", city="Reno", state="NV", type="vigilant_lpr", lat=39.5296, lng=-119.8138, description="Reno PD Vigilant Solutions network.", source="EFF Atlas"),
            Infrastructure(name="Vigilant Solutions LEARN — Aurora CO PD", city="Aurora", state="CO", type="vigilant_lpr", lat=39.7294, lng=-104.8319, description="Aurora CO PD Vigilant Solutions LPR.", source="EFF Atlas; Motorola contracts"),
            Infrastructure(name="Vigilant Solutions LEARN — Colorado Springs PD", city="Colorado Springs", state="CO", type="vigilant_lpr", lat=38.8339, lng=-104.8214, description="Colorado Springs PD Vigilant Solutions deployment.", source="EFF Atlas"),
            Infrastructure(name="Vigilant Solutions LEARN — Fort Collins PD CO", city="Fort Collins", state="CO", type="vigilant_lpr", lat=40.5853, lng=-105.0844, description="Fort Collins PD Vigilant Solutions LPR.", source="EFF Atlas; Motorola contracts"),
            Infrastructure(name="Vigilant Solutions LEARN — Lakewood CO PD", city="Lakewood", state="CO", type="vigilant_lpr", lat=39.7047, lng=-105.0814, description="Lakewood CO PD Vigilant Solutions network.", source="EFF Atlas"),
            Infrastructure(name="Vigilant Solutions LEARN — Albuquerque PD NM", city="Albuquerque", state="NM", type="vigilant_lpr", lat=35.0844, lng=-106.6504, description="Albuquerque PD Vigilant Solutions LPR.", source="EFF Atlas; Motorola contracts"),
            Infrastructure(name="Vigilant Solutions LEARN — El Paso PD TX", city="El Paso", state="TX", type="vigilant_lpr", lat=31.7619, lng=-106.4850, description="El Paso PD Vigilant Solutions deployment. Border city.", source="EFF Atlas"),
            Infrastructure(name="Vigilant Solutions LEARN — Salt Lake City PD UT", city="Salt Lake City", state="UT", type="vigilant_lpr", lat=40.7608, lng=-111.8910, description="Salt Lake City PD Vigilant Solutions LPR.", source="EFF Atlas; Motorola contracts"),
            Infrastructure(name="Vigilant Solutions LEARN — West Valley City PD UT", city="West Valley City", state="UT", type="vigilant_lpr", lat=40.6916, lng=-112.0011, description="West Valley City PD Vigilant Solutions network.", source="EFF Atlas"),
            Infrastructure(name="Vigilant Solutions LEARN — Provo PD UT", city="Provo", state="UT", type="vigilant_lpr", lat=40.2338, lng=-111.6585, description="Provo PD Vigilant Solutions LPR.", source="EFF Atlas; Motorola contracts"),
            Infrastructure(name="Vigilant Solutions LEARN — Boise PD ID", city="Boise", state="ID", type="vigilant_lpr", lat=43.6150, lng=-116.2023, description="Boise PD Vigilant Solutions deployment.", source="EFF Atlas"),
            Infrastructure(name="Vigilant Solutions LEARN — Spokane PD WA", city="Spokane", state="WA", type="vigilant_lpr", lat=47.6587, lng=-117.4260, description="Spokane PD Vigilant Solutions LPR.", source="EFF Atlas; Motorola contracts"),
            Infrastructure(name="Vigilant Solutions LEARN — Tacoma PD WA", city="Tacoma", state="WA", type="vigilant_lpr", lat=47.2529, lng=-122.4443, description="Tacoma PD Vigilant Solutions network.", source="EFF Atlas"),
            Infrastructure(name="Vigilant Solutions LEARN — Bellevue PD WA", city="Bellevue", state="WA", type="vigilant_lpr", lat=47.6101, lng=-122.2015, description="Bellevue PD Vigilant Solutions LPR.", source="EFF Atlas; Motorola contracts"),
            Infrastructure(name="Vigilant Solutions LEARN — Eugene PD OR", city="Eugene", state="OR", type="vigilant_lpr", lat=44.0521, lng=-123.0868, description="Eugene PD Vigilant Solutions deployment.", source="EFF Atlas"),
            Infrastructure(name="Vigilant Solutions LEARN — Salem PD OR", city="Salem", state="OR", type="vigilant_lpr", lat=44.9429, lng=-123.0351, description="Salem PD Vigilant Solutions LPR.", source="EFF Atlas; Motorola contracts"),
            Infrastructure(name="Vigilant Solutions LEARN — Louisville Metro PD KY", city="Louisville", state="KY", type="vigilant_lpr", lat=38.2527, lng=-85.7585, description="LMPD Vigilant Solutions network.", source="EFF Atlas"),
            Infrastructure(name="Vigilant Solutions LEARN — Lexington PD KY", city="Lexington", state="KY", type="vigilant_lpr", lat=38.0406, lng=-84.5037, description="Lexington PD Vigilant Solutions LPR.", source="EFF Atlas; Motorola contracts"),
            Infrastructure(name="Vigilant Solutions LEARN — Nashville Metro PD TN", city="Nashville", state="TN", type="vigilant_lpr", lat=36.1627, lng=-86.7816, description="MNPD Vigilant Solutions deployment.", source="EFF Atlas"),
            Infrastructure(name="Vigilant Solutions LEARN — Memphis PD TN", city="Memphis", state="TN", type="vigilant_lpr", lat=35.1495, lng=-90.0490, description="Memphis PD Vigilant Solutions LPR.", source="EFF Atlas; Motorola contracts"),
            Infrastructure(name="Vigilant Solutions LEARN — Knoxville PD TN", city="Knoxville", state="TN", type="vigilant_lpr", lat=35.9606, lng=-83.9207, description="Knoxville PD Vigilant Solutions network.", source="EFF Atlas"),
            Infrastructure(name="Vigilant Solutions LEARN — Chattanooga PD TN", city="Chattanooga", state="TN", type="vigilant_lpr", lat=35.0456, lng=-85.3097, description="Chattanooga PD Vigilant Solutions LPR.", source="EFF Atlas; Motorola contracts"),
            Infrastructure(name="Vigilant Solutions LEARN — Charlotte-Mecklenburg PD NC", city="Charlotte", state="NC", type="vigilant_lpr", lat=35.2271, lng=-80.8431, description="CMPD Vigilant Solutions deployment.", source="EFF Atlas"),
            Infrastructure(name="Vigilant Solutions LEARN — Raleigh PD NC", city="Raleigh", state="NC", type="vigilant_lpr", lat=35.7796, lng=-78.6382, description="Raleigh PD Vigilant Solutions LPR.", source="EFF Atlas; Motorola contracts"),
            Infrastructure(name="Vigilant Solutions LEARN — Durham PD NC", city="Durham", state="NC", type="vigilant_lpr", lat=35.9940, lng=-78.8986, description="Durham PD Vigilant Solutions network.", source="EFF Atlas"),
            Infrastructure(name="Vigilant Solutions LEARN — Greensboro PD NC", city="Greensboro", state="NC", type="vigilant_lpr", lat=36.0726, lng=-79.7920, description="Greensboro PD Vigilant Solutions LPR.", source="EFF Atlas; Motorola contracts"),
            Infrastructure(name="Vigilant Solutions LEARN — Columbia SC PD", city="Columbia", state="SC", type="vigilant_lpr", lat=34.0007, lng=-81.0348, description="Columbia SC PD Vigilant Solutions deployment.", source="EFF Atlas"),
            Infrastructure(name="Vigilant Solutions LEARN — Charleston SC PD", city="Charleston", state="SC", type="vigilant_lpr", lat=32.7765, lng=-79.9311, description="Charleston PD Vigilant Solutions LPR.", source="EFF Atlas; Motorola contracts"),
            Infrastructure(name="Vigilant Solutions LEARN — Jacksonville Sheriff FL", city="Jacksonville", state="FL", type="vigilant_lpr", lat=30.3322, lng=-81.6557, description="JSO Vigilant Solutions network.", source="EFF Atlas"),
            Infrastructure(name="Vigilant Solutions LEARN — Tampa PD FL", city="Tampa", state="FL", type="vigilant_lpr", lat=27.9506, lng=-82.4572, description="Tampa PD Vigilant Solutions LPR.", source="EFF Atlas; Motorola contracts"),
            Infrastructure(name="Vigilant Solutions LEARN — Orlando PD FL", city="Orlando", state="FL", type="vigilant_lpr", lat=28.5383, lng=-81.3792, description="Orlando PD Vigilant Solutions deployment.", source="EFF Atlas"),
            Infrastructure(name="Vigilant Solutions LEARN — Tallahassee PD FL", city="Tallahassee", state="FL", type="vigilant_lpr", lat=30.4518, lng=-84.2807, description="Tallahassee PD Vigilant Solutions LPR.", source="EFF Atlas; Motorola contracts"),
            Infrastructure(name="Vigilant Solutions LEARN — Savannah PD GA", city="Savannah", state="GA", type="vigilant_lpr", lat=32.0835, lng=-81.0998, description="Savannah PD Vigilant Solutions network.", source="EFF Atlas"),
            Infrastructure(name="Vigilant Solutions LEARN — Augusta PD GA", city="Augusta", state="GA", type="vigilant_lpr", lat=33.4735, lng=-82.0105, description="Augusta PD Vigilant Solutions LPR.", source="EFF Atlas; Motorola contracts"),
            Infrastructure(name="Vigilant Solutions LEARN — Montgomery PD AL", city="Montgomery", state="AL", type="vigilant_lpr", lat=32.3617, lng=-86.2792, description="Montgomery PD Vigilant Solutions deployment.", source="EFF Atlas"),
            Infrastructure(name="Vigilant Solutions LEARN — Mobile PD AL", city="Mobile", state="AL", type="vigilant_lpr", lat=30.6954, lng=-88.0399, description="Mobile PD Vigilant Solutions LPR.", source="EFF Atlas; Motorola contracts"),
            Infrastructure(name="Vigilant Solutions LEARN — Jackson PD MS", city="Jackson", state="MS", type="vigilant_lpr", lat=32.2988, lng=-90.1848, description="Jackson MS PD Vigilant Solutions network.", source="EFF Atlas"),
            Infrastructure(name="Vigilant Solutions LEARN — Little Rock PD AR", city="Little Rock", state="AR", type="vigilant_lpr", lat=34.7465, lng=-92.2896, description="Little Rock PD Vigilant Solutions LPR.", source="EFF Atlas; Motorola contracts"),
            Infrastructure(name="Vigilant Solutions LEARN — Shreveport PD LA", city="Shreveport", state="LA", type="vigilant_lpr", lat=32.5252, lng=-93.7502, description="Shreveport PD Vigilant Solutions deployment.", source="EFF Atlas"),
            Infrastructure(name="Vigilant Solutions LEARN — Baton Rouge PD LA", city="Baton Rouge", state="LA", type="vigilant_lpr", lat=30.4515, lng=-91.1871, description="Baton Rouge PD Vigilant Solutions LPR.", source="EFF Atlas; Motorola contracts"),
            Infrastructure(name="Vigilant Solutions LEARN — Oklahoma City PD OK", city="Oklahoma City", state="OK", type="vigilant_lpr", lat=35.4676, lng=-97.5164, description="OCPD Vigilant Solutions network.", source="EFF Atlas"),
            Infrastructure(name="Vigilant Solutions LEARN — Tulsa PD OK", city="Tulsa", state="OK", type="vigilant_lpr", lat=36.1540, lng=-95.9928, description="Tulsa PD Vigilant Solutions LPR.", source="EFF Atlas; Motorola contracts"),
            Infrastructure(name="Vigilant Solutions LEARN — Wichita PD KS", city="Wichita", state="KS", type="vigilant_lpr", lat=37.6872, lng=-97.3301, description="Wichita PD Vigilant Solutions deployment.", source="EFF Atlas"),
            Infrastructure(name="Vigilant Solutions LEARN — Des Moines PD IA", city="Des Moines", state="IA", type="vigilant_lpr", lat=41.5868, lng=-93.6250, description="Des Moines PD Vigilant Solutions LPR.", source="EFF Atlas; Motorola contracts"),
            Infrastructure(name="Vigilant Solutions LEARN — Madison PD WI", city="Madison", state="WI", type="vigilant_lpr", lat=43.0731, lng=-89.4012, description="Madison PD Vigilant Solutions network.", source="EFF Atlas"),
            Infrastructure(name="Vigilant Solutions LEARN — Green Bay PD WI", city="Green Bay", state="WI", type="vigilant_lpr", lat=44.5133, lng=-88.0133, description="Green Bay PD Vigilant Solutions LPR.", source="EFF Atlas; Motorola contracts"),
            Infrastructure(name="Vigilant Solutions LEARN — Rochester PD MN", city="Rochester", state="MN", type="vigilant_lpr", lat=44.0121, lng=-92.4802, description="Rochester MN PD Vigilant Solutions deployment.", source="EFF Atlas"),
            Infrastructure(name="Vigilant Solutions LEARN — Duluth PD MN", city="Duluth", state="MN", type="vigilant_lpr", lat=46.7867, lng=-92.1005, description="Duluth PD Vigilant Solutions LPR.", source="EFF Atlas; Motorola contracts"),
            Infrastructure(name="Vigilant Solutions LEARN — Fargo PD ND", city="Fargo", state="ND", type="vigilant_lpr", lat=46.8772, lng=-96.7898, description="Fargo PD Vigilant Solutions network.", source="EFF Atlas"),
            Infrastructure(name="Vigilant Solutions LEARN — Sioux Falls PD SD", city="Sioux Falls", state="SD", type="vigilant_lpr", lat=43.5446, lng=-96.7311, description="Sioux Falls PD Vigilant Solutions LPR.", source="EFF Atlas; Motorola contracts"),
            Infrastructure(name="Vigilant Solutions LEARN — Billings PD MT", city="Billings", state="MT", type="vigilant_lpr", lat=45.7833, lng=-108.5007, description="Billings PD Vigilant Solutions deployment.", source="EFF Atlas"),
            Infrastructure(name="Vigilant Solutions LEARN — Anchorage PD AK", city="Anchorage", state="AK", type="vigilant_lpr", lat=61.2181, lng=-149.9003, description="Anchorage PD Vigilant Solutions LPR.", source="EFF Atlas; Motorola contracts"),
            Infrastructure(name="Vigilant Solutions LEARN — Honolulu PD HI", city="Honolulu", state="HI", type="vigilant_lpr", lat=21.3069, lng=-157.8583, description="Honolulu PD Vigilant Solutions network.", source="EFF Atlas"),

            # ══════════════════════════════════════════════════════════════
            # ADDITIONAL COUNTY IMSI CATCHERS — SMALLER COUNTIES
            # Source: ACLU Stingray tracking, EFF, FOIA
            # ══════════════════════════════════════════════════════════════

            Infrastructure(name="Tarrant County Sheriff IMSI Catcher TX", city="Fort Worth", state="TX", type="county_imsi", lat=32.7555, lng=-97.3308, description="Tarrant County Sheriff Stingray. Fort Worth metro.", source="ACLU Texas"),
            Infrastructure(name="Bexar County Sheriff IMSI Catcher TX", city="San Antonio", state="TX", type="county_imsi", lat=29.4241, lng=-98.4936, description="Bexar County Sheriff Stingray deployment.", source="ACLU Texas"),
            Infrastructure(name="El Paso County Sheriff IMSI Catcher TX", city="El Paso", state="TX", type="county_imsi", lat=31.7619, lng=-106.4850, description="El Paso County Sheriff Stingray. Border operations.", source="ACLU Texas"),
            Infrastructure(name="Travis County Sheriff IMSI Catcher TX", city="Austin", state="TX", type="county_imsi", lat=30.2672, lng=-97.7431, description="Travis County Sheriff Stingray deployment.", source="ACLU Texas"),
            Infrastructure(name="Denton County Sheriff IMSI Catcher TX", city="Denton", state="TX", type="county_imsi", lat=33.2148, lng=-97.1331, description="Denton County Sheriff Stingray.", source="ACLU Texas"),
            Infrastructure(name="Collin County Sheriff IMSI Catcher TX", city="McKinney", state="TX", type="county_imsi", lat=33.1972, lng=-96.6397, description="Collin County Sheriff Stingray deployment.", source="ACLU Texas"),
            Infrastructure(name="Broward County Sheriff IMSI Catcher FL", city="Fort Lauderdale", state="FL", type="county_imsi", lat=26.1224, lng=-80.1373, description="BSO Stingray deployment. Documented use.", source="ACLU Florida"),
            Infrastructure(name="Palm Beach County Sheriff IMSI Catcher FL", city="West Palm Beach", state="FL", type="county_imsi", lat=26.7153, lng=-80.0534, description="PBCSO Stingray use confirmed.", source="ACLU Florida"),
            Infrastructure(name="Sarasota County Sheriff IMSI Catcher FL", city="Sarasota", state="FL", type="county_imsi", lat=27.3364, lng=-82.5307, description="SCSO Stingray. Early adopter — purchased in 2010.", source="ACLU Florida; USA Today"),
            Infrastructure(name="Lee County Sheriff IMSI Catcher FL", city="Fort Myers", state="FL", type="county_imsi", lat=26.6406, lng=-81.8723, description="LCSO Stingray deployment.", source="ACLU Florida"),
            Infrastructure(name="Volusia County Sheriff IMSI Catcher FL", city="DeLand", state="FL", type="county_imsi", lat=29.0286, lng=-81.3034, description="VCSO Stingray use confirmed.", source="ACLU Florida"),
            Infrastructure(name="Brevard County Sheriff IMSI Catcher FL", city="Titusville", state="FL", type="county_imsi", lat=28.6122, lng=-80.8075, description="BCSO Stingray deployment.", source="ACLU Florida"),
            Infrastructure(name="Fulton County Sheriff IMSI Catcher GA", city="Atlanta", state="GA", type="county_imsi", lat=33.7490, lng=-84.3880, description="Fulton County Sheriff Stingray.", source="ACLU Georgia"),
            Infrastructure(name="DeKalb County PD IMSI Catcher GA", city="Decatur", state="GA", type="county_imsi", lat=33.7748, lng=-84.2963, description="DeKalb County PD Stingray deployment.", source="ACLU Georgia"),
            Infrastructure(name="Gwinnett County PD IMSI Catcher GA", city="Lawrenceville", state="GA", type="county_imsi", lat=33.9526, lng=-83.9877, description="Gwinnett County PD Stingray.", source="ACLU Georgia"),
            Infrastructure(name="Cobb County PD IMSI Catcher GA", city="Marietta", state="GA", type="county_imsi", lat=33.9526, lng=-84.5499, description="Cobb County PD Stingray deployment.", source="ACLU Georgia"),
            Infrastructure(name="Maricopa County Sheriff IMSI Catcher AZ", city="Phoenix", state="AZ", type="county_imsi", lat=33.5722, lng=-112.0892, description="MCSO Stingray fleet. Documented use against activists.", source="ACLU Arizona; Phoenix New Times"),
            Infrastructure(name="Pima County Sheriff IMSI Catcher AZ", city="Tucson", state="AZ", type="county_imsi", lat=32.2217, lng=-110.9265, description="PCSO Stingray deployment.", source="ACLU Arizona"),
            Infrastructure(name="Yavapai County Sheriff IMSI Catcher AZ", city="Prescott", state="AZ", type="county_imsi", lat=34.5400, lng=-112.4685, description="Yavapai County Sheriff Stingray.", source="ACLU Arizona"),
            Infrastructure(name="Yuma County Sheriff IMSI Catcher AZ", city="Yuma", state="AZ", type="county_imsi", lat=32.6927, lng=-114.6277, description="Yuma County Sheriff Stingray. Border operations.", source="ACLU Arizona"),
            Infrastructure(name="Ada County Sheriff IMSI Catcher ID", city="Boise", state="ID", type="county_imsi", lat=43.6150, lng=-116.2023, description="Ada County Sheriff Stingray deployment.", source="ACLU Idaho"),
            Infrastructure(name="Salt Lake County Sheriff IMSI Catcher UT", city="Salt Lake City", state="UT", type="county_imsi", lat=40.7608, lng=-111.8910, description="Salt Lake County Sheriff Stingray.", source="ACLU Utah"),
            Infrastructure(name="Utah County Sheriff IMSI Catcher UT", city="Provo", state="UT", type="county_imsi", lat=40.2338, lng=-111.6585, description="Utah County Sheriff Stingray deployment.", source="ACLU Utah"),
            Infrastructure(name="Bernalillo County Sheriff IMSI Catcher NM", city="Albuquerque", state="NM", type="county_imsi", lat=35.0844, lng=-106.6504, description="Bernalillo County Sheriff Stingray.", source="ACLU NM"),
            Infrastructure(name="El Paso County Sheriff IMSI Catcher CO", city="Colorado Springs", state="CO", type="county_imsi", lat=38.8339, lng=-104.8214, description="El Paso County CO Sheriff Stingray.", source="ACLU Colorado"),
            Infrastructure(name="Jefferson County Sheriff IMSI Catcher CO", city="Golden", state="CO", type="county_imsi", lat=39.7555, lng=-105.2211, description="Jefferson County Sheriff Stingray deployment.", source="ACLU Colorado"),
            Infrastructure(name="Arapahoe County Sheriff IMSI Catcher CO", city="Centennial", state="CO", type="county_imsi", lat=39.5772, lng=-104.8769, description="Arapahoe County Sheriff Stingray.", source="ACLU Colorado"),
            Infrastructure(name="Clark County Sheriff IMSI Catcher NV", city="Las Vegas", state="NV", type="county_imsi", lat=36.1699, lng=-115.1398, description="CCSD Stingray deployment. Las Vegas metro.", source="ACLU Nevada"),
            Infrastructure(name="Washoe County Sheriff IMSI Catcher NV", city="Reno", state="NV", type="county_imsi", lat=39.5296, lng=-119.8138, description="Washoe County Sheriff Stingray.", source="ACLU Nevada"),
            Infrastructure(name="Pierce County Sheriff IMSI Catcher WA", city="Tacoma", state="WA", type="county_imsi", lat=47.2529, lng=-122.4443, description="Pierce County Sheriff Stingray deployment.", source="ACLU WA"),
            Infrastructure(name="Snohomish County Sheriff IMSI Catcher WA", city="Everett", state="WA", type="county_imsi", lat=47.9790, lng=-122.2021, description="Snohomish County Sheriff Stingray.", source="ACLU WA"),
            Infrastructure(name="Clackamas County Sheriff IMSI Catcher OR", city="Oregon City", state="OR", type="county_imsi", lat=45.3565, lng=-122.6068, description="Clackamas County Sheriff Stingray deployment.", source="ACLU Oregon"),
            Infrastructure(name="Washington County Sheriff IMSI Catcher OR", city="Hillsboro", state="OR", type="county_imsi", lat=45.5229, lng=-122.9898, description="Washington County OR Sheriff Stingray.", source="ACLU Oregon"),
            Infrastructure(name="Ramsey County Sheriff IMSI Catcher MN", city="St. Paul", state="MN", type="county_imsi", lat=44.9537, lng=-93.0900, description="Ramsey County Sheriff Stingray deployment.", source="ACLU MN"),
            Infrastructure(name="Olmsted County Sheriff IMSI Catcher MN", city="Rochester", state="MN", type="county_imsi", lat=44.0121, lng=-92.4802, description="Olmsted County Sheriff Stingray.", source="ACLU MN"),
            Infrastructure(name="Milwaukee County Sheriff IMSI Catcher WI", city="Milwaukee", state="WI", type="county_imsi", lat=43.0389, lng=-87.9065, description="Milwaukee County Sheriff Stingray deployment.", source="ACLU WI"),
            Infrastructure(name="Dane County Sheriff IMSI Catcher WI", city="Madison", state="WI", type="county_imsi", lat=43.0731, lng=-89.4012, description="Dane County Sheriff Stingray.", source="ACLU WI"),
            Infrastructure(name="Lake County Sheriff IMSI Catcher IL", city="Waukegan", state="IL", type="county_imsi", lat=42.3636, lng=-87.8448, description="Lake County IL Sheriff Stingray deployment.", source="ACLU IL"),
            Infrastructure(name="DuPage County Sheriff IMSI Catcher IL", city="Wheaton", state="IL", type="county_imsi", lat=41.8659, lng=-88.1073, description="DuPage County Sheriff Stingray.", source="ACLU IL"),
            Infrastructure(name="Will County Sheriff IMSI Catcher IL", city="Joliet", state="IL", type="county_imsi", lat=41.5250, lng=-88.0817, description="Will County Sheriff Stingray deployment.", source="ACLU IL"),
            Infrastructure(name="St. Louis County PD IMSI Catcher MO", city="Clayton", state="MO", type="county_imsi", lat=38.6490, lng=-90.3238, description="St. Louis County PD Stingray. Separate from city.", source="ACLU Missouri"),
            Infrastructure(name="Jackson County Sheriff IMSI Catcher MO", city="Kansas City", state="MO", type="county_imsi", lat=39.0997, lng=-94.5786, description="Jackson County Sheriff Stingray deployment.", source="ACLU Missouri"),
            Infrastructure(name="Jefferson Parish Sheriff IMSI Catcher LA", city="Gretna", state="LA", type="county_imsi", lat=29.9143, lng=-90.0532, description="Jefferson Parish Sheriff Stingray.", source="ACLU Louisiana"),
            Infrastructure(name="East Baton Rouge Sheriff IMSI Catcher LA", city="Baton Rouge", state="LA", type="county_imsi", lat=30.4515, lng=-91.1871, description="EBR Sheriff Stingray deployment.", source="ACLU Louisiana"),
            Infrastructure(name="Caddo Parish Sheriff IMSI Catcher LA", city="Shreveport", state="LA", type="county_imsi", lat=32.5252, lng=-93.7502, description="Caddo Parish Sheriff Stingray.", source="ACLU Louisiana"),
            Infrastructure(name="Jefferson County Sheriff IMSI Catcher AL", city="Birmingham", state="AL", type="county_imsi", lat=33.5186, lng=-86.8104, description="Jefferson County AL Sheriff Stingray deployment.", source="ACLU Alabama"),
            Infrastructure(name="Shelby County Sheriff IMSI Catcher TN", city="Memphis", state="TN", type="county_imsi", lat=35.1495, lng=-90.0490, description="Shelby County Sheriff Stingray.", source="ACLU TN"),
            Infrastructure(name="Davidson County Sheriff IMSI Catcher TN", city="Nashville", state="TN", type="county_imsi", lat=36.1627, lng=-86.7816, description="Davidson County Sheriff Stingray deployment.", source="ACLU TN"),
            Infrastructure(name="Knox County Sheriff IMSI Catcher TN", city="Knoxville", state="TN", type="county_imsi", lat=35.9606, lng=-83.9207, description="Knox County Sheriff Stingray.", source="ACLU TN"),
            Infrastructure(name="Hamilton County Sheriff IMSI Catcher TN", city="Chattanooga", state="TN", type="county_imsi", lat=35.0456, lng=-85.3097, description="Hamilton County TN Sheriff Stingray deployment.", source="ACLU TN"),
            Infrastructure(name="Wake County Sheriff IMSI Catcher NC", city="Raleigh", state="NC", type="county_imsi", lat=35.7796, lng=-78.6382, description="Wake County Sheriff Stingray.", source="ACLU NC"),
            Infrastructure(name="Mecklenburg County Sheriff IMSI Catcher NC", city="Charlotte", state="NC", type="county_imsi", lat=35.2271, lng=-80.8431, description="Mecklenburg County Sheriff Stingray deployment.", source="ACLU NC"),
            Infrastructure(name="Guilford County Sheriff IMSI Catcher NC", city="Greensboro", state="NC", type="county_imsi", lat=36.0726, lng=-79.7920, description="Guilford County Sheriff Stingray.", source="ACLU NC"),
            Infrastructure(name="Richland County Sheriff IMSI Catcher SC", city="Columbia", state="SC", type="county_imsi", lat=34.0007, lng=-81.0348, description="Richland County Sheriff Stingray deployment.", source="ACLU SC"),
            Infrastructure(name="Charleston County Sheriff IMSI Catcher SC", city="Charleston", state="SC", type="county_imsi", lat=32.7765, lng=-79.9311, description="Charleston County Sheriff Stingray.", source="ACLU SC"),
            Infrastructure(name="Fairfax County PD IMSI Catcher VA", city="Fairfax", state="VA", type="county_imsi", lat=38.8462, lng=-77.3064, description="FCPD Stingray deployment. Northern Virginia.", source="ACLU VA"),
            Infrastructure(name="Arlington County PD IMSI Catcher VA", city="Arlington", state="VA", type="county_imsi", lat=38.8799, lng=-77.1068, description="ACPD Stingray. Pentagon proximity.", source="ACLU VA"),
            Infrastructure(name="Chesterfield County PD IMSI Catcher VA", city="Chesterfield", state="VA", type="county_imsi", lat=37.3776, lng=-77.5131, description="Chesterfield County PD Stingray.", source="ACLU VA"),
            Infrastructure(name="Prince William County PD IMSI Catcher VA", city="Woodbridge", state="VA", type="county_imsi", lat=38.6582, lng=-77.2497, description="Prince William County PD Stingray deployment.", source="ACLU VA"),
            Infrastructure(name="Loudoun County Sheriff IMSI Catcher VA", city="Leesburg", state="VA", type="county_imsi", lat=39.1151, lng=-77.5636, description="Loudoun County Sheriff Stingray.", source="ACLU VA"),
            Infrastructure(name="Anne Arundel County PD IMSI Catcher MD", city="Annapolis", state="MD", type="county_imsi", lat=38.9784, lng=-76.4922, description="AACPD Stingray deployment.", source="ACLU Maryland"),
            Infrastructure(name="Baltimore County PD IMSI Catcher MD", city="Towson", state="MD", type="county_imsi", lat=39.3976, lng=-76.6039, description="Baltimore County PD Stingray.", source="ACLU Maryland"),
            Infrastructure(name="Howard County PD IMSI Catcher MD", city="Ellicott City", state="MD", type="county_imsi", lat=39.2676, lng=-76.7983, description="Howard County PD Stingray deployment.", source="ACLU Maryland"),
            Infrastructure(name="Bucks County DA IMSI Catcher PA", city="Doylestown", state="PA", type="county_imsi", lat=40.3101, lng=-75.1299, description="Bucks County DA Stingray. DA offices operate independently.", source="ACLU PA"),
            Infrastructure(name="Montgomery County PA PD IMSI Catcher", city="Norristown", state="PA", type="county_imsi", lat=40.1215, lng=-75.3398, description="Montgomery County PA PD Stingray deployment.", source="ACLU PA"),
            Infrastructure(name="Delaware County PA PD IMSI Catcher", city="Media", state="PA", type="county_imsi", lat=39.9173, lng=-75.3879, description="Delaware County PA PD Stingray.", source="ACLU PA"),
            Infrastructure(name="Onondaga County Sheriff IMSI Catcher NY", city="Syracuse", state="NY", type="county_imsi", lat=43.0481, lng=-76.1474, description="Onondaga County Sheriff Stingray deployment.", source="ACLU NY"),
            Infrastructure(name="Erie County Sheriff IMSI Catcher NY", city="Buffalo", state="NY", type="county_imsi", lat=42.8864, lng=-78.8784, description="Erie County Sheriff Stingray.", source="ACLU NY"),
            Infrastructure(name="Monroe County Sheriff IMSI Catcher NY", city="Rochester", state="NY", type="county_imsi", lat=43.1566, lng=-77.6088, description="Monroe County Sheriff Stingray deployment.", source="ACLU NY"),
            Infrastructure(name="Albany County Sheriff IMSI Catcher NY", city="Albany", state="NY", type="county_imsi", lat=42.6526, lng=-73.7562, description="Albany County Sheriff Stingray.", source="ACLU NY"),
            Infrastructure(name="Rockland County Sheriff IMSI Catcher NY", city="New City", state="NY", type="county_imsi", lat=41.1476, lng=-73.9893, description="Rockland County Sheriff Stingray deployment.", source="ACLU NY"),

            # ══════════════════════════════════════════════════════════════
            # POLICE DRONES — ADDITIONAL AGENCIES AND PRECINCTS
            # Source: FAA records, EFF Atlas, local news
            # ══════════════════════════════════════════════════════════════

            Infrastructure(name="NYPD Drone — 40th Precinct South Bronx", city="New York", state="NY", type="police_drone", lat=40.8120, lng=-73.9270, description="NYPD drone operations from 40th Precinct. South Bronx.", source="FAA records; NYCLU"),
            Infrastructure(name="NYPD Drone — 75th Precinct East New York", city="New York", state="NY", type="police_drone", lat=40.6630, lng=-73.8820, description="NYPD drone operations from 75th Precinct. East New York.", source="FAA records; NYCLU"),
            Infrastructure(name="NYPD Drone — 73rd Precinct Brownsville", city="New York", state="NY", type="police_drone", lat=40.6620, lng=-73.9110, description="NYPD drone from 73rd Precinct. Brownsville.", source="FAA records; NYCLU"),
            Infrastructure(name="LAPD Drone — 77th Street Division", city="Los Angeles", state="CA", type="police_drone", lat=33.9970, lng=-118.2970, description="LAPD drone operations from 77th Street Division. South LA.", source="FAA records; EFF Atlas"),
            Infrastructure(name="LAPD Drone — Southeast Division", city="Los Angeles", state="CA", type="police_drone", lat=33.9730, lng=-118.2480, description="LAPD drone from Southeast Division. Watts area.", source="FAA records; EFF Atlas"),
            Infrastructure(name="LAPD Drone — Newton Division", city="Los Angeles", state="CA", type="police_drone", lat=34.0130, lng=-118.2540, description="LAPD drone operations from Newton Division.", source="FAA records; EFF Atlas"),
            Infrastructure(name="LAPD Drone — Hollenbeck Division", city="Los Angeles", state="CA", type="police_drone", lat=34.0540, lng=-118.2010, description="LAPD drone from Hollenbeck Division. East LA.", source="FAA records; EFF Atlas"),
            Infrastructure(name="CPD Drone — District 11 Harrison", city="Chicago", state="IL", type="police_drone", lat=41.8730, lng=-87.7350, description="CPD drone from District 11. West Garfield Park.", source="FAA records; Chicago Tribune"),
            Infrastructure(name="CPD Drone — District 7 Englewood", city="Chicago", state="IL", type="police_drone", lat=41.7790, lng=-87.6470, description="CPD drone from District 7. Englewood.", source="FAA records; Chicago Tribune"),
            Infrastructure(name="CPD Drone — District 3 Grand Crossing", city="Chicago", state="IL", type="police_drone", lat=41.7590, lng=-87.6020, description="CPD drone from District 3. Grand Crossing.", source="FAA records; Chicago Tribune"),
            Infrastructure(name="Houston PD Drone — North Division", city="Houston", state="TX", type="police_drone", lat=29.8450, lng=-95.3980, description="HPD drone operations from North Division.", source="FAA records; EFF Atlas"),
            Infrastructure(name="Houston PD Drone — Northeast Division", city="Houston", state="TX", type="police_drone", lat=29.8150, lng=-95.3120, description="HPD drone from Northeast Division.", source="FAA records; EFF Atlas"),
            Infrastructure(name="Houston PD Drone — Southeast Division", city="Houston", state="TX", type="police_drone", lat=29.7010, lng=-95.2940, description="HPD drone from Southeast Division.", source="FAA records; EFF Atlas"),
            Infrastructure(name="Houston PD Drone — Southwest Division", city="Houston", state="TX", type="police_drone", lat=29.6900, lng=-95.5000, description="HPD drone from Southwest Division.", source="FAA records; EFF Atlas"),
            Infrastructure(name="Miami-Dade PD Drone — North District", city="Miami", state="FL", type="police_drone", lat=25.9000, lng=-80.2000, description="MDPD drone operations North District.", source="FAA records; EFF Atlas"),
            Infrastructure(name="Miami-Dade PD Drone — South District", city="Miami", state="FL", type="police_drone", lat=25.6500, lng=-80.4000, description="MDPD drone from South District.", source="FAA records; EFF Atlas"),
            Infrastructure(name="Miami-Dade PD Drone — West District", city="Miami", state="FL", type="police_drone", lat=25.7500, lng=-80.5000, description="MDPD drone operations West District.", source="FAA records; EFF Atlas"),
            Infrastructure(name="Dallas PD Drone — South Central Division", city="Dallas", state="TX", type="police_drone", lat=32.7360, lng=-96.7970, description="DPD drone from South Central Division.", source="FAA records; EFF Atlas"),
            Infrastructure(name="Dallas PD Drone — Southeast Division", city="Dallas", state="TX", type="police_drone", lat=32.7350, lng=-96.7360, description="DPD drone from Southeast Division.", source="FAA records; EFF Atlas"),
            Infrastructure(name="Dallas PD Drone — Southwest Division", city="Dallas", state="TX", type="police_drone", lat=32.7130, lng=-96.8700, description="DPD drone from Southwest Division.", source="FAA records; EFF Atlas"),
            Infrastructure(name="Philadelphia PD Drone — South Division", city="Philadelphia", state="PA", type="police_drone", lat=39.9270, lng=-75.1580, description="PPD drone from South Division.", source="FAA records; EFF Atlas"),
            Infrastructure(name="Philadelphia PD Drone — North Division", city="Philadelphia", state="PA", type="police_drone", lat=39.9920, lng=-75.1580, description="PPD drone from North Division.", source="FAA records; EFF Atlas"),
            Infrastructure(name="Philadelphia PD Drone — West Division", city="Philadelphia", state="PA", type="police_drone", lat=39.9680, lng=-75.2290, description="PPD drone from West Division.", source="FAA records; EFF Atlas"),
            Infrastructure(name="San Antonio PD Drone — South", city="San Antonio", state="TX", type="police_drone", lat=29.3810, lng=-98.4810, description="SAPD drone from South substation.", source="FAA records; EFF Atlas"),
            Infrastructure(name="San Antonio PD Drone — West", city="San Antonio", state="TX", type="police_drone", lat=29.4240, lng=-98.5610, description="SAPD drone from West substation.", source="FAA records; EFF Atlas"),
            Infrastructure(name="Phoenix PD Drone — South Mountain", city="Phoenix", state="AZ", type="police_drone", lat=33.3620, lng=-112.0460, description="Phoenix PD drone from South Mountain precinct.", source="FAA records; EFF Atlas"),
            Infrastructure(name="Phoenix PD Drone — Maryvale", city="Phoenix", state="AZ", type="police_drone", lat=33.4720, lng=-112.1430, description="Phoenix PD drone from Maryvale precinct.", source="FAA records; EFF Atlas"),
            Infrastructure(name="Phoenix PD Drone — Desert Horizon", city="Phoenix", state="AZ", type="police_drone", lat=33.6340, lng=-111.9780, description="Phoenix PD drone from Desert Horizon precinct.", source="FAA records; EFF Atlas"),
            Infrastructure(name="Baltimore PD Drone — Eastern District", city="Baltimore", state="MD", type="police_drone", lat=39.2990, lng=-76.5810, description="BPD drone from Eastern District.", source="FAA records; Baltimore Sun"),
            Infrastructure(name="Baltimore PD Drone — Western District", city="Baltimore", state="MD", type="police_drone", lat=39.2970, lng=-76.6490, description="BPD drone from Western District.", source="FAA records; Baltimore Sun"),
            Infrastructure(name="Memphis PD Drone — Raines Road", city="Memphis", state="TN", type="police_drone", lat=35.0370, lng=-90.0490, description="Memphis PD drone from South Memphis substation.", source="FAA records; EFF Atlas"),
            Infrastructure(name="Memphis PD Drone — Tillman Cove", city="Memphis", state="TN", type="police_drone", lat=35.1980, lng=-90.0490, description="Memphis PD drone from North Memphis substation.", source="FAA records; EFF Atlas"),
            Infrastructure(name="Detroit PD Drone — East Side", city="Detroit", state="MI", type="police_drone", lat=42.3522, lng=-82.9918, description="DPD drone operations from East Side precinct.", source="FAA records; EFF Atlas"),
            Infrastructure(name="Detroit PD Drone — West Side", city="Detroit", state="MI", type="police_drone", lat=42.3314, lng=-83.1024, description="DPD drone from West Side precinct.", source="FAA records; EFF Atlas"),
            Infrastructure(name="Detroit PD Drone — Northeast", city="Detroit", state="MI", type="police_drone", lat=42.3950, lng=-83.0200, description="DPD drone operations from Northeast precinct.", source="FAA records; EFF Atlas"),
            Infrastructure(name="Columbus PD Drone — East District", city="Columbus", state="OH", type="police_drone", lat=39.9640, lng=-82.9430, description="CPD drone from East District.", source="FAA records; EFF Atlas"),
            Infrastructure(name="Columbus PD Drone — South District", city="Columbus", state="OH", type="police_drone", lat=39.9260, lng=-82.9990, description="CPD drone from South District.", source="FAA records; EFF Atlas"),
            Infrastructure(name="Columbus PD Drone — West District", city="Columbus", state="OH", type="police_drone", lat=39.9640, lng=-83.0560, description="CPD drone from West District.", source="FAA records; EFF Atlas"),
            Infrastructure(name="Minneapolis PD Drone — 3rd Precinct", city="Minneapolis", state="MN", type="police_drone", lat=44.9380, lng=-93.2490, description="MPD drone from 3rd Precinct. George Floyd area.", source="FAA records; Star Tribune"),
            Infrastructure(name="Minneapolis PD Drone — 4th Precinct", city="Minneapolis", state="MN", type="police_drone", lat=44.9990, lng=-93.3020, description="MPD drone from 4th Precinct. North Minneapolis.", source="FAA records; Star Tribune"),
            Infrastructure(name="Denver PD Drone — District 2", city="Denver", state="CO", type="police_drone", lat=39.7840, lng=-104.9390, description="DPD drone from District 2. Northeast Denver.", source="FAA records; EFF Atlas"),
            Infrastructure(name="Denver PD Drone — District 4", city="Denver", state="CO", type="police_drone", lat=39.7010, lng=-105.0240, description="DPD drone from District 4. Southwest Denver.", source="FAA records; EFF Atlas"),
            Infrastructure(name="Denver PD Drone — District 5", city="Denver", state="CO", type="police_drone", lat=39.7770, lng=-105.0380, description="DPD drone from District 5. Northwest Denver.", source="FAA records; EFF Atlas"),
            Infrastructure(name="Seattle PD Drone — South Precinct", city="Seattle", state="WA", type="police_drone", lat=47.5537, lng=-122.2989, description="SPD drone from South Precinct. Rainier Valley.", source="FAA records; ACLU WA"),
            Infrastructure(name="Seattle PD Drone — East Precinct", city="Seattle", state="WA", type="police_drone", lat=47.6205, lng=-122.3212, description="SPD drone from East Precinct. Capitol Hill.", source="FAA records; ACLU WA"),
            Infrastructure(name="Atlanta PD Drone — Zone 1", city="Atlanta", state="GA", type="police_drone", lat=33.7820, lng=-84.4230, description="APD drone from Zone 1. Northwest Atlanta.", source="FAA records; EFF Atlas"),
            Infrastructure(name="Atlanta PD Drone — Zone 3", city="Atlanta", state="GA", type="police_drone", lat=33.7090, lng=-84.4460, description="APD drone from Zone 3. Southwest Atlanta.", source="FAA records; EFF Atlas"),
            Infrastructure(name="Atlanta PD Drone — Zone 4", city="Atlanta", state="GA", type="police_drone", lat=33.7130, lng=-84.3820, description="APD drone from Zone 4. Southeast Atlanta.", source="FAA records; EFF Atlas"),
            Infrastructure(name="New Orleans PD Drone — 5th District", city="New Orleans", state="LA", type="police_drone", lat=29.9710, lng=-89.9990, description="NOPD drone from 5th District. Lower Ninth Ward.", source="FAA records; EFF Atlas"),
            Infrastructure(name="New Orleans PD Drone — 7th District", city="New Orleans", state="LA", type="police_drone", lat=30.0160, lng=-89.9510, description="NOPD drone from 7th District. New Orleans East.", source="FAA records; EFF Atlas"),
            Infrastructure(name="Kansas City PD Drone — East Patrol", city="Kansas City", state="MO", type="police_drone", lat=39.0970, lng=-94.5090, description="KCPD drone from East Patrol Division.", source="FAA records; EFF Atlas"),
            Infrastructure(name="Kansas City PD Drone — South Patrol", city="Kansas City", state="MO", type="police_drone", lat=39.0460, lng=-94.5710, description="KCPD drone from South Patrol Division.", source="FAA records; EFF Atlas"),
            Infrastructure(name="Louisville Metro PD Drone — 2nd Division", city="Louisville", state="KY", type="police_drone", lat=38.2530, lng=-85.8090, description="LMPD drone from 2nd Division. West Louisville.", source="FAA records; EFF Atlas"),
            Infrastructure(name="Louisville Metro PD Drone — 4th Division", city="Louisville", state="KY", type="police_drone", lat=38.2020, lng=-85.7510, description="LMPD drone from 4th Division. South Louisville.", source="FAA records; EFF Atlas"),
            Infrastructure(name="Indianapolis Metro PD Drone — East District", city="Indianapolis", state="IN", type="police_drone", lat=39.7700, lng=-86.0990, description="IMPD drone from East District.", source="FAA records; EFF Atlas"),
            Infrastructure(name="Indianapolis Metro PD Drone — North District", city="Indianapolis", state="IN", type="police_drone", lat=39.8350, lng=-86.1580, description="IMPD drone from North District.", source="FAA records; EFF Atlas"),
            Infrastructure(name="Milwaukee PD Drone — District 5", city="Milwaukee", state="WI", type="police_drone", lat=43.0540, lng=-87.9660, description="Milwaukee PD drone from District 5.", source="FAA records; EFF Atlas"),
            Infrastructure(name="Milwaukee PD Drone — District 7", city="Milwaukee", state="WI", type="police_drone", lat=43.0150, lng=-87.9550, description="Milwaukee PD drone from District 7.", source="FAA records; EFF Atlas"),

            # ══════════════════════════════════════════════════════════════
            # ADDITIONAL JTTF LOCATIONS
            # Source: FBI public directory
            # ══════════════════════════════════════════════════════════════

            Infrastructure(name="JTTF — Baton Rouge LA", city="Baton Rouge", state="LA", type="jttf", lat=30.4515, lng=-91.1871, description="Baton Rouge JTTF.", source="FBI"),
            Infrastructure(name="JTTF — Little Rock AR", city="Little Rock", state="AR", type="jttf", lat=34.7465, lng=-92.2896, description="Little Rock JTTF.", source="FBI"),
            Infrastructure(name="JTTF — Jackson MS", city="Jackson", state="MS", type="jttf", lat=32.2988, lng=-90.1848, description="Jackson MS JTTF.", source="FBI"),
            Infrastructure(name="JTTF — Mobile AL", city="Mobile", state="AL", type="jttf", lat=30.6954, lng=-88.0399, description="Mobile JTTF.", source="FBI"),
            Infrastructure(name="JTTF — Birmingham AL", city="Birmingham", state="AL", type="jttf", lat=33.5186, lng=-86.8104, description="Birmingham JTTF.", source="FBI"),
            Infrastructure(name="JTTF — Columbia SC", city="Columbia", state="SC", type="jttf", lat=34.0007, lng=-81.0348, description="Columbia SC JTTF.", source="FBI"),
            Infrastructure(name="JTTF — Lexington KY", city="Lexington", state="KY", type="jttf", lat=38.0406, lng=-84.5037, description="Lexington KY JTTF.", source="FBI"),
            Infrastructure(name="JTTF — Providence RI", city="Providence", state="RI", type="jttf", lat=41.8240, lng=-71.4128, description="Providence JTTF.", source="FBI"),
            Infrastructure(name="JTTF — Hartford CT", city="Hartford", state="CT", type="jttf", lat=41.7637, lng=-72.6851, description="Hartford JTTF.", source="FBI"),
            Infrastructure(name="JTTF — Albany NY", city="Albany", state="NY", type="jttf", lat=42.6526, lng=-73.7562, description="Albany NY JTTF.", source="FBI"),
            Infrastructure(name="JTTF — Springfield MA", city="Springfield", state="MA", type="jttf", lat=42.1015, lng=-72.5898, description="Springfield MA JTTF.", source="FBI"),
            Infrastructure(name="JTTF — Honolulu HI", city="Honolulu", state="HI", type="jttf", lat=21.3069, lng=-157.8583, description="Honolulu JTTF. Pacific operations.", source="FBI"),
            Infrastructure(name="JTTF — Anchorage AK", city="Anchorage", state="AK", type="jttf", lat=61.2181, lng=-149.9003, description="Anchorage JTTF. Alaska operations.", source="FBI"),
            Infrastructure(name="JTTF — Fargo ND", city="Fargo", state="ND", type="jttf", lat=46.8772, lng=-96.7898, description="Fargo JTTF.", source="FBI"),
            Infrastructure(name="JTTF — Sioux Falls SD", city="Sioux Falls", state="SD", type="jttf", lat=43.5446, lng=-96.7311, description="Sioux Falls JTTF.", source="FBI"),
            Infrastructure(name="JTTF — Billings MT", city="Billings", state="MT", type="jttf", lat=45.7833, lng=-108.5007, description="Billings JTTF.", source="FBI"),
            Infrastructure(name="JTTF — Cheyenne WY", city="Cheyenne", state="WY", type="jttf", lat=41.1400, lng=-104.8202, description="Cheyenne JTTF.", source="FBI"),
            Infrastructure(name="JTTF — Boise ID", city="Boise", state="ID", type="jttf", lat=43.6150, lng=-116.2023, description="Boise JTTF.", source="FBI"),
            Infrastructure(name="JTTF — Helena MT", city="Helena", state="MT", type="jttf", lat=46.5958, lng=-112.0270, description="Helena JTTF. Montana operations.", source="FBI"),
            Infrastructure(name="JTTF — Jackson WY", city="Jackson", state="WY", type="jttf", lat=43.4799, lng=-110.7624, description="Jackson WY JTTF.", source="FBI"),
            Infrastructure(name="JTTF — Spokane WA", city="Spokane", state="WA", type="jttf", lat=47.6587, lng=-117.4260, description="Spokane JTTF.", source="FBI"),
            Infrastructure(name="JTTF — Eugene OR", city="Eugene", state="OR", type="jttf", lat=44.0521, lng=-123.0868, description="Eugene JTTF.", source="FBI"),
            Infrastructure(name="JTTF — Reno NV", city="Reno", state="NV", type="jttf", lat=39.5296, lng=-119.8138, description="Reno JTTF.", source="FBI"),
            Infrastructure(name="JTTF — Fresno CA", city="Fresno", state="CA", type="jttf", lat=36.7378, lng=-119.7871, description="Fresno JTTF.", source="FBI"),
            Infrastructure(name="JTTF — Bakersfield CA", city="Bakersfield", state="CA", type="jttf", lat=35.3733, lng=-119.0187, description="Bakersfield JTTF.", source="FBI"),
            Infrastructure(name="JTTF — Riverside CA", city="Riverside", state="CA", type="jttf", lat=33.9533, lng=-117.3961, description="Riverside JTTF.", source="FBI"),
            Infrastructure(name="JTTF — Stockton CA", city="Stockton", state="CA", type="jttf", lat=37.9577, lng=-121.2908, description="Stockton JTTF.", source="FBI"),
            Infrastructure(name="JTTF — Sacramento CA", city="Sacramento", state="CA", type="jttf", lat=38.5816, lng=-121.4944, description="Sacramento JTTF.", source="FBI"),
            Infrastructure(name="JTTF — Colorado Springs CO", city="Colorado Springs", state="CO", type="jttf", lat=38.8339, lng=-104.8214, description="Colorado Springs JTTF. Military city.", source="FBI"),
            Infrastructure(name="JTTF — Wichita KS", city="Wichita", state="KS", type="jttf", lat=37.6872, lng=-97.3301, description="Wichita JTTF.", source="FBI"),
            Infrastructure(name="JTTF — Des Moines IA", city="Des Moines", state="IA", type="jttf", lat=41.5868, lng=-93.6250, description="Des Moines JTTF.", source="FBI"),
            Infrastructure(name="JTTF — Madison WI", city="Madison", state="WI", type="jttf", lat=43.0731, lng=-89.4012, description="Madison WI JTTF.", source="FBI"),
            Infrastructure(name="JTTF — Grand Rapids MI", city="Grand Rapids", state="MI", type="jttf", lat=42.9634, lng=-85.6681, description="Grand Rapids JTTF.", source="FBI"),
            Infrastructure(name="JTTF — Lansing MI", city="Lansing", state="MI", type="jttf", lat=42.7325, lng=-84.5555, description="Lansing JTTF.", source="FBI"),
            Infrastructure(name="JTTF — Fort Wayne IN", city="Fort Wayne", state="IN", type="jttf", lat=41.1306, lng=-85.1289, description="Fort Wayne JTTF.", source="FBI"),
            Infrastructure(name="JTTF — South Bend IN", city="South Bend", state="IN", type="jttf", lat=41.6764, lng=-86.2520, description="South Bend JTTF.", source="FBI"),
            Infrastructure(name="JTTF — Evansville IN", city="Evansville", state="IN", type="jttf", lat=37.9716, lng=-87.5711, description="Evansville JTTF.", source="FBI"),
            Infrastructure(name="JTTF — Peoria IL", city="Peoria", state="IL", type="jttf", lat=40.6936, lng=-89.5890, description="Peoria JTTF.", source="FBI"),
            Infrastructure(name="JTTF — Rockford IL", city="Rockford", state="IL", type="jttf", lat=42.2711, lng=-89.0940, description="Rockford JTTF.", source="FBI"),

            # ══════════════════════════════════════════════════════════════
            # FACIAL RECOGNITION / AI SURVEILLANCE — ADDITIONAL AGENCIES
            # Source: EFF Atlas, GAO reports, ACLU, NIST evaluations
            # ══════════════════════════════════════════════════════════════

            Infrastructure(name="DataWorks Plus Facial Recognition — Pinellas County FL", city="Clearwater", state="FL", type="facial_recognition", lat=27.9659, lng=-82.8001, description="Pinellas County Sheriff DataWorks Plus facial recognition. Most searches per capita of any US agency. 3,000+ searches/month.", source="EFF Atlas; Tampa Bay Times; GAO"),
            Infrastructure(name="DataWorks Plus Facial Recognition — Detroit PD MI", city="Detroit", state="MI", type="facial_recognition", lat=42.3314, lng=-83.0458, description="DPD DataWorks Plus. Project Green Light integration. Documented wrongful arrests of Black men.", source="EFF Atlas; MIT Media Lab; NYT"),
            Infrastructure(name="DataWorks Plus Facial Recognition — Chicago PD IL", city="Chicago", state="IL", type="facial_recognition", lat=41.8781, lng=-87.6298, description="CPD DataWorks Plus facial recognition system.", source="EFF Atlas; Chicago Tribune"),
            Infrastructure(name="Amazon Rekognition — Orlando PD FL", city="Orlando", state="FL", type="facial_recognition", lat=28.5383, lng=-81.3792, description="Orlando PD Amazon Rekognition pilot. Terminated after ACLU pressure.", source="ACLU; EFF Atlas; Washington Post"),
            Infrastructure(name="Amazon Rekognition — Washington County Sheriff OR", city="Hillsboro", state="OR", type="facial_recognition", lat=45.5229, lng=-122.9898, description="Washington County OR Sheriff Amazon Rekognition. First law enforcement Rekognition user.", source="EFF Atlas; The Intercept"),
            Infrastructure(name="NEC NeoFace Facial Recognition — NYPD NY", city="New York", state="NY", type="facial_recognition", lat=40.7128, lng=-74.0060, description="NYPD NEC NeoFace facial recognition. Domain Awareness System integration. 22,000+ searches.", source="EFF Atlas; NYCLU; The Verge"),
            Infrastructure(name="NEC NeoFace Facial Recognition — Dallas PD TX", city="Dallas", state="TX", type="facial_recognition", lat=32.7767, lng=-96.7970, description="DPD NEC facial recognition system.", source="EFF Atlas; Dallas Morning News"),
            Infrastructure(name="Idemia Facial Recognition — FBI NGI System", city="Clarksburg", state="WV", type="facial_recognition", lat=39.2806, lng=-80.3445, description="FBI Next Generation Identification facial recognition. 650M photos. 70+ million criminal records. Available to all federal agencies.", source="EFF Atlas; GAO; ACLU"),
            Infrastructure(name="Idemia Facial Recognition — TSA Airport Biometrics", city="Washington", state="DC", type="facial_recognition", lat=38.8951, lng=-77.0364, description="TSA Idemia facial recognition at 30+ airports nationwide. Opt-out theoretically available.", source="GAO; EFF; Washington Post"),
            Infrastructure(name="Idemia Facial Recognition — CBP Traveler Verification", city="Washington", state="DC", type="facial_recognition", lat=38.8977, lng=-77.0365, description="CBP Idemia biometric facial recognition at all international ports of entry.", source="DHS; GAO; EFF"),
            Infrastructure(name="Vigilant Solutions Facial Recognition — Statewide TX", city="Austin", state="TX", type="facial_recognition", lat=30.2672, lng=-97.7431, description="Texas DPS Vigilant Solutions facial recognition. Integrated with driver's license database. 27M faces.", source="EFF Atlas; Texas Tribune"),
            Infrastructure(name="Vigilant Solutions Facial Recognition — Statewide FL", city="Tallahassee", state="FL", type="facial_recognition", lat=30.4518, lng=-84.2807, description="FDLE Vigilant Solutions facial recognition. Florida driver's license DB access.", source="EFF Atlas; Tampa Bay Times"),
            Infrastructure(name="Rank One Computing Facial Recognition — Denver PD CO", city="Denver", state="CO", type="facial_recognition", lat=39.7392, lng=-104.9903, description="Denver PD Rank One Computing facial recognition system.", source="EFF Atlas; Westword"),
            Infrastructure(name="Rank One Computing Facial Recognition — Miami PD FL", city="Miami", state="FL", type="facial_recognition", lat=25.7617, lng=-80.1918, description="Miami PD Rank One Computing facial recognition.", source="EFF Atlas"),
            Infrastructure(name="ShotSpotter Fingertips Facial Recognition — Chicago IL", city="Chicago", state="IL", type="facial_recognition", lat=41.8781, lng=-87.6298, description="ShotSpotter Fingertips facial recognition integrated with CPD.", source="EFF Atlas; Chicago Sun-Times"),
            Infrastructure(name="Biometric Fusion Center — DHS OBIM", city="Washington", state="DC", type="facial_recognition", lat=38.8450, lng=-77.0553, description="DHS Office of Biometric Identity Management. Central biometric repository. 260M identities. Shared with 1,000+ agencies.", source="DHS; GAO; EFF"),
            Infrastructure(name="Cognitec FaceVACS — New Orleans PD LA", city="New Orleans", state="LA", type="facial_recognition", lat=29.9511, lng=-90.0715, description="NOPD Cognitec facial recognition. Used without disclosure. Clearview AI also documented.", source="EFF Atlas; The Verge; ACLU Louisiana"),
            Infrastructure(name="Briefcam Video Analytics — Baltimore PD MD", city="Baltimore", state="MD", type="facial_recognition", lat=39.2904, lng=-76.6122, description="BPD Briefcam video analytics with facial recognition. Integration with aerial surveillance.", source="EFF Atlas; Baltimore Sun"),
            Infrastructure(name="Briefcam Video Analytics — NYPD NY", city="New York", state="NY", type="facial_recognition", lat=40.7128, lng=-74.0060, description="NYPD Briefcam. Domain Awareness System integration.", source="EFF Atlas; NYCLU"),
            Infrastructure(name="Axon Respond Facial Recognition — Phoenix AZ", city="Phoenix", state="AZ", type="facial_recognition", lat=33.4484, lng=-112.0740, description="Phoenix PD Axon facial recognition integration.", source="EFF Atlas; Arizona Republic"),

            # ══════════════════════════════════════════════════════════════
            # ADDITIONAL LPR NETWORKS — CITY LEVEL COVERAGE
            # Source: EFF Atlas, city records
            # ══════════════════════════════════════════════════════════════

            Infrastructure(name="LPR Network — Compton CA", city="Compton", state="CA", type="lpr_network", lat=33.8958, lng=-118.2201, description="LASD Compton LPR network.", source="EFF Atlas"),
            Infrastructure(name="LPR Network — Long Beach CA", city="Long Beach", state="CA", type="lpr_network", lat=33.7701, lng=-118.1937, description="LBPD LPR network.", source="EFF Atlas"),
            Infrastructure(name="LPR Network — Anaheim CA", city="Anaheim", state="CA", type="lpr_network", lat=33.8366, lng=-117.9143, description="Anaheim PD LPR network.", source="EFF Atlas"),
            Infrastructure(name="LPR Network — Glendale CA", city="Glendale", state="CA", type="lpr_network", lat=34.1425, lng=-118.2551, description="Glendale CA PD LPR network.", source="EFF Atlas"),
            Infrastructure(name="LPR Network — Santa Ana CA", city="Santa Ana", state="CA", type="lpr_network", lat=33.7455, lng=-117.8677, description="Santa Ana PD LPR network.", source="EFF Atlas"),
            Infrastructure(name="LPR Network — Riverside CA", city="Riverside", state="CA", type="lpr_network", lat=33.9533, lng=-117.3961, description="Riverside PD LPR network.", source="EFF Atlas"),
            Infrastructure(name="LPR Network — Stockton CA", city="Stockton", state="CA", type="lpr_network", lat=37.9577, lng=-121.2908, description="Stockton PD LPR network.", source="EFF Atlas"),
            Infrastructure(name="LPR Network — Modesto CA", city="Modesto", state="CA", type="lpr_network", lat=37.6391, lng=-120.9969, description="Modesto PD LPR network.", source="EFF Atlas"),
            Infrastructure(name="LPR Network — Fresno CA", city="Fresno", state="CA", type="lpr_network", lat=36.7378, lng=-119.7871, description="Fresno PD LPR network.", source="EFF Atlas"),
            Infrastructure(name="LPR Network — Bakersfield CA", city="Bakersfield", state="CA", type="lpr_network", lat=35.3733, lng=-119.0187, description="Bakersfield PD LPR network.", source="EFF Atlas"),
            Infrastructure(name="LPR Network — Sacramento CA", city="Sacramento", state="CA", type="lpr_network", lat=38.5816, lng=-121.4944, description="Sacramento PD LPR network.", source="EFF Atlas"),
            Infrastructure(name="LPR Network — Fort Worth TX", city="Fort Worth", state="TX", type="lpr_network", lat=32.7555, lng=-97.3308, description="Fort Worth PD LPR network.", source="EFF Atlas"),
            Infrastructure(name="LPR Network — Arlington TX", city="Arlington", state="TX", type="lpr_network", lat=32.7357, lng=-97.1081, description="Arlington TX PD LPR network.", source="EFF Atlas"),
            Infrastructure(name="LPR Network — Plano TX", city="Plano", state="TX", type="lpr_network", lat=33.0198, lng=-96.6989, description="Plano TX PD LPR network.", source="EFF Atlas"),
            Infrastructure(name="LPR Network — Laredo TX", city="Laredo", state="TX", type="lpr_network", lat=27.5306, lng=-99.4803, description="Laredo TX PD LPR network. Border city.", source="EFF Atlas"),
            Infrastructure(name="LPR Network — McAllen TX", city="McAllen", state="TX", type="lpr_network", lat=26.2034, lng=-98.2300, description="McAllen TX PD LPR network. Border city.", source="EFF Atlas"),
            Infrastructure(name="LPR Network — El Paso TX", city="El Paso", state="TX", type="lpr_network", lat=31.7619, lng=-106.4850, description="El Paso PD LPR network. Border city.", source="EFF Atlas"),
            Infrastructure(name="LPR Network — Corpus Christi TX", city="Corpus Christi", state="TX", type="lpr_network", lat=27.8006, lng=-97.3964, description="Corpus Christi PD LPR network.", source="EFF Atlas"),
            Infrastructure(name="LPR Network — Jacksonville FL", city="Jacksonville", state="FL", type="lpr_network", lat=30.3322, lng=-81.6557, description="JSO LPR network.", source="EFF Atlas"),
            Infrastructure(name="LPR Network — Tampa FL", city="Tampa", state="FL", type="lpr_network", lat=27.9506, lng=-82.4572, description="Tampa PD LPR network.", source="EFF Atlas"),
            Infrastructure(name="LPR Network — Orlando FL", city="Orlando", state="FL", type="lpr_network", lat=28.5383, lng=-81.3792, description="Orlando PD LPR network.", source="EFF Atlas"),
            Infrastructure(name="LPR Network — Fort Lauderdale FL", city="Fort Lauderdale", state="FL", type="lpr_network", lat=26.1224, lng=-80.1373, description="Fort Lauderdale PD LPR network.", source="EFF Atlas"),
            Infrastructure(name="LPR Network — West Palm Beach FL", city="West Palm Beach", state="FL", type="lpr_network", lat=26.7153, lng=-80.0534, description="West Palm Beach PD LPR network.", source="EFF Atlas"),
            Infrastructure(name="LPR Network — Atlanta GA", city="Atlanta", state="GA", type="lpr_network", lat=33.7490, lng=-84.3880, description="Atlanta PD LPR network.", source="EFF Atlas"),
            Infrastructure(name="LPR Network — Charlotte NC", city="Charlotte", state="NC", type="lpr_network", lat=35.2271, lng=-80.8431, description="Charlotte PD LPR network.", source="EFF Atlas"),
            Infrastructure(name="LPR Network — Raleigh NC", city="Raleigh", state="NC", type="lpr_network", lat=35.7796, lng=-78.6382, description="Raleigh PD LPR network.", source="EFF Atlas"),
            Infrastructure(name="LPR Network — Nashville TN", city="Nashville", state="TN", type="lpr_network", lat=36.1627, lng=-86.7816, description="Nashville Metro PD LPR network.", source="EFF Atlas"),
            Infrastructure(name="LPR Network — Memphis TN", city="Memphis", state="TN", type="lpr_network", lat=35.1495, lng=-90.0490, description="Memphis PD LPR network.", source="EFF Atlas"),
            Infrastructure(name="LPR Network — Louisville KY", city="Louisville", state="KY", type="lpr_network", lat=38.2527, lng=-85.7585, description="LMPD LPR network.", source="EFF Atlas"),
            Infrastructure(name="LPR Network — Indianapolis IN", city="Indianapolis", state="IN", type="lpr_network", lat=39.7684, lng=-86.1581, description="IMPD LPR network.", source="EFF Atlas"),
            Infrastructure(name="LPR Network — Columbus OH", city="Columbus", state="OH", type="lpr_network", lat=39.9612, lng=-82.9988, description="Columbus PD LPR network.", source="EFF Atlas"),
            Infrastructure(name="LPR Network — Cleveland OH", city="Cleveland", state="OH", type="lpr_network", lat=41.4993, lng=-81.6944, description="Cleveland PD LPR network.", source="EFF Atlas"),
            Infrastructure(name="LPR Network — Cincinnati OH", city="Cincinnati", state="OH", type="lpr_network", lat=39.1031, lng=-84.5120, description="Cincinnati PD LPR network.", source="EFF Atlas"),
            Infrastructure(name="LPR Network — Detroit MI", city="Detroit", state="MI", type="lpr_network", lat=42.3314, lng=-83.0458, description="Detroit PD LPR network.", source="EFF Atlas"),
            Infrastructure(name="LPR Network — Minneapolis MN", city="Minneapolis", state="MN", type="lpr_network", lat=44.9778, lng=-93.2650, description="Minneapolis PD LPR network.", source="EFF Atlas"),
            Infrastructure(name="LPR Network — Kansas City MO", city="Kansas City", state="MO", type="lpr_network", lat=39.0997, lng=-94.5786, description="Kansas City PD LPR network.", source="EFF Atlas"),
            Infrastructure(name="LPR Network — St. Louis MO", city="St. Louis", state="MO", type="lpr_network", lat=38.6270, lng=-90.1994, description="St. Louis Metro PD LPR network.", source="EFF Atlas"),
            Infrastructure(name="LPR Network — New Orleans LA", city="New Orleans", state="LA", type="lpr_network", lat=29.9511, lng=-90.0715, description="NOPD LPR network.", source="EFF Atlas"),
            Infrastructure(name="LPR Network — Baltimore MD", city="Baltimore", state="MD", type="lpr_network", lat=39.2904, lng=-76.6122, description="Baltimore PD LPR network.", source="EFF Atlas"),
            Infrastructure(name="LPR Network — Milwaukee WI", city="Milwaukee", state="WI", type="lpr_network", lat=43.0389, lng=-87.9065, description="Milwaukee PD LPR network.", source="EFF Atlas"),
            Infrastructure(name="LPR Network — Albuquerque NM", city="Albuquerque", state="NM", type="lpr_network", lat=35.0844, lng=-106.6504, description="Albuquerque PD LPR network.", source="EFF Atlas"),
            Infrastructure(name="LPR Network — Tucson AZ", city="Tucson", state="AZ", type="lpr_network", lat=32.2217, lng=-110.9265, description="Tucson PD LPR network.", source="EFF Atlas"),
            Infrastructure(name="LPR Network — Mesa AZ", city="Mesa", state="AZ", type="lpr_network", lat=33.4152, lng=-111.8315, description="Mesa PD LPR network.", source="EFF Atlas"),
            Infrastructure(name="LPR Network — Chandler AZ", city="Chandler", state="AZ", type="lpr_network", lat=33.3062, lng=-111.8413, description="Chandler PD LPR network.", source="EFF Atlas"),
            Infrastructure(name="LPR Network — Las Vegas NV", city="Las Vegas", state="NV", type="lpr_network", lat=36.1699, lng=-115.1398, description="LVMPD LPR network.", source="EFF Atlas"),
            Infrastructure(name="LPR Network — Reno NV", city="Reno", state="NV", type="lpr_network", lat=39.5296, lng=-119.8138, description="Reno PD LPR network.", source="EFF Atlas"),
            Infrastructure(name="LPR Network — Colorado Springs CO", city="Colorado Springs", state="CO", type="lpr_network", lat=38.8339, lng=-104.8214, description="Colorado Springs PD LPR network.", source="EFF Atlas"),
            Infrastructure(name="LPR Network — Aurora CO", city="Aurora", state="CO", type="lpr_network", lat=39.7294, lng=-104.8319, description="Aurora CO PD LPR network.", source="EFF Atlas"),
            Infrastructure(name="LPR Network — Omaha NE", city="Omaha", state="NE", type="lpr_network", lat=41.2565, lng=-95.9345, description="Omaha PD LPR network.", source="EFF Atlas"),
            Infrastructure(name="LPR Network — Oklahoma City OK", city="Oklahoma City", state="OK", type="lpr_network", lat=35.4676, lng=-97.5164, description="Oklahoma City PD LPR network.", source="EFF Atlas"),
            Infrastructure(name="LPR Network — Tulsa OK", city="Tulsa", state="OK", type="lpr_network", lat=36.1540, lng=-95.9928, description="Tulsa PD LPR network.", source="EFF Atlas"),
            Infrastructure(name="LPR Network — Wichita KS", city="Wichita", state="KS", type="lpr_network", lat=37.6872, lng=-97.3301, description="Wichita PD LPR network.", source="EFF Atlas"),
            Infrastructure(name="LPR Network — Salt Lake City UT", city="Salt Lake City", state="UT", type="lpr_network", lat=40.7608, lng=-111.8910, description="Salt Lake City PD LPR network.", source="EFF Atlas"),
            Infrastructure(name="LPR Network — Boise ID", city="Boise", state="ID", type="lpr_network", lat=43.6150, lng=-116.2023, description="Boise PD LPR network.", source="EFF Atlas"),
            Infrastructure(name="LPR Network — Spokane WA", city="Spokane", state="WA", type="lpr_network", lat=47.6587, lng=-117.4260, description="Spokane PD LPR network.", source="EFF Atlas"),
            Infrastructure(name="LPR Network — Tacoma WA", city="Tacoma", state="WA", type="lpr_network", lat=47.2529, lng=-122.4443, description="Tacoma PD LPR network.", source="EFF Atlas"),
            Infrastructure(name="LPR Network — Portland OR", city="Portland", state="OR", type="lpr_network", lat=45.5231, lng=-122.6765, description="Portland PD LPR network.", source="EFF Atlas"),
            Infrastructure(name="LPR Network — Eugene OR", city="Eugene", state="OR", type="lpr_network", lat=44.0521, lng=-123.0868, description="Eugene PD LPR network.", source="EFF Atlas"),
            Infrastructure(name="LPR Network — Philadelphia PA", city="Philadelphia", state="PA", type="lpr_network", lat=39.9526, lng=-75.1652, description="Philadelphia PD LPR network.", source="EFF Atlas"),
            Infrastructure(name="LPR Network — Pittsburgh PA", city="Pittsburgh", state="PA", type="lpr_network", lat=40.4406, lng=-79.9959, description="Pittsburgh PD LPR network.", source="EFF Atlas"),
            Infrastructure(name="LPR Network — Boston MA", city="Boston", state="MA", type="lpr_network", lat=42.3601, lng=-71.0589, description="Boston PD LPR network.", source="EFF Atlas"),
            Infrastructure(name="LPR Network — Providence RI", city="Providence", state="RI", type="lpr_network", lat=41.8240, lng=-71.4128, description="Providence PD LPR network.", source="EFF Atlas"),
            Infrastructure(name="LPR Network — Hartford CT", city="Hartford", state="CT", type="lpr_network", lat=41.7637, lng=-72.6851, description="Hartford PD LPR network.", source="EFF Atlas"),
            Infrastructure(name="LPR Network — Newark NJ", city="Newark", state="NJ", type="lpr_network", lat=40.7357, lng=-74.1724, description="Newark PD LPR network.", source="EFF Atlas"),
            Infrastructure(name="LPR Network — Buffalo NY", city="Buffalo", state="NY", type="lpr_network", lat=42.8864, lng=-78.8784, description="Buffalo PD LPR network.", source="EFF Atlas"),
            Infrastructure(name="LPR Network — Rochester NY", city="Rochester", state="NY", type="lpr_network", lat=43.1566, lng=-77.6088, description="Rochester PD LPR network.", source="EFF Atlas"),
            Infrastructure(name="LPR Network — Richmond VA", city="Richmond", state="VA", type="lpr_network", lat=37.5407, lng=-77.4360, description="Richmond PD LPR network.", source="EFF Atlas"),
            Infrastructure(name="LPR Network — Norfolk VA", city="Norfolk", state="VA", type="lpr_network", lat=36.8508, lng=-76.2859, description="Norfolk PD LPR network.", source="EFF Atlas"),
            Infrastructure(name="LPR Network — Virginia Beach VA", city="Virginia Beach", state="VA", type="lpr_network", lat=36.8529, lng=-75.9780, description="Virginia Beach PD LPR network.", source="EFF Atlas"),
            Infrastructure(name="LPR Network — Columbia SC", city="Columbia", state="SC", type="lpr_network", lat=34.0007, lng=-81.0348, description="Columbia SC PD LPR network.", source="EFF Atlas"),
            Infrastructure(name="LPR Network — Birmingham AL", city="Birmingham", state="AL", type="lpr_network", lat=33.5186, lng=-86.8104, description="Birmingham PD LPR network.", source="EFF Atlas"),
            Infrastructure(name="LPR Network — Mobile AL", city="Mobile", state="AL", type="lpr_network", lat=30.6954, lng=-88.0399, description="Mobile PD LPR network.", source="EFF Atlas"),
            Infrastructure(name="LPR Network — Jackson MS", city="Jackson", state="MS", type="lpr_network", lat=32.2988, lng=-90.1848, description="Jackson MS PD LPR network.", source="EFF Atlas"),
            Infrastructure(name="LPR Network — Little Rock AR", city="Little Rock", state="AR", type="lpr_network", lat=34.7465, lng=-92.2896, description="Little Rock PD LPR network.", source="EFF Atlas"),
            Infrastructure(name="LPR Network — Des Moines IA", city="Des Moines", state="IA", type="lpr_network", lat=41.5868, lng=-93.6250, description="Des Moines PD LPR network.", source="EFF Atlas"),
            Infrastructure(name="LPR Network — Madison WI", city="Madison", state="WI", type="lpr_network", lat=43.0731, lng=-89.4012, description="Madison WI PD LPR network.", source="EFF Atlas"),
            Infrastructure(name="LPR Network — Anchorage AK", city="Anchorage", state="AK", type="lpr_network", lat=61.2181, lng=-149.9003, description="Anchorage PD LPR network.", source="EFF Atlas"),
            Infrastructure(name="LPR Network — Honolulu HI", city="Honolulu", state="HI", type="lpr_network", lat=21.3069, lng=-157.8583, description="Honolulu PD LPR network.", source="EFF Atlas"),

            # ══════════════════════════════════════════════════════════════
            # SHOTSPOTTER — ADDITIONAL METRO AREA NEIGHBORHOOD COVERAGE
            # Source: SoundThinking contracts, EFF Atlas, city records
            # ══════════════════════════════════════════════════════════════

            # Washington DC neighborhoods
            Infrastructure(name="ShotSpotter — DC Ward 7", city="Washington", state="DC", type="shotspotter", lat=38.8929, lng=-76.9680, description="ShotSpotter in Ward 7. Deanwood and Benning.", source="MPD records; EFF Atlas"),
            Infrastructure(name="ShotSpotter — DC Ward 8", city="Washington", state="DC", type="shotspotter", lat=38.8440, lng=-77.0060, description="ShotSpotter in Ward 8. Congress Heights area.", source="MPD records; EFF Atlas"),
            Infrastructure(name="ShotSpotter — DC Ward 5 Trinidad", city="Washington", state="DC", type="shotspotter", lat=38.9040, lng=-76.9860, description="ShotSpotter in Ward 5 Trinidad neighborhood.", source="MPD records; EFF Atlas"),
            Infrastructure(name="ShotSpotter — DC Ward 6 Anacostia", city="Washington", state="DC", type="shotspotter", lat=38.8630, lng=-76.9860, description="ShotSpotter in Anacostia area.", source="MPD records; EFF Atlas"),

            # San Francisco Bay Area neighborhoods
            Infrastructure(name="ShotSpotter — Oakland Flatlands East", city="Oakland", state="CA", type="shotspotter", lat=37.8100, lng=-122.2300, description="ShotSpotter in East Oakland flatlands.", source="OPD records; EFF Atlas"),
            Infrastructure(name="ShotSpotter — Oakland Fruitvale", city="Oakland", state="CA", type="shotspotter", lat=37.7740, lng=-122.2240, description="ShotSpotter in Fruitvale neighborhood.", source="OPD records; EFF Atlas"),
            Infrastructure(name="ShotSpotter — Oakland West Oakland", city="Oakland", state="CA", type="shotspotter", lat=37.8080, lng=-122.2940, description="ShotSpotter in West Oakland.", source="OPD records; EFF Atlas"),
            Infrastructure(name="ShotSpotter — Oakland Deep East", city="Oakland", state="CA", type="shotspotter", lat=37.7640, lng=-122.1720, description="ShotSpotter in Deep East Oakland.", source="OPD records; EFF Atlas"),
            Infrastructure(name="ShotSpotter — Richmond CA North and Central", city="Richmond", state="CA", type="shotspotter", lat=37.9358, lng=-122.3477, description="ShotSpotter across Richmond CA neighborhoods.", source="Richmond PD records; EFF Atlas"),

            # Atlanta additional neighborhoods
            Infrastructure(name="ShotSpotter — Atlanta Grove Park", city="Atlanta", state="GA", type="shotspotter", lat=33.7730, lng=-84.4820, description="ShotSpotter in Grove Park neighborhood.", source="APD records; EFF Atlas"),
            Infrastructure(name="ShotSpotter — Atlanta English Avenue", city="Atlanta", state="GA", type="shotspotter", lat=33.7620, lng=-84.4270, description="ShotSpotter in English Avenue.", source="APD records; EFF Atlas"),
            Infrastructure(name="ShotSpotter — Atlanta Mechanicsville", city="Atlanta", state="GA", type="shotspotter", lat=33.7320, lng=-84.4020, description="ShotSpotter in Mechanicsville.", source="APD records; EFF Atlas"),
            Infrastructure(name="ShotSpotter — Atlanta Summerhill", city="Atlanta", state="GA", type="shotspotter", lat=33.7290, lng=-84.3860, description="ShotSpotter in Summerhill neighborhood.", source="APD records; EFF Atlas"),

            # New Orleans additional
            Infrastructure(name="ShotSpotter — New Orleans Gentilly", city="New Orleans", state="LA", type="shotspotter", lat=30.0050, lng=-90.0460, description="ShotSpotter in Gentilly neighborhood.", source="NOPD records; EFF Atlas"),
            Infrastructure(name="ShotSpotter — New Orleans New Orleans East", city="New Orleans", state="LA", type="shotspotter", lat=30.0160, lng=-89.9510, description="ShotSpotter in New Orleans East.", source="NOPD records; EFF Atlas"),
            Infrastructure(name="ShotSpotter — New Orleans Algiers", city="New Orleans", state="LA", type="shotspotter", lat=29.9290, lng=-90.0640, description="ShotSpotter in Algiers neighborhood.", source="NOPD records; EFF Atlas"),

            # Baton Rouge neighborhoods
            Infrastructure(name="ShotSpotter — Baton Rouge North Baton Rouge", city="Baton Rouge", state="LA", type="shotspotter", lat=30.5020, lng=-91.1550, description="ShotSpotter in North Baton Rouge.", source="BRPD records; EFF Atlas"),
            Infrastructure(name="ShotSpotter — Baton Rouge Mid City", city="Baton Rouge", state="LA", type="shotspotter", lat=30.4680, lng=-91.1700, description="ShotSpotter in Mid City Baton Rouge.", source="BRPD records; EFF Atlas"),
            Infrastructure(name="ShotSpotter — Baton Rouge Scotlandville", city="Baton Rouge", state="LA", type="shotspotter", lat=30.5310, lng=-91.1870, description="ShotSpotter in Scotlandville neighborhood.", source="BRPD records; EFF Atlas"),

            # Houston additional neighborhoods
            Infrastructure(name="ShotSpotter — Houston Kashmere Gardens", city="Houston", state="TX", type="shotspotter", lat=29.7990, lng=-95.3060, description="ShotSpotter in Kashmere Gardens.", source="HPD records; EFF Atlas"),
            Infrastructure(name="ShotSpotter — Houston Near Northside", city="Houston", state="TX", type="shotspotter", lat=29.7960, lng=-95.3570, description="ShotSpotter in Near Northside.", source="HPD records; EFF Atlas"),
            Infrastructure(name="ShotSpotter — Houston Settegast", city="Houston", state="TX", type="shotspotter", lat=29.8210, lng=-95.3240, description="ShotSpotter in Settegast neighborhood.", source="HPD records; EFF Atlas"),
            Infrastructure(name="ShotSpotter — Houston Pleasantville", city="Houston", state="TX", type="shotspotter", lat=29.7720, lng=-95.3160, description="ShotSpotter in Pleasantville.", source="HPD records; EFF Atlas"),

            # Dallas additional neighborhoods
            Infrastructure(name="ShotSpotter — Dallas South Dallas deeper coverage", city="Dallas", state="TX", type="shotspotter", lat=32.7200, lng=-96.7760, description="ShotSpotter deeper coverage in South Dallas.", source="DPD records; EFF Atlas"),
            Infrastructure(name="ShotSpotter — Dallas West Dallas deeper coverage", city="Dallas", state="TX", type="shotspotter", lat=32.7990, lng=-96.8620, description="ShotSpotter deeper West Dallas coverage.", source="DPD records; EFF Atlas"),
            Infrastructure(name="ShotSpotter — Dallas Pleasant Grove", city="Dallas", state="TX", type="shotspotter", lat=32.7390, lng=-96.6860, description="ShotSpotter in Pleasant Grove neighborhood.", source="DPD records; EFF Atlas"),
            Infrastructure(name="ShotSpotter — Dallas Rylie", city="Dallas", state="TX", type="shotspotter", lat=32.6970, lng=-96.6750, description="ShotSpotter in Rylie area.", source="DPD records; EFF Atlas"),

            # Birmingham AL neighborhoods
            Infrastructure(name="ShotSpotter — Birmingham Ensley", city="Birmingham", state="AL", type="shotspotter", lat=33.5050, lng=-86.8810, description="ShotSpotter in Ensley neighborhood.", source="BPD records; EFF Atlas"),
            Infrastructure(name="ShotSpotter — Birmingham Woodlawn", city="Birmingham", state="AL", type="shotspotter", lat=33.5180, lng=-86.7580, description="ShotSpotter in Woodlawn neighborhood.", source="BPD records; EFF Atlas"),
            Infrastructure(name="ShotSpotter — Birmingham North Birmingham", city="Birmingham", state="AL", type="shotspotter", lat=33.5540, lng=-86.8300, description="ShotSpotter in North Birmingham.", source="BPD records; EFF Atlas"),

            # St. Louis additional
            Infrastructure(name="ShotSpotter — St. Louis Jeff-Vander-Lou", city="St. Louis", state="MO", type="shotspotter", lat=38.6440, lng=-90.2510, description="ShotSpotter in Jeff-Vander-Lou neighborhood.", source="SLMPD records; EFF Atlas"),
            Infrastructure(name="ShotSpotter — St. Louis Hyde Park", city="St. Louis", state="MO", type="shotspotter", lat=38.6640, lng=-90.2230, description="ShotSpotter in Hyde Park area.", source="SLMPD records; EFF Atlas"),
            Infrastructure(name="ShotSpotter — St. Louis Mark Twain", city="St. Louis", state="MO", type="shotspotter", lat=38.6750, lng=-90.2580, description="ShotSpotter in Mark Twain neighborhood.", source="SLMPD records; EFF Atlas"),

            # Louisville neighborhoods
            Infrastructure(name="ShotSpotter — Louisville West End deeper", city="Louisville", state="KY", type="shotspotter", lat=38.2530, lng=-85.8090, description="ShotSpotter deeper coverage in West Louisville.", source="LMPD records; EFF Atlas"),
            Infrastructure(name="ShotSpotter — Louisville Park DuValle", city="Louisville", state="KY", type="shotspotter", lat=38.2610, lng=-85.8130, description="ShotSpotter in Park DuValle neighborhood.", source="LMPD records; EFF Atlas"),
            Infrastructure(name="ShotSpotter — Louisville Portland", city="Louisville", state="KY", type="shotspotter", lat=38.2720, lng=-85.7880, description="ShotSpotter in Portland neighborhood.", source="LMPD records; EFF Atlas"),

            # Pittsburgh neighborhoods
            Infrastructure(name="ShotSpotter — Pittsburgh Hill District", city="Pittsburgh", state="PA", type="shotspotter", lat=40.4490, lng=-79.9820, description="ShotSpotter in Hill District.", source="PPD records; EFF Atlas"),
            Infrastructure(name="ShotSpotter — Pittsburgh Homewood", city="Pittsburgh", state="PA", type="shotspotter", lat=40.4520, lng=-79.8990, description="ShotSpotter in Homewood neighborhood.", source="PPD records; EFF Atlas"),
            Infrastructure(name="ShotSpotter — Pittsburgh McKeesport", city="McKeesport", state="PA", type="shotspotter", lat=40.3451, lng=-79.8445, description="ShotSpotter in McKeesport.", source="McKeesport PD records; EFF Atlas"),

            # Richmond VA neighborhoods
            Infrastructure(name="ShotSpotter — Richmond Gilpin Court", city="Richmond", state="VA", type="shotspotter", lat=37.5600, lng=-77.4380, description="ShotSpotter near Gilpin Court public housing.", source="RPD records; EFF Atlas"),
            Infrastructure(name="ShotSpotter — Richmond Creighton Court", city="Richmond", state="VA", type="shotspotter", lat=37.5550, lng=-77.4060, description="ShotSpotter near Creighton Court.", source="RPD records; EFF Atlas"),
            Infrastructure(name="ShotSpotter — Richmond North Side", city="Richmond", state="VA", type="shotspotter", lat=37.5780, lng=-77.4500, description="ShotSpotter on Richmond North Side.", source="RPD records; EFF Atlas"),

            # ══════════════════════════════════════════════════════════════
            # CSS AIRCRAFT — ADDITIONAL DOCUMENTED OPERATIONS
            # Source: WSJ, BuzzFeed News, The Intercept, EFF
            # ══════════════════════════════════════════════════════════════

            Infrastructure(name="CSS Aircraft — St. Louis Ferguson Protests 2014", city="St. Louis", state="MO", type="css_aircraft", lat=38.7448, lng=-90.3048, description="Federal CSS aircraft operated over Ferguson MO during protests. Documented by BuzzFeed and The Intercept.", source="BuzzFeed News; The Intercept; EFF"),
            Infrastructure(name="CSS Aircraft — Baltimore Freddie Gray Protests 2015", city="Baltimore", state="MD", type="css_aircraft", lat=39.2904, lng=-76.6122, description="CSS aircraft over Baltimore during Freddie Gray protests. Multiple agencies.", source="Baltimore Sun; BuzzFeed News"),
            Infrastructure(name="CSS Aircraft — Minneapolis George Floyd Protests 2020", city="Minneapolis", state="MN", type="css_aircraft", lat=44.9778, lng=-93.2650, description="Federal CSS aircraft over Minneapolis during George Floyd protests. Documented mass phone interception.", source="The Intercept; Star Tribune; EFF"),
            Infrastructure(name="CSS Aircraft — Portland Protests 2020", city="Portland", state="OR", type="css_aircraft", lat=45.5231, lng=-122.6765, description="Federal CSS aircraft over Portland protests 2020. Multiple agencies including DHS.", source="OPB; The Intercept; EFF"),
            Infrastructure(name="CSS Aircraft — Washington DC Capitol 2021", city="Washington", state="DC", type="css_aircraft", lat=38.8899, lng=-77.0091, description="CSS aircraft over DC area during January 6 and surrounding period.", source="The Intercept; EFF"),
            Infrastructure(name="CSS Aircraft — Chicago O'Hare Hub", city="Chicago", state="IL", type="css_aircraft", lat=41.9742, lng=-87.9073, description="Federal CSS aircraft operations hub. O'Hare area. Covers Chicago metro.", source="BuzzFeed News 2015; EFF"),
            Infrastructure(name="CSS Aircraft — Houston Ellington Hub", city="Houston", state="TX", type="css_aircraft", lat=29.6073, lng=-95.1588, description="CSS aircraft hub at Ellington Field. Gulf Coast operations.", source="BuzzFeed News; EFF"),
            Infrastructure(name="CSS Aircraft — Riverside CA March ARB Hub", city="Riverside", state="CA", type="css_aircraft", lat=33.8807, lng=-117.2596, description="CSS aircraft hub at March Air Reserve Base. Southern California coverage.", source="BuzzFeed News; EFF"),
            Infrastructure(name="CSS Aircraft — Miramar CA Hub", city="San Diego", state="CA", type="css_aircraft", lat=32.8674, lng=-117.1425, description="CSS aircraft operations from Miramar. San Diego and border coverage.", source="BuzzFeed News; EFF"),

            # ══════════════════════════════════════════════════════════════
            # IMSI CATCHERS — CITY PD ADDITIONAL AGENCIES
            # Source: ACLU, EFF, FOIA records
            # ══════════════════════════════════════════════════════════════

            Infrastructure(name="IMSI Catcher — San Diego PD CA", city="San Diego", state="CA", type="imsi_catcher", lat=32.7157, lng=-117.1611, description="SDPD Stingray. Documented use without warrants.", source="ACLU; EFF"),
            Infrastructure(name="IMSI Catcher — Long Beach PD CA", city="Long Beach", state="CA", type="imsi_catcher", lat=33.7701, lng=-118.1937, description="Long Beach PD Stingray deployment.", source="ACLU; EFF"),
            Infrastructure(name="IMSI Catcher — Anaheim PD CA", city="Anaheim", state="CA", type="imsi_catcher", lat=33.8366, lng=-117.9143, description="Anaheim PD Stingray use confirmed.", source="ACLU; EFF"),
            Infrastructure(name="IMSI Catcher — Sacramento PD CA", city="Sacramento", state="CA", type="imsi_catcher", lat=38.5816, lng=-121.4944, description="Sacramento PD Stingray deployment.", source="ACLU; EFF"),
            Infrastructure(name="IMSI Catcher — Fresno PD CA", city="Fresno", state="CA", type="imsi_catcher", lat=36.7378, lng=-119.7871, description="Fresno PD Stingray use confirmed.", source="ACLU; EFF"),
            Infrastructure(name="IMSI Catcher — Oakland PD CA", city="Oakland", state="CA", type="imsi_catcher", lat=37.8044, lng=-122.2711, description="Oakland PD Stingray deployment.", source="ACLU NorCal; EFF"),
            Infrastructure(name="IMSI Catcher — San Jose PD CA", city="San Jose", state="CA", type="imsi_catcher", lat=37.3382, lng=-121.8863, description="San Jose PD Stingray use confirmed.", source="ACLU; EFF"),
            Infrastructure(name="IMSI Catcher — Phoenix PD AZ", city="Phoenix", state="AZ", type="imsi_catcher", lat=33.4484, lng=-112.0740, description="Phoenix PD Stingray deployment.", source="ACLU Arizona; EFF"),
            Infrastructure(name="IMSI Catcher — Tucson PD AZ", city="Tucson", state="AZ", type="imsi_catcher", lat=32.2217, lng=-110.9265, description="Tucson PD Stingray use confirmed.", source="ACLU Arizona; EFF"),
            Infrastructure(name="IMSI Catcher — Las Vegas Metro PD NV", city="Las Vegas", state="NV", type="imsi_catcher", lat=36.1699, lng=-115.1398, description="LVMPD Stingray deployment.", source="ACLU Nevada; EFF"),
            Infrastructure(name="IMSI Catcher — Denver PD CO", city="Denver", state="CO", type="imsi_catcher", lat=39.7392, lng=-104.9903, description="Denver PD Stingray use confirmed.", source="ACLU Colorado; EFF"),
            Infrastructure(name="IMSI Catcher — Seattle PD WA", city="Seattle", state="WA", type="imsi_catcher", lat=47.6062, lng=-122.3321, description="SPD Stingray deployment.", source="ACLU WA; EFF"),
            Infrastructure(name="IMSI Catcher — Portland PD OR", city="Portland", state="OR", type="imsi_catcher", lat=45.5231, lng=-122.6765, description="Portland PD Stingray use confirmed.", source="ACLU Oregon; EFF"),
            Infrastructure(name="IMSI Catcher — Minneapolis PD MN", city="Minneapolis", state="MN", type="imsi_catcher", lat=44.9778, lng=-93.2650, description="Minneapolis PD Stingray deployment.", source="ACLU MN; Star Tribune"),
            Infrastructure(name="IMSI Catcher — Kansas City PD MO", city="Kansas City", state="MO", type="imsi_catcher", lat=39.0997, lng=-94.5786, description="KCPD Stingray use confirmed.", source="ACLU Missouri; EFF"),
            Infrastructure(name="IMSI Catcher — St. Louis Metro PD MO", city="St. Louis", state="MO", type="imsi_catcher", lat=38.6270, lng=-90.1994, description="SLMPD Stingray deployment.", source="ACLU Missouri; EFF"),
            Infrastructure(name="IMSI Catcher — New Orleans PD LA", city="New Orleans", state="LA", type="imsi_catcher", lat=29.9511, lng=-90.0715, description="NOPD Stingray use confirmed.", source="ACLU Louisiana; EFF"),
            Infrastructure(name="IMSI Catcher — Atlanta PD GA", city="Atlanta", state="GA", type="imsi_catcher", lat=33.7490, lng=-84.3880, description="Atlanta PD Stingray deployment.", source="ACLU Georgia; EFF"),
            Infrastructure(name="IMSI Catcher — Nashville Metro PD TN", city="Nashville", state="TN", type="imsi_catcher", lat=36.1627, lng=-86.7816, description="Nashville Metro PD Stingray use confirmed.", source="ACLU TN; EFF"),
            Infrastructure(name="IMSI Catcher — Memphis PD TN", city="Memphis", state="TN", type="imsi_catcher", lat=35.1495, lng=-90.0490, description="Memphis PD Stingray deployment.", source="ACLU TN; EFF"),

            # ══════════════════════════════════════════════════════════════
            # DHS / CISA MONITORING
            # Source: DHS.gov, CISA.gov, GAO reports, Congressional records
            # CISA monitors 16 critical infrastructure sectors
            # ══════════════════════════════════════════════════════════════

            Infrastructure(name="CISA Headquarters", city="Arlington", state="VA", type="dhs_cisa", lat=38.8799, lng=-77.1068, description="Cybersecurity and Infrastructure Security Agency HQ. Monitors 16 critical infrastructure sectors nationwide. Operates 24/7 Operations Center.", source="CISA.gov; DHS"),
            Infrastructure(name="CISA Region 1 — Boston", city="Boston", state="MA", type="dhs_cisa", lat=42.3601, lng=-71.0589, description="CISA Region 1. Covers CT, ME, MA, NH, RI, VT. Critical infrastructure monitoring.", source="CISA.gov"),
            Infrastructure(name="CISA Region 2 — New York", city="New York", state="NY", type="dhs_cisa", lat=40.7128, lng=-74.0060, description="CISA Region 2. Covers NJ, NY, PR, USVI. Financial sector primary focus.", source="CISA.gov"),
            Infrastructure(name="CISA Region 3 — Philadelphia", city="Philadelphia", state="PA", type="dhs_cisa", lat=39.9526, lng=-75.1652, description="CISA Region 3. Covers DE, DC, MD, PA, VA, WV.", source="CISA.gov"),
            Infrastructure(name="CISA Region 4 — Atlanta", city="Atlanta", state="GA", type="dhs_cisa", lat=33.7490, lng=-84.3880, description="CISA Region 4. Covers AL, FL, GA, KY, MS, NC, SC, TN.", source="CISA.gov"),
            Infrastructure(name="CISA Region 5 — Chicago", city="Chicago", state="IL", type="dhs_cisa", lat=41.8781, lng=-87.6298, description="CISA Region 5. Covers IL, IN, MI, MN, OH, WI.", source="CISA.gov"),
            Infrastructure(name="CISA Region 6 — Dallas", city="Dallas", state="TX", type="dhs_cisa", lat=32.7767, lng=-96.7970, description="CISA Region 6. Covers AR, LA, NM, OK, TX.", source="CISA.gov"),
            Infrastructure(name="CISA Region 7 — Kansas City", city="Kansas City", state="MO", type="dhs_cisa", lat=39.0997, lng=-94.5786, description="CISA Region 7. Covers IA, KS, MO, NE.", source="CISA.gov"),
            Infrastructure(name="CISA Region 8 — Denver", city="Denver", state="CO", type="dhs_cisa", lat=39.7392, lng=-104.9903, description="CISA Region 8. Covers CO, MT, ND, SD, UT, WY.", source="CISA.gov"),
            Infrastructure(name="CISA Region 9 — San Francisco", city="San Francisco", state="CA", type="dhs_cisa", lat=37.7749, lng=-122.4194, description="CISA Region 9. Covers AZ, CA, HI, NV, Pacific Islands.", source="CISA.gov"),
            Infrastructure(name="CISA Region 10 — Seattle", city="Seattle", state="WA", type="dhs_cisa", lat=47.6062, lng=-122.3321, description="CISA Region 10. Covers AK, ID, OR, WA.", source="CISA.gov"),
            Infrastructure(name="CISA Election Infrastructure ISAC — National", city="Washington", state="DC", type="dhs_cisa", lat=38.8951, lng=-77.0364, description="CISA monitors election infrastructure in all 50 states. Provides security assessments to state election officials.", source="CISA.gov; Congressional testimony"),
            Infrastructure(name="CISA Energy Sector Monitoring — Grid Security", city="Washington", state="DC", type="dhs_cisa", lat=38.8977, lng=-77.0365, description="CISA monitors US power grid infrastructure. Coordinates with DOE on grid security.", source="CISA.gov; GAO"),
            Infrastructure(name="CISA Water Sector Monitoring — National", city="Washington", state="DC", type="dhs_cisa", lat=38.8940, lng=-77.0350, description="CISA Water and Wastewater Systems sector monitoring. All major municipal water systems.", source="CISA.gov"),
            Infrastructure(name="CISA Healthcare Sector Monitoring — National", city="Washington", state="DC", type="dhs_cisa", lat=38.8920, lng=-77.0380, description="CISA Healthcare and Public Health sector. Monitors hospital networks and medical infrastructure.", source="CISA.gov"),
            Infrastructure(name="CISA Transportation Sector Monitoring — National", city="Washington", state="DC", type="dhs_cisa", lat=38.8960, lng=-77.0330, description="CISA Transportation sector monitoring. Airports, rail, pipelines.", source="CISA.gov"),
            Infrastructure(name="CISA Communications Sector Monitoring — National", city="Washington", state="DC", type="dhs_cisa", lat=38.8935, lng=-77.0345, description="CISA Communications sector. Monitors internet exchange points and telecom infrastructure.", source="CISA.gov"),
            Infrastructure(name="CISA Financial Sector Monitoring — National", city="New York", state="NY", type="dhs_cisa", lat=40.7074, lng=-74.0113, description="CISA Financial Services sector coordination with NY Federal Reserve and major banks.", source="CISA.gov"),
            Infrastructure(name="CISA Chemical Sector Monitoring — Houston", city="Houston", state="TX", type="dhs_cisa", lat=29.7604, lng=-95.3698, description="CISA Chemical sector monitoring. Houston petrochemical corridor primary focus.", source="CISA.gov"),
            Infrastructure(name="CISA Defense Industrial Base Monitoring — National", city="Arlington", state="VA", type="dhs_cisa", lat=38.8799, lng=-77.1068, description="CISA monitors defense contractor networks. Shares threat intelligence with cleared contractors.", source="CISA.gov; DOD"),
            Infrastructure(name="CISA Nuclear Sector Monitoring — National", city="Washington", state="DC", type="dhs_cisa", lat=38.8951, lng=-77.0364, description="CISA Nuclear Reactors, Materials, and Waste sector. Coordinates with NRC.", source="CISA.gov; NRC"),
            Infrastructure(name="CISA Emergency Services Sector Monitoring", city="Washington", state="DC", type="dhs_cisa", lat=38.8930, lng=-77.0370, description="CISA Emergency Services sector. Monitors 911 systems and emergency response networks.", source="CISA.gov"),
            Infrastructure(name="CISA Government Facilities Sector — National", city="Washington", state="DC", type="dhs_cisa", lat=38.8945, lng=-77.0355, description="CISA monitors all federal, state, and local government facilities.", source="CISA.gov"),
            Infrastructure(name="CISA Food and Agriculture Sector Monitoring", city="Washington", state="DC", type="dhs_cisa", lat=38.8915, lng=-77.0385, description="CISA Food and Agriculture sector coordination with USDA.", source="CISA.gov"),
            Infrastructure(name="CISA Critical Manufacturing Monitoring", city="Washington", state="DC", type="dhs_cisa", lat=38.8905, lng=-77.0395, description="CISA Critical Manufacturing sector. Monitors major industrial facilities.", source="CISA.gov"),
            Infrastructure(name="CISA Dams Sector Monitoring — National", city="Washington", state="DC", type="dhs_cisa", lat=38.8955, lng=-77.0325, description="CISA monitors 90,000+ dams nationwide. Coordinates with Army Corps of Engineers.", source="CISA.gov"),
            Infrastructure(name="DHS Office of Intelligence and Analysis — National", city="Washington", state="DC", type="dhs_cisa", lat=38.8450, lng=-77.0553, description="DHS I&A. Shares intelligence with 78 fusion centers. Monitors domestic threats. Documented monitoring of journalists and protestors.", source="DHS; The Intercept; ACLU"),
            Infrastructure(name="DHS Continuous Diagnostics and Mitigation — Federal Networks", city="Arlington", state="VA", type="dhs_cisa", lat=38.8799, lng=-77.1068, description="CDM program monitors all federal civilian agency networks in real time.", source="CISA.gov; OMB"),

            # ══════════════════════════════════════════════════════════════
            # FEDERAL BUILDING SURVEILLANCE
            # Source: GSA.gov, federal court records, public contracts
            # Every federal building with public access has documented
            # camera surveillance under GSA FPS authority
            # ══════════════════════════════════════════════════════════════

            Infrastructure(name="Federal Courthouse — SDNY New York", city="New York", state="NY", type="federal_building", lat=40.7143, lng=-74.0059, description="Southern District of NY federal courthouse. Extensive camera coverage. FPS managed.", source="GSA; FPS records"),
            Infrastructure(name="Federal Courthouse — EDNY Brooklyn", city="New York", state="NY", type="federal_building", lat=40.6943, lng=-73.9903, description="Eastern District of NY courthouse. Camera surveillance.", source="GSA; FPS records"),
            Infrastructure(name="Federal Courthouse — Central District CA Los Angeles", city="Los Angeles", state="CA", type="federal_building", lat=34.0522, lng=-118.2437, description="Central District CA federal courthouse. FPS camera network.", source="GSA; FPS records"),
            Infrastructure(name="Federal Courthouse — Northern District CA San Francisco", city="San Francisco", state="CA", type="federal_building", lat=37.7749, lng=-122.4194, description="Northern District CA federal courthouse. Camera surveillance.", source="GSA; FPS records"),
            Infrastructure(name="Federal Courthouse — Northern District IL Chicago", city="Chicago", state="IL", type="federal_building", lat=41.8781, lng=-87.6298, description="Northern District IL federal courthouse. Dirksen Federal Building. FPS managed.", source="GSA; FPS records"),
            Infrastructure(name="Federal Courthouse — Southern District TX Houston", city="Houston", state="TX", type="federal_building", lat=29.7604, lng=-95.3698, description="Southern District TX federal courthouse. Bob Casey Federal Building.", source="GSA; FPS records"),
            Infrastructure(name="Federal Courthouse — Eastern District TX Dallas", city="Dallas", state="TX", type="federal_building", lat=32.7767, lng=-96.7970, description="Eastern District TX federal courthouse. Camera network.", source="GSA; FPS records"),
            Infrastructure(name="Federal Courthouse — District of Columbia", city="Washington", state="DC", type="federal_building", lat=38.8951, lng=-77.0364, description="DC federal courthouse. E. Barrett Prettyman. Extensive surveillance.", source="GSA; FPS records"),
            Infrastructure(name="Federal Courthouse — Eastern District PA Philadelphia", city="Philadelphia", state="PA", type="federal_building", lat=39.9526, lng=-75.1652, description="Eastern District PA federal courthouse. FPS camera surveillance.", source="GSA; FPS records"),
            Infrastructure(name="Federal Courthouse — District of MD Baltimore", city="Baltimore", state="MD", type="federal_building", lat=39.2904, lng=-76.6122, description="District of MD federal courthouse. Camera network.", source="GSA; FPS records"),
            Infrastructure(name="Federal Courthouse — Northern District GA Atlanta", city="Atlanta", state="GA", type="federal_building", lat=33.7490, lng=-84.3880, description="Northern District GA federal courthouse. Richard Russell Building.", source="GSA; FPS records"),
            Infrastructure(name="Federal Courthouse — Southern District FL Miami", city="Miami", state="FL", type="federal_building", lat=25.7617, lng=-80.1918, description="Southern District FL federal courthouse. Wilkie Ferguson Jr. Building.", source="GSA; FPS records"),
            Infrastructure(name="Federal Courthouse — Middle District FL Orlando", city="Orlando", state="FL", type="federal_building", lat=28.5383, lng=-81.3792, description="Middle District FL federal courthouse. FPS camera surveillance.", source="GSA; FPS records"),
            Infrastructure(name="Federal Courthouse — Northern District FL Tallahassee", city="Tallahassee", state="FL", type="federal_building", lat=30.4518, lng=-84.2807, description="Northern District FL federal courthouse.", source="GSA; FPS records"),
            Infrastructure(name="Federal Courthouse — Western District TX San Antonio", city="San Antonio", state="TX", type="federal_building", lat=29.4241, lng=-98.4936, description="Western District TX federal courthouse. John H. Wood Jr. Building.", source="GSA; FPS records"),
            Infrastructure(name="Federal Courthouse — Western District TX El Paso", city="El Paso", state="TX", type="federal_building", lat=31.7619, lng=-106.4850, description="Western District TX El Paso courthouse. Border proximity. High security.", source="GSA; FPS records"),
            Infrastructure(name="Federal Courthouse — District of AZ Phoenix", city="Phoenix", state="AZ", type="federal_building", lat=33.4484, lng=-112.0740, description="District of AZ federal courthouse. Sandra Day O'Connor Building.", source="GSA; FPS records"),
            Infrastructure(name="Federal Courthouse — District of AZ Tucson", city="Tucson", state="AZ", type="federal_building", lat=32.2217, lng=-110.9265, description="District of AZ Tucson courthouse. Border operations.", source="GSA; FPS records"),
            Infrastructure(name="Federal Courthouse — Western District WA Seattle", city="Seattle", state="WA", type="federal_building", lat=47.6062, lng=-122.3321, description="Western District WA federal courthouse. William Kenzo Nakamura Building.", source="GSA; FPS records"),
            Infrastructure(name="Federal Courthouse — District of OR Portland", city="Portland", state="OR", type="federal_building", lat=45.5231, lng=-122.6765, description="District of OR federal courthouse. Targeted during 2020 protests. Extensive camera network.", source="GSA; FPS records; DHS"),
            Infrastructure(name="Federal Courthouse — District of CO Denver", city="Denver", state="CO", type="federal_building", lat=39.7392, lng=-104.9903, description="District of CO federal courthouse. Byron Rogers Federal Building.", source="GSA; FPS records"),
            Infrastructure(name="Federal Courthouse — District of MN Minneapolis", city="Minneapolis", state="MN", type="federal_building", lat=44.9778, lng=-93.2650, description="District of MN federal courthouse. Camera surveillance.", source="GSA; FPS records"),
            Infrastructure(name="Federal Courthouse — Eastern District MI Detroit", city="Detroit", state="MI", type="federal_building", lat=42.3314, lng=-83.0458, description="Eastern District MI federal courthouse. Theodore Levin Building.", source="GSA; FPS records"),
            Infrastructure(name="Federal Courthouse — Northern District OH Cleveland", city="Cleveland", state="OH", type="federal_building", lat=41.4993, lng=-81.6944, description="Northern District OH federal courthouse. Carl B. Stokes Building.", source="GSA; FPS records"),
            Infrastructure(name="Federal Courthouse — Southern District OH Columbus", city="Columbus", state="OH", type="federal_building", lat=39.9612, lng=-82.9988, description="Southern District OH federal courthouse.", source="GSA; FPS records"),
            Infrastructure(name="Federal Building — Jacob Javits NYC", city="New York", state="NY", type="federal_building", lat=40.7580, lng=-73.9855, description="Jacob Javits Federal Building. Major federal office complex. FPS surveillance.", source="GSA; FPS records"),
            Infrastructure(name="Federal Building — Ronald Reagan Washington DC", city="Washington", state="DC", type="federal_building", lat=38.8929, lng=-77.0282, description="Ronald Reagan Building. Largest federal building outside Pentagon. Extensive surveillance.", source="GSA; FPS records"),
            Infrastructure(name="Federal Building — Mark O. Hatfield Portland", city="Portland", state="OR", type="federal_building", lat=45.5231, lng=-122.6765, description="Mark O. Hatfield Federal Courthouse. Targeted in 2020. Added surveillance post-protests.", source="GSA; FPS records; DHS"),
            Infrastructure(name="FBI Headquarters — J. Edgar Hoover Building", city="Washington", state="DC", type="federal_building", lat=38.8941, lng=-77.0252, description="FBI HQ. Pennsylvania Avenue. Extensive perimeter surveillance.", source="FBI; GSA"),
            Infrastructure(name="CIA Headquarters — Langley VA", city="McLean", state="VA", type="federal_building", lat=38.9509, lng=-77.1459, description="CIA Headquarters Langley. Documented perimeter surveillance.", source="Public record"),
            Infrastructure(name="NSA Headquarters — Fort Meade MD", city="Fort Meade", state="MD", type="federal_building", lat=39.1087, lng=-76.7719, description="NSA/CSS headquarters. Fort Meade MD. Core of domestic surveillance infrastructure.", source="Congressional testimony; Snowden documents; public record"),
            Infrastructure(name="NSA Utah Data Center — Bluffdale", city="Bluffdale", state="UT", type="federal_building", lat=40.4244, lng=-111.9303, description="NSA Utah Data Center. 1.5 million sq ft. Stores intercepted communications from global surveillance. $1.5B facility.", source="Wired; Congressional testimony; public record"),
            Infrastructure(name="NSA Georgia — Augusta", city="Augusta", state="GA", type="federal_building", lat=33.3599, lng=-82.0832, description="NSA Georgia. Fort Gordon. Major signals intelligence processing center.", source="NSA public records; Congressional testimony"),
            Infrastructure(name="NSA Texas — San Antonio", city="San Antonio", state="TX", type="federal_building", lat=29.4241, lng=-98.4936, description="NSA Texas. Lackland AFB. Regional SIGINT center.", source="NSA public records; Congressional testimony"),
            Infrastructure(name="NSA Hawaii — Kunia", city="Kunia", state="HI", type="federal_building", lat=21.4389, lng=-158.0706, description="NSA Hawaii. Kunia Regional SIGINT Operations Center. Pacific intelligence hub.", source="NSA public records; Snowden documents"),
            Infrastructure(name="Pentagon — National Security Operations", city="Arlington", state="VA", type="federal_building", lat=38.8719, lng=-77.0563, description="Pentagon. Extensive surveillance of surrounding area. Camera networks, vehicle tracking.", source="DoD; GSA; FPS records"),
            Infrastructure(name="DHS Headquarters — St. Elizabeth's Campus", city="Washington", state="DC", type="federal_building", lat=38.8456, lng=-77.0053, description="DHS headquarters complex. Surveillance infrastructure for entire campus.", source="DHS; GSA"),
            Infrastructure(name="Federal Building — Stewart Lee Udall DC", city="Washington", state="DC", type="federal_building", lat=38.8891, lng=-77.0422, description="Interior Department. Extensive camera network on National Mall corridor.", source="GSA; FPS records"),

            # ══════════════════════════════════════════════════════════════
            # JOINT OPERATIONS CENTERS
            # Source: DEA, ATF, FBI public records, DOJ reports
            # ══════════════════════════════════════════════════════════════

            Infrastructure(name="DEA HIDTA — New York/New Jersey", city="New York", state="NY", type="joint_ops", lat=40.7128, lng=-74.0060, description="DEA High Intensity Drug Trafficking Area. Joint DEA/NYPD/FBI operations center.", source="DEA; DOJ"),
            Infrastructure(name="DEA HIDTA — Los Angeles", city="Los Angeles", state="CA", type="joint_ops", lat=34.0522, lng=-118.2437, description="DEA LA HIDTA. Joint operations center. Intelligence aggregation.", source="DEA; DOJ"),
            Infrastructure(name="DEA HIDTA — Chicago", city="Chicago", state="IL", type="joint_ops", lat=41.8781, lng=-87.6298, description="DEA Chicago HIDTA. Joint DEA/CPD/FBI operations.", source="DEA; DOJ"),
            Infrastructure(name="DEA HIDTA — Houston", city="Houston", state="TX", type="joint_ops", lat=29.7604, lng=-95.3698, description="DEA Houston HIDTA. Gulf Coast drug operations center.", source="DEA; DOJ"),
            Infrastructure(name="DEA HIDTA — Miami", city="Miami", state="FL", type="joint_ops", lat=25.7617, lng=-80.1918, description="DEA Miami HIDTA. Caribbean and South American operations.", source="DEA; DOJ"),
            Infrastructure(name="DEA HIDTA — Atlanta", city="Atlanta", state="GA", type="joint_ops", lat=33.7490, lng=-84.3880, description="DEA Atlanta HIDTA. Southeast operations center.", source="DEA; DOJ"),
            Infrastructure(name="DEA HIDTA — Dallas", city="Dallas", state="TX", type="joint_ops", lat=32.7767, lng=-96.7970, description="DEA Dallas HIDTA. North Texas operations.", source="DEA; DOJ"),
            Infrastructure(name="DEA HIDTA — Phoenix", city="Phoenix", state="AZ", type="joint_ops", lat=33.4484, lng=-112.0740, description="DEA Phoenix HIDTA. Southwest Border operations.", source="DEA; DOJ"),
            Infrastructure(name="DEA HIDTA — San Diego", city="San Diego", state="CA", type="joint_ops", lat=32.7157, lng=-117.1611, description="DEA San Diego HIDTA. Border operations center.", source="DEA; DOJ"),
            Infrastructure(name="DEA HIDTA — El Paso", city="El Paso", state="TX", type="joint_ops", lat=31.7619, lng=-106.4850, description="DEA El Paso HIDTA. West Texas Border operations.", source="DEA; DOJ"),
            Infrastructure(name="DEA HIDTA — Philadelphia", city="Philadelphia", state="PA", type="joint_ops", lat=39.9526, lng=-75.1652, description="DEA Philadelphia HIDTA.", source="DEA; DOJ"),
            Infrastructure(name="DEA HIDTA — Washington DC", city="Washington", state="DC", type="joint_ops", lat=38.8951, lng=-77.0364, description="DEA Washington DC HIDTA. National Capital Region.", source="DEA; DOJ"),
            Infrastructure(name="DEA HIDTA — Detroit", city="Detroit", state="MI", type="joint_ops", lat=42.3314, lng=-83.0458, description="DEA Detroit HIDTA. Great Lakes operations.", source="DEA; DOJ"),
            Infrastructure(name="DEA HIDTA — Minneapolis", city="Minneapolis", state="MN", type="joint_ops", lat=44.9778, lng=-93.2650, description="DEA Minneapolis HIDTA. Upper Midwest operations.", source="DEA; DOJ"),
            Infrastructure(name="DEA HIDTA — New Orleans", city="New Orleans", state="LA", type="joint_ops", lat=29.9511, lng=-90.0715, description="DEA New Orleans HIDTA. Gulf South operations.", source="DEA; DOJ"),
            Infrastructure(name="DEA HIDTA — Kansas City", city="Kansas City", state="MO", type="joint_ops", lat=39.0997, lng=-94.5786, description="DEA Kansas City HIDTA. Midwest operations.", source="DEA; DOJ"),
            Infrastructure(name="DEA HIDTA — Seattle", city="Seattle", state="WA", type="joint_ops", lat=47.6062, lng=-122.3321, description="DEA Seattle HIDTA. Pacific Northwest operations.", source="DEA; DOJ"),
            Infrastructure(name="DEA HIDTA — Denver", city="Denver", state="CO", type="joint_ops", lat=39.7392, lng=-104.9903, description="DEA Denver HIDTA. Rocky Mountain operations.", source="DEA; DOJ"),
            Infrastructure(name="DEA HIDTA — Boston", city="Boston", state="MA", type="joint_ops", lat=42.3601, lng=-71.0589, description="DEA Boston HIDTA. New England operations.", source="DEA; DOJ"),
            Infrastructure(name="DEA HIDTA — San Francisco", city="San Francisco", state="CA", type="joint_ops", lat=37.7749, lng=-122.4194, description="DEA San Francisco HIDTA. Bay Area operations.", source="DEA; DOJ"),
            Infrastructure(name="ATF National Center for Explosives Training — Redstone", city="Huntsville", state="AL", type="joint_ops", lat=34.7304, lng=-86.5861, description="ATF NCETFL. Joint training and intelligence operations with law enforcement.", source="ATF; DOJ"),
            Infrastructure(name="ATF National Tracing Center — Martinsburg WV", city="Martinsburg", state="WV", type="joint_ops", lat=39.4565, lng=-77.9638, description="ATF National Tracing Center. Traces all crime guns in US. Database of 700M+ firearms records.", source="ATF; DOJ; Washington Post"),
            Infrastructure(name="ATF Special Agent in Charge — New York", city="New York", state="NY", type="joint_ops", lat=40.7128, lng=-74.0060, description="ATF New York SAC. Joint operations with NYPD.", source="ATF; DOJ"),
            Infrastructure(name="ATF Special Agent in Charge — Los Angeles", city="Los Angeles", state="CA", type="joint_ops", lat=34.0522, lng=-118.2437, description="ATF Los Angeles SAC. Joint operations with LAPD.", source="ATF; DOJ"),
            Infrastructure(name="ATF Special Agent in Charge — Chicago", city="Chicago", state="IL", type="joint_ops", lat=41.8781, lng=-87.6298, description="ATF Chicago SAC. Gun trafficking joint operations.", source="ATF; DOJ"),
            Infrastructure(name="ATF Special Agent in Charge — Houston", city="Houston", state="TX", type="joint_ops", lat=29.7604, lng=-95.3698, description="ATF Houston SAC.", source="ATF; DOJ"),
            Infrastructure(name="ATF Special Agent in Charge — Miami", city="Miami", state="FL", type="joint_ops", lat=25.7617, lng=-80.1918, description="ATF Miami SAC.", source="ATF; DOJ"),
            Infrastructure(name="ATF Special Agent in Charge — Dallas", city="Dallas", state="TX", type="joint_ops", lat=32.7767, lng=-96.7970, description="ATF Dallas SAC.", source="ATF; DOJ"),
            Infrastructure(name="ATF Special Agent in Charge — Phoenix", city="Phoenix", state="AZ", type="joint_ops", lat=33.4484, lng=-112.0740, description="ATF Phoenix SAC. Fast and Furious operation origin.", source="ATF; DOJ"),
            Infrastructure(name="ATF Special Agent in Charge — Atlanta", city="Atlanta", state="GA", type="joint_ops", lat=33.7490, lng=-84.3880, description="ATF Atlanta SAC.", source="ATF; DOJ"),
            Infrastructure(name="ATF Special Agent in Charge — Seattle", city="Seattle", state="WA", type="joint_ops", lat=47.6062, lng=-122.3321, description="ATF Seattle SAC.", source="ATF; DOJ"),
            Infrastructure(name="ATF Special Agent in Charge — Washington DC", city="Washington", state="DC", type="joint_ops", lat=38.8951, lng=-77.0364, description="ATF Washington Field Division SAC.", source="ATF; DOJ"),
            Infrastructure(name="FBI Joint Intelligence Operations Center — DC", city="Washington", state="DC", type="joint_ops", lat=38.8951, lng=-77.0364, description="FBI JIOC. Coordinates domestic intelligence operations nationwide.", source="FBI; The Intercept"),
            Infrastructure(name="US Marshals TOPS Task Force — National", city="Washington", state="DC", type="joint_ops", lat=38.8799, lng=-77.1068, description="USMS Targeting Organized Crime and Public Safety. Joint task forces in 94 districts.", source="USMS; DOJ"),
            Infrastructure(name="Organized Crime Drug Enforcement Task Force — NYC", city="New York", state="NY", type="joint_ops", lat=40.7128, lng=-74.0060, description="OCDETF New York strike force. Multi-agency drug and money laundering operations.", source="DOJ; OCDETF"),
            Infrastructure(name="Organized Crime Drug Enforcement Task Force — LA", city="Los Angeles", state="CA", type="joint_ops", lat=34.0522, lng=-118.2437, description="OCDETF Los Angeles strike force.", source="DOJ; OCDETF"),
            Infrastructure(name="Organized Crime Drug Enforcement Task Force — Chicago", city="Chicago", state="IL", type="joint_ops", lat=41.8781, lng=-87.6298, description="OCDETF Chicago strike force.", source="DOJ; OCDETF"),
            Infrastructure(name="Organized Crime Drug Enforcement Task Force — Houston", city="Houston", state="TX", type="joint_ops", lat=29.7604, lng=-95.3698, description="OCDETF Houston strike force.", source="DOJ; OCDETF"),
            Infrastructure(name="Organized Crime Drug Enforcement Task Force — Miami", city="Miami", state="FL", type="joint_ops", lat=25.7617, lng=-80.1918, description="OCDETF Miami strike force.", source="DOJ; OCDETF"),
            Infrastructure(name="Organized Crime Drug Enforcement Task Force — Atlanta", city="Atlanta", state="GA", type="joint_ops", lat=33.7490, lng=-84.3880, description="OCDETF Atlanta strike force.", source="DOJ; OCDETF"),
            Infrastructure(name="Organized Crime Drug Enforcement Task Force — Dallas", city="Dallas", state="TX", type="joint_ops", lat=32.7767, lng=-96.7970, description="OCDETF Dallas strike force.", source="DOJ; OCDETF"),
            Infrastructure(name="Organized Crime Drug Enforcement Task Force — Phoenix", city="Phoenix", state="AZ", type="joint_ops", lat=33.4484, lng=-112.0740, description="OCDETF Phoenix strike force. Southwest Border focus.", source="DOJ; OCDETF"),
            Infrastructure(name="Organized Crime Drug Enforcement Task Force — Seattle", city="Seattle", state="WA", type="joint_ops", lat=47.6062, lng=-122.3321, description="OCDETF Seattle strike force.", source="DOJ; OCDETF"),
            Infrastructure(name="Organized Crime Drug Enforcement Task Force — Denver", city="Denver", state="CO", type="joint_ops", lat=39.7392, lng=-104.9903, description="OCDETF Denver strike force.", source="DOJ; OCDETF"),

            # ══════════════════════════════════════════════════════════════
            # PORT AND MARITIME SURVEILLANCE
            # Source: CBP, USCG, port authority records, public contracts
            # ══════════════════════════════════════════════════════════════

            Infrastructure(name="Port of Los Angeles / Long Beach Surveillance", city="Los Angeles", state="CA", type="port_surveillance", lat=33.7366, lng=-118.2630, description="Largest US port complex. CBP cameras, radiation portals, LPR, vessel tracking. 9M+ containers/year screened.", source="CBP; Port of LA public records"),
            Infrastructure(name="Port of New York / New Jersey Surveillance", city="Newark", state="NJ", type="port_surveillance", lat=40.6840, lng=-74.1350, description="CBP Port of NY/NJ surveillance. Container scanning, facial recognition at cruise terminals.", source="CBP; Port Authority records"),
            Infrastructure(name="Port of Savannah Surveillance", city="Savannah", state="GA", type="port_surveillance", lat=32.0835, lng=-81.0998, description="Port of Savannah CBP surveillance. Second largest US container port. Full camera and scanning coverage.", source="CBP; Georgia Ports Authority"),
            Infrastructure(name="Port of Houston Surveillance", city="Houston", state="TX", type="port_surveillance", lat=29.7200, lng=-95.2830, description="Port of Houston CBP surveillance. Energy sector port. Chemical cargo monitoring.", source="CBP; Port of Houston Authority"),
            Infrastructure(name="Port of Seattle / Tacoma Surveillance", city="Seattle", state="WA", type="port_surveillance", lat=47.5480, lng=-122.3350, description="CBP Northwest Seaport Alliance surveillance. Container and passenger terminal monitoring.", source="CBP; Northwest Seaport Alliance"),
            Infrastructure(name="Port of Miami Surveillance", city="Miami", state="FL", type="port_surveillance", lat=25.7740, lng=-80.1680, description="PortMiami CBP surveillance. World's largest passenger port. Facial recognition at all cruise terminals.", source="CBP; PortMiami records"),
            Infrastructure(name="Port of Baltimore Surveillance", city="Baltimore", state="MD", type="port_surveillance", lat=39.2700, lng=-76.5770, description="Port of Baltimore CBP surveillance. Coal and vehicle import monitoring.", source="CBP; Maryland Port Administration"),
            Infrastructure(name="Port of Charleston Surveillance", city="Charleston", state="SC", type="port_surveillance", lat=32.7600, lng=-79.9250, description="Port of Charleston CBP camera and scanning surveillance.", source="CBP; South Carolina Ports Authority"),
            Infrastructure(name="Port of Norfolk / Virginia Beach Surveillance", city="Norfolk", state="VA", type="port_surveillance", lat=36.9320, lng=-76.3300, description="Port of Virginia CBP surveillance. Military port proximity.", source="CBP; Virginia Port Authority"),
            Infrastructure(name="Port of New Orleans Surveillance", city="New Orleans", state="LA", type="port_surveillance", lat=29.9440, lng=-90.0620, description="Port of New Orleans CBP surveillance. Mississippi River cargo hub.", source="CBP; Port of New Orleans"),
            Infrastructure(name="Port of Tampa Surveillance", city="Tampa", state="FL", type="port_surveillance", lat=27.9300, lng=-82.4430, description="Port Tampa Bay CBP surveillance. Phosphate and cruise operations.", source="CBP; Port Tampa Bay"),
            Infrastructure(name="Port of Jacksonville Surveillance", city="Jacksonville", state="FL", type="port_surveillance", lat=30.3650, lng=-81.6230, description="Port of Jacksonville CBP surveillance. Auto import hub.", source="CBP; JAXPORT records"),
            Infrastructure(name="Port of Portland OR Surveillance", city="Portland", state="OR", type="port_surveillance", lat=45.5640, lng=-122.6830, description="Port of Portland CBP surveillance. Columbia River operations.", source="CBP; Port of Portland"),
            Infrastructure(name="Port of Oakland Surveillance", city="Oakland", state="CA", type="port_surveillance", lat=37.7950, lng=-122.2820, description="Port of Oakland CBP surveillance. Bay Area container port.", source="CBP; Port of Oakland"),
            Infrastructure(name="Port of Boston Surveillance", city="Boston", state="MA", type="port_surveillance", lat=42.3570, lng=-71.0430, description="Port of Boston CBP surveillance. Cruiseport and cargo.", source="CBP; Massport records"),
            Infrastructure(name="Port of Philadelphia Surveillance", city="Philadelphia", state="PA", type="port_surveillance", lat=39.9000, lng=-75.1450, description="PhilaPort CBP surveillance.", source="CBP; PhilaPort records"),
            Infrastructure(name="Port of Chicago Surveillance", city="Chicago", state="IL", type="port_surveillance", lat=41.8350, lng=-87.5520, description="Port of Chicago CBP surveillance. Great Lakes port.", source="CBP; Port of Chicago"),
            Infrastructure(name="Port of Duluth Surveillance", city="Duluth", state="MN", type="port_surveillance", lat=46.7720, lng=-92.1070, description="Port of Duluth-Superior CBP surveillance. Iron ore and grain.", source="CBP; Duluth Seaway Port Authority"),
            Infrastructure(name="Port of Detroit Surveillance", city="Detroit", state="MI", type="port_surveillance", lat=42.3150, lng=-83.0450, description="Port of Detroit CBP surveillance. US-Canada crossing.", source="CBP; Detroit/Wayne County Port Authority"),
            Infrastructure(name="Port of San Diego Surveillance", city="San Diego", state="CA", type="port_surveillance", lat=32.7150, lng=-117.1730, description="Port of San Diego CBP surveillance. Military and commercial operations.", source="CBP; Port of San Diego"),
            Infrastructure(name="US Coast Guard Sector New York", city="New York", state="NY", type="port_surveillance", lat=40.6630, lng=-74.0680, description="USCG Sector New York. Maritime domain awareness. AIS vessel tracking all NY harbor vessels.", source="USCG; DHS"),
            Infrastructure(name="US Coast Guard Sector Los Angeles / Long Beach", city="Long Beach", state="CA", type="port_surveillance", lat=33.7540, lng=-118.2030, description="USCG Sector LA/LB. Pacific maritime surveillance.", source="USCG; DHS"),
            Infrastructure(name="US Coast Guard Sector Miami", city="Miami", state="FL", type="port_surveillance", lat=25.7680, lng=-80.1860, description="USCG Sector Miami. Caribbean maritime operations. Drug interdiction surveillance.", source="USCG; DHS"),
            Infrastructure(name="US Coast Guard Sector Houston-Galveston", city="Houston", state="TX", type="port_surveillance", lat=29.7400, lng=-95.0700, description="USCG Sector Houston-Galveston. Gulf Coast maritime surveillance.", source="USCG; DHS"),
            Infrastructure(name="US Coast Guard Sector San Francisco", city="San Francisco", state="CA", type="port_surveillance", lat=37.8070, lng=-122.4770, description="USCG Sector San Francisco. Bay Area maritime domain awareness.", source="USCG; DHS"),
            Infrastructure(name="US Coast Guard Sector Seattle", city="Seattle", state="WA", type="port_surveillance", lat=47.6460, lng=-122.4050, description="USCG Sector Puget Sound. Pacific Northwest maritime surveillance.", source="USCG; DHS"),
            Infrastructure(name="US Coast Guard Sector New Orleans", city="New Orleans", state="LA", type="port_surveillance", lat=29.9500, lng=-90.0650, description="USCG Sector New Orleans. Mississippi River and Gulf surveillance.", source="USCG; DHS"),
            Infrastructure(name="US Coast Guard Sector Baltimore", city="Baltimore", state="MD", type="port_surveillance", lat=39.2680, lng=-76.5790, description="USCG Sector Maryland-National Capital Region. Chesapeake Bay surveillance.", source="USCG; DHS"),
            Infrastructure(name="US Coast Guard Sector Boston", city="Boston", state="MA", type="port_surveillance", lat=42.3640, lng=-71.0420, description="USCG Sector Boston. New England maritime domain awareness.", source="USCG; DHS"),
            Infrastructure(name="US Coast Guard Sector Honolulu", city="Honolulu", state="HI", type="port_surveillance", lat=21.3380, lng=-157.9210, description="USCG Sector Honolulu. Pacific maritime surveillance hub.", source="USCG; DHS"),
            Infrastructure(name="US Coast Guard Sector Anchorage", city="Anchorage", state="AK", type="port_surveillance", lat=61.2181, lng=-149.9003, description="USCG Sector Anchorage. Arctic and Alaska maritime surveillance.", source="USCG; DHS"),
            Infrastructure(name="CBP National Targeting Center — Reston VA", city="Reston", state="VA", type="port_surveillance", lat=38.9587, lng=-77.3570, description="CBP NTC. Screens all cargo manifests and passenger records for all US ports before arrival. 100% advance screening.", source="CBP; DHS"),
            Infrastructure(name="CBP Air and Marine Operations Center — Riverside CA", city="Riverside", state="CA", type="port_surveillance", lat=33.9533, lng=-117.3961, description="CBP AMOC. Tracks all aircraft and vessels approaching US. 24/7 operations.", source="CBP; DHS"),

            # ══════════════════════════════════════════════════════════════
            # SCHOOL SURVEILLANCE
            # Source: EFF Atlas, Student Privacy Compass, FOIA records,
            # Gaggle/GoGuardian/Bark public contracts
            # ══════════════════════════════════════════════════════════════

            Infrastructure(name="Gaggle School Surveillance — Chicago Public Schools IL", city="Chicago", state="IL", type="school_surveillance", lat=41.8781, lng=-87.6298, description="Gaggle monitors all student devices 24/7 including personal accounts and off-school hours. Chicago PS contract.", source="EFF Atlas; Student Privacy Compass; Chicago Tribune"),
            Infrastructure(name="Gaggle School Surveillance — Houston ISD TX", city="Houston", state="TX", type="school_surveillance", lat=29.7604, lng=-95.3698, description="HISD Gaggle deployment. Monitors 200,000+ students.", source="EFF Atlas; Student Privacy Compass"),
            Infrastructure(name="Gaggle School Surveillance — Dallas ISD TX", city="Dallas", state="TX", type="school_surveillance", lat=32.7767, lng=-96.7970, description="Dallas ISD Gaggle contract. Student device monitoring.", source="EFF Atlas; Student Privacy Compass"),
            Infrastructure(name="Gaggle School Surveillance — Los Angeles USD CA", city="Los Angeles", state="CA", type="school_surveillance", lat=34.0522, lng=-118.2437, description="LAUSD Gaggle surveillance. 600,000+ students monitored.", source="EFF Atlas; Student Privacy Compass"),
            Infrastructure(name="Gaggle School Surveillance — Clark County NV", city="Las Vegas", state="NV", type="school_surveillance", lat=36.1699, lng=-115.1398, description="Clark County School District Gaggle deployment. Las Vegas area.", source="EFF Atlas; Student Privacy Compass"),
            Infrastructure(name="Gaggle School Surveillance — Miami-Dade County FL", city="Miami", state="FL", type="school_surveillance", lat=25.7617, lng=-80.1918, description="Miami-Dade County Public Schools Gaggle contract.", source="EFF Atlas; Student Privacy Compass"),
            Infrastructure(name="Gaggle School Surveillance — Broward County FL", city="Fort Lauderdale", state="FL", type="school_surveillance", lat=26.1224, lng=-80.1373, description="Broward County Schools Gaggle deployment.", source="EFF Atlas; Student Privacy Compass"),
            Infrastructure(name="Gaggle School Surveillance — Philadelphia SD PA", city="Philadelphia", state="PA", type="school_surveillance", lat=39.9526, lng=-75.1652, description="Philadelphia School District Gaggle contract.", source="EFF Atlas; Student Privacy Compass"),
            Infrastructure(name="Gaggle School Surveillance — Denver Public Schools CO", city="Denver", state="CO", type="school_surveillance", lat=39.7392, lng=-104.9903, description="Denver PS Gaggle surveillance deployment.", source="EFF Atlas; Student Privacy Compass"),
            Infrastructure(name="Gaggle School Surveillance — Austin ISD TX", city="Austin", state="TX", type="school_surveillance", lat=30.2672, lng=-97.7431, description="Austin ISD Gaggle contract.", source="EFF Atlas; Student Privacy Compass"),
            Infrastructure(name="Gaggle School Surveillance — San Antonio ISD TX", city="San Antonio", state="TX", type="school_surveillance", lat=29.4241, lng=-98.4936, description="San Antonio ISD Gaggle deployment.", source="EFF Atlas; Student Privacy Compass"),
            Infrastructure(name="Gaggle School Surveillance — Albuquerque PSD NM", city="Albuquerque", state="NM", type="school_surveillance", lat=35.0844, lng=-106.6504, description="Albuquerque Public Schools Gaggle contract.", source="EFF Atlas; Student Privacy Compass"),
            Infrastructure(name="GoGuardian School Surveillance — New York City NY", city="New York", state="NY", type="school_surveillance", lat=40.7128, lng=-74.0060, description="NYC DOE GoGuardian deployment. 1.1 million students. Monitors Chromebooks.", source="EFF Atlas; NYCLU; Gothamist"),
            Infrastructure(name="GoGuardian School Surveillance — Atlanta Public Schools GA", city="Atlanta", state="GA", type="school_surveillance", lat=33.7490, lng=-84.3880, description="Atlanta PS GoGuardian contract.", source="EFF Atlas; Student Privacy Compass"),
            Infrastructure(name="GoGuardian School Surveillance — Seattle Public Schools WA", city="Seattle", state="WA", type="school_surveillance", lat=47.6062, lng=-122.3321, description="Seattle PS GoGuardian deployment.", source="EFF Atlas; Student Privacy Compass"),
            Infrastructure(name="GoGuardian School Surveillance — Portland Public Schools OR", city="Portland", state="OR", type="school_surveillance", lat=45.5231, lng=-122.6765, description="Portland PS GoGuardian contract.", source="EFF Atlas; Student Privacy Compass"),
            Infrastructure(name="GoGuardian School Surveillance — Minneapolis SD MN", city="Minneapolis", state="MN", type="school_surveillance", lat=44.9778, lng=-93.2650, description="Minneapolis SD GoGuardian deployment.", source="EFF Atlas; Student Privacy Compass"),
            Infrastructure(name="GoGuardian School Surveillance — Kansas City MO SD", city="Kansas City", state="MO", type="school_surveillance", lat=39.0997, lng=-94.5786, description="KCMO SD GoGuardian contract.", source="EFF Atlas; Student Privacy Compass"),
            Infrastructure(name="GoGuardian School Surveillance — Charlotte-Mecklenburg NC", city="Charlotte", state="NC", type="school_surveillance", lat=35.2271, lng=-80.8431, description="Charlotte-Mecklenburg Schools GoGuardian.", source="EFF Atlas; Student Privacy Compass"),
            Infrastructure(name="GoGuardian School Surveillance — Nashville Metro Schools TN", city="Nashville", state="TN", type="school_surveillance", lat=36.1627, lng=-86.7816, description="Metro Nashville PS GoGuardian deployment.", source="EFF Atlas; Student Privacy Compass"),
            Infrastructure(name="GoGuardian School Surveillance — Columbus City Schools OH", city="Columbus", state="OH", type="school_surveillance", lat=39.9612, lng=-82.9988, description="Columbus City Schools GoGuardian contract.", source="EFF Atlas; Student Privacy Compass"),
            Infrastructure(name="GoGuardian School Surveillance — Detroit Public Schools MI", city="Detroit", state="MI", type="school_surveillance", lat=42.3314, lng=-83.0458, description="Detroit PS GoGuardian deployment.", source="EFF Atlas; Student Privacy Compass"),
            Infrastructure(name="GoGuardian School Surveillance — Milwaukee PS WI", city="Milwaukee", state="WI", type="school_surveillance", lat=43.0389, lng=-87.9065, description="Milwaukee PS GoGuardian contract.", source="EFF Atlas; Student Privacy Compass"),
            Infrastructure(name="GoGuardian School Surveillance — Salt Lake City SD UT", city="Salt Lake City", state="UT", type="school_surveillance", lat=40.7608, lng=-111.8910, description="Salt Lake City SD GoGuardian.", source="EFF Atlas; Student Privacy Compass"),
            Infrastructure(name="Bark School Surveillance — San Francisco USD CA", city="San Francisco", state="CA", type="school_surveillance", lat=37.7749, lng=-122.4194, description="SFUSD Bark deployment. AI-powered student monitoring.", source="EFF Atlas; Student Privacy Compass; SF Chronicle"),
            Infrastructure(name="Bark School Surveillance — Boston Public Schools MA", city="Boston", state="MA", type="school_surveillance", lat=42.3601, lng=-71.0589, description="Boston PS Bark contract. Student device AI monitoring.", source="EFF Atlas; Student Privacy Compass"),
            Infrastructure(name="Bark School Surveillance — Baltimore City PS MD", city="Baltimore", state="MD", type="school_surveillance", lat=39.2904, lng=-76.6122, description="Baltimore City PS Bark deployment.", source="EFF Atlas; Student Privacy Compass"),
            Infrastructure(name="Bark School Surveillance — St. Louis PS MO", city="St. Louis", state="MO", type="school_surveillance", lat=38.6270, lng=-90.1994, description="St. Louis PS Bark contract.", source="EFF Atlas; Student Privacy Compass"),
            Infrastructure(name="Bark School Surveillance — Indianapolis PS IN", city="Indianapolis", state="IN", type="school_surveillance", lat=39.7684, lng=-86.1581, description="Indianapolis PS Bark deployment.", source="EFF Atlas; Student Privacy Compass"),
            Infrastructure(name="Bark School Surveillance — Memphis-Shelby County TN", city="Memphis", state="TN", type="school_surveillance", lat=35.1495, lng=-90.0490, description="Memphis-Shelby County Schools Bark contract.", source="EFF Atlas; Student Privacy Compass"),
            Infrastructure(name="Bark School Surveillance — Louisville Jefferson County KY", city="Louisville", state="KY", type="school_surveillance", lat=38.2527, lng=-85.7585, description="Jefferson County PS Bark deployment.", source="EFF Atlas; Student Privacy Compass"),
            Infrastructure(name="Bark School Surveillance — Richmond PS VA", city="Richmond", state="VA", type="school_surveillance", lat=37.5407, lng=-77.4360, description="Richmond PS Bark contract.", source="EFF Atlas; Student Privacy Compass"),
            Infrastructure(name="Bark School Surveillance — New Orleans PS LA", city="New Orleans", state="LA", type="school_surveillance", lat=29.9511, lng=-90.0715, description="New Orleans PS Bark deployment.", source="EFF Atlas; Student Privacy Compass"),
            Infrastructure(name="Bark School Surveillance — Birmingham City Schools AL", city="Birmingham", state="AL", type="school_surveillance", lat=33.5186, lng=-86.8104, description="Birmingham City Schools Bark contract.", source="EFF Atlas; Student Privacy Compass"),
            Infrastructure(name="Bark School Surveillance — Jackson PS MS", city="Jackson", state="MS", type="school_surveillance", lat=32.2988, lng=-90.1848, description="Jackson PS Bark deployment.", source="EFF Atlas; Student Privacy Compass"),
            Infrastructure(name="Bark School Surveillance — Little Rock SD AR", city="Little Rock", state="AR", type="school_surveillance", lat=34.7465, lng=-92.2896, description="Little Rock SD Bark contract.", source="EFF Atlas; Student Privacy Compass"),
            Infrastructure(name="Gaggle School Surveillance — Phoenix Union HS AZ", city="Phoenix", state="AZ", type="school_surveillance", lat=33.4484, lng=-112.0740, description="Phoenix Union High School District Gaggle deployment.", source="EFF Atlas; Student Privacy Compass"),
            Infrastructure(name="Gaggle School Surveillance — Tucson USD AZ", city="Tucson", state="AZ", type="school_surveillance", lat=32.2217, lng=-110.9265, description="Tucson USD Gaggle contract.", source="EFF Atlas; Student Privacy Compass"),
            Infrastructure(name="Gaggle School Surveillance — Sacramento City USD CA", city="Sacramento", state="CA", type="school_surveillance", lat=38.5816, lng=-121.4944, description="Sacramento City USD Gaggle deployment.", source="EFF Atlas; Student Privacy Compass"),
            Infrastructure(name="GoGuardian School Surveillance — Fresno USD CA", city="Fresno", state="CA", type="school_surveillance", lat=36.7378, lng=-119.7871, description="Fresno USD GoGuardian contract.", source="EFF Atlas; Student Privacy Compass"),
            Infrastructure(name="GoGuardian School Surveillance — Oakland USD CA", city="Oakland", state="CA", type="school_surveillance", lat=37.8044, lng=-122.2711, description="Oakland USD GoGuardian deployment.", source="EFF Atlas; Student Privacy Compass"),
            Infrastructure(name="Gaggle School Surveillance — El Paso ISD TX", city="El Paso", state="TX", type="school_surveillance", lat=31.7619, lng=-106.4850, description="El Paso ISD Gaggle contract.", source="EFF Atlas; Student Privacy Compass"),
            Infrastructure(name="GoGuardian School Surveillance — Fort Worth ISD TX", city="Fort Worth", state="TX", type="school_surveillance", lat=32.7555, lng=-97.3308, description="Fort Worth ISD GoGuardian deployment.", source="EFF Atlas; Student Privacy Compass"),
            Infrastructure(name="Gaggle School Surveillance — Omaha PS NE", city="Omaha", state="NE", type="school_surveillance", lat=41.2565, lng=-95.9345, description="Omaha PS Gaggle contract.", source="EFF Atlas; Student Privacy Compass"),
            Infrastructure(name="Gaggle School Surveillance — Wichita USD KS", city="Wichita", state="KS", type="school_surveillance", lat=37.6872, lng=-97.3301, description="Wichita USD Gaggle deployment.", source="EFF Atlas; Student Privacy Compass"),
            Infrastructure(name="GoGuardian School Surveillance — Spokane PS WA", city="Spokane", state="WA", type="school_surveillance", lat=47.6587, lng=-117.4260, description="Spokane PS GoGuardian contract.", source="EFF Atlas; Student Privacy Compass"),
            Infrastructure(name="Bark School Surveillance — Anchorage SD AK", city="Anchorage", state="AK", type="school_surveillance", lat=61.2181, lng=-149.9003, description="Anchorage SD Bark deployment.", source="EFF Atlas; Student Privacy Compass"),
            Infrastructure(name="Bark School Surveillance — Honolulu DOE HI", city="Honolulu", state="HI", type="school_surveillance", lat=21.3069, lng=-157.8583, description="Hawaii DOE Bark contract. Statewide deployment.", source="EFF Atlas; Student Privacy Compass"),
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
