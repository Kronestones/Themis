"""
veil.py — VeilAlerts
ledger_module.py — LedgerRecords
witness_module.py — WitnessIntel
bridge_module.py — BridgeTranslator

The remaining four leads.
Each carries the full weight of their domain.

Founded by Krone the Architect · Powers Tracey Lynn
Project Themis · 2026
"""

import json
import os
import time
from datetime import datetime, timezone

# ── Gaia Layer 5/8: Disappearance-of-signal tracking ─────────────────────────
# Absence is data. A camera that was on the network last scan and is now gone
# is either powered down, moved — or actively jamming/hiding. Veil tracks
# previously seen detections and flags sudden disappearances.
VEIL_LAST_SEEN_FILE      = "veil_last_seen.json"
DISAPPEARANCE_GRACE_SCANS = 2   # allow this many missed scans before flagging


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# VEIL — Alert and Protection
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class VeilAlerts:

    SEVERITY_ICONS = {
        "critical": "🔴",
        "warning":  "🟡",
        "info":     "🔵",
    }

    THREAT_LEVELS = {
        "drone_signal":              2,
        "drone_bluetooth":           2,
        "surveillance_camera":       3,
        "surveillance_device_local": 4,
        "surveillance_port":         3,
        "hidden_network":            1,
        "imsi_catcher":              5,
        "facial_recognition":        5,
        "license_plate_reader":      3,
        "wearable_camera":           4,   # Meta Ray-Ban / smart glasses
        "known_infrastructure":      2,
        "signal_disappeared":        4,
    }

    def process_detections(self, detections: list, settings: dict):
        """
        Process detections and generate alerts.
        Also checks for disappeared signals — Gaia Layer 5/8.
        """
        alert_level = settings.get("alert_level", 2)

        # ── Gaia Layer 5/8: Check for disappeared signals ─────────────────────
        disappearances = self._check_disappearances(detections)
        for d in disappearances:
            self._alert(d, threat_level=4)   # Disappearance is always at least level 4

        # Update last-seen store with this scan's detections
        self._update_last_seen(detections)

        # Standard alert processing
        for detection in detections:
            detection_type = detection.get("type", "unknown")
            threat_level   = self.THREAT_LEVELS.get(detection_type, 1)

            # Cluster events are always critical — override threat level
            if detection.get("cluster_event"):
                threat_level = 5

            if threat_level >= alert_level:
                self._alert(detection, threat_level)

    # ── Gaia Layer 5/8: Disappearance detection ───────────────────────────────

    def _load_last_seen(self) -> dict:
        try:
            with open(VEIL_LAST_SEEN_FILE) as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_last_seen(self, store: dict):
        try:
            with open(VEIL_LAST_SEEN_FILE, "w") as f:
                json.dump(store, f)
        except Exception:
            pass

    def _detection_key(self, d: dict) -> str:
        return f"{d.get('type','')}::{d.get('ssid') or d.get('ip') or d.get('detail','')[:40]}"

    def _update_last_seen(self, detections: list):
        """Record every detection we saw this scan."""
        store = self._load_last_seen()
        now   = datetime.now(timezone.utc).isoformat()
        for d in detections:
            key = self._detection_key(d)
            store[key] = {
                "last_seen":    now,
                "missed_scans": 0,
                "detail":       d.get("detail", ""),
                "type":         d.get("type", ""),
                "severity":     d.get("severity", "info"),
            }
        self._save_last_seen(store)

    def _check_disappearances(self, current_detections: list) -> list:
        """
        Compare the current scan's detections against previously seen ones.
        Any previously stable detection now absent gets its missed_scan count
        incremented. Once it exceeds DISAPPEARANCE_GRACE_SCANS, flag it.

        Gaia Layer 5/8 insight: an absence-of-signal can indicate active
        countermeasures — RF jamming, camera physically moved, IMSI catcher
        repositioned. The intake work showed that what's *missing* is as
        meaningful as what's present.
        """
        store = self._load_last_seen()
        if not store:
            return []

        current_keys = {self._detection_key(d) for d in current_detections}
        now          = datetime.now(timezone.utc).isoformat()
        disappeared  = []

        for key, record in store.items():
            if key not in current_keys:
                record["missed_scans"] = record.get("missed_scans", 0) + 1
                store[key] = record

                if record["missed_scans"] == DISAPPEARANCE_GRACE_SCANS + 1:
                    # Just crossed the threshold — generate a disappearance alert
                    disappeared.append({
                        "lead":        "Veil",
                        "type":        "signal_disappeared",
                        "detail":      (
                            f"Previously detected signal has vanished: "
                            f"{record.get('detail','unknown')} — "
                            f"absent for {record['missed_scans']} consecutive scans. "
                            f"Possible jamming, repositioning, or power-down."
                        ),
                        "severity":    "warning",
                        "original_type": record.get("type"),
                        "missed_scans":  record["missed_scans"],
                        "last_seen":     record.get("last_seen"),
                        "time":          now,
                        "source":        "Veil disappearance monitor",
                    })
            else:
                # Back in view — reset missed count
                record["missed_scans"] = 0
                store[key] = record

        self._save_last_seen(store)
        return disappeared

    def _alert(self, detection: dict, threat_level: int):
        """Display an alert to the user."""
        severity = detection.get("severity", "info")
        icon     = self.SEVERITY_ICONS.get(severity, "🔵")
        detail   = detection.get("plain_language") or detection.get("detail", "")
        lead     = detection.get("lead", "Themis")
        time_str = datetime.now().strftime("%H:%M:%S")

        print(f"\n  {icon} [{time_str}] [{lead}] Threat Level {threat_level}")
        print(f"  {detail}")

        # ── Trajectory context (Gaia Layer 3) ─────────────────────────────────
        traj = detection.get("trajectory")
        if traj and traj != "new":
            hits   = detection.get("hit_count", 1)
            delta  = detection.get("signal_delta", 0)
            delta_str = f"+{delta}" if delta > 0 else str(delta)
            traj_icon = {"approaching": "📡⬆", "receding": "📡⬇", "stable": "📡—"}.get(traj, "")
            print(f"  {traj_icon}  Signal trajectory: {traj.upper()} "
                  f"(seen {hits}x, dBm delta {delta_str})")

        # ── Cluster context (Gaia Layer 8) ────────────────────────────────────
        if detection.get("cluster_event"):
            types = ", ".join(detection.get("cluster_types", []))
            print(f"  ⚠  COORDINATED SURVEILLANCE EVENT — {detection['cluster_size']} types: {types}")

        if detection.get("type") in ("imsi_catcher", "facial_recognition", "signal_disappeared"):
            print(f"\n  ⚠  HIGH PRIORITY DETECTION")
            print(f"  Your rights may be under active threat.")
            print(f"  Document this. Know your rights.")
            self._print_emergency_rights()

        print()

    def _print_emergency_rights(self):
        print()
        print("  ─── YOUR RIGHTS ───────────────────────────────────────")
        print("  • You have the right to remain silent.")
        print("  • You have the right to refuse consent to search.")
        print("  • You have the right to photograph in public spaces.")
        print("  • You have the right to record police in public.")
        print("  • If stopped: 'Am I free to go?' If yes, leave calmly.")
        print("  • Emergency: ACLU 212-549-2500 · NLG 212-679-6018")
        print("  ────────────────────────────────────────────────────────")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# LEDGER — Records and Evidence
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

