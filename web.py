"""
web.py — Themis Web Interface

Public map. No login. No account. No tracking.
Anyone can see what Themis has found.

Routes:
    /               → Leaflet map (public)
    /api/detections → Live + recent scan detections (JSON)
    /api/infrastructure → Static surveillance infrastructure (JSON)
    /api/status     → Themis status summary (JSON)

Founded by Krone the Architect · Powers Tracey Lynn
Project Themis · 2026
"""

import os
from flask import Flask, jsonify, render_template, request
from datetime import datetime, timezone

from .database import (
    init_db,
    save_detection,
    get_detections,
    get_infrastructure,
    get_detection_count,
)

app = Flask(__name__)


# ── Init ──────────────────────────────────────────────────────────────────────

def create_app():
    """Called by Render / gunicorn."""
    try:
        init_db()
        print("[Themis Web] DB initialized.")
    except Exception as e:
        print(f"[Themis Web] DB init warning: {e}")
    return app


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("map.html")


@app.route("/api/detections")
def api_detections():
    """
    Returns recent detections from Themis scans.
    Includes lat/lng when available.
    Only returns detections that have location data for map display.
    Also returns all recent detections (without location) for the activity feed.
    """
    limit = min(int(request.args.get("limit", 200)), 1000)
    all_detections   = get_detections(limit=limit)

    mapped    = [d for d in all_detections if d.get("lat") and d.get("lng")]
    unmapped  = all_detections  # feed shows all

    return jsonify({
        "ok":      True,
        "mapped":  mapped,
        "feed":    unmapped[:50],   # most recent 50 for activity feed
        "total":   get_detection_count(),
        "updated": datetime.now(timezone.utc).isoformat(),
    })


@app.route("/api/infrastructure")
def api_infrastructure():
    """
    Returns static surveillance infrastructure.
    All sourced from public records — EFF, DHS, ICE.gov, ACLU, journalism.
    """
    records = get_infrastructure()
    return jsonify({
        "ok":      True,
        "records": records,
        "count":   len(records),
        "source_note": (
            "All locations sourced from publicly available records: "
            "DHS fusion center public directory (dhs.gov/fusion-centers), "
            "ICE detention facility locator (ice.gov), "
            "EFF Atlas of Surveillance (atlasofsurveillance.org), "
            "ACLU investigations, and verified investigative journalism. "
            "No private or classified data. All public record."
        ),
    })


@app.route("/api/status")
def api_status():
    return jsonify({
        "ok":        True,
        "version":   "1.0.0",
        "detections": get_detection_count(),
        "time":      datetime.now(timezone.utc).isoformat(),
        "message":   "The watch does not stop.",
    })


# ── Direct run (dev only) ─────────────────────────────────────────────────────

if __name__ == "__main__":
    app = create_app()
    port = int(os.environ.get("PORT", 5050))
    app.run(host="0.0.0.0", port=port, debug=False)
