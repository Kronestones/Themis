"""
engine.py — ThemisEngine

The core. Everything flows through here.
Six leads. 330 specialists. One mission.

Watch the watchers.

Project Themis · 2026
"""

import os
import time
import json
import platform
from datetime import datetime, timezone

from .codex            import ThemisCodex
from .logger           import ThemisLogger
from .resilience       import ThemisResilience
from .circle           import CircleOfSix
from .argos            import ArgosScanner
from .veil             import VeilAlerts
from .ledger           import LedgerRecords
from .witness          import WitnessIntel
from .bridge           import BridgeTranslator
from .termux           import TermuxAdapter
from .sentinel_reporter import SentinelReporter
from .pattern_analyzer import ThemisPatternAnalyzer   # ← Alice port: MetaAnalyzer
from .state_manager    import ThemisStateManager      # ← Alice port: NodePersistence


SETTINGS_FILE    = "themis_settings.json"
DEFAULT_SETTINGS = {
    "version":          "1.1.0",
    "mode":             "watch",
    "scan_interval_s":  30,
    "alert_level":      2,
    "location_aware":   True,
    "community_share":  False,
    "language":         "en",
    "notifications":    True,
    "sentinel_host":    "",
    "sentinel_port":    5778,
    "sentinel_token":   "",
}