DETECTIONS_FILE = "themis_detections.json"


class LedgerRecords:

    def record(self, detection: dict):
        """
        Record a detection to the permanent ledger.
        Every detection documented. Nothing lost.
        """
        record = {
            "time":       detection.get("time", datetime.now(timezone.utc).isoformat()),
            "lead":       detection.get("lead", "Themis"),
            "type":       detection.get("type", "unknown"),
            "detail":     detection.get("detail", ""),
            "severity":   detection.get("severity", "info"),
            "confidence": detection.get("confidence", 0.0),
            "source":     detection.get("source", ""),
        }

        if detection.get("location"):
            record["location"] = detection["location"]

        try:
            records = self._load()
            records.append(record)
            with open(DETECTIONS_FILE, "w") as f:
                json.dump(records, f, indent=2)
        except Exception:
            pass

    def get_all(self) -> list:
        return self._load()

    def get_by_type(self, detection_type: str) -> list:
        return [r for r in self._load()
                if r.get("type") == detection_type]

    def summary(self) -> dict:
        records = self._load()
        by_type = {}
        for r in records:
            t = r.get("type", "unknown")
            by_type[t] = by_type.get(t, 0) + 1

        return {
            "total":   len(records),
            "by_type": by_type,
            "first":   records[0]["time"] if records else None,
            "last":    records[-1]["time"] if records else None,
        }

    def export(self, filepath: str) -> bool:
        """Export all records to a file for legal use."""
        records = self._load()
        try:
            with open(filepath, "w") as f:
                json.dump({
                    "exported":  datetime.now(timezone.utc).isoformat(),
                    "total":     len(records),
                    "records":   records,
                    "note":      "Generated by Project Themis. Cryptographic chain in themis_audit.log.",
                }, f, indent=2)
            return True
        except Exception:
            return False

    def _load(self) -> list:
        try:
            if os.path.exists(DETECTIONS_FILE):
                with open(DETECTIONS_FILE) as f:
                    return json.load(f)
        except Exception:
            pass
        return []


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# WITNESS — Community Intelligence
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

