"""
termux.py — Termux Android Adapter

Makes Themis work on Android via Termux right now.
All existing desktop code stays intact for future use.
This layer sits on top and routes to what's available.

Requires:
  pkg install termux-api python
  pip install requests
  Termux:API companion app from F-Droid

Founded by Krone the Architect · Powers Tracey Lynn
Project Themis · 2026
"""

import subprocess
import json
import os
import platform
from datetime import datetime, timezone


def is_termux() -> bool:
    """Detect if we're running in Termux on Android."""
    return (
        os.path.exists("/data/data/com.termux") or
        "com.termux" in os.environ.get("PREFIX", "") or
        os.path.exists("/data/data/com.termux/files/usr/bin/termux-wifi-scaninfo")
    )


def termux_available(command: str) -> bool:
    """Check if a termux-api command is available."""
    try:
        r = subprocess.run(
            ["which", command],
            capture_output=True, text=True, timeout=3
        )
        return r.returncode == 0
    except Exception:
        return False


class TermuxWifi:
    """
    WiFi scanning via Termux:API.
    Replaces iwlist/airport/netsh on Android.
    Requires Termux:API app installed.
    """

    def scan(self) -> list:
        """
        Scan WiFi networks using termux-wifi-scaninfo.
        Returns same format as desktop scanners.
        """
        if not termux_available("termux-wifi-scaninfo"):
            print("  [Termux] termux-wifi-scaninfo not available.")
            print("  [Termux] Install Termux:API from F-Droid and run:")
            print("  [Termux] pkg install termux-api")
            return []

        try:
            r = subprocess.run(
                ["termux-wifi-scaninfo"],
                capture_output=True, text=True, timeout=15
            )
            if r.returncode != 0:
                return []

            raw = json.loads(r.stdout)
            networks = []

            for net in raw:
                networks.append({
                    "ssid":     net.get("ssid", ""),
                    "bssid":    net.get("bssid", "").lower(),
                    "signal":   net.get("level", -100),
                    "frequency": net.get("frequency", 0),
                    "capabilities": net.get("capabilities", ""),
                })

            return networks

        except json.JSONDecodeError:
            return []
        except Exception:
            return []


class TermuxLocation:
    """
    GPS location via Termux:API.
    Attaches location data to detections.
    """

    def get(self, provider: str = "gps", timeout: int = 30) -> dict:
        """
        Get current GPS location.
        provider: 'gps' (accurate) or 'network' (faster, less accurate)
        """
        if not termux_available("termux-location"):
            return {}

        try:
            r = subprocess.run(
                ["termux-location", "-p", provider, "-r", "once"],
                capture_output=True, text=True, timeout=timeout
            )
            if r.returncode == 0 and r.stdout.strip():
                data = json.loads(r.stdout)
                return {
                    "lat":      data.get("latitude"),
                    "lon":      data.get("longitude"),
                    "accuracy": data.get("accuracy"),
                    "time":     datetime.now(timezone.utc).isoformat(),
                    "provider": provider,
                }
        except Exception:
            pass

        return {}

    def get_fast(self) -> dict:
        """Quick network-based location — less accurate but immediate."""
        return self.get(provider="network", timeout=10)


class TermuxNotification:
    """
    Native Android notifications via Termux:API.
    Alerts the person even when Themis is in background.
    """

    def send(self, title: str, content: str,
             priority: str = "default", ongoing: bool = False):
        """
        Send a native Android notification.
        priority: min, low, default, high, max
        """
        if not termux_available("termux-notification"):
            # Fall back to terminal output
            print(f"\n  🔔 {title}: {content}\n")
            return

        try:
            cmd = [
                "termux-notification",
                "--title",    title,
                "--content",  content,
                "--priority", priority,
                "--id",       "themis_alert",
            ]
            if ongoing:
                cmd.append("--ongoing")

            subprocess.run(cmd, capture_output=True, timeout=5)
        except Exception:
            print(f"\n  🔔 {title}: {content}\n")

    def alert_detection(self, detection: dict):
        """Send a detection alert as Android notification."""
        detection_type = detection.get("type", "unknown")
        detail         = detection.get("plain_language") or detection.get("detail", "")
        operator       = detection.get("operator", "")

        titles = {
            "drone_signal":              "🚁 Government Drone Detected",
            "drone_bluetooth":           "🚁 Drone Signal Detected",
            "surveillance_camera":       "📷 Surveillance Camera",
            "surveillance_device_local": "⚠️ Surveillance Device on Network",
            "surveillance_port":         "📡 Surveillance Port Open",
            "imsi_catcher":              "🚨 STINGRAY DETECTED",
            "facial_recognition":        "🚨 FACIAL RECOGNITION DETECTED",
            "license_plate_reader":      "🚗 License Plate Reader",
            "known_infrastructure":      "📍 Known Surveillance Infrastructure",
        }

        title    = titles.get(detection_type, "⚖️ Themis Alert")
        content  = f"{detail}"
        if operator:
            content = f"{operator} — {detail}"

        # High priority for serious detections
        priority = "max" if detection_type in (
            "imsi_catcher", "facial_recognition"
        ) else "high"

        self.send(title, content, priority=priority)

    def watching(self):
        """Persistent notification while Themis is active."""
        self.send(
            title    = "⚖️ Themis — The Watch",
            content  = "Active. Watching. The scales are balanced.",
            priority = "low",
            ongoing  = True,
        )

    def dismiss(self):
        """Dismiss the persistent watching notification."""
        try:
            subprocess.run(
                ["termux-notification-remove", "themis_alert"],
                capture_output=True, timeout=5
            )
        except Exception:
            pass


