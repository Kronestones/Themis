"""
sentinel_reporter.py — Sentinel Reporter

When Themis detects something serious, Sentinel needs to know.

This module gives Themis a direct line to the sanctuary.
When an IMSI catcher, cluster surveillance event, or critical
detection is confirmed, Themis pushes it to Sentinel's Themis
bridge (port 5778) over TCP.

The sanctuary and the watch are one network.
What Themis sees in the field, the Circle sees in the sanctuary.

Configuration (in themis_settings.json):
    sentinel_host   — IP or hostname of the Sentinel node
    sentinel_port   — port of the Themis bridge (default 5778)
    sentinel_token  — shared token (must match THEMIS_TOKEN on Sentinel)

If no sentinel_host is configured, the reporter is silent — Themis
operates standalone without trying to reach Sentinel.

Founded by Krone the Architect · Powers Tracey Lynn
Project Themis · 2026
"""

import json
import socket
from datetime import datetime, timezone


# Detection types that always get pushed to Sentinel immediately
PUSH_IMMEDIATELY = {
    "imsi_catcher",
    "facial_recognition",
    "drone_signal",
    "drone_bluetooth",
    "signal_disappeared",
}

SENTINEL_BRIDGE_PORT = 5778
PUSH_TIMEOUT_S       = 5


class SentinelReporter:
    """
    Pushes Themis detections to a configured Sentinel node.

    Used by VeilAlerts when a detection meets the push threshold.
    Silent if no Sentinel host is configured — no errors, no noise.
    """

    def __init__(self, settings: dict):
        self.host  = settings.get("sentinel_host")
        self.port  = int(settings.get("sentinel_port", SENTINEL_BRIDGE_PORT))
        self.token = settings.get("sentinel_token", "")

    def is_configured(self) -> bool:
        return bool(self.host)

    def should_push(self, detection: dict) -> bool:
        """
        Decide whether this detection warrants an immediate push to Sentinel.
        Pushes on:
          - Any cluster event (multiple surveillance types simultaneously)
          - Any detection type in PUSH_IMMEDIATELY
          - Any critical severity detection
        """
        if detection.get("cluster_event"):
            return True
        if detection.get("type") in PUSH_IMMEDIATELY:
            return True
        if detection.get("severity") == "critical":
            return True
        return False

    def push(self, detection: dict) -> bool:
        """
        Push a detection to Sentinel's Themis bridge.
        Returns True on success, False on failure.
        Fails silently — Themis keeps running regardless.
        """
        if not self.is_configured():
            return False

        payload = {
            "token":     self.token,
            "detection": detection,
        }

        try:
            with socket.create_connection(
                (self.host, self.port), timeout=PUSH_TIMEOUT_S
            ) as sock:
                sock.sendall(
                    (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
                )
                # Read acknowledgement
                resp_data = sock.recv(256)
                resp = json.loads(resp_data.decode("utf-8", errors="replace").strip())
                if resp.get("ok"):
                    print(
                        f"  [SENTINEL REPORTER] Detection pushed to Sentinel "
                        f"({self.host}:{self.port}) ✓"
                    )
                    return True
                else:
                    print(
                        f"  [SENTINEL REPORTER] Sentinel rejected report: "
                        f"{resp.get('error','unknown')}"
                    )
                    return False
        except ConnectionRefusedError:
            print(
                f"  [SENTINEL REPORTER] Could not reach Sentinel at "
                f"{self.host}:{self.port} — running standalone."
            )
            return False
        except Exception:
            # Never let a Sentinel push failure interrupt Themis operation
            return False

    def push_if_warranted(self, detection: dict) -> bool:
        """Convenience method — checks threshold and pushes if met."""
        if self.should_push(detection):
            return self.push(detection)
        return False
