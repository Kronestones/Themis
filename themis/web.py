from flask import Flask, jsonify, request, send_from_directory, Response
from functools import wraps
from collections import Counter
import time
from datetime import datetime, timezone
import os

app = Flask(__name__)

def create_app():
    try:
        from .database import init_db
        init_db()
        print("[Themis Web] DB initialized.")
    except Exception as e:
        print(f"[Themis Web] DB init warning: {e}")
    return app

@app.route("/")
def index():
    return send_from_directory('templates', 'map.html')

@app.route("/api/detections")
def api_detections():
    from .database import get_detections, get_detection_count
    limit = min(int(request.args.get("limit", 200)), 1000)
    all_detections = get_detections(limit=limit)
    mapped = [d for d in all_detections if d.get("lat") and d.get("lng")]
    return jsonify({
        "ok": True,
        "mapped": mapped,
        "feed": all_detections[:50],
        "total": get_detection_count(),
        "updated": datetime.now(timezone.utc).isoformat(),
    })

@app.route("/api/infrastructure")
def api_infrastructure():
    from .database import get_infrastructure
    records = get_infrastructure()
    return jsonify({
        "ok": True,
        "records": records,
        "count": len(records),
        "source_note": "All locations sourced from publicly available records: DHS fusion center public directory, ICE.gov facility locator, EFF Atlas of Surveillance, ACLU investigations, and verified investigative journalism. No private or classified data. All public record.",
    })


@app.route("/api/threats")
def api_threats():
    from .database import get_infrastructure
    from .intelligence import build_threat_map
    records = get_infrastructure()
    # Normalize field names for intelligence engine
    for r in records:
        r["lon"] = r.get("lng")
        r["category"] = r.get("type")
    result = build_threat_map(records)
    return jsonify(result)

@app.route("/api/v1/surveillance")
def public_api():
    from .database import get_infrastructure
    category = request.args.get("category")
    state    = request.args.get("state")
    city     = request.args.get("city")
    limit    = min(int(request.args.get("limit", 100)), 500)
    offset   = int(request.args.get("offset", 0))
    records  = get_infrastructure()
    if category:
        records = [r for r in records if r.get("type") == category]
    if state:
        records = [r for r in records if r.get("state","").lower() == state.lower()]
    if city:
        records = [r for r in records if city.lower() in r.get("city","").lower()]
    total = len(records)
    page  = records[offset: offset + limit]
    return jsonify({
        "api_version": "1.0",
        "total": total,
        "limit": limit,
        "offset": offset,
        "count": len(page),
        "records": page,
    })

