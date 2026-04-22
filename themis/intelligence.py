from math import radians, sin, cos, sqrt, atan2
from collections import defaultdict
from datetime import datetime

THREAT_LEVELS = {
    "NOMINAL":      {"level": 0, "color": "#4ade80", "label": "Nominal"},
    "ELEVATED":     {"level": 1, "color": "#facc15", "label": "Elevated"},
    "COORDINATED":  {"level": 2, "color": "#fb923c", "label": "Coordinated"},
    "SATURATION":   {"level": 3, "color": "#f87171", "label": "Saturation"},
}

PROXIMITY_RADIUS_MI = 1.0

COORDINATION_PAIRS = [
    {"drone_signal", "imsi_catcher"},
    {"drone_signal", "lpr_network"},
    {"imsi_catcher", "lpr_network"},
    {"drone_signal", "camera_network"},
    {"ai_surveillance", "imsi_catcher"},
    {"fusion_center", "imsi_catcher"},
    {"fusion_center", "drone_signal"},
]

SATURATION_THRESHOLD = 3

def haversine_miles(lat1, lon1, lat2, lon2):
    R = 3958.8
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = sin(dlat/2)**2 + cos(lat1)*cos(lat2)*sin(dlon/2)**2
    return R * 2 * atan2(sqrt(a), sqrt(1-a))

def get_nearby(record, all_records, radius_mi=PROXIMITY_RADIUS_MI):
    nearby = []
    for r in all_records:
        if r["id"] == record["id"]:
            continue
        try:
            dist = haversine_miles(
                float(record["lat"]), float(record["lon"]),
                float(r["lat"]), float(r["lon"])
            )
            if dist <= radius_mi:
                nearby.append({**r, "_dist_mi": round(dist, 3)})
        except (TypeError, ValueError):
            continue
    return nearby

def score_record(record, all_records):
    nearby = get_nearby(record, all_records)
    nearby_categories = {r["category"] for r in nearby}
    all_categories = nearby_categories | {record["category"]}
    reasons = []
    threat = "NOMINAL"
    for pair in COORDINATION_PAIRS:
        if pair.issubset(all_categories):
            threat = "COORDINATED"
            reasons.append("Co-located: " + " + ".join(sorted(pair)))
    if len(all_categories) >= SATURATION_THRESHOLD:
        threat = "SATURATION"
        reasons.append(f"{len(all_categories)} surveillance types within {PROXIMITY_RADIUS_MI}mi")
    if threat == "NOMINAL" and len(all_categories) >= 2:
        threat = "ELEVATED"
        reasons.append("Multiple surveillance types nearby")
    return {
        "id": record["id"],
        "threat": threat,
        "threat_level": THREAT_LEVELS[threat]["level"],
        "threat_color": THREAT_LEVELS[threat]["color"],
        "threat_label": THREAT_LEVELS[threat]["label"],
        "reasons": reasons,
        "nearby_count": len(nearby),
        "nearby_categories": sorted(list(all_categories)),
    }

def build_threat_map(all_records):
    scored = {}
    for record in all_records:
        try:
            scored[record["id"]] = score_record(record, all_records)
        except Exception:
            continue
    city_scores = defaultdict(lambda: {"records": [], "max_threat": 0, "threat": "NOMINAL"})
    for record in all_records:
        city_key = f"{record.get('city', 'Unknown')}, {record.get('state', '')}"
        s = scored.get(record["id"], {})
        level = s.get("threat_level", 0)
        city_scores[city_key]["records"].append(record["id"])
        if level > city_scores[city_key]["max_threat"]:
            city_scores[city_key]["max_threat"] = level
            city_scores[city_key]["threat"] = s.get("threat", "NOMINAL")
            city_scores[city_key]["threat_color"] = s.get("threat_color", "#4ade80")
    hotspots = [
        {"city": city, **data}
        for city, data in city_scores.items()
        if data["max_threat"] >= 2
    ]
    hotspots.sort(key=lambda x: x["max_threat"], reverse=True)
    return {
        "scored": scored,
        "city_summaries": dict(city_scores),
        "hotspots": hotspots,
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "total_records": len(all_records),
        "threat_counts": {
            level: sum(1 for s in scored.values() if s["threat"] == level)
            for level in THREAT_LEVELS
        }
    }

def proximity_check(user_lat, user_lon, all_records, radius_mi=0.5):
    alerts = []
    for record in all_records:
        try:
            dist = haversine_miles(
                float(user_lat), float(user_lon),
                float(record["lat"]), float(record["lon"])
            )
            if dist <= radius_mi:
                alerts.append({**record, "distance_mi": round(dist, 3), "distance_ft": round(dist * 5280)})
        except (TypeError, ValueError):
            continue
    alerts.sort(key=lambda x: x["distance_mi"])
    return alerts
