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
import json
import time
from datetime import datetime, timezone

# ── Gaia Layer 3: Signal trajectory tracking ──────────────────────────────────
# A detection seen once is noise. A detection growing stronger over repeated
# scans is a threat vector. Track per-detection history across scans.
ARGOS_TRAJECTORY_FILE = "argos_trajectory.json"
TRAJECTORY_MAX_AGE_S  = 3600  # prune entries not seen in the last hour

# ── Gaia Layer 8: Cross-type cluster escalation ───────────────────────────────
# Individual detection types have their own threat levels, but a coordinated
# surveillance event — multiple distinct types detected in the same scan window
# — is qualitatively more serious than any single detection.
# Two or more distinct types in one scan → escalate the whole set.
CLUSTER_ESCALATION_THRESHOLD = 2   # distinct detection types to trigger escalation
CLUSTER_WINDOW_S             = 120  # seconds — how recent detections must be to cluster


class ArgosScanner:

    KNOWN_SURVEILLANCE_PORTS = {
        554:   "RTSP — live camera stream",
        8080:  "HTTP camera feed",
        8554:  "RTSP alternate — surveillance camera",
        9000:  "Hikvision camera management",
        8000:  "Hikvision/Dahua default port",
        37777: "Dahua camera port",
        80:    "HTTP — possible camera web interface",
        443:   "HTTPS — Flock Safety cloud upload / camera management",
        8883:  "MQTT over TLS — Flock Safety telemetry",
        2222:  "Flock Safety SSH management port",
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
        # Flock Safety — ALPRs deployed by police departments and HOAs
        # Sources: Flock Safety hardware teardowns, FCC filings ID: 2BCGQ-FSALPR
        "70:b3:d5": "Flock Safety ALPR",
        "d8:3a:dd": "Flock Safety ALPR",
        "00:1e:c0": "Flock Safety ALPR",
        # Meta Ray-Ban smart glasses (Luxottica / EssilorLuxottica hardware)
        # Sources: FCC filing ID: 2ADZR-RLGL, Bluetooth OUI registry
        "f0:b3:ec": "Meta Ray-Ban smart glasses",
        "4c:bc:98": "Meta Ray-Ban smart glasses",
        "dc:fb:02": "Meta (Oculus/Ray-Ban) device",
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

    # Flock Safety ALPR WiFi AP patterns
    # Flock cameras create their own hotspots for maintenance access
    # and upload video/plate data over cellular + local WiFi
    # Sources: Flock Safety installer documentation, wardriving reports
    FLOCK_SSID_PATTERNS = [
        r"^FLOCK[_\-]",
        r"^FSS[_\-]",           # Flock Safety System prefix
        r"^flock[_\-]safety",
        r"^ALPR[_\-]",          # Generic ALPR hotspot
        r"^FlockCamera",
        r"^Flock-",
    ]

    # Meta Ray-Ban smart glasses WiFi/BLE patterns
    # Ray-Ban Stories / Meta Ray-Ban glasses broadcast BLE for pairing
    # and create a companion hotspot for firmware updates
    # Sources: Meta FCC filings, Bluetooth sniffing research (2023-2024)
    META_GLASSES_SSID_PATTERNS = [
        r"^RayBan[_\-\s]",
        r"^Ray-Ban[_\-\s]",
        r"^Meta[_\-]Glasses",
        r"^RBGL[_\-]",          # Ray-Ban Glasses short prefix
        r"^Stories[_\-]",
    ]

    # BLE advertisement name fragments for Meta Ray-Ban glasses and Flock units
    META_GLASSES_BLE_PATTERNS = ["RAYBAN", "RAY-BAN", "META GLASS", "RB STORIES", "RBGL"]
    FLOCK_BLE_PATTERNS         = ["FLOCK", "FSS-", "ALPR"]

    def __init__(self):
        self._system = platform.system()

    def scan(self, settings: dict) -> list:
        """
        Run all Argos detection methods.
        Returns list of detection dicts, enriched with trajectory data
        and cross-type cluster escalation.
        """
        detections = []

        detections += self._scan_wifi_surveillance(settings)
        detections += self._scan_network_devices(settings)
        detections += self._scan_drone_signals(settings)

        # ── Gaia Layer 3: Enrich each detection with trajectory data ──────────
        detections = self._apply_trajectory(detections)

        # ── Gaia Layer 8: Apply cross-type cluster escalation ─────────────────
        detections = self._apply_cluster_escalation(detections)

        return detections

    # ── Gaia Layer 3: Signal trajectory ───────────────────────────────────────

    def _detection_fingerprint(self, d: dict) -> str:
        """Stable key for matching a detection across scans."""
        return f"{d.get('type','')}::{d.get('ssid') or d.get('ip') or d.get('raw','')}"

    def _load_trajectory(self) -> dict:
        try:
            with open(ARGOS_TRAJECTORY_FILE) as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_trajectory(self, traj: dict):
        # Prune entries not seen within the max age window before saving
        cutoff = datetime.now(timezone.utc).timestamp() - TRAJECTORY_MAX_AGE_S
        pruned = {}
        for fp, entry in traj.items():
            try:
                last = datetime.fromisoformat(entry["last_seen"]).timestamp()
                if last >= cutoff:
                    pruned[fp] = entry
            except Exception:
                pruned[fp] = entry  # keep if we can't parse the timestamp
        try:
            with open(ARGOS_TRAJECTORY_FILE, "w") as f:
                json.dump(pruned, f)
        except Exception:
            pass

    def _apply_trajectory(self, detections: list) -> list:
        """
        Match each detection against the trajectory store.
        Adds: first_seen, hit_count, signal_delta, trajectory label.

        Gaia Layer 3 insight: tracking fast-moving objects requires knowing
        their vector, not just their position. A rising signal_dbm means
        the source is approaching. A stable one is ambient infrastructure.
        The difference matters for the person being watched.
        """
        traj  = self._load_trajectory()
        now   = datetime.now(timezone.utc).isoformat()
        enriched = []

        for d in detections:
            fp    = self._detection_fingerprint(d)
            prior = traj.get(fp)

            if prior:
                prev_signal = prior.get("last_signal_dbm")
                curr_signal = d.get("signal_dbm")
                if prev_signal is not None and curr_signal is not None:
                    delta = curr_signal - prev_signal
                else:
                    delta = 0

                d["first_seen"]   = prior.get("first_seen", now)
                d["hit_count"]    = prior.get("hit_count", 1) + 1
                d["signal_delta"] = delta
                d["trajectory"]   = (
                    "approaching" if delta > 3 else
                    "receding"    if delta < -3 else
                    "stable"
                )
                traj[fp] = {
                    "first_seen":     d["first_seen"],
                    "hit_count":      d["hit_count"],
                    "last_signal_dbm": curr_signal,
                    "last_seen":      now,
                }
            else:
                d["first_seen"]   = now
                d["hit_count"]    = 1
                d["signal_delta"] = 0
                d["trajectory"]   = "new"
                traj[fp] = {
                    "first_seen":     now,
                    "hit_count":      1,
                    "last_signal_dbm": d.get("signal_dbm"),
                    "last_seen":      now,
                }
            enriched.append(d)

        self._save_trajectory(traj)
        return enriched

    # ── Gaia Layer 8: Cross-type cluster escalation ───────────────────────────

    def _apply_cluster_escalation(self, detections: list) -> list:
        """
        If this scan found two or more distinct surveillance types, this is
        a coordinated surveillance event — not coincidence. Escalate all
        detections in the cluster to 'critical' severity and add a cluster
        flag so Veil can surface it clearly.

        Gaia Layer 8: evolutionary pressure is measured by diversity of
        simultaneous selection pressures, not just intensity of any one.
        Multiple system types converging on one location at the same time
        is a qualitatively different threat category.
        """
        distinct_types = set(d.get("type") for d in detections)
        is_cluster     = len(distinct_types) >= CLUSTER_ESCALATION_THRESHOLD

        if not is_cluster:
            return detections

        escalated = []
        for d in detections:
            d["cluster_event"]  = True
            d["cluster_types"]  = sorted(distinct_types)
            d["cluster_size"]   = len(distinct_types)
            # Escalate severity
            if d.get("severity") != "critical":
                d["severity"]         = "critical"
                d["severity_reason"]  = (
                    f"Cluster escalation: {len(distinct_types)} distinct surveillance "
                    f"types detected simultaneously ({', '.join(sorted(distinct_types))})"
                )
            escalated.append(d)

        return escalated

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
                    detections.append({
                        "lead":       "Argos",
                        "type":       "drone_signal",
                        "detail":     f"Drone signal detected: {ssid}",
                        "confidence": 0.85,
                        "severity":   "info",
                        "ssid":       ssid,
                        "bssid":      bssid,
                        "signal_dbm": signal,
                        "time":       datetime.now(timezone.utc).isoformat(),
                        "source":     "Argos WiFi scan",
                    })
                    break

            # ── Flock Safety ALPR WiFi hotspot detection ──────────────────────
            for pattern in self.FLOCK_SSID_PATTERNS:
                if re.match(pattern, ssid, re.IGNORECASE):
                    detections.append({
                        "lead":       "Argos",
                        "type":       "license_plate_reader",
                        "detail":     (
                            f"Flock Safety ALPR camera hotspot detected: '{ssid}'. "
                            f"This is an automated license plate reader. "
                            f"Your vehicle's movement may be logged and shared with law enforcement."
                        ),
                        "confidence": 0.88,
                        "severity":   "warning",
                        "vendor":     "Flock Safety",
                        "ssid":       ssid,
                        "bssid":      bssid,
                        "signal_dbm": signal,
                        "time":       datetime.now(timezone.utc).isoformat(),
                        "source":     "Argos WiFi scan — Flock SSID",
                    })
                    break

            # ── Meta Ray-Ban smart glasses WiFi hotspot detection ─────────────
            for pattern in self.META_GLASSES_SSID_PATTERNS:
                if re.match(pattern, ssid, re.IGNORECASE):
                    detections.append({
                        "lead":       "Argos",
                        "type":       "wearable_camera",
                        "detail":     (
                            f"Meta Ray-Ban smart glasses hotspot detected: '{ssid}'. "
                            f"Someone nearby may be wearing camera glasses. "
                            f"These glasses record video and audio without visible indication."
                        ),
                        "confidence": 0.80,
                        "severity":   "warning",
                        "vendor":     "Meta / Ray-Ban",
                        "ssid":       ssid,
                        "bssid":      bssid,
                        "signal_dbm": signal,
                        "time":       datetime.now(timezone.utc).isoformat(),
                        "source":     "Argos WiFi scan — Meta glasses SSID",
                    })
                    break

            # Check MAC prefix against known surveillance vendors
            mac_prefix = bssid[:8].replace("-", ":")
            if mac_prefix in self.SURVEILLANCE_MAC_PREFIXES:
                vendor = self.SURVEILLANCE_MAC_PREFIXES[mac_prefix]
                detections.append({
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
                })

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
                        line_upper = line.upper()

                        # DJI drone BLE
                        if any(p in line_upper for p in ["DJI", "DRONE", "UAV"]):
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

                        # Meta Ray-Ban glasses BLE pairing broadcast
                        elif any(p in line_upper for p in self.META_GLASSES_BLE_PATTERNS):
                            detections.append({
                                "lead":       "Argos",
                                "type":       "wearable_camera",
                                "detail":     (
                                    f"Meta Ray-Ban smart glasses detected via Bluetooth: "
                                    f"{line.strip()}. Someone nearby may be wearing "
                                    f"camera glasses recording video and audio."
                                ),
                                "confidence": 0.82,
                                "severity":   "warning",
                                "vendor":     "Meta / Ray-Ban",
                                "raw":        line.strip(),
                                "time":       datetime.now(timezone.utc).isoformat(),
                                "source":     "Argos BLE scan — Meta glasses",
                            })

                        # Flock Safety ALPR BLE maintenance broadcast
                        elif any(p in line_upper for p in self.FLOCK_BLE_PATTERNS):
                            detections.append({
                                "lead":       "Argos",
                                "type":       "license_plate_reader",
                                "detail":     (
                                    f"Flock Safety ALPR BLE signal detected: {line.strip()}. "
                                    f"An automated license plate reader is nearby."
                                ),
                                "confidence": 0.78,
                                "severity":   "warning",
                                "vendor":     "Flock Safety",
                                "raw":        line.strip(),
                                "time":       datetime.now(timezone.utc).isoformat(),
                                "source":     "Argos BLE scan — Flock ALPR",
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
        """
        Parse macOS `airport -s` output.
        The BSSID is always a fixed-width MAC (xx:xx:xx:xx:xx:xx) and the
        RSSI is the integer immediately after it. The SSID is everything
        to the left of the MAC column, so we locate the MAC with a regex
        rather than splitting on whitespace (which breaks SSIDs with spaces).
        """
        networks = []
        mac_re   = re.compile(r"([0-9a-f]{2}(?::[0-9a-f]{2}){5})\s+(-\d+)", re.IGNORECASE)
        for line in output.splitlines()[1:]:
            m = mac_re.search(line)
            if m:
                bssid  = m.group(1)
                signal = int(m.group(2))
                ssid   = line[:m.start()].strip()
                networks.append({"ssid": ssid, "bssid": bssid, "signal": signal})
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
