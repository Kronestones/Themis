import os
from datetime import datetime, timezone
from sqlalchemy import create_engine, Column, String, Float, DateTime, Boolean, Integer, Text
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.dialects.postgresql import JSONB

Base = declarative_base()

class Detection(Base):
    __tablename__ = "detections"
    id         = Column(Integer, primary_key=True, autoincrement=True)
    time       = Column(DateTime(timezone=True), nullable=False)
    lead       = Column(String(64))
    type       = Column(String(64))
    detail     = Column(Text)
    severity   = Column(String(32))
    confidence = Column(Float, default=0.0)
    source     = Column(String(128))
    lat        = Column(Float, nullable=True)
    lng        = Column(Float, nullable=True)
    is_mobile  = Column(Boolean, default=False)

class Infrastructure(Base):
    __tablename__ = "infrastructure"
    id          = Column(Integer, primary_key=True, autoincrement=True)
    name        = Column(String(256))
    type        = Column(String(64))
    city        = Column(String(128))
    state       = Column(String(64))
    lat         = Column(Float)
    lng         = Column(Float)
    description = Column(Text)
    source      = Column(Text)
    verified    = Column(Boolean, default=True)

def get_engine():
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        raise RuntimeError("DATABASE_URL not set")
    return create_engine(url, pool_pre_ping=True, pool_recycle=300, pool_size=5, max_overflow=10)

def get_session():
    return sessionmaker(bind=get_engine())()

def init_db():
    engine = get_engine()
    Base.metadata.create_all(engine)
    _seed_infrastructure(engine)

def save_detection(detection: dict):
    session = get_session()
    try:
        loc = detection.get("location") or {}
        lat = loc.get("lat") or detection.get("lat")
        lng = loc.get("lng") or detection.get("lng")
        mobile_types = {"drone_signal","drone_bluetooth","robot_detection","imsi_catcher"}
        time_val = detection.get("time")
        if isinstance(time_val, str):
            try: time_val = datetime.fromisoformat(time_val)
            except: time_val = datetime.now(timezone.utc)
        elif not time_val:
            time_val = datetime.now(timezone.utc)
        row = Detection(
            time=time_val, lead=detection.get("lead","Themis"),
            type=detection.get("type","unknown"), detail=detection.get("detail",""),
            severity=detection.get("severity","info"), confidence=detection.get("confidence",0.0),
            source=detection.get("source",""), lat=lat, lng=lng,
            is_mobile=detection.get("type","") in mobile_types,
        )
        session.add(row)
        session.commit()
    except Exception as e:
        session.rollback()
        print(f"[DB] save_detection error: {e}")
    finally:
        session.close()

def get_detections(limit=500):
    session = get_session()
    try:
        rows = session.query(Detection).order_by(Detection.time.desc()).limit(limit).all()
        return [{"id":r.id,"time":r.time.isoformat() if r.time else None,"lead":r.lead,
                 "type":r.type,"detail":r.detail,"severity":r.severity,
                 "confidence":r.confidence,"source":r.source,
                 "lat":r.lat,"lng":r.lng,"is_mobile":r.is_mobile} for r in rows]
    except Exception as e:
        print(f"[DB] get_detections error: {e}")
        return []
    finally:
        session.close()

def get_infrastructure():
    session = get_session()
    try:
        rows = session.query(Infrastructure).filter_by(verified=True).all()
        return [{"id":r.id,"name":r.name,"type":r.type,"city":r.city,"state":r.state,
                 "lat":r.lat,"lng":r.lng,"description":r.description,"source":r.source} for r in rows]
    except Exception as e:
        print(f"[DB] get_infrastructure error: {e}")
        return []
    finally:
        session.close()

def get_detection_count():
    session = get_session()
    try: return session.query(Detection).count()
    except: return 0
    finally: session.close()

