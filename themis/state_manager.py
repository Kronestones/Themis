"""
state_manager.py — ThemisStateManager

Ported from Alice's NodePersistence (persistence.py v4).
Replaces the unwired build_integrity_map / check_integrity
functions in resilience.py with a working implementation.

Alice saves and restores node engine indices and collective
grid history across restarts so she wakes up knowing what
she looked like before.

Themis needs the same thing:
  - scan history (recent detection cycles for pattern analysis)
  - integrity hashes (tamper detection on source files)
  - engine state (scan count, last known good config)

On restart, ThemisStateManager restores all of this so the
PatternAnalyzer has real baselines and the integrity check
has real hashes to compare against.

Three files:
  themis_state.json    — engine counters + last settings hash
  themis_scan_cache.json — recent scan cycles for pattern continuity
  themis_integrity.json  — file hash map (already used by resilience.py)

Project Themis · 2026
"""

import hashlib
import json
import os
import threading
import time
from datetime import datetime, timezone


STATE_FILE     = "themis_state.json"
SCAN_CACHE_FILE = "themis_scan_cache.json"
INTEGRITY_FILE = "themis_integrity.json"
MAX_SAVED_CYCLES = 50   # matches META_WINDOW in pattern_analyzer.py

# Files Themis should watch for tampering
DEFAULT_WATCH_PATHS = [
    "themis/engine.py",
    "themis/argos.py",
    "themis/codex.py",
    "themis/resilience.py",
    "themis/logger.py",
    "themis/veil.py",
    "themis/database.py",
    "themis/web.py",
    "themis/templates/map.html",
    "main.py",
    "wsgi.py",
]


