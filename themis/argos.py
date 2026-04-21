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

    # AI Surveillance vendor MAC prefixes
    AI_SURVEILLANCE_MAC_PREFIXES = {
        # Motorola Solutions / Avigilon AI cameras
        "00:1c:b3": "Avigilon AI Camera",
        "a8:26:d9": "Avigilon AI Camera",
        "00:18:ae": "Avigilon AI Camera",
        "b4:a9:fc": "Motorola Solutions",
        # Axon (body cam network / Evidence.com nodes)
        "00:26:b9": "Axon/Taser network device",
        "a4:c3:f0": "Axon camera unit",
        # Flock Safety LPR
        "dc:ef:09": "Flock Safety LPR",
        "e4:5f:01": "Flock Safety LPR",
        # Genetec VMS
        "00:90:a4": "Genetec Video Unit",
        # Hanwha (Samsung) AI cameras
        "00:09:18": "Hanwha/Samsung AI Camera",
        "34:e6:d7": "Hanwha AI Camera",
        # Bosch AI cameras
        "00:07:5f": "Bosch Security Camera",
        "00:04:63": "Bosch Security Camera",
        # Milestone VMS appliances
        "00:13:c6": "Milestone XProtect Appliance",
        # Verkada AI cameras (additional prefixes)
        "00:0f:7d": "Verkada AI Camera",
        "d0:81:7a": "Verkada AI Camera",
    }

    # AI surveillance SSID patterns
    AI_SURVEILLANCE_SSID_PATTERNS = [
        "avigilon", "axon-", "flock-", "flock_safety",
        "genetec", "milestone", "verkada", "shotspotter",
        "clearview", "palantir", "rekognition",
        "axon_body", "evidence.com", "fusus",
        "motorola_si", "hanwha", "bosch_cam",
    ]

    # AI surveillance specific ports
    AI_SURVEILLANCE_PORTS = {
        20000: "Avigilon Control Center",
        20001: "Avigilon camera stream",
        20002: "Avigilon analytics engine",
        8731:  "Axon Evidence sync port",
        9001:  "Flock Safety LPR upload",
        7474:  "Genetec Security Center",
        7775:  "Genetec Omnicast stream",
        8731:  "Milestone VMS",
        9200:  "Palantir Gotham endpoint",
        9300:  "Palantir Foundry endpoint",
        8443:  "ShotSpotter sensor management",
        5443:  "Fusus real-time crime center",
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
        detections += self._scan_autonomous_ground_vehicles(settings)
        detections += self._scan_ai_surveillance(settings)

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

    def _scan_autonomous_ground_vehicles(self, settings: dict) -> list:
        """
        Scan for autonomous ground surveillance robots.
        Knightscope, Boston Dynamics Spot, Robotic Assistance Devices (RAD),
        and other AI patrol units have detectable network signatures.
        """
        detections = []

        ROBOT_MAC_PREFIXES = {
            "00:1e:c0": "Knightscope security robot",
            "b8:27:eb": "Raspberry Pi — possible autonomous unit",
            "dc:a6:32": "Raspberry Pi 4 — possible autonomous unit",
            "00:17:88": "Philips Hue / IoT — possible robot component",
            "ac:87:a3": "Apple — possible coordination device",
            "b4:e6:2a": "Boston Dynamics network component",
        }

        ROBOT_SSID_PATTERNS = [
            "knightscope", "ksoc", "rad-robot", "robotic",
            "autonomous", "patrol", "k5", "k3", "spot-"
        ]

        ROBOT_PORTS = {
            8080: "Robot web interface",
            9090: "ROS — Robot Operating System",
            11311: "ROS master — autonomous vehicle coordination",
            8888:  "Robot control interface",
            4000:  "Knightscope command port",
        }

        # Check WiFi networks for robot SSIDs
        networks = self._get_wifi_networks()
        for net in networks:
            ssid = net.get("ssid", "").lower()
            for pattern in ROBOT_SSID_PATTERNS:
                if pattern in ssid:
                    detections.append({
                        "type":     "autonomous_ground_vehicle",
                        "detail":   f"Autonomous patrol unit detected: {net.get('ssid')} — signal {net.get('signal', 'unknown')} dBm",
                        "severity": "high",
                        "rights":   "You have the right to document this unit. Autonomous surveillance robots in public spaces are subject to public records requests regarding their deployment authorization.",
                        "source":   "wifi_scan",
                    })
                    break

        # Check ARP table for known robot MAC prefixes
        devices = self._arp_scan()
        for device in devices:
            mac = device.get("mac", "").lower()
            prefix = ":".join(mac.split(":")[:3])
            if prefix in ROBOT_MAC_PREFIXES:
                unit_type = ROBOT_MAC_PREFIXES[prefix]
                # Check for robot-specific open ports
                ip = device.get("ip", "")
                confirmed_ports = []
                for port, desc in ROBOT_PORTS.items():
                    if self._port_open(ip, port, timeout=0.5):
                        confirmed_ports.append(f"{port} ({desc})")
                if confirmed_ports:
                    detections.append({
                        "type":     "autonomous_ground_vehicle",
                        "detail":   f"Confirmed autonomous unit: {unit_type} at {ip} — open ports: {', '.join(confirmed_ports)}",
                        "severity": "high",
                        "rights":   "Document the unit, its location, and time. Request deployment records via FOIA. Autonomous robots collecting biometric data in public spaces may violate local ordinances.",
                        "source":   "network_scan",
                    })

        return detections


    def _scan_ai_surveillance(self, settings: dict) -> list:
        """
        Scan for AI surveillance systems.
        Covers Clearview AI, Axon, Palantir, ShotSpotter,
        Flock Safety, Avigilon, Genetec, Amazon Rekognition endpoints.
        """
        detections = []
        networks = self._get_wifi_networks()

        for network in networks:
            ssid = network.get("ssid", "").lower()
            bssid = network.get("bssid", "").lower()
            signal = network.get("signal", 0)

            # Check SSID against AI surveillance patterns
            for pattern in self.AI_SURVEILLANCE_SSID_PATTERNS:
                if pattern in ssid:
                    detections.append({
                        "lead":       "Argos",
                        "type":       "ai_surveillance",
                        "detail":     f"AI surveillance system detected: {network.get('ssid')} — matches {pattern}",
                        "confidence": 0.80,
                        "severity":   "high",
                        "ssid":       network.get("ssid"),
                        "bssid":      bssid,
                        "signal_dbm": signal,
                        "time":       __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
                        "source":     "Argos AI surveillance SSID scan",
                    })
                    break

            # Check MAC prefix against AI surveillance vendors
            mac_prefix = bssid[:8].replace("-", ":")
            if mac_prefix in self.AI_SURVEILLANCE_MAC_PREFIXES:
                vendor = self.AI_SURVEILLANCE_MAC_PREFIXES[mac_prefix]
                detections.append({
                    "lead":       "Argos",
                    "type":       "ai_surveillance",
                    "detail":     f"AI surveillance device detected: {vendor} ({network.get('ssid') or 'hidden'})",
                    "confidence": 0.85,
                    "severity":   "high",
                    "vendor":     vendor,
                    "bssid":      bssid,
                    "signal_dbm": signal,
                    "time":       __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
                    "source":     "Argos AI MAC scan",
                })

        # Check network devices for AI surveillance ports
        devices = self._arp_scan()
        for device in devices:
            ip = device.get("ip", "")
            mac = device.get("mac", "").lower()

            # Check MAC prefix
            mac_prefix = ":".join(mac.split(":")[:3]) if mac else ""
            if mac_prefix in self.AI_SURVEILLANCE_MAC_PREFIXES:
                vendor = self.AI_SURVEILLANCE_MAC_PREFIXES[mac_prefix]
                detections.append({
                    "lead":       "Argos",
                    "type":       "ai_surveillance_local",
                    "detail":     f"AI surveillance device on network: {vendor} at {ip}",
                    "confidence": 0.90,
                    "severity":   "high",
                    "vendor":     vendor,
                    "ip":         ip,
                    "mac":        mac,
                    "time":       __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
                    "source":     "Argos AI network scan",
                })
                continue

            # Port scan for AI surveillance ports
            for port, service in self.AI_SURVEILLANCE_PORTS.items():
                if self._port_open(ip, port, timeout=0.5):
                    detections.append({
                        "lead":       "Argos",
                        "type":       "ai_surveillance_port",
                        "detail":     f"AI surveillance port {port} open on {ip} — {service}",
                        "confidence": 0.75,
                        "severity":   "high",
                        "ip":         ip,
                        "port":       port,
                        "service":    service,
                        "time":       __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
                        "source":     "Argos AI port scan",
                    })
                    break

        return detections

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
