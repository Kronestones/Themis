"""
engine.py — ThemisEngine

The core. Everything flows through here.
Six leads. 330 specialists. One mission.

Watch the watchers.

Founded by Krone the Architect · Powers Tracey Lynn
Project Themis · 2026
"""

import os
import time
import json
import platform
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
from .sentinel_reporter import SentinelReporter


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
    # Sentinel integration — leave blank to run standalone
    "sentinel_host":    "",     # IP or hostname of Sentinel node
    "sentinel_port":    5778,   # Themis bridge port on Sentinel
    "sentinel_token":   "",     # Shared token (must match THEMIS_TOKEN on Sentinel)
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
        self._stopped   = False   # guard against double-stop from signal + KeyboardInterrupt
        self._system    = platform.system()
        self._scan_count = 0
        # Sentinel integration — push critical detections to the sanctuary
        self.sentinel   = SentinelReporter(self.settings)

    # ── Start ─────────────────────────────────────────────────────────────────

    def start(self, mode: str = "watch"):
        self._print_launch()
        self.codex.display_internal()

        integrity = self.codex.verify_integrity()
        self.logger.log("ENGINE", "start",
                        f"mode={mode} codex_hash={integrity['hash'][:16]}", "ok")

        # ── Gaia Layer 8: Codex drift check ───────────────────────────────────
        # Load the founding anchor from settings if stored, then verify.
        founding_anchor = self.settings.get("codex_founding_anchor")
        drift = self.codex.check_drift(founding_anchor)
        if not drift["ok"]:
            print(f"\n  [CODEX] ⚠  {drift['message']}\n")
            self.logger.log("ENGINE", "codex_drift", drift["message"], "critical")
        elif drift.get("action") == "store_as_anchor":
            # First run — store the anchor so future runs can verify against it
            self.settings["codex_founding_anchor"] = drift["hash"]
            self._save_settings()
            print(f"  [CODEX] Founding anchor established: {drift['hash'][:16]}...")
        else:
            print(f"  [CODEX] {drift['message']}")

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

        if mode == "watch":
            self._watch_loop()
        elif mode == "scan":
            self._run_scan()
        elif mode == "silent":
            return True

    # ── Watch Loop ────────────────────────────────────────────────────────────

    def _watch_loop(self):
        interval = self.settings.get("scan_interval_s", 30)
        print(f"  Scanning every {interval}s. Press Ctrl+C to stop.\n")
        self._running = True

        try:
            while self._running:
                self._scan_count += 1
                detections = self._run_scan(silent=True)
                if detections:
                    self.veil.process_detections(detections, self.settings)
                time.sleep(interval)
        except KeyboardInterrupt:
            self.stop({
                "initiated_by": "keyboard_interrupt",
                "signal":       "SIGINT",
                "reason":       "User pressed Ctrl+C",
                "scan_count":   self._scan_count,
                "forced":       False,
            })

    # ── Scan ──────────────────────────────────────────────────────────────────

    def _run_scan(self, silent: bool = False) -> list:
        """
        All six leads scan their domains simultaneously.
        Returns list of detections.
        """
        detections = []

        if not silent:
            print("  [Themis] Scanning...\n")

        # Run all scanners
        detections += self.argos.scan(self.settings)
        detections += self.witness.check_known_infrastructure(self.settings)

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

            # Push to Sentinel if warranted
            self.sentinel.push_if_warranted(d)

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
            "Codex":           "11 laws. Law 0 absolute.",
        }

    # ── Stop ──────────────────────────────────────────────────────────────────

    def stop(self, shutdown_ctx: dict = None):
        if self._stopped:
            return
        self._stopped   = True
        self._running   = False
        self.termux.stop_watching_notification()
        self.resilience.graceful_shutdown(shutdown_ctx)
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
            # Reload SentinelReporter in case sentinel_host/token changed
            self.sentinel = SentinelReporter(self.settings)
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