@app.route("/report/<city_state>")
def city_report(city_state):
    from .database import get_infrastructure
    from .intelligence import build_threat_map
    from collections import Counter
    from datetime import datetime
    from flask import Response
    parts = city_state.replace("+"," ").replace("-"," ").split()
    if len(parts) >= 2 and len(parts[-1]) == 2:
        state = parts[-1].upper()
        city  = " ".join(parts[:-1]).title()
    else:
        city  = " ".join(parts).title()
        state = None
    records = get_infrastructure()
    filtered = [r for r in records if city.lower() in r.get("city","").lower()]
    if state:
        filtered = [r for r in filtered if r.get("state","").upper() == state]
    for r in filtered:
        r["lon"] = r.get("lng")
        r["category"] = r.get("type")
    threat_data = build_threat_map(filtered) if filtered else {"hotspots":[],"threat_counts":{},"scored":{}}
    cat_counts = Counter(r["type"] for r in filtered)
    rows = "".join(f"<tr><td>{r.get('name','')}</td><td>{r.get('type','')}</td><td>{r.get('city','')}</td><td>{r.get('state','')}</td><td>{threat_data.get('scored',{}).get(r['id'],{}).get('threat_label','Nominal')}</td></tr>" for r in filtered)
    html = f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Themis Report — {city}</title>
    <style>body{{font-family:Georgia,serif;max-width:800px;margin:40px auto;padding:0 20px}}
    table{{width:100%;border-collapse:collapse}}th{{background:#111;color:#fff;padding:8px}}
    td{{padding:7px;border-bottom:1px solid #eee}}h1{{border-bottom:3px solid #111;padding-bottom:10px}}</style></head>
    <body><h1>Themis Surveillance Report</h1><h2>{city}{', '+state if state else ''}</h2>
    <p>Generated: {datetime.utcnow().strftime('%B %d, %Y')} · {len(filtered)} records · {len(cat_counts)} surveillance types</p>
    <table><tr><th>Name</th><th>Type</th><th>City</th><th>State</th><th>Threat</th></tr>{rows}</table>
    <p style="margin-top:40px;font-size:0.8em;color:#666">Themis — Public surveillance accountability. All data from public records. Power to the People. 🌾⚖️</p>
    </body></html>"""
    return Response(html, mimetype="text/html")

@app.route("/api/status")
def api_status():
    from .database import get_detection_count
    return jsonify({
        "ok": True,
        "version": "1.0.0",
        "detections": get_detection_count(),
        "time": datetime.now(timezone.utc).isoformat(),
        "message": "The watch does not stop.",
    })


# ── Rate limiter ─────────────────────────────────────────────────────────────
_rate_cache = {}

def rate_limit(max_per_minute=30):
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            ip = request.remote_addr
            now = time.time()
            window = _rate_cache.get(ip, [])
            window = [t for t in window if now - t < 60]
            if len(window) >= max_per_minute:
                return jsonify({"error": "Rate limit exceeded."}), 429
            window.append(now)
            _rate_cache[ip] = window
            return f(*args, **kwargs)
        return wrapped
    return decorator


# ── /api/threats ─────────────────────────────────────────────────────────────
@app.route("/api/threats")
@rate_limit(30)
def api_threats():
    from .intelligence import build_threat_map
    from .database import get_all_records_as_dicts
    records = get_all_records_as_dicts()
    result = build_threat_map(records)
    return jsonify(result)


# ── /api/proximity ───────────────────────────────────────────────────────────
@app.route("/api/proximity")
@rate_limit(60)
def api_proximity():
    from .intelligence import proximity_check
    from .database import get_all_records_as_dicts
    try:
        lat    = float(request.args.get("lat"))
        lon    = float(request.args.get("lon"))
        radius = min(float(request.args.get("radius", 0.5)), 5.0)
    except (TypeError, ValueError):
        return jsonify({"error": "lat and lon required"}), 400
    records = get_all_records_as_dicts()
    alerts  = proximity_check(lat, lon, records, radius_mi=radius)
    return jsonify({"alerts": alerts, "count": len(alerts), "radius_mi": radius})


# ── /api/v1/surveillance ─────────────────────────────────────────────────────
@app.route("/api/v1/surveillance")
@rate_limit(30)
def public_api():
    from .database import get_all_records_as_dicts
    category = request.args.get("category")
    state    = request.args.get("state")
    city     = request.args.get("city")
    limit    = min(int(request.args.get("limit", 100)), 500)
    offset   = int(request.args.get("offset", 0))
    records  = get_all_records_as_dicts()
    if category:
        records = [r for r in records if r.get("category") == category]
    if state:
        records = [r for r in records if r.get("state", "").lower() == state.lower()]
    if city:
        records = [r for r in records if city.lower() in r.get("city", "").lower()]
    total = len(records)
    page  = records[offset: offset + limit]
    return jsonify({
        "api_version": "1.0",
        "total":  total,
        "limit":  limit,
        "offset": offset,
        "count":  len(page),
        "records": page,
    })


# ── /report/<city_state> ─────────────────────────────────────────────────────
@app.route("/report/<city_state>")
def city_report(city_state):
    from .database import get_all_records_as_dicts
    from .intelligence import build_threat_map
    parts = city_state.replace("+", " ").replace("-", " ").split()
    if len(parts) >= 2 and len(parts[-1]) == 2:
        state = parts[-1].upper()
        city  = " ".join(parts[:-1]).title()
    else:
        city  = " ".join(parts).title()
        state = None
    records  = get_all_records_as_dicts()
    filtered = [r for r in records if city.lower() in r.get("city", "").lower()]
    if state:
        filtered = [r for r in filtered if r.get("state", "").upper() == state]
    threat_data = build_threat_map(filtered) if filtered else {"hotspots": [], "threat_counts": {}, "scored": {}}
    cat_counts  = Counter(r["category"] for r in filtered)
    rows = "".join(f"""<tr>
        <td>{r.get("name","")}</td>
        <td>{r.get("category","")}</td>
        <td>{r.get("city","")}</td>
        <td>{r.get("state","")}</td>
        <td>{threat_data.get("scored",{{}}).get(r["id"],{{}}).get("threat_label","Nominal")}</td>
        <td>{"<a href='" + r["foia_url"] + "' target='_blank'>FOIA ↗</a>" if r.get("foia_url") else "—"}</td>
    </tr>""" for r in filtered)
    cat_rows = "".join(f"<tr><td>{cat}</td><td>{cnt}</td></tr>" for cat, cnt in sorted(cat_counts.items(), key=lambda x: -x[1]))
    html = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<title>Themis Report — {city}{", " + state if state else ""}</title>
<style>
body{{font-family:Georgia,serif;max-width:800px;margin:40px auto;padding:0 20px;color:#111}}
h1{{border-bottom:3px solid #111;padding-bottom:10px}}
table{{width:100%;border-collapse:collapse;margin-top:16px;font-size:0.85em}}
th{{background:#111;color:#fff;padding:8px 12px;text-align:left}}
td{{padding:7px 12px;border-bottom:1px solid #eee}}
tr:nth-child(even) td{{background:#f9f9f9}}
.footer{{margin-top:40px;padding-top:20px;border-top:1px solid #ddd;font-size:0.8em;color:#666}}
</style></head><body>
<h1>Themis Surveillance Report</h1>
<h2>{city}{", " + state if state else ""}</h2>
<p style="color:#666;font-size:0.9em">Generated: {datetime.now().strftime("%B %d, %Y")} · themis-2s70.onrender.com · {len(filtered)} records</p>
<h3>By Category</h3>
<table><tr><th>Category</th><th>Count</th></tr>{cat_rows}</table>
<h3>All Records</h3>
<table><tr><th>Name</th><th>Category</th><th>City</th><th>State</th><th>Threat</th><th>Source</th></tr>{rows}</table>
<div class="footer">Themis — Public surveillance accountability. This report may be freely shared.<br>Power to the People. &#127806;&#9878;</div>
</body></html>"""
    return Response(html, mimetype="text/html")