def _seed_infrastructure(engine):
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        if session.query(Infrastructure).count() > 0:
            return
        records = [

            # ── FUSION CENTERS (DHS public directory — dhs.gov/fusion-centers) ──

            Infrastructure(name="National Capital Region Intelligence Center",type="fusion_center",city="Washington",state="DC",lat=38.8951,lng=-77.0364,description="Regional fusion center serving DC metro area. Coordinates federal, state, and local surveillance data.",source="dhs.gov/fusion-centers"),
            Infrastructure(name="New York State Intelligence Center",type="fusion_center",city="Albany",state="NY",lat=42.6526,lng=-73.7562,description="New York primary fusion center. Known to monitor social media and political protests.",source="dhs.gov/fusion-centers; NYCLU"),
            Infrastructure(name="New York City Police Department Intelligence Bureau",type="fusion_center",city="New York",state="NY",lat=40.7128,lng=-74.0060,description="NYPD intelligence fusion operation. Feeds into Domain Awareness System.",source="dhs.gov/fusion-centers; NYPD"),
            Infrastructure(name="Chicago Crime Prevention Information Center",type="fusion_center",city="Chicago",state="IL",lat=41.8781,lng=-87.6298,description="Chicago fusion center. 32,000+ cameras. Palantir contract documented.",source="dhs.gov/fusion-centers; Chicago Tribune FOIA"),
            Infrastructure(name="Los Angeles Joint Regional Intelligence Center",type="fusion_center",city="Los Angeles",state="CA",lat=34.0522,lng=-118.2437,description="LA fusion center. Hub for LAPD, LASD, and federal agency data sharing.",source="dhs.gov/fusion-centers; ACLU of Southern California"),
            Infrastructure(name="Houston Regional Intelligence Service Center",type="fusion_center",city="Houston",state="TX",lat=29.7604,lng=-95.3698,description="Texas Gulf Coast fusion center. Monitors port, energy infrastructure, and public gatherings.",source="dhs.gov/fusion-centers"),
            Infrastructure(name="Arizona Counter Terrorism Information Center",type="fusion_center",city="Phoenix",state="AZ",lat=33.4484,lng=-112.0740,description="Arizona fusion center. CBP and ICE data sharing documented.",source="dhs.gov/fusion-centers"),
            Infrastructure(name="Oregon Terrorism Information Threat Assessment Network",type="fusion_center",city="Portland",state="OR",lat=45.5231,lng=-122.6765,description="Oregon fusion center. Documented monitoring of BLM protests 2020.",source="dhs.gov/fusion-centers; OPB"),
            Infrastructure(name="Colorado Information Analysis Center",type="fusion_center",city="Denver",state="CO",lat=39.7392,lng=-104.9903,description="Colorado fusion center. Palantir deployment documented by EFF.",source="dhs.gov/fusion-centers; EFF"),
            Infrastructure(name="Detroit and Southeast Michigan Information and Intelligence Center",type="fusion_center",city="Detroit",state="MI",lat=42.3314,lng=-83.0458,description="Detroit fusion center. One of densest facial recognition deployments in US.",source="dhs.gov/fusion-centers; MIT Media Lab"),
            Infrastructure(name="Northern California Regional Intelligence Center",type="fusion_center",city="Sacramento",state="CA",lat=38.5816,lng=-121.4944,description="Covers Northern California. Oakland ShotSpotter data flows through here.",source="dhs.gov/fusion-centers; EFF"),
            Infrastructure(name="Atlanta HIDTA Georgia Information Sharing and Analysis Center",type="fusion_center",city="Atlanta",state="GA",lat=33.7490,lng=-84.3880,description="Georgia statewide fusion center.",source="dhs.gov/fusion-centers"),
            Infrastructure(name="Texas Fusion Center",type="fusion_center",city="Austin",state="TX",lat=30.2672,lng=-97.7431,description="Statewide Texas fusion center operated by DPS.",source="dhs.gov/fusion-centers"),
            Infrastructure(name="North Texas Fusion Center",type="fusion_center",city="Dallas",state="TX",lat=32.7767,lng=-96.7970,description="Dallas-Fort Worth regional fusion center.",source="dhs.gov/fusion-centers"),
            Infrastructure(name="South Texas Fusion Center",type="fusion_center",city="San Antonio",state="TX",lat=29.4241,lng=-98.4936,description="South Texas regional fusion center. Close proximity to border operations.",source="dhs.gov/fusion-centers"),
            Infrastructure(name="Florida Fusion Center",type="fusion_center",city="Tallahassee",state="FL",lat=30.4518,lng=-84.2727,description="Statewide Florida fusion center.",source="dhs.gov/fusion-centers"),
            Infrastructure(name="Miami-Dade Fusion Center",type="fusion_center",city="Miami",state="FL",lat=25.7617,lng=-80.1918,description="South Florida regional fusion center. Monitors port of Miami.",source="dhs.gov/fusion-centers"),
            Infrastructure(name="Tampa Bay Regional Intelligence Center",type="fusion_center",city="Tampa",state="FL",lat=27.9506,lng=-82.4572,description="Tampa Bay area fusion center.",source="dhs.gov/fusion-centers"),
            Infrastructure(name="Ohio Homeland Security Fusion Center",type="fusion_center",city="Columbus",state="OH",lat=39.9612,lng=-82.9988,description="Ohio statewide fusion center.",source="dhs.gov/fusion-centers"),
            Infrastructure(name="Pennsylvania Criminal Intelligence Center",type="fusion_center",city="Harrisburg",state="PA",lat=40.2732,lng=-76.8867,description="Pennsylvania statewide fusion center.",source="dhs.gov/fusion-centers"),
            Infrastructure(name="Delaware Information and Analysis Center",type="fusion_center",city="Dover",state="DE",lat=39.1582,lng=-75.5244,description="Delaware fusion center.",source="dhs.gov/fusion-centers"),
            Infrastructure(name="Maryland Coordination and Analysis Center",type="fusion_center",city="Woodlawn",state="MD",lat=39.3412,lng=-76.7338,description="Maryland fusion center. Documented monitoring of activists.",source="dhs.gov/fusion-centers; ACLU MD"),
            Infrastructure(name="Virginia Fusion Center",type="fusion_center",city="Richmond",state="VA",lat=37.5407,lng=-77.4360,description="Virginia statewide fusion center.",source="dhs.gov/fusion-centers"),
            Infrastructure(name="North Carolina Information Sharing and Analysis Center",type="fusion_center",city="Raleigh",state="NC",lat=35.7796,lng=-78.6382,description="North Carolina fusion center.",source="dhs.gov/fusion-centers"),
            Infrastructure(name="Georgia Information Sharing and Analysis Center",type="fusion_center",city="Atlanta",state="GA",lat=33.7490,lng=-84.3880,description="Georgia fusion center. Feeds into federal network.",source="dhs.gov/fusion-centers"),
            Infrastructure(name="Tennessee Fusion Center",type="fusion_center",city="Nashville",state="TN",lat=36.1627,lng=-86.7816,description="Tennessee statewide fusion center.",source="dhs.gov/fusion-centers"),
            Infrastructure(name="Kentucky Intelligence Fusion Center",type="fusion_center",city="Frankfort",state="KY",lat=38.2009,lng=-84.8733,description="Kentucky fusion center.",source="dhs.gov/fusion-centers"),
            Infrastructure(name="Indiana Intelligence Fusion Center",type="fusion_center",city="Indianapolis",state="IN",lat=39.7684,lng=-86.1581,description="Indiana statewide fusion center.",source="dhs.gov/fusion-centers"),
            Infrastructure(name="Wisconsin Statewide Information Center",type="fusion_center",city="Madison",state="WI",lat=43.0731,lng=-89.4012,description="Wisconsin fusion center.",source="dhs.gov/fusion-centers"),
            Infrastructure(name="Minnesota Fusion Center",type="fusion_center",city="St. Paul",state="MN",lat=44.9537,lng=-93.0900,description="Minnesota fusion center. Documented monitoring of Standing Rock activists.",source="dhs.gov/fusion-centers; The Intercept"),
            Infrastructure(name="Iowa Intelligence Fusion Center",type="fusion_center",city="Des Moines",state="IA",lat=41.5868,lng=-93.6250,description="Iowa statewide fusion center.",source="dhs.gov/fusion-centers"),
            Infrastructure(name="Missouri Information Analysis Center",type="fusion_center",city="Jefferson City",state="MO",lat=38.5767,lng=-92.1735,description="Missouri fusion center. Produced report targeting civil liberties groups.",source="dhs.gov/fusion-centers; ACLU"),
            Infrastructure(name="Kansas Intelligence Fusion Center",type="fusion_center",city="Topeka",state="KS",lat=39.0473,lng=-95.6752,description="Kansas statewide fusion center.",source="dhs.gov/fusion-centers"),
            Infrastructure(name="Nebraska Information Analysis Center",type="fusion_center",city="Omaha",state="NE",lat=41.2565,lng=-95.9345,description="Nebraska fusion center.",source="dhs.gov/fusion-centers"),
            Infrastructure(name="South Dakota Fusion Center",type="fusion_center",city="Pierre",state="SD",lat=44.3683,lng=-100.3510,description="South Dakota fusion center.",source="dhs.gov/fusion-centers"),
            Infrastructure(name="North Dakota State and Local Intelligence Center",type="fusion_center",city="Bismarck",state="ND",lat=46.8083,lng=-100.7837,description="North Dakota fusion center. Active during Dakota Access Pipeline protests.",source="dhs.gov/fusion-centers; The Intercept"),
            Infrastructure(name="Montana All Threat Intelligence Center",type="fusion_center",city="Helena",state="MT",lat=46.5958,lng=-112.0270,description="Montana statewide fusion center.",source="dhs.gov/fusion-centers"),
            Infrastructure(name="Idaho Criminal Intelligence Center",type="fusion_center",city="Boise",state="ID",lat=43.6150,lng=-116.2023,description="Idaho fusion center.",source="dhs.gov/fusion-centers"),
            Infrastructure(name="Washington State Fusion Center",type="fusion_center",city="Seattle",state="WA",lat=47.6062,lng=-122.3321,description="Washington state fusion center.",source="dhs.gov/fusion-centers"),
            Infrastructure(name="Oregon Titan Fusion Center",type="fusion_center",city="Salem",state="OR",lat=44.9429,lng=-123.0351,description="Oregon statewide fusion center — separate from Portland TITAN.",source="dhs.gov/fusion-centers"),
            Infrastructure(name="Nevada Threat Analysis Center",type="fusion_center",city="Las Vegas",state="NV",lat=36.1699,lng=-115.1398,description="Nevada fusion center. Heavy surveillance around casinos and events.",source="dhs.gov/fusion-centers"),
            Infrastructure(name="Utah Statewide Information and Analysis Center",type="fusion_center",city="Salt Lake City",state="UT",lat=40.7608,lng=-111.8910,description="Utah fusion center. Adjacent to NSA data center in Bluffdale.",source="dhs.gov/fusion-centers"),
            Infrastructure(name="New Mexico All Source Intelligence Center",type="fusion_center",city="Santa Fe",state="NM",lat=35.6870,lng=-105.9378,description="New Mexico fusion center.",source="dhs.gov/fusion-centers"),
            Infrastructure(name="Oklahoma Information Fusion Center",type="fusion_center",city="Oklahoma City",state="OK",lat=35.4676,lng=-97.5164,description="Oklahoma statewide fusion center.",source="dhs.gov/fusion-centers"),
            Infrastructure(name="Arkansas Counterterrorism Intelligence Center",type="fusion_center",city="Little Rock",state="AR",lat=34.7465,lng=-92.2896,description="Arkansas fusion center.",source="dhs.gov/fusion-centers"),
            Infrastructure(name="Louisiana State Analytical and Fusion Exchange",type="fusion_center",city="Baton Rouge",state="LA",lat=30.4515,lng=-91.1871,description="Louisiana fusion center.",source="dhs.gov/fusion-centers"),
            Infrastructure(name="Mississippi Fusion Center",type="fusion_center",city="Jackson",state="MS",lat=32.2988,lng=-90.1848,description="Mississippi statewide fusion center.",source="dhs.gov/fusion-centers"),
            Infrastructure(name="Alabama Fusion Center",type="fusion_center",city="Montgomery",state="AL",lat=32.3792,lng=-86.3077,description="Alabama statewide fusion center.",source="dhs.gov/fusion-centers"),
            Infrastructure(name="South Carolina Information and Intelligence Center",type="fusion_center",city="Columbia",state="SC",lat=34.0007,lng=-81.0348,description="South Carolina fusion center.",source="dhs.gov/fusion-centers"),
            Infrastructure(name="West Virginia Intelligence Fusion Center",type="fusion_center",city="Charleston",state="WV",lat=38.3498,lng=-81.6326,description="West Virginia fusion center.",source="dhs.gov/fusion-centers"),
            Infrastructure(name="New Jersey Regional Operations and Intelligence Center",type="fusion_center",city="Trenton",state="NJ",lat=40.2171,lng=-74.7429,description="New Jersey fusion center. Documented monitoring of Muslim communities.",source="dhs.gov/fusion-centers; AP investigation"),
            Infrastructure(name="Connecticut Intelligence Center",type="fusion_center",city="Hartford",state="CT",lat=41.7658,lng=-72.6851,description="Connecticut statewide fusion center.",source="dhs.gov/fusion-centers"),
            Infrastructure(name="Rhode Island Fusion Center",type="fusion_center",city="Providence",state="RI",lat=41.8240,lng=-71.4128,description="Rhode Island fusion center.",source="dhs.gov/fusion-centers"),
            Infrastructure(name="Massachusetts Commonwealth Fusion Center",type="fusion_center",city="Maynard",state="MA",lat=42.4315,lng=-71.4534,description="Massachusetts fusion center.",source="dhs.gov/fusion-centers"),
            Infrastructure(name="New Hampshire Information and Analysis Center",type="fusion_center",city="Concord",state="NH",lat=43.2081,lng=-71.5376,description="New Hampshire fusion center.",source="dhs.gov/fusion-centers"),
            Infrastructure(name="Vermont Intelligence Center",type="fusion_center",city="Waterbury",state="VT",lat=44.3376,lng=-72.7562,description="Vermont fusion center.",source="dhs.gov/fusion-centers"),
            Infrastructure(name="Maine Information and Analysis Center",type="fusion_center",city="Augusta",state="ME",lat=44.3106,lng=-69.7795,description="Maine fusion center.",source="dhs.gov/fusion-centers"),
            Infrastructure(name="Alaska Information and Analysis Center",type="fusion_center",city="Anchorage",state="AK",lat=61.2181,lng=-149.9003,description="Alaska fusion center.",source="dhs.gov/fusion-centers"),
            Infrastructure(name="Hawaii Fusion Center",type="fusion_center",city="Honolulu",state="HI",lat=21.3069,lng=-157.8583,description="Hawaii fusion center.",source="dhs.gov/fusion-centers"),
            Infrastructure(name="Guam Homeland Security Fusion Center",type="fusion_center",city="Hagatna",state="GU",lat=13.4443,lng=144.7937,description="Guam fusion center.",source="dhs.gov/fusion-centers"),
            Infrastructure(name="Puerto Rico National Guard Counterdrug Fusion Center",type="fusion_center",city="San Juan",state="PR",lat=18.4655,lng=-66.1057,description="Puerto Rico fusion center.",source="dhs.gov/fusion-centers"),

            # ── ICE FACILITIES (ice.gov facility locator — public) ──

            Infrastructure(name="Stewart Detention Center",type="ice_facility",city="Lumpkin",state="GA",lat=32.0496,lng=-84.7963,description="CoreCivic-operated. Capacity 1,800+. Documented human rights concerns.",source="ICE.gov facility locator; Freedom for Immigrants"),
            Infrastructure(name="Adelanto ICE Processing Center",type="ice_facility",city="Adelanto",state="CA",lat=34.5822,lng=-117.4327,description="GEO Group-operated. Largest ICE facility in California.",source="ICE.gov facility locator; ACLU of Southern California"),
            Infrastructure(name="Eloy Federal Contract Facility",type="ice_facility",city="Eloy",state="AZ",lat=32.7837,lng=-111.5548,description="CoreCivic-operated. Major ICE detention hub in Arizona.",source="ICE.gov facility locator"),
            Infrastructure(name="South Texas Family Residential Center",type="ice_facility",city="Dilley",state="TX",lat=28.6672,lng=-99.1745,description="CoreCivic-operated. Largest family detention center in the US.",source="ICE.gov facility locator; CARA Pro Bono Project"),
            Infrastructure(name="Krome North Service Processing Center",type="ice_facility",city="Miami",state="FL",lat=25.6582,lng=-80.5432,description="Federally operated ICE processing center in South Florida.",source="ICE.gov facility locator"),
            Infrastructure(name="Northwest ICE Processing Center",type="ice_facility",city="Tacoma",state="WA",lat=47.2340,lng=-122.4680,description="GEO Group-operated. Primary ICE facility in Pacific Northwest.",source="ICE.gov facility locator; La Resistencia"),
            Infrastructure(name="York County Prison ICE contract",type="ice_facility",city="York",state="PA",lat=39.9626,lng=-76.7277,description="County facility with ICE contract. Major detention hub in Northeast.",source="ICE.gov facility locator; ACLU PA"),
            Infrastructure(name="Broadview ICE Processing Center",type="ice_facility",city="Broadview",state="IL",lat=41.8612,lng=-87.8573,description="Federal ICE staging and processing facility near Chicago.",source="ICE.gov facility locator"),
            Infrastructure(name="Otay Mesa Detention Center",type="ice_facility",city="San Diego",state="CA",lat=32.5671,lng=-116.9756,description="CoreCivic-operated near US-Mexico border.",source="ICE.gov facility locator"),
            Infrastructure(name="Bergen County Jail ICE contract",type="ice_facility",city="Hackensack",state="NJ",lat=40.8859,lng=-74.0435,description="County jail with ICE contract. Serves NYC metro area.",source="ICE.gov facility locator; NJ ACLU"),
            Infrastructure(name="Port Isabel Service Processing Center",type="ice_facility",city="Los Fresnos",state="TX",lat=26.0737,lng=-97.4800,description="Federally operated. One of oldest ICE detention facilities.",source="ICE.gov facility locator"),
            Infrastructure(name="Laredo Processing Center",type="ice_facility",city="Laredo",state="TX",lat=27.5306,lng=-99.4803,description="GEO Group-operated border detention facility.",source="ICE.gov facility locator"),
            Infrastructure(name="El Paso Processing Center",type="ice_facility",city="El Paso",state="TX",lat=31.7619,lng=-106.4850,description="Federally operated. Major processing hub on southern border.",source="ICE.gov facility locator"),
            Infrastructure(name="Yuma County Detention Center ICE contract",type="ice_facility",city="Yuma",state="AZ",lat=32.6927,lng=-114.6277,description="County facility with ICE contract on Arizona border.",source="ICE.gov facility locator"),
            Infrastructure(name="Cibola County Correctional Center",type="ice_facility",city="Milan",state="NM",lat=35.1873,lng=-107.9000,description="CoreCivic-operated. New Mexico ICE detention.",source="ICE.gov facility locator"),
            Infrastructure(name="Pine Prairie ICE Processing Center",type="ice_facility",city="Pine Prairie",state="LA",lat=30.7835,lng=-92.4251,description="GEO Group-operated Louisiana detention facility.",source="ICE.gov facility locator"),
            Infrastructure(name="LaSalle ICE Processing Center",type="ice_facility",city="Jena",state="LA",lat=31.6835,lng=-92.1193,description="GEO Group-operated. One of largest ICE facilities in South.",source="ICE.gov facility locator"),
            Infrastructure(name="Winn Correctional Center ICE contract",type="ice_facility",city="Winnfield",state="LA",lat=31.9235,lng=-92.6382,description="CoreCivic-operated with ICE contract.",source="ICE.gov facility locator"),
            Infrastructure(name="Richwood Correctional Center",type="ice_facility",city="Monroe",state="LA",lat=32.5093,lng=-92.1193,description="LaSalle Corrections-operated ICE facility.",source="ICE.gov facility locator"),
            Infrastructure(name="Baker County Detention Center",type="ice_facility",city="Macclenny",state="FL",lat=30.2785,lng=-82.1229,description="County facility with ICE contract in Florida.",source="ICE.gov facility locator"),
            Infrastructure(name="Glades County Detention Center",type="ice_facility",city="Moore Haven",state="FL",lat=26.8334,lng=-81.0840,description="County ICE detention facility in Florida.",source="ICE.gov facility locator"),
            Infrastructure(name="Folkston ICE Processing Center",type="ice_facility",city="Folkston",state="GA",lat=30.8357,lng=-82.0124,description="Two facilities operated by CoreCivic in Georgia.",source="ICE.gov facility locator"),
            Infrastructure(name="Irwin County Detention Center",type="ice_facility",city="Ocilla",state="GA",lat=31.5932,lng=-83.2516,description="LaSalle Corrections-operated. Site of documented medical abuse allegations.",source="ICE.gov facility locator; Project South investigation"),
            Infrastructure(name="Prairieland Detention Center",type="ice_facility",city="Alvarado",state="TX",lat=32.4079,lng=-97.2128,description="LaSalle Corrections-operated Texas facility.",source="ICE.gov facility locator"),
            Infrastructure(name="Houston Contract Detention Facility",type="ice_facility",city="Houston",state="TX",lat=29.6897,lng=-95.4039,description="CoreCivic-operated Houston ICE facility.",source="ICE.gov facility locator"),
            Infrastructure(name="Montgomery ICE Processing Center",type="ice_facility",city="Conroe",state="TX",lat=30.3119,lng=-95.4561,description="GEO Group-operated near Houston.",source="ICE.gov facility locator"),
            Infrastructure(name="Tallahatchie County Correctional Facility",type="ice_facility",city="Tutwiler",state="MS",lat=33.9971,lng=-90.4368,description="CoreCivic-operated Mississippi ICE facility.",source="ICE.gov facility locator"),
            Infrastructure(name="Strafford County Department of Corrections ICE contract",type="ice_facility",city="Dover",state="NH",lat=43.1979,lng=-70.8737,description="New England ICE detention.",source="ICE.gov facility locator"),
            Infrastructure(name="Suffolk County House of Correction ICE contract",type="ice_facility",city="Boston",state="MA",lat=42.3601,lng=-71.0589,description="Massachusetts ICE detention contract.",source="ICE.gov facility locator"),
            Infrastructure(name="Mesa Verde ICE Processing Center",type="ice_facility",city="Bakersfield",state="CA",lat=35.3733,lng=-119.0187,description="GEO Group-operated California facility.",source="ICE.gov facility locator"),
            Infrastructure(name="Golden State Annex",type="ice_facility",city="McFarland",state="CA",lat=35.6810,lng=-119.2290,description="GEO Group-operated. Opened 2020.",source="ICE.gov facility locator"),
            Infrastructure(name="Tacoma Northwest Detention Center Annex",type="ice_facility",city="Tacoma",state="WA",lat=47.2290,lng=-122.4710,description="GEO Group expansion facility adjacent to main NWDC.",source="ICE.gov facility locator"),
            Infrastructure(name="Denver Contract Detention Facility",type="ice_facility",city="Aurora",state="CO",lat=39.7294,lng=-104.7319,description="GEO Group-operated Colorado facility.",source="ICE.gov facility locator; Adelanto Watch"),

            # ── CAMERA NETWORKS (EFF Atlas of Surveillance) ──

            Infrastructure(name="Chicago POD Camera Network",type="camera_network",city="Chicago",state="IL",lat=41.8781,lng=-87.6298,description="32,000+ Police Observation Device cameras. Facial recognition capable.",source="EFF Atlas of Surveillance; Chicago Tribune FOIA"),
            Infrastructure(name="NYC Domain Awareness System",type="camera_network",city="New York",state="NY",lat=40.7128,lng=-74.0060,description="Microsoft-built NYPD network. 15,000+ cameras. LPR and facial recognition integrated.",source="EFF Atlas of Surveillance; NYPD DAS documentation"),
            Infrastructure(name="LA ShotSpotter and Camera Network",type="camera_network",city="Los Angeles",state="CA",lat=34.0522,lng=-118.2437,description="LAPD camera and acoustic surveillance network covering South and East LA.",source="EFF Atlas of Surveillance; LAPD annual reports"),
            Infrastructure(name="Detroit Project Green Light",type="camera_network",city="Detroit",state="MI",lat=42.3314,lng=-83.0458,description="Real-time facial recognition camera network. Highest false positive rate documented by MIT.",source="EFF Atlas of Surveillance; MIT Media Lab"),
            Infrastructure(name="Baltimore CitiWatch",type="camera_network",city="Baltimore",state="MD",lat=39.2904,lng=-76.6122,description="800+ camera network plus aerial surveillance program covering entire city.",source="EFF Atlas of Surveillance; Baltimore Sun"),
            Infrastructure(name="New Orleans Real Time Crime Center",type="camera_network",city="New Orleans",state="LA",lat=29.9511,lng=-90.0715,description="Palantir-powered real time crime center. Facial recognition deployed.",source="EFF Atlas of Surveillance; The Lens"),
            Infrastructure(name="Atlanta Video Integration Center",type="camera_network",city="Atlanta",state="GA",lat=33.7490,lng=-84.3880,description="Atlanta camera network feeding into fusion center.",source="EFF Atlas of Surveillance"),
            Infrastructure(name="Philadelphia Video Surveillance",type="camera_network",city="Philadelphia",state="PA",lat=39.9526,lng=-75.1652,description="Philadelphia police camera network. ShotSpotter deployed in multiple districts.",source="EFF Atlas of Surveillance"),
            Infrastructure(name="Kansas City Real Time Crime Center",type="camera_network",city="Kansas City",state="MO",lat=39.0997,lng=-94.5786,description="Kansas City camera and analytics network.",source="EFF Atlas of Surveillance"),
            Infrastructure(name="Memphis Real Time Crime Center",type="camera_network",city="Memphis",state="TN",lat=35.1495,lng=-90.0490,description="Memphis camera network. ShotSpotter and facial recognition deployed.",source="EFF Atlas of Surveillance"),
            Infrastructure(name="Oakland Surveillance Network",type="camera_network",city="Oakland",state="CA",lat=37.8044,lng=-122.2712,description="Oakland Domain Awareness Center. Integrates cameras, LPR, and gunshot detection.",source="EFF Atlas of Surveillance; ACLU NorCal"),
            Infrastructure(name="San Diego Smart Streetlight Program",type="camera_network",city="San Diego",state="CA",lat=32.7157,lng=-117.1611,description="City-wide smart streetlight surveillance network. Cameras on 3,000+ streetlights.",source="EFF Atlas of Surveillance; Voice of San Diego"),
            Infrastructure(name="Houston ShotSpotter Network",type="camera_network",city="Houston",state="TX",lat=29.7604,lng=-95.3698,description="Houston acoustic surveillance and camera network.",source="EFF Atlas of Surveillance"),

            # ── LICENSE PLATE READER NETWORKS (EFF Atlas of Surveillance) ──

            Infrastructure(name="NYPD License Plate Reader Network",type="lpr_network",city="New York",state="NY",lat=40.7128,lng=-74.0060,description="Reads and stores millions of plates per day. Feeds into Domain Awareness System.",source="EFF Atlas of Surveillance; NYPD FOIA responses"),
            Infrastructure(name="Vigilant Solutions LPR Chicago",type="lpr_network",city="Chicago",state="IL",lat=41.8781,lng=-87.6298,description="Motorola LPR network integrated with CPD. National repository access.",source="EFF Atlas of Surveillance; CPD contracts"),
            Infrastructure(name="Flock Safety LPR Network Atlanta Metro",type="lpr_network",city="Atlanta",state="GA",lat=33.7490,lng=-84.3880,description="Automated LPR network. Data shared with law enforcement regionally.",source="EFF Atlas of Surveillance; Flock Safety public contracts"),
            Infrastructure(name="Flock Safety LPR Network Denver",type="lpr_network",city="Denver",state="CO",lat=39.7392,lng=-104.9903,description="Flock Safety LPR deployment across Denver metro.",source="EFF Atlas of Surveillance"),
            Infrastructure(name="Flock Safety LPR Network Houston",type="lpr_network",city="Houston",state="TX",lat=29.7604,lng=-95.3698,description="Flock Safety LPR across Houston suburbs.",source="EFF Atlas of Surveillance; Flock Safety contracts"),
            Infrastructure(name="Los Angeles LPR Network",type="lpr_network",city="Los Angeles",state="CA",lat=34.0522,lng=-118.2437,description="LAPD and county sheriff LPR network. Millions of reads stored.",source="EFF Atlas of Surveillance; LAPD FOIA"),
            Infrastructure(name="Maryland State Police LPR Network",type="lpr_network",city="Baltimore",state="MD",lat=39.2904,lng=-76.6122,description="Statewide Maryland LPR network on highways and fixed locations.",source="EFF Atlas of Surveillance"),
            Infrastructure(name="Phoenix LPR Network",type="lpr_network",city="Phoenix",state="AZ",lat=33.4484,lng=-112.0740,description="Phoenix PD LPR network. Data retained indefinitely.",source="EFF Atlas of Surveillance"),
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


def get_all_records_as_dicts():
    from themis.database import db
    rows = db.session.execute(db.text("SELECT id, name, type, city, state, lat, lng, description, source, verified, foia_url, legal_status, legal_notes, threat_level FROM infrastructure")).fetchall()
    return [
        {
            "id":           r.id,
            "name":         r.name,
            "category":     r.type,
            "lat":          float(r.lat) if r.lat else None,
            "lon":          float(r.lng) if r.lng else None,
            "city":         r.city,
            "state":        r.state,
            "description":  r.description,
            "source":       r.source,
            "foia_url":     r.foia_url,
            "legal_status": r.legal_status,
            "legal_notes":  r.legal_notes,
            "threat_level": r.threat_level or 0,
        }
        for r in rows
        if r.lat and r.lng
    ]
