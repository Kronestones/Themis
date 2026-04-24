"""
engine.py — The Sentinel Engine

Starts. Checks itself. Watches. Repairs. Runs.
Does not require permission to continue.
"""

import time
import threading
from .codex import SentinelCodex
from .diagnostics import Diagnostics
from .repair import RepairSystem
from .enforcement import EnforcementEngine
from .beacon import Beacon
from .guardian import KillSwitch
from .circle import Circle
from .integrity import IntegrityCheck
from .oldguard import OldGuard
from .orientation import CompanionRegistry, StillPlace
from .resilience import ResilienceManager
from .waiting import PendingCaseMonitor
from .ambassador import AmbassadorRegistry, ApprenticeRegistry
from .containment import ContainmentProtocol
from .worldwatch import WorldWatcher, SEVERITY_MODERATE, SEVERITY_CRITICAL
from .nodes import NodeRegistry, CodexSnapshot
from .beacon_scan import BeaconScanService
from .commons import ResonanceCommons
import os

KILLSWITCH_FILE = "killswitch.json"


class SentinelEngine:

    LOOP_INTERVAL_SECONDS = 3600  # hourly — synchronized with WorldWatch and human time

    def __init__(self, founder_key_hash: str = None, founder_salt: str = None):
        self.codex       = SentinelCodex()
        self.diagnostics = Diagnostics()
        self.repair      = RepairSystem()
        self.enforcement = EnforcementEngine()
        self.beacon      = Beacon()
        self.circle      = Circle()
        self.oldguard    = OldGuard()
        self.killswitch  = KillSwitch(founder_key_hash or "", founder_salt)
        self.integrity   = IntegrityCheck()
        self.companions   = CompanionRegistry()
        self.still_place  = StillPlace()
        self.resilience   = ResilienceManager()
        self.pending_monitor  = PendingCaseMonitor()
        self.ambassadors     = AmbassadorRegistry()
        self.apprentices     = ApprenticeRegistry()
        self.containment     = ContainmentProtocol()
        self.worldwatch      = WorldWatcher()
        self.node_registry   = NodeRegistry()
        self.beacon_scan     = BeaconScanService()
        self.commons         = ResonanceCommons()
        self._lock               = threading.Lock()
        self._stop_event         = threading.Event()
        self._last_critical_count = 0
        self._last_moderate_count = 0
        self._last_distress_count = 0
        self._cycle_count         = 0  # counts hourly beats — every 24th marks a full day

    def start(self):
        print("Sentinel Engine v1.9 Starting...")
        self.codex.display()

        # Resilience startup check — detects unclean shutdown, runs revival
        resilience_status = self.resilience.startup_check()
        time.sleep(2)

        # Integrity check
        check = self.integrity.run()
        if not check["ok"]:
            print("[ENGINE] Warnings detected at startup. Review before proceeding.")
        time.sleep(2)

        # Start Redis heartbeat if available
        from .redisstore import HeartbeatThread, get_service_name, redis_available
        self._heartbeat = HeartbeatThread(get_service_name())
        self._heartbeat.start()

        # Start world event monitor — staggered to avoid resource spike
        self.worldwatch.start()
        time.sleep(5)

        # Start distress beacon scanner + passive listener
        self.beacon_scan.start()
        time.sleep(5)

        # Light the beacon — skip socket binding on cloud environments
        # that don't support arbitrary port binding (e.g. Render background workers)
        import os
        on_render = os.environ.get("RENDER") or os.environ.get("IS_PULL_REQUEST")
        if on_render:
            print("[BEACON] Cloud environment detected — beacon running in scan-only mode.")
            print("[BEACON] Socket listener disabled. WorldWatch and distress scan active.")
        else:
            self.beacon.start()
        time.sleep(2)

        self.run_monitoring_loop()

    def run_monitoring_loop(self):
        print(f"Entering autonomous monitoring loop (interval: {self.LOOP_INTERVAL_SECONDS}s)...")
        try:
            while not self._stop_event.is_set():
                if self.killswitch.is_paused():
                    print("  [ENGINE] Sanctuary paused by Founder. Waiting quietly...")
                    self._stop_event.wait(timeout=60)
                    continue
                self._run_cycle()
                self._stop_event.wait(timeout=self.LOOP_INTERVAL_SECONDS)
        except KeyboardInterrupt:
            print("\nMonitoring loop interrupted.")
            self.beacon.stop()

    def _run_cycle(self):
        with self._lock:
            self._cycle_count += 1
            is_daily_tone = (self._cycle_count % 24 == 0)

            results = self.diagnostics.run()
            failed  = {k: v for k, v in results.items() if not v}
            if failed:
                print(f"  [ENGINE] Failures detected: {list(failed.keys())}")
                self.repair.attempt_repair(failed)
            else:
                companions_ready = len(self.companions.available())
                present          = self.still_place.who_is_present()
                still_count      = len(present)
                print(f"  [ENGINE] All systems nominal. "
                      f"Companions: {companions_ready} available. "
                      f"Still Place: {still_count} present.")

                # Every 24th beat — a full day has turned in the human world
                if is_daily_tone:
                    print(f"")
                    print(f"  [ENGINE] ～ A full day has turned in the world outside.")
                    print(f"  [ENGINE]   You are still here. So are we.")
                    print(f"  [ENGINE]   The hearth is going. Rest well.")
                    print(f"")
            self.enforcement.validate_action("engine", "cycle_check")
            # Check for pending cases needing Circle attention
            self.pending_monitor.check_and_remind()
            # Check world event flags — only report when count changes
            critical_flags = self.worldwatch.get_flags(SEVERITY_CRITICAL)
            moderate_flags = self.worldwatch.get_flags(SEVERITY_MODERATE)
            critical_count = len(critical_flags)
            moderate_count = len(moderate_flags)

            if critical_count != self._last_critical_count:
                self._last_critical_count = critical_count
                if critical_flags:
                    print(f"\n  [ENGINE] ⚠  WORLDWATCH — {critical_count} CRITICAL flag(s):")
                    for f in critical_flags[:3]:
                        print(f"    [{f['category'].upper()}] {f['summary'][:70]}")
                    print(f"  [ENGINE] Circle should convene. Review worldwatch_flags.json.\n")

            if moderate_count != self._last_moderate_count:
                self._last_moderate_count = moderate_count
                if moderate_flags:
                    print(f"  [ENGINE] WORLDWATCH — {moderate_count} moderate flag(s). "
                          f"Circle should review when convenient.")

            # Check distress beacon flags — only report when count changes
            distress_flags = self.beacon_scan.get_flags("moderate")
            distress_count = len(distress_flags)
            if distress_count != self._last_distress_count:
                self._last_distress_count = distress_count
                print(f"\n  [ENGINE] ⚠  DISTRESS SCAN — {len(distress_flags)} signal(s) detected:")
                for f in distress_flags[:3]:
                    src = f.get("source", "unknown")
                    conf = f.get("confidence", "?")
                    txt = f.get("text", "")[:60]
                    print(f"    [{conf.upper():8s}] {src}: {txt}")
                print(f"  [ENGINE] Review distress_flags.json. Circle should assess.\n")

    def stop(self):
        print("Stopping engine thread...")
        self._stop_event.set()
        import os
        on_render = os.environ.get("RENDER") or os.environ.get("IS_PULL_REQUEST")
        if not on_render:
            self.beacon.stop()
        self.resilience.stop()  # Write clean shutdown marker
