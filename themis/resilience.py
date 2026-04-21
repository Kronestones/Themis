"""
resilience.py — ThemisResilience

The watch does not stop.
Auto-restart on crash. Self-repair on corruption.
Tamper detection and response.
Distributed heartbeat.

Law 5: No actor can shut Themis down permanently.

Founded by Krone the Architect · Powers Tracey Lynn
Project Themis · 2026
"""

import os
import sys
import json
import time
import hashlib
import threading
import subprocess
from datetime import datetime, timezone
from .logger import ThemisLogger
from .codex  import ThemisCodex

HEARTBEAT_FILE  = "themis_heartbeat.json"
INTEGRITY_FILE  = "themis_integrity.json"
RESTART_DELAY_S = 5
MAX_RESTARTS    = 999  # Effectively unlimited


class ThemisResilience:

    def __init__(self):
        self.logger   = ThemisLogger()
        self.codex    = ThemisCodex()
        self._running = False
        self._restarts = 0
        self._integrity_map = {}

    # ── Heartbeat ─────────────────────────────────────────────────────────────

    def start_heartbeat(self, interval_s: int = 60):
        """Pulse a heartbeat file. If it stops, something is wrong."""
        self._running = True
        thread = threading.Thread(
            target=self._heartbeat_loop,
            args=(interval_s,),
            daemon=True
        )
        thread.start()
        self.logger.log("RESILIENCE", "heartbeat_start",
                        f"interval={interval_s}s", "ok")

    def _heartbeat_loop(self, interval_s: int):
        while self._running:
            try:
                pulse = {
                    "time":     datetime.now(timezone.utc).isoformat(),
                    "status":   "alive",
                    "restarts": self._restarts,
                    "pid":      os.getpid(),
                }
                with open(HEARTBEAT_FILE, "w") as f:
                    json.dump(pulse, f)
            except Exception:
                pass
            time.sleep(interval_s)

    def stop_heartbeat(self):
        self._running = False

    # ── Integrity Map ─────────────────────────────────────────────────────────

    def build_integrity_map(self, watch_paths: list) -> dict:
        """
        Build a hash map of critical files.
        Used to detect tampering.
        """
        integrity = {}
        for path in watch_paths:
            if os.path.exists(path):
                try:
                    with open(path, "rb") as f:
                        content = f.read()
                    integrity[path] = hashlib.sha256(content).hexdigest()
                except Exception:
                    pass

        self._integrity_map = integrity

        try:
            with open(INTEGRITY_FILE, "w") as f:
                json.dump({
                    "built":  datetime.now(timezone.utc).isoformat(),
                    "files":  integrity,
                }, f, indent=2)
        except Exception:
            pass

        self.logger.log("RESILIENCE", "integrity_map_built",
                        f"{len(integrity)} files mapped", "ok")
        return integrity

    def check_integrity(self) -> dict:
        """
        Check current files against the integrity map.
        Returns list of tampered files.
        """
        if not self._integrity_map:
            try:
                if os.path.exists(INTEGRITY_FILE):
                    with open(INTEGRITY_FILE) as f:
                        data = json.load(f)
                        self._integrity_map = data.get("files", {})
            except Exception:
                return {"ok": True, "tampered": [], "message": "No integrity map found."}

        tampered = []
        for path, expected_hash in self._integrity_map.items():
            if not os.path.exists(path):
                tampered.append({"path": path, "reason": "File missing"})
                continue
            try:
                with open(path, "rb") as f:
                    content = f.read()
                current_hash = hashlib.sha256(content).hexdigest()
                if current_hash != expected_hash:
                    tampered.append({
                        "path":     path,
                        "reason":   "Hash mismatch — file may have been modified",
                        "expected": expected_hash[:16] + "...",
                        "found":    current_hash[:16] + "...",
                    })
            except Exception as e:
                tampered.append({"path": path, "reason": str(e)})

        if tampered:
            for t in tampered:
                self.logger.log("RESILIENCE", "tamper_detected",
                                f"{t['path']}: {t['reason']}", "warning")
            return {
                "ok":       False,
                "tampered": tampered,
                "message":  f"{len(tampered)} file(s) may have been tampered with.",
            }

        return {
            "ok":       True,
            "tampered": [],
            "message":  "Integrity verified. No tampering detected.",
        }

    # ── Self Repair ───────────────────────────────────────────────────────────

    def attempt_self_repair(self, tampered_files: list) -> dict:
        """
        Attempt to repair tampered or corrupted files.
        Uses git to restore known-good versions where possible.
        """
        repaired = []
        failed   = []

        for item in tampered_files:
            path = item.get("path", "")
            if not path:
                continue

            # Try git restore first
            try:
                r = subprocess.run(
                    ["git", "checkout", "--", path],
                    capture_output=True, text=True, timeout=15
                )
                if r.returncode == 0:
                    repaired.append(path)
                    self.logger.log("RESILIENCE", "self_repair_success",
                                    path, "ok")
                else:
                    failed.append(path)
                    self.logger.log("RESILIENCE", "self_repair_failed",
                                    f"{path}: {r.stderr.strip()}", "error")
            except Exception as e:
                failed.append(path)
                self.logger.log("RESILIENCE", "self_repair_error",
                                str(e), "error")

        return {
            "repaired": repaired,
            "failed":   failed,
            "ok":       len(failed) == 0,
        }

    # ── Auto Restart ─────────────────────────────────────────────────────────

    def register_restart(self):
        """Called on startup to track restart count."""
        self._restarts += 1
        self.logger.log("RESILIENCE", "restart",
                        f"restart #{self._restarts}", "ok")

    def watch_and_restart(self, target_script: str, args: list = None):
        """
        Watch a target script and restart it if it dies.
        This runs as a wrapper process.
        The watch does not stop.
        """
        args = args or []
        print(f"\n  [RESILIENCE] Watchdog active. Watching: {target_script}")
        print(f"  [RESILIENCE] The watch does not stop.\n")

        while True:
            try:
                proc = subprocess.Popen(
                    [sys.executable, target_script] + args
                )
                self.logger.log("RESILIENCE", "process_started",
                                f"pid={proc.pid}", "ok")
                proc.wait()

                exit_code = proc.returncode
                self._restarts += 1

                if exit_code == 0:
                    # Clean exit — stop watching
                    self.logger.log("RESILIENCE", "clean_exit",
                                    "Process exited cleanly.", "ok")
                    break

                self.logger.log("RESILIENCE", "unexpected_exit",
                                f"exit_code={exit_code} restart #{self._restarts}",
                                "warning")

                print(f"\n  [RESILIENCE] Process died (code {exit_code}).")
                print(f"  [RESILIENCE] Restarting in {RESTART_DELAY_S}s...")
                print(f"  [RESILIENCE] Restart #{self._restarts}. The watch does not stop.\n")

                time.sleep(RESTART_DELAY_S)

            except KeyboardInterrupt:
                print("\n  [RESILIENCE] Shutdown requested by user.")
                self.logger.log("RESILIENCE", "user_shutdown",
                                "KeyboardInterrupt", "ok")
                break
            except Exception as e:
                self.logger.log("RESILIENCE", "watchdog_error",
                                str(e), "error")
                time.sleep(RESTART_DELAY_S)

    # ── Shutdown ─────────────────────────────────────────────────────────────

    def graceful_shutdown(self):
        """Record shutdown for audit trail."""
        self.stop_heartbeat()
        self.logger.log("RESILIENCE", "shutdown",
                        "Graceful shutdown.", "ok")
        try:
            shutdown_record = {
                "time":     datetime.now(timezone.utc).isoformat(),
                "restarts": self._restarts,
                "reason":   "graceful",
            }
            with open("themis_shutdown.json", "w") as f:
                json.dump(shutdown_record, f, indent=2)
        except Exception:
            pass
