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
        # Check if all expected types are present
        existing_types = [r[0] for r in session.query(Infrastructure.type).distinct().all()]
        all_types = [
            'fusion_center', 'ice_facility', 'camera_network', 'lpr_network',
            'border_surveillance', 'imsi_catcher', 'facial_recognition',
            'police_drone', 'surveillance_camera', 'robot_detection',
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