class ThemisStateManager:
    """
    Persistent state across Themis restarts.

    Manages three concerns:
      1. Engine state — scan count, uptime, restart history
      2. Scan cache   — recent detection cycles for PatternAnalyzer
      3. Integrity    — file hash map for tamper detection

    Usage in engine.py:
        state = ThemisStateManager()

        # On startup:
        state.load_all()
        scan_cache = state.get_scan_cache()   # restore to PatternAnalyzer
        integrity  = state.get_integrity()    # baseline for tamper check

        # After each scan:
        state.record_scan_cycle(detections)

        # On shutdown:
        state.save_all(scan_count=self._scan_count)
    """

    def __init__(self):
        self._lock        = threading.Lock()
        self._state       = {}
        self._scan_cycles = []   # list of serialized cycle dicts
        self._integrity   = {}
        self._loaded      = False

    # ── Load ──────────────────────────────────────────────────────────────────

    def load_all(self) -> dict:
        """
        Load all saved state on startup.
        Returns summary of what was restored.
        """
        restored = {}

        # Engine state
        self._state = self._load_json(STATE_FILE) or {}
        if self._state:
            restored["engine_state"] = True
            sc = self._state.get("scan_count", 0)
            print(f"  [STATE] Restored engine state. Previous scan count: {sc}")

        # Scan cache
        raw = self._load_json(SCAN_CACHE_FILE) or {}
        self._scan_cycles = raw.get("cycles", [])
        if self._scan_cycles:
            restored["scan_cycles"] = len(self._scan_cycles)
            print(f"  [STATE] Restored {len(self._scan_cycles)} scan cycles "
                  f"for pattern analysis.")

        # Integrity map
        raw_int = self._load_json(INTEGRITY_FILE) or {}
        self._integrity = raw_int.get("files", {})
        if self._integrity:
            restored["integrity_files"] = len(self._integrity)
            print(f"  [STATE] Integrity map: {len(self._integrity)} files tracked.")
        else:
            # First run — build the integrity map now
            self._integrity = self._build_integrity(DEFAULT_WATCH_PATHS)
            self._save_integrity()
            print(f"  [STATE] Integrity map built: "
                  f"{len(self._integrity)} files hashed.")
            restored["integrity_built"] = True

        self._loaded = True
        return restored

    # ── Scan cache ────────────────────────────────────────────────────────────

    def record_scan_cycle(self, detections: list):
        """
        Save a scan cycle to persistent cache.
        Call after every ArgosScanner.scan().
        """
        cycle = {
            "timestamp"      : time.time(),
            "detection_count": len(detections),
            "types"          : list({d.get("type", "unknown") for d in detections}),
            "locations"      : list({
                d.get("location") or f"{d.get('city','')},{d.get('state','')}"
                for d in detections
            }),
        }
        with self._lock:
            self._scan_cycles.append(cycle)
            # Keep only the most recent cycles
            if len(self._scan_cycles) > MAX_SAVED_CYCLES:
                self._scan_cycles = self._scan_cycles[-MAX_SAVED_CYCLES:]

    def get_scan_cache(self) -> list:
        """
        Return saved scan cycles for restoring PatternAnalyzer history.
        Returns list of dicts that can be fed back into PatternAnalyzer.
        """
        with self._lock:
            return list(self._scan_cycles)

    # ── Integrity ─────────────────────────────────────────────────────────────

    def check_integrity(self, watch_paths: list = None) -> dict:
        """
        Check current files against the saved integrity map.
        Returns dict with ok, tampered list, and message.

        Replaces resilience.py's check_integrity() with a working
        implementation that actually has baselines to compare against.
        """
        paths = watch_paths or DEFAULT_WATCH_PATHS

        if not self._integrity:
            # No baseline — build one
            self._integrity = self._build_integrity(paths)
            self._save_integrity()
            return {
                "ok"      : True,
                "tampered": [],
                "message" : "No integrity baseline — built fresh map now.",
            }

        tampered = []
        for path in paths:
            if path not in self._integrity:
                continue  # new file, not in baseline

            if not os.path.exists(path):
                tampered.append({
                    "path"  : path,
                    "reason": "File missing",
                })
                continue

            current_hash = self._hash_file(path)
            if current_hash and current_hash != self._integrity[path]:
                tampered.append({
                    "path"    : path,
                    "reason"  : "Hash mismatch — file may have been modified",
                    "expected": self._integrity[path][:16] + "...",
                    "found"   : current_hash[:16] + "...",
                })

        if tampered:
            return {
                "ok"      : False,
                "tampered": tampered,
                "message" : f"{len(tampered)} file(s) may have been tampered with.",
            }

        return {
            "ok"      : True,
            "tampered": [],
            "message" : f"Integrity verified. {len(paths)} files clean.",
        }

    def get_integrity(self) -> dict:
        """Return the current integrity map."""
        with self._lock:
            return dict(self._integrity)

    def rebuild_integrity(self, watch_paths: list = None) -> dict:
        """
        Rebuild the integrity map from scratch.
        Call after a legitimate update to reset the baseline.
        """
        paths = watch_paths or DEFAULT_WATCH_PATHS
        self._integrity = self._build_integrity(paths)
        self._save_integrity()
        return self._integrity

    # ── Save ──────────────────────────────────────────────────────────────────

    def save_all(self, scan_count: int = 0, uptime_seconds: float = 0):
        """
        Save all state on shutdown or periodically.
        """
        self._save_engine_state(scan_count, uptime_seconds)
        self._save_scan_cache()
        self._save_integrity()

    def _save_engine_state(self, scan_count: int, uptime_seconds: float):
        state = {
            "saved_at"      : datetime.now(timezone.utc).isoformat(),
            "scan_count"    : scan_count,
            "uptime_seconds": uptime_seconds,
            "restarts"      : self._state.get("restarts", 0) + 1,
        }
        self._write_json(STATE_FILE, state)

    def _save_scan_cache(self):
        with self._lock:
            payload = {
                "saved_at"   : time.time(),
                "cycle_count": len(self._scan_cycles),
                "cycles"     : self._scan_cycles[-MAX_SAVED_CYCLES:],
            }
        self._write_json(SCAN_CACHE_FILE, payload)

    def _save_integrity(self):
        payload = {
            "built" : datetime.now(timezone.utc).isoformat(),
            "count" : len(self._integrity),
            "files" : self._integrity,
        }
        self._write_json(INTEGRITY_FILE, payload)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _build_integrity(self, paths: list) -> dict:
        result = {}
        for path in paths:
            if os.path.exists(path):
                h = self._hash_file(path)
                if h:
                    result[path] = h
        return result

    def _hash_file(self, path: str) -> str:
        try:
            with open(path, "rb") as f:
                return hashlib.sha256(f.read()).hexdigest()
        except Exception:
            return ""

    def _load_json(self, path: str) -> dict:
        if not os.path.exists(path):
            return {}
        try:
            with open(path, "r") as f:
                return json.load(f)
        except Exception:
            return {}

    def _write_json(self, path: str, data: dict):
        try:
            with open(path, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"  [STATE] Write error ({path}): {e}")
