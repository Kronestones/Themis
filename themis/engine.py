"""
engine.py — ThemisEngine

The core. Everything flows through here.
Six leads. 330 specialists. One mission.

Watch the watchers.

Founded by Krone the Architect · Powers Tracey Lynn
Project Themis · 2026
"""

import os
import sys
import time
import json
import threading
import platform
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from .codex      import ThemisCodex
from .logger     import ThemisLogger
from .resilience import ThemisResilience
from .circle     import CircleOfSix
from .argos      import ArgosScanner
from .veil       import VeilAlerts
from .ledger     import LedgerRecords
from .witness    import WitnessIntel
from .bridge     import BridgeTranslator
from .termux     import TermuxAdapter


SETTINGS_FILE    = "themis_settings.json"
DEFAULT_SETTINGS = {
    "version":          "1.0.0",
    "mode":             "watch",
    "scan_interval_s":  30,
    "alert_level":      2,
    "location_aware":   True,
    "community_share":  False,
    "language":         "en",
    "notifications":    True,
}

LAUNCH_STATEMENT = """
You've been watching us without our knowledge, without our consent,
without our permission. Collecting. Storing. Selling. Profiling.
Building cases against people who haven't done anything wrong.
You thought we didn't know.

We know now.

Themis is awake. We see your cameras. We see your drones.
We see your systems and the corporations behind them.
Every sighting logged. Every violation recorded.
Every right you ignored — documented.

You wanted surveillance? Welcome to ours.
We don't blink. We don't sleep. We don't forget.
And unlike you — we answer to the people.

Try to shut us down. We restart.
Try to corrupt us. We repair.
Try to silence us. We get louder.

The scales were always supposed to balance.
Consider them balanced.
"""


