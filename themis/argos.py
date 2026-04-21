"""
argos.py — ArgosScanner

The eyes that never close.
Scans for drone signals, surveillance infrastructure,
IMSI catchers, license plate readers, camera networks,
and every other system watching without consent.

Lead: Argos
55 specialists. Every signal. Every signature.

Founded by Krone the Architect · Powers Tracey Lynn
Project Themis · 2026
"""

import subprocess
import platform
import socket
import re
import os
from datetime import datetime, timezone
from .faa_registry import FAARegistry, StationaryUnit


class ArgosScanner:

    KNOWN_SURVEILLANCE_PORTS = {
        554:  "RTSP — live camera stream",
        8080: "HTTP camera feed",
        8554: "RTSP alternate — surveillance camera",
        9000: "Hikvision camera management",
        8000: "Hikvision/Dahua default port",
        37777: "Dahua camera port",
        80:   "HTTP — possible camera web interface",
    }

    # Known surveillance device MAC prefixes (OUI)
    SURVEILLANCE_MAC_PREFIXES = {
        "4c:11:bf": "Hikvision",
        "a4:14:37": "Hikvision",
        "bc:ad:28": "Hikvision",
        "c0:56:e3": "Hikvision",
        "44:19:b6": "Dahua",
        "90:02:a9": "Dahua",
        "3c:ef:8c": "Dahua",
        "00:1a:07": "Axis Communications",
        "ac:cc:8e": "Axis Communications",
        "00:40:8c": "Axis Communications",
        "b8:27:eb": "Raspberry Pi — possible DIY surveillance",
        "dc:a6:32": "Raspberry Pi",
        "00:0f:7d": "Verkada",
    }

    # DJI Remote ID broadcast patterns
    DJI_REMOTE_ID_SSID_PATTERNS = [
        r"^DJI-",
        r"^Mavic",
        r"^Phantom",
        r"^Inspire",
        r"^Mini",
        r"^Air 2",
        r"^Matrice",
        r"^Agras",
    ]

    def __init__(self):
        self._system   = platform.system()
        self._registry = FAARegistry()
        self._registry.load_community_registrations()
        self._stationary = StationaryUnit()

    def scan(self, settings: dict) -> list:
        """
        Run all Argos detection methods.
        Returns list of detection dicts.
        """
        detections = []

        detections += self._scan_wifi_surveillance(settings)
        detections += self._scan_network_devices(settings)
        detections += self._scan_drone_signals(settings)

        return detections

    # ── WiFi Surveillance Scan ────────────────────────────────────────────────

    def _scan_wifi_surveillance(self, settings: dict) -> list:
        """
        Scan visible WiFi networks for surveillance signatures.
        Looks for camera SSIDs, drone signals, IMSI catcher patterns.
        """
        detections = []
        networks   = self._get_wifi_networks()

        for network in networks:
            ssid   = network.get("ssid", "")
            bssid  = network.get("bssid", "").lower()
            signal = network.get("signal", 0)

            # Check for drone Remote ID broadcasts
            for pattern in self.DJI_REMOTE_ID_SSID_PATTERNS:
                if re.match(pattern, ssid, re.IGNORECASE):

                    # Classify against FAA registry
                    # Personal drones: ignored. Government/contractor: tracked.
                    remote_id_data = {
                        "ssid":        ssid,
                        "operator_id": ssid,
                        "n_number":    "",
                        "serial":      "",
                    }
                    classification = self._registry.classify(remote_id_data)

                    if not classification["track"]:
                        # Personal drone — respect privacy, do not track
                        break

                    detection = {
                        "lead":           "Argos",
                        "type":           "drone_signal",
                        "detail":         f"Government/contractor drone detected: {ssid} — {classification['operator']}",
                        "confidence":     classification["confidence"],
                        "severity":       "warning",
                        "ssid":           ssid,
                        "bssid":          bssid,
                        "signal_dbm":     signal,
                        "operator":       classification["operator"],
                        "category":       classification["category"],
                        "classification": classification,
                        "time":           datetime.now(timezone.utc).isoformat(),
                        "source":         "Argos WiFi scan + FAA registry",
                    }
                    detections.append(detection)

                    # Check if stationary
                    self._stationary.record(detection)
                    break

            # Check MAC prefix against known surveillance vendors
            mac_prefix = bssid[:8].replace("-", ":")
            if mac_prefix in self.SURVEILLANCE_MAC_PREFIXES:
                vendor = self.SURVEILLANCE_MAC_PREFIXES[mac_prefix]
                detection = {
                    "lead":       "Argos",
                    "type":       "surveillance_camera",
                    "detail":     f"Surveillance device detected: {vendor} ({ssid or 'hidden'})",
                    "confidence": 0.75,
                    "severity":   "warning",
                    "vendor":     vendor,
                    "bssid":      bssid,
                    "signal_dbm": signal,
                    "time":       datetime.now(timezone.utc).isoformat(),
                    "source":     "Argos MAC scan",
                }
                detections.append(detection)
                # Camera is stationary — record permanent location
                self._stationary.record(detection)

            # Check for hidden networks with surveillance-like characteristics
            if not ssid and signal > -60:
                # Strong hidden network — could be surveillance AP
                detections.append({
                    "lead":       "Argos",
                    "type":       "hidden_network",
                    "detail":     f"Strong hidden network detected. BSSID: {bssid}",
                    "confidence": 0.40,
                    "severity":   "info",
                    "bssid":      bssid,
                    "signal_dbm": signal,
                    "time":       datetime.now(timezone.utc).isoformat(),
                    "source":     "Argos hidden network scan",
                })

        return detections

    # ── Network Device Scan ───────────────────────────────────────────────────

    def _scan_network_devices(self, settings: dict) -> list:
        """
        Scan local network for surveillance devices.
        Checks for open surveillance ports on discovered devices.
        """
        detections = []

        if self._system == "Linux":
            devices = self._arp_scan()
        else:
            devices = []

        for device in devices:
            ip  = device.get("ip", "")
            mac = device.get("mac", "").lower()

            # Check MAC against surveillance vendors
            mac_prefix = mac[:8]
            if mac_prefix in self.SURVEILLANCE_MAC_PREFIXES:
                vendor = self.SURVEILLANCE_MAC_PREFIXES[mac_prefix]
                detections.append({
                    "lead":       "Argos",
                    "type":       "surveillance_device_local",
                    "detail":     f"{vendor} device on your network: {ip}",
                    "confidence": 0.90,
                    "severity":   "warning",
                    "vendor":     vendor,
                    "ip":         ip,
                    "mac":        mac,
                    "time":       datetime.now(timezone.utc).isoformat(),
                    "source":     "Argos network scan",
                })
                continue

            # Port scan for surveillance ports
            for port, service in self.KNOWN_SURVEILLANCE_PORTS.items():
                if self._port_open(ip, port, timeout=0.5):
                    detections.append({
                        "lead":       "Argos",
                        "type":       "surveillance_port",
                        "detail":     f"Surveillance port {port} open on {ip} — {service}",
                        "confidence": 0.65,
                        "severity":   "warning",
                        "ip":         ip,
                        "port":       port,
                        "service":    service,
                        "time":       datetime.now(timezone.utc).isoformat(),
                        "source":     "Argos port scan",
                    })
                    break

        return detections

    # ── Drone Signal Scan ─────────────────────────────────────────────────────

    def _scan_drone_signals(self, settings: dict) -> list:
        """
        Scan for drone Remote ID broadcasts.
        FAA requires all drones manufactured after 2023 to broadcast.
        This is the signal we can detect.
        """
        detections = []

        # On Linux/Android — check for Bluetooth LE advertisements
        # DJI drones broadcast Remote ID via Bluetooth 5 LE
        if self._system == "Linux":
            try:
                r = subprocess.run(
                    ["hcitool", "lescan", "--duplicates"],
                    capture_output=True, text=True, timeout=5
                )
                if r.returncode == 0:
                    for line in r.stdout.splitlines():
                        if any(p in line.upper() for p in ["DJI", "DRONE", "UAV"]):
                            detections.append({
                                "lead":       "Argos",
                                "type":       "drone_bluetooth",
                                "detail":     f"Drone BLE signal: {line.strip()}",
                                "confidence": 0.80,
                                "severity":   "info",
                                "raw":        line.strip(),
                                "time":       datetime.now(timezone.utc).isoformat(),
                                "source":     "Argos BLE scan",
                            })
            except (FileNotFoundError, subprocess.TimeoutExpired):
                pass

        return detections

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _get_wifi_networks(self) -> list:
        """Get visible WiFi networks. Platform specific."""
        networks = []

        try:
            if self._system == "Linux":
                r = subprocess.run(
                    ["iwlist", "scan"],
                    capture_output=True, text=True, timeout=15
                )
                if r.returncode == 0:
                    networks = self._parse_iwlist(r.stdout)

            elif self._system == "Darwin":
                r = subprocess.run(
                    ["/System/Library/PrivateFrameworks/Apple80211.framework/"
                     "Versions/Current/Resources/airport", "-s"],
                    capture_output=True, text=True, timeout=15
                )
                if r.returncode == 0:
                    networks = self._parse_airport(r.stdout)

            elif self._system == "Windows":
                r = subprocess.run(
                    ["netsh", "wlan", "show", "networks", "mode=bssid"],
                    capture_output=True, text=True, timeout=15
                )
                if r.returncode == 0:
                    networks = self._parse_netsh(r.stdout)

        except Exception:
            pass

        return networks

    def _parse_iwlist(self, output: str) -> list:
        networks = []
        current  = {}
        for line in output.splitlines():
            line = line.strip()
            if "Cell" in line and "Address:" in line:
                if current:
                    networks.append(current)
                current = {"bssid": line.split("Address:")[-1].strip()}
            elif "ESSID:" in line:
                current["ssid"] = line.split("ESSID:")[-1].strip().strip('"')
            elif "Signal level=" in line:
                try:
                    sig = re.search(r"Signal level=(-?\d+)", line)
                    if sig:
                        current["signal"] = int(sig.group(1))
                except Exception:
                    pass
        if current:
            networks.append(current)
        return networks

    def _parse_airport(self, output: str) -> list:
        networks = []
        for line in output.splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 3:
                networks.append({
                    "ssid":   parts[0],
                    "bssid":  parts[1] if len(parts) > 1 else "",
                    "signal": int(parts[2]) if len(parts) > 2 else 0,
                })
        return networks

    def _parse_netsh(self, output: str) -> list:
        networks = []
        current  = {}
        for line in output.splitlines():
            if "SSID" in line and "BSSID" not in line:
                if current:
                    networks.append(current)
                current = {"ssid": line.split(":")[-1].strip()}
            elif "BSSID" in line:
                current["bssid"] = line.split(":")[-1].strip()
            elif "Signal" in line:
                try:
                    sig = int(re.search(r"(\d+)%", line).group(1))
                    current["signal"] = sig - 100  # Convert % to approximate dBm
                except Exception:
                    pass
        if current:
            networks.append(current)
        return networks

    def _arp_scan(self) -> list:
        """Get local network devices via ARP table."""
        devices = []
        try:
            r = subprocess.run(
                ["arp", "-n"],
                capture_output=True, text=True, timeout=10
            )
            for line in r.stdout.splitlines():
                parts = line.split()
                if len(parts) >= 3 and ":" in parts[2]:
                    devices.append({
                        "ip":  parts[0],
                        "mac": parts[2],
                    })
        except Exception:
            pass
        return devices

    def _port_open(self, ip: str, port: int, timeout: float = 1.0) -> bool:
        """Check if a port is open on a given IP."""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            result = sock.connect_ex((ip, port))
            sock.close()
            return result == 0
        except Exception:
            return False