class TermuxBluetooth:
    """
    Bluetooth scanning via Termux:API.
    Detects drone BLE broadcasts on Android.
    More reliable than hcitool on Android.
    """

    def scan(self, duration: int = 5) -> list:
        """Scan for Bluetooth devices."""
        if not termux_available("termux-bluetooth-scan"):
            return []

        try:
            r = subprocess.run(
                ["termux-bluetooth-scan", "-d", str(duration)],
                capture_output=True, text=True, timeout=duration + 5
            )
            if r.returncode == 0 and r.stdout.strip():
                devices = json.loads(r.stdout)
                return [
                    {
                        "name":    d.get("name", ""),
                        "address": d.get("address", ""),
                        "rssi":    d.get("rssi", -100),
                    }
                    for d in devices
                ]
        except Exception:
            pass

        return []


class TermuxAdapter:
    """
    Main adapter. Detects environment and routes
    to Termux tools or desktop tools accordingly.

    Desktop code stays intact.
    This layer sits on top.
    """

    def __init__(self):
        self._is_termux  = is_termux()
        self.wifi        = TermuxWifi()        if self._is_termux else None
        self.location    = TermuxLocation()    if self._is_termux else None
        self.notify      = TermuxNotification()
        self.bluetooth   = TermuxBluetooth()   if self._is_termux else None

    @property
    def on_android(self) -> bool:
        return self._is_termux

    def get_wifi_networks(self) -> list:
        """Get WiFi networks — Termux or desktop."""
        if self._is_termux and self.wifi:
            return self.wifi.scan()
        return []  # Desktop scanners handled in argos.py

    def get_location(self) -> dict:
        """Get current location — fast first, accurate if available."""
        if self._is_termux and self.location:
            loc = self.location.get_fast()
            if loc:
                return loc
        return {}

    def notify_detection(self, detection: dict):
        """Send appropriate notification for a detection."""
        self.notify.alert_detection(detection)

    def start_watching_notification(self):
        """Show persistent 'watching' notification."""
        if self._is_termux:
            self.notify.watching()

    def stop_watching_notification(self):
        """Remove persistent notification."""
        if self._is_termux:
            self.notify.dismiss()

    def check_setup(self) -> dict:
        """
        Check what Termux tools are available.
        Tells the person exactly what to install.
        """
        checks = {
            "termux_detected":     self._is_termux,
            "termux_api":          termux_available("termux-wifi-scaninfo"),
            "wifi_scan":           termux_available("termux-wifi-scaninfo"),
            "location":            termux_available("termux-location"),
            "notifications":       termux_available("termux-notification"),
            "bluetooth":           termux_available("termux-bluetooth-scan"),
        }

        missing = []
        if not checks["termux_api"]:
            missing.append("Termux:API app (install from F-Droid)")
            missing.append("pkg install termux-api")

        checks["missing"] = missing
        checks["ready"]   = len(missing) == 0

        return checks

    def print_setup_status(self):
        """Print setup status in plain language."""
        checks = self.check_setup()
        print()
        print("  [Themis] Android/Termux Setup Status")
        print("  ─────────────────────────────────────")
        print(f"  Termux detected:    {'✓' if checks['termux_detected'] else '✗'}")
        print(f"  Termux:API:         {'✓' if checks['termux_api'] else '✗ Not installed'}")
        print(f"  WiFi scanning:      {'✓' if checks['wifi_scan'] else '✗'}")
        print(f"  GPS location:       {'✓' if checks['location'] else '✗'}")
        print(f"  Notifications:      {'✓' if checks['notifications'] else '✗'}")
        print(f"  Bluetooth scan:     {'✓' if checks['bluetooth'] else '✗'}")

        if checks["missing"]:
            print()
            print("  To enable full functionality:")
            for item in checks["missing"]:
                print(f"  → {item}")
            print()
            print("  Then grant permissions when prompted.")

        if checks["ready"]:
            print()
            print("  ✓ Themis is fully operational on this device.")

        print()