KNOWN_INFRASTRUCTURE_FILE = "themis_known_infrastructure.json"


class WitnessIntel:
    """
    Community reported and publicly documented
    surveillance infrastructure database.
    Updated by the community. Verified by the team.
    """

    # Publicly documented surveillance deployments
    # Sources: EFF Atlas of Surveillance, ACLU, investigative journalism
    KNOWN_SYSTEMS = {
        "shotspotter_cities": [
            "New York City", "Chicago", "Washington DC", "Oakland",
            "San Francisco", "Los Angeles", "Detroit", "Memphis",
            "Milwaukee", "Cleveland", "Hartford", "Omaha",
        ],
        "palantir_cities": [
            "New Orleans", "Los Angeles", "New York City", "Chicago",
            "Denver", "New Orleans", "Washington DC",
        ],
        "clearview_known_clients": [
            "FBI", "ICE", "CBP", "US Marshals Service",
            "ATF", "numerous state police departments",
        ],
        "real_time_crime_centers": [
            "New York City", "Chicago", "Detroit", "Memphis",
            "Sacramento", "Denver", "Atlanta", "Houston",
            "Philadelphia", "Seattle",
        ],
        # Flock Safety ALPR network — over 5,000 US cities and communities
        # Sources: Flock Safety website, EFF Atlas of Surveillance, local news
        "flock_safety_cities": [
            "Atlanta", "Austin", "Charlotte", "Dallas", "Denver",
            "Houston", "Los Angeles", "Miami", "Nashville", "Phoenix",
            "San Antonio", "Seattle", "hundreds of HOA communities nationwide",
        ],
        # Meta Ray-Ban smart glasses — sold publicly, no registration required
        # Anyone may be wearing them. No visible indicator when recording.
        "meta_rayban_notes": [
            "Sold in retail stores and online since 2021",
            "Second generation released 2023 with live streaming capability",
            "No LED recording indicator visible from the front",
            "Records 1080p video and spatial audio",
            "Can livestream directly to Instagram/Facebook",
        ],
    }

    def check_known_infrastructure(self, settings: dict) -> list:
        """
        Check community database for known surveillance
        infrastructure in the user's area.
        """
        detections = []
        local_db   = self._load_local()

        for record in local_db:
            if record.get("verified"):
                detections.append({
                    "lead":       "Witness",
                    "type":       "known_infrastructure",
                    "detail":     record.get("description", ""),
                    "confidence": record.get("confidence", 0.70),
                    "severity":   record.get("severity", "info"),
                    "source":     record.get("source", "Community report"),
                    "time":       datetime.now(timezone.utc).isoformat(),
                })

        return detections

    def submit_sighting(self, sighting: dict) -> bool:
        """
        Submit a community sighting for verification.
        Anonymous. Protected. Every submission matters.
        """
        record = {
            "time":        datetime.now(timezone.utc).isoformat(),
            "type":        sighting.get("type", "unknown"),
            "description": sighting.get("description", ""),
            "location":    sighting.get("location"),
            "photo_hash":  sighting.get("photo_hash"),
            "verified":    False,
            "confidence":  0.50,
            "source":      "Community report",
        }

        records = self._load_local()
        records.append(record)

        try:
            with open(KNOWN_INFRASTRUCTURE_FILE, "w") as f:
                json.dump(records, f, indent=2)
            return True
        except Exception:
            return False

    def get_known_systems_summary(self) -> dict:
        return self.KNOWN_SYSTEMS

    def _load_local(self) -> list:
        try:
            if os.path.exists(KNOWN_INFRASTRUCTURE_FILE):
                with open(KNOWN_INFRASTRUCTURE_FILE) as f:
                    return json.load(f)
        except Exception:
            pass
        return []


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# BRIDGE — Translation and Education
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class BridgeTranslator:
    """
    Plain language. Always. No jargon. No exceptions.
    Every detection explained so anyone can understand it.
    Every right explained so anyone can exercise it.
    """

    TRANSLATIONS = {
        "drone_signal": {
            "en": "A drone is nearby. It may be recording video or collecting data.",
            "es": "Hay un dron cerca. Puede estar grabando video o recopilando datos.",
        },
        "drone_bluetooth": {
            "en": "A drone broadcasting its identity signal has been detected nearby.",
            "es": "Se detectó un dron transmitiendo su señal de identidad cerca.",
        },
        "surveillance_camera": {
            "en": "A surveillance camera from a known manufacturer was detected on this network.",
            "es": "Se detectó una cámara de vigilancia de un fabricante conocido en esta red.",
        },
        "surveillance_device_local": {
            "en": "A surveillance device is on your local network. It can see local traffic.",
            "es": "Un dispositivo de vigilancia está en su red local.",
        },
        "surveillance_port": {
            "en": "A device on this network has an open port used by surveillance cameras.",
            "es": "Un dispositivo en esta red tiene un puerto abierto usado por cámaras.",
        },
        "hidden_network": {
            "en": "A strong hidden WiFi network is nearby. This can indicate surveillance equipment.",
            "es": "Hay una red WiFi oculta y fuerte cerca. Puede indicar equipo de vigilancia.",
        },
        "imsi_catcher": {
            "en": "WARNING: A device that captures cell phone signals (Stingray) may be nearby. Your calls and location may be tracked.",
            "es": "ADVERTENCIA: Un dispositivo que captura señales de teléfono celular puede estar cerca.",
        },
        "facial_recognition": {
            "en": "WARNING: A facial recognition system has been detected in this area. You may be identified without consent.",
            "es": "ADVERTENCIA: Se detectó un sistema de reconocimiento facial en esta área.",
        },
        "license_plate_reader": {
            "en": "A license plate reader (possibly Flock Safety) is in this area. Your vehicle's plate, location, and time of travel may be logged and shared with police.",
            "es": "Hay un lector de placas (posiblemente Flock Safety) en esta área. Su placa, ubicación y hora de viaje pueden registrarse y compartirse con la policía.",
        },
        "wearable_camera": {
            "en": "WARNING: Smart glasses capable of recording video (possibly Meta Ray-Ban) detected nearby. Someone around you may be recording without any visible indicator.",
            "es": "ADVERTENCIA: Se detectaron lentes inteligentes con cámara (posiblemente Meta Ray-Ban) cerca. Alguien puede estar grabando sin ningún indicador visible.",
        },
        "known_infrastructure": {
            "en": "Known surveillance infrastructure has been documented in this area by the community.",
            "es": "La comunidad ha documentado infraestructura de vigilancia conocida en esta área.",
        },
    }

    RIGHTS_BY_SITUATION = {
        "drone": (
            "If a drone is filming you in public:\n"
            "• You generally cannot be legally identified from drone footage without a warrant.\n"
            "• FAA Part 107 requires drones to maintain visual line of sight.\n"
            "• Document the drone if safe to do so — note time, location, direction.\n"
            "• File a complaint with FAA at: faa.gov/uas/resources/public_records"
        ),
        "camera": (
            "If you're being filmed by a surveillance camera:\n"
            "• In public spaces, filming is generally legal.\n"
            "• Private companies cannot use footage to track you across locations without consent.\n"
            "• You can request footage of yourself under CCPA (California) or GDPR (EU).\n"
            "• Document the location for community reporting."
        ),
        "imsi": (
            "If a Stingray/IMSI catcher may be nearby:\n"
            "• Switch to WiFi calling if available — avoids cell network.\n"
            "• Use Signal for calls and messages — end to end encrypted.\n"
            "• Consider airplane mode if you don't need connectivity.\n"
            "• Contact ACLU: aclu.org or 212-549-2500"
        ),
        "flock": (
            "If a Flock Safety license plate reader is nearby:\n"
            "• Flock cameras capture your plate, vehicle make/color, direction of travel, and timestamp.\n"
            "• Data is typically retained 30 days but often shared with hundreds of law enforcement agencies.\n"
            "• You can check if your city uses Flock: EFF Atlas of Surveillance — atlasofsurveillance.org\n"
            "• Submit a public records request to your local police for their Flock data-sharing agreements.\n"
            "• Contact EFF: eff.org or Electronic Privacy Information Center: epic.org"
        ),
        "glasses": (
            "If Meta Ray-Ban smart glasses may be nearby:\n"
            "• These glasses record 1080p video and audio with no visible indicator when recording.\n"
            "• The second-generation model can livestream directly to Instagram/Facebook.\n"
            "• In public spaces, filming is generally legal — but covert recording laws vary by state.\n"
            "• Two-party consent states (CA, FL, IL, etc.) may prohibit secret audio recording.\n"
            "• If you believe you are being recorded without consent, document the situation.\n"
            "• Contact your state attorney general's office about covert recording laws."
        ),
    }

    def translate(self, detection: dict, language: str = "en") -> str:
        """
        Translate a detection into plain language.
        Default English. Expanding to all languages.
        """
        detection_type = detection.get("type", "unknown")
        translations   = self.TRANSLATIONS.get(detection_type, {})

        if language in translations:
            return translations[language]
        if "en" in translations:
            return translations["en"]

        # Fallback to raw detail
        return detection.get("detail", "Surveillance activity detected.")

    def explain(self, topic: str) -> str:
        """Plain language explainer for surveillance topics."""
        explainers = {
            "stingray": (
                "A Stingray (IMSI catcher) is a device that pretends to be a cell tower. "
                "Your phone connects to it instead of a real tower. "
                "This lets the operator capture your location, calls, and texts. "
                "Police and federal agencies use them. Often without a warrant."
            ),
            "facial_recognition": (
                "Facial recognition software analyzes your face and compares it to a database. "
                "It can identify you from camera footage without your knowledge or consent. "
                "It has a high error rate, especially for people of color. "
                "It is being used by police, corporations, and landlords."
            ),
            "flock": (
                "Flock Safety makes automated license plate reader (ALPR) cameras. "
                "They are sold to police departments, HOAs, and private communities. "
                "Each camera photographs every passing vehicle — plate, make, color, direction, timestamp. "
                "Data is stored in the cloud and automatically shared with thousands of law enforcement agencies "
                "through Flock's National Partner Network — without a warrant or individual request. "
                "As of 2024, Flock cameras are deployed in over 5,000 cities and communities across the US."
            ),
            "meta_glasses": (
                "Meta Ray-Ban smart glasses are eyeglasses with a built-in camera, microphone, and speaker. "
                "They look like ordinary Ray-Ban frames. "
                "They can record 1080p video and audio. There is no indicator light visible from the front. "
                "The second generation (2023) can livestream directly to Instagram and Facebook. "
                "They are sold in stores and online. Anyone can buy them. "
                "Two Harvard students demonstrated in 2024 that they could be used to identify strangers "
                "in public by streaming video to a facial recognition API in real time."
            ),
            "palantir": (
                "Palantir is a company that sells data analysis software to governments and police. "
                "Their software connects many databases — arrests, social media, location data — "
                "and builds profiles on people. They work with ICE, FBI, and many police departments. "
                "Named after the all-seeing stones from Lord of the Rings."
            ),
            "drone": (
                "Surveillance drones are aircraft used to film or track people from above. "
                "Police departments, corporations, and federal agencies use them. "
                "Since 2023, most drones must broadcast a Remote ID signal — "
                "Themis can detect this signal."
            ),
            "fusion_center": (
                "A fusion center is a facility where local, state, and federal agencies "
                "share surveillance data. There are 80+ in the US. "
                "They collect information on people with no criminal history. "
                "They have a documented history of targeting activists and communities of color."
            ),
        }

        return explainers.get(topic.lower(),
               f"No explainer found for '{topic}'. Ask the team.")

    def rights_card(self, situation: str) -> str:
        """Return a Know Your Rights card for a situation."""
        return self.RIGHTS_BY_SITUATION.get(
            situation.lower(),
            "Know your rights. You have them. themis.watch for more."
        )
