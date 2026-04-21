from flask import Flask, jsonify, request, send_from_directory
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
