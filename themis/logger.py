"""
logger.py — ThemisLogger

Every detection recorded. Cryptographically timestamped.
The record belongs to the person running Themis.
No one else ever sees it without their consent.

Founded by Krone the Architect · Powers Tracey Lynn
Project Themis · 2026
"""

import json
import os
import hashlib
from datetime import datetime, timezone


class ThemisLogger:

    LOG_FILE     = "themis_audit.log"
    CHAIN_FILE   = "themis_chain.log"
    MAX_ENTRIES  = 50000

    def __init__(self):
        self._last_hash = self._get_last_hash()

    def log(self, member: str, action: str, detail: str,
            status: str = "ok", location: dict = None) -> str:
        """
        Log an entry with cryptographic chaining.
        Each entry references the hash of the previous — tamper evident.
        """
        entry = {
            "time":     datetime.now(timezone.utc).isoformat(),
            "member":   member,
            "action":   action,
            "detail":   detail,
            "status":   status,
            "prev":     self._last_hash,
        }

        if location:
            entry["location"] = location

        entry_str  = json.dumps(entry, sort_keys=True)
        entry_hash = hashlib.sha256(entry_str.encode()).hexdigest()
        entry["hash"] = entry_hash

        try:
            with open(self.LOG_FILE, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception:
            pass

        self._last_hash = entry_hash
        return entry_hash

    def log_detection(self, member: str, detection_type: str,
                      detail: str, location: dict = None,
                      confidence: float = 0.0) -> str:
        """Log a surveillance detection specifically."""
        return self.log(
            member  = member,
            action  = f"detected:{detection_type}",
            detail  = detail,
            status  = "detection",
            location = location,
        )

    def verify_chain(self) -> dict:
        """
        Verify the integrity of the audit chain.
        Any tampering breaks the chain.
        """
        entries = self._load_all()
        if not entries:
            return {"ok": True, "entries": 0, "message": "No entries yet."}

        broken_at = None
        prev_hash = "genesis"

        for i, entry in enumerate(entries):
            stored_hash = entry.get("hash", "")
            prev        = entry.get("prev", "")

            if prev != prev_hash:
                broken_at = i
                break

            # Recompute hash
            check = {k: v for k, v in entry.items() if k != "hash"}
            computed = hashlib.sha256(
                json.dumps(check, sort_keys=True).encode()
            ).hexdigest()

            if computed != stored_hash:
                broken_at = i
                break

            prev_hash = stored_hash

        if broken_at is not None:
            return {
                "ok":       False,
                "entries":  len(entries),
                "broken_at": broken_at,
                "message":  f"Chain integrity violated at entry {broken_at}. Possible tampering.",
            }

        return {
            "ok":      True,
            "entries": len(entries),
            "message": "Chain intact. No tampering detected.",
        }

    def recent(self, n: int = 20) -> list:
        entries = self._load_all()
        return entries[-n:]

    def detections_only(self) -> list:
        return [
            e for e in self._load_all()
            if e.get("action", "").startswith("detected:")
        ]

    def _load_all(self) -> list:
        entries = []
        try:
            if os.path.exists(self.LOG_FILE):
                with open(self.LOG_FILE) as f:
                    for line in f:
                        try:
                            entries.append(json.loads(line))
                        except Exception:
                            pass
        except Exception:
            pass
        return entries

    def _get_last_hash(self) -> str:
        entries = self._load_all()
        if entries:
            return entries[-1].get("hash", "genesis")
        return "genesis"