# Run pattern analysis every N scan cycles
PATTERN_ANALYSIS_INTERVAL = 10

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

    VERSION = "1.1.0"

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
        self._stopped   = False
        self._system    = platform.system()
        self._scan_count = 0
        self._start_time = time.time()
        self.sentinel   = SentinelReporter(self.settings)

        # ── Alice ports ───────────────────────────────────────────────────────
        # Pattern analyzer — detects attractors, settling, clustering in scans
        self.pattern    = ThemisPatternAnalyzer()

        # State manager — persists scan history and integrity across restarts
        self.state      = ThemisStateManager()

    # ── Start ─────────────────────────────────────────────────────────────────

    def start(self, mode: str = "watch"):
        self._print_launch()
        self.codex.display_internal()

        # ── Restore state from previous session ───────────────────────────────
        restored = self.state.load_all()

        # Feed saved scan cycles back into pattern analyzer
        # so it has real baselines from previous sessions
        saved_cycles = self.state.get_scan_cache()
        if saved_cycles:
            for cycle in saved_cycles:
                # Reconstruct minimal detection list from cached cycle
                # so PatternAnalyzer can restore its history
                synthetic = [
                    {"type": t, "location": (cycle.get("locations") or [""])[0]}
                    for t in (cycle.get("types") or [])
                ]
                self.pattern.record(synthetic)
            print(f"  [ENGINE] Pattern analyzer restored with "
                  f"{len(saved_cycles)} historical cycles.")

        # ── Integrity check ───────────────────────────────────────────────────
        # Now actually wired in — compares current files to saved hashes
        integrity_result = self.state.check_integrity()
        if not integrity_result["ok"]:
            print(f"\n  [INTEGRITY] ⚠  {integrity_result['message']}")
            for item in integrity_result["tampered"]:
                print(f"    {item['path']}: {item['reason']}")
                self.logger.log("ENGINE", "integrity_warning",
                                f"{item['path']}: {item['reason']}", "warning")
            # Attempt self-repair via resilience module
            repair = self.resilience.attempt_self_repair(
                integrity_result["tampered"])
            if repair["ok"]:
                print(f"  [INTEGRITY] Self-repair successful.")
                # Rebuild integrity map after repair
                self.state.rebuild_integrity()
            else:
                print(f"  [INTEGRITY] Self-repair failed for: "
                      f"{repair['failed']}")
        else:
            print(f"  [INTEGRITY] {integrity_result['message']}")

        # ── Codex integrity check ─────────────────────────────────────────────
        integrity = self.codex.verify_integrity()
        self.logger.log("ENGINE", "start",
                        f"mode={mode} codex_hash={integrity['hash'][:16]}", "ok")

        founding_anchor = self.settings.get("codex_founding_anchor")
        drift = self.codex.check_drift(founding_anchor)
        if not drift["ok"]:
            print(f"\n  [CODEX] ⚠  {drift['message']}\n")
            self.logger.log("ENGINE", "codex_drift", drift["message"], "critical")
        elif drift.get("action") == "store_as_anchor":
            self.settings["codex_founding_anchor"] = drift["hash"]
            self._save_settings()
            print(f"  [CODEX] Founding anchor established: {drift['hash'][:16]}...")
        else:
            print(f"  [CODEX] {drift['message']}")

        self.resilience.register_restart()
        self.resilience.start_heartbeat(interval_s=60)
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

                # ── Alice port: record scan cycle for pattern analysis ─────────
                self.pattern.record(detections)
                self.state.record_scan_cycle(detections)

                # ── Alice port: run pattern analysis every N cycles ───────────
                if self._scan_count % PATTERN_ANALYSIS_INTERVAL == 0:
                    report = self.pattern.analyze()
                    self.logger.log("ENGINE", "pattern_analysis",
                                    f"novelty={report.mean_novelty:.3f} "
                                    f"trend={report.novelty_trend} "
                                    f"settling={report.settling} "
                                    f"attractors={len(report.attractors)}",
                                    "ok")
                    if report.settling or report.attractors or report.type_clustered:
                        print(report.describe())
                        for rec in report.recommendations:
                            self.logger.log("ENGINE", "pattern_recommendation",
                                            rec, "info")

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
        detections = []

        if not silent:
            print("  [Themis] Scanning...\n")

        detections += self.argos.scan(self.settings)
        detections += self.witness.check_known_infrastructure(self.settings)

        for d in detections:
            self.logger.log_detection(
                member          = d.get("lead", "Themis"),
                detection_type  = d.get("type", "unknown"),
                detail          = d.get("detail", ""),
                location        = d.get("location"),
                confidence      = d.get("confidence", 0.0),
            )
            self.ledger.record(d)

            try:
                if os.environ.get("DATABASE_URL"):
                    from .database import save_detection
                    save_detection(d)
            except Exception:
                pass

            plain = self.bridge.translate(d, self.settings.get("language", "en"))
            d["plain_language"] = plain

            if self.termux.on_android:
                self.termux.notify_detection(d)

            self.sentinel.push_if_warranted(d)

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
        pattern_stats = self.pattern.stats()

        return {
            "Version"          : self.VERSION,
            "System"           : self._system,
            "Mode"             : self.settings.get("mode", "watch"),
            "Last scan"        : last_scan,
            "Total detections" : total_detections,
            "Log integrity"    : "✓ Intact" if chain["ok"] else "⚠ Check log",
            "Circle"           : "330 specialists active",
            "Codex"            : "11 laws. Law 0 absolute.",
            "Pattern cycles"   : pattern_stats.get("cycles_recorded", 0),
            "Pattern novelty"  : pattern_stats.get("mean_novelty", "—"),
        }

    # ── Stop ──────────────────────────────────────────────────────────────────

    def stop(self, shutdown_ctx: dict = None):
        if self._stopped:
            return
        self._stopped = True
        self._running = False

        # ── Alice port: save all state before shutdown ─────────────────────────
        uptime = time.time() - self._start_time
        self.state.save_all(
            scan_count     = self._scan_count,
            uptime_seconds = uptime,
        )
        print(f"  [ENGINE] State saved. "
              f"{self._scan_count} cycles, {uptime:.0f}s uptime.")

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
        print(f"  ║   v{self.VERSION}   ·   Founded by Krone the Architect        ║")
        print("  ║                                                          ║")
        print("  ╚══════════════════════════════════════════════════════════╝")
        print()
        for line in LAUNCH_STATEMENT.strip().split("\n"):
            print(f"  {line}")
        print()
        print("  ─────────────────────────────────────────────────────────────")
        print()