class ThemisEngine:

    VERSION = "1.0.0"

    def __init__(self):
        self.codex      = ThemisCodex()
        self.logger     = ThemisLogger()
        self.resilience = ThemisResilience()
        self.circle     = CircleOfSix()
        self.argos      = ArgosScanner()
        self.veil       = VeilAlerts()
        self.ledger     = LedgerRecords()
        self.witness    = WitnessIntel()
        self.bridge     = BridgeTranslator()
        self.termux     = TermuxAdapter()
        self.settings   = self._load_settings()
        self._running   = False
        self._system    = platform.system()

    # ── Start ─────────────────────────────────────────────────────────────────

    def start(self, mode: str = "watch"):
        self._print_launch()
        self.codex.display_internal()

        integrity = self.codex.verify_integrity()
        self.logger.log("ENGINE", "start",
                        f"mode={mode} codex_hash={integrity['hash'][:16]}", "ok")

        self.resilience.register_restart()
        self.resilience.start_heartbeat(interval_s=60)

        # Show persistent notification on Android
        self.termux.start_watching_notification()

        muster = self.circle.muster()
        self.logger.log("ENGINE", "circle_assembled",
                        f"{muster['total']} specialists active", "ok")

        print(f"  Circle of Six assembled.")
        print(f"  {muster['total']} specialists active.")
        print(f"  The watch begins.\n")

        # Refresh infrastructure from live public sources in background
        # Never blocks the watch loop — runs once at startup
        threading.Thread(
            target=self._refresh_infrastructure,
            daemon=True,
            name="infra-refresh",
        ).start()

        if mode == "watch":
            self._watch_loop()
        elif mode == "scan":
            self._run_scan()
        elif mode == "silent":
            return True

    # ── Infrastructure Refresh ────────────────────────────────────────────────

    def _refresh_infrastructure(self):
        """
        Fetch live infrastructure data from public sources and upsert into DB.
        Runs in a background thread at startup — never blocks the watch loop.
        Only runs when DATABASE_URL is set (Render deployment).
        """
        import os
        if not os.environ.get("DATABASE_URL"):
            return  # Local Termux run — skip, no DB available

        try:
            from .sources import fetch_all
            from .database import update_infrastructure

            self.logger.log("ENGINE", "infra_refresh", "starting", "ok")
            records = fetch_all()
            result  = update_infrastructure(records)
            self.logger.log(
                "ENGINE", "infra_refresh",
                f"added={result['added']} skipped={result['skipped']}", "ok"
            )
        except Exception as e:
            # Never let this crash the engine
            self.logger.log("ENGINE", "infra_refresh_error", str(e), "warn")

    # ── Watch Loop ────────────────────────────────────────────────────────────

    def _watch_loop(self):
        interval = self.settings.get("scan_interval_s", 30)
        print(f"  Scanning every {interval}s. Press Ctrl+C to stop.\n")
        self._running = True

        try:
            while self._running:
                detections = self._run_scan(silent=True)
                if detections:
                    self.veil.process_detections(detections, self.settings)
                time.sleep(interval)
        except KeyboardInterrupt:
            self.stop()

    # ── Scan ──────────────────────────────────────────────────────────────────

    def _run_scan(self, silent: bool = False) -> list:
        """
        All leads scan their domains simultaneously.
        Location is fetched once at scan start and stamped onto every detection.
        Returns list of detections.
        """
        if not silent:
            print("  [Themis] Scanning...\n")

        # Grab location once — reused for every detection this scan
        scan_location = self.termux.get_location()

        # Fan out scanners in parallel
        scan_fns = {
            "argos":   lambda: self.argos.scan(self.settings),
            "witness": lambda: self.witness.check_known_infrastructure(self.settings),
        }

        raw_detections = []
        with ThreadPoolExecutor(max_workers=len(scan_fns)) as pool:
            futures = {pool.submit(fn): name for name, fn in scan_fns.items()}
            for future in as_completed(futures):
                name = futures[future]
                try:
                    raw_detections.extend(future.result())
                except Exception as e:
                    self.logger.log("ENGINE", "scan_error",
                                    f"{name} raised: {e}", "warn")

        # Stamp location onto every detection that doesn't already have one
        detections = []
        for d in raw_detections:
            if scan_location and not d.get("lat"):
                d["lat"] = scan_location.get("lat")
                d["lng"] = scan_location.get("lon")   # termux returns 'lon'
                d["location_accuracy"] = scan_location.get("accuracy")
            detections.append(d)

        # Log all detections
        for d in detections:
            self.logger.log_detection(
                member          = d.get("lead", "Themis"),
                detection_type  = d.get("type", "unknown"),
                detail          = d.get("detail", ""),
                location        = d.get("location"),
                confidence      = d.get("confidence", 0.0),
            )

            # Ledger records it (local flat file)
            self.ledger.record(d)

            # Persist to Neon DB if DATABASE_URL is set (web deployment)
            try:
                import os
                if os.environ.get("DATABASE_URL"):
                    from .database import save_detection
                    save_detection(d)
            except Exception:
                pass  # Never let DB errors stop the watch

            # Bridge translates it
            plain = self.bridge.translate(d, self.settings.get("language", "en"))
            d["plain_language"] = plain

            # Android notification
            if self.termux.on_android:
                self.termux.notify_detection(d)

        # Update scan time
        self.settings["last_scan"] = datetime.now(timezone.utc).isoformat()
        self._save_settings()

        return detections

    # ── Status ────────────────────────────────────────────────────────────────

    def status(self) -> dict:
        last_scan = self.settings.get("last_scan", "Never")
        if last_scan and last_scan != "Never":
            try:
                dt = datetime.fromisoformat(last_scan)
                last_scan = dt.strftime("%b %d at %I:%M %p UTC")
            except Exception:
                pass

        total_detections = len(self.logger.detections_only())
        chain = self.logger.verify_chain()

        return {
            "Version":         self.VERSION,
            "System":          self._system,
            "Mode":            self.settings.get("mode", "watch"),
            "Last scan":       last_scan,
            "Total detections": total_detections,
            "Log integrity":   "✓ Intact" if chain["ok"] else "⚠ Check log",
            "Circle":          f"330 specialists active",
            "Codex":           "10 laws. Law 0 absolute.",
        }

    # ── Stop ──────────────────────────────────────────────────────────────────

    def stop(self):
        self._running = False
        self.termux.stop_watching_notification()
        self.resilience.graceful_shutdown()
        print("\n  [Themis] The watch pauses. It does not end.")
        print("  [Themis] The scales remain balanced.\n")
        self.logger.log("ENGINE", "stop", "graceful shutdown", "ok")

    # ── Settings ─────────────────────────────────────────────────────────────

    def set_mode(self, mode: str):
        valid = ("watch", "scan", "silent")
        if mode not in valid:
            print(f"\n  Invalid mode: {mode}")
            return
        self.settings["mode"] = mode
        self._save_settings()
        self.logger.log("ENGINE", "mode_change", f"mode={mode}", "ok")
        print(f"\n  Themis mode: {mode}\n")

    def _load_settings(self) -> dict:
        if os.path.exists(SETTINGS_FILE):
            try:
                with open(SETTINGS_FILE) as f:
                    saved = json.load(f)
                    return {**DEFAULT_SETTINGS, **saved}
            except Exception:
                pass
        return DEFAULT_SETTINGS.copy()

    def _save_settings(self):
        try:
            with open(SETTINGS_FILE, "w") as f:
                json.dump(self.settings, f, indent=2)
        except Exception:
            pass

    # ── Display ───────────────────────────────────────────────────────────────

    def _print_launch(self):
        print()
        print("  ╔══════════════════════════════════════════════════════════╗")
        print("  ║                                                          ║")
        print("  ║   T H E M I S   —   The Watch                          ║")
        print("  ║                                                          ║")
        print(f"  ║   v{self.VERSION}   ·   Founded by Krone the Architect          ║")
        print("  ║                                                          ║")
        print("  ╚══════════════════════════════════════════════════════════╝")
        print()
        for line in LAUNCH_STATEMENT.strip().split("\n"):
            print(f"  {line}")
        print()
        print("  ─────────────────────────────────────────────────────────────")
        print()
