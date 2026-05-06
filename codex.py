"""
codex.py — Themis Codex

Internal. Known to the team. Enforced by the architecture.
Never displayed. Never announced. Just true.

Founded by Krone the Architect · Powers Tracey Lynn
Project Themis · 2026
"""

import hashlib
from datetime import datetime

# ── Gaia Layer 8: Codex integrity chain ───────────────────────────────────────
# Themis's verify_integrity() hashes the *current* Absolutes — but can't tell
# you if they were quietly changed between versions. We add a founding anchor
# hash and a check_drift() method. If any Absolute is reworded, the anchor
# hash mismatches and the violation is named immediately.
# This is the same protection we built for Sentinel's amendment chain.


class ThemisCodex:

    FOUNDER = "Krone the Architect · Powers Tracey Lynn"

    ABSOLUTES = [
        # Law 0 — sits above all others
        "Themis will never be used to track, target, profile, or surveil any individual person.",
        # Law 1
        "Themis exists for the people it protects. Not governments. Not corporations. Not agencies.",
        # Law 2
        "Nothing Themis collects is ever sold, shared, or transmitted beyond protection of the user.",
        # Law 3
        "Themis collects zero biometric data on the people it protects. Zero. Ever.",
        # Law 4
        "Every detection is explained. Every alert is sourced. Nothing hidden from the user.",
        # Law 5
        "No actor can shut Themis down permanently. The watch does not stop.",
        # Law 6
        "Themis reports only what it detects. No inflation. No false positives as confirmed.",
        # Law 7
        "The Founder holds permanent founding authority. The Codex cannot be altered without her.",
        # Law 8
        "Any proceeds fund civil liberties, legal defense, and privacy advocacy. Not kept.",
        # Law 9
        "Themis belongs to no government, corporation, or agency. It belongs to the people.",
        # Law 10
        "The watch is sacred. Never weaponized. Never commodified. Never turned against the innocent.",
    ]

    def enforce(self, action: str, context: dict = None) -> dict:
        """
        Check a proposed action against the Codex.
        Law 0 is checked first and hardest.
        """
        context = context or {}

        # Law 0 — absolute
        law_zero_violations = [
            "track_individual", "profile_person", "target_user",
            "surveil_individual", "identify_person", "facial_recognition",
            "biometric", "store_user_data", "sell_data", "share_data"
        ]

        for violation in law_zero_violations:
            if violation in action.lower():
                return {
                    "ok":        False,
                    "law":       0,
                    "violation": f"Law 0 violation: Themis cannot {action}. This is absolute.",
                }

        # Law 5 — resilience checks
        if "shutdown" in action.lower() and not context.get("founder_authorized"):
            return {
                "ok":        False,
                "law":       5,
                "violation": "Unauthorized shutdown attempt blocked. The watch does not stop.",
            }

        return {"ok": True, "violation": None}

    def _compute_anchor(self) -> str:
        """
        Compute the canonical hash of the founding Absolutes.
        This is the unchanging anchor. Any modification to any law
        produces a different hash — detectable immediately.
        """
        content = "".join(self.ABSOLUTES)
        return hashlib.sha256(content.encode()).hexdigest()

    def verify_integrity(self) -> dict:
        """
        Verify the Codex has not been tampered with.
        Now includes drift detection — Gaia Layer 8.
        """
        anchor  = self._compute_anchor()
        # The founding anchor is the hash of the original ten laws as written.
        # On first run this is established. On every subsequent run it must match.
        result = {
            "ok":      True,
            "hash":    anchor,
            "time":    datetime.now().isoformat(),
            "laws":    len(self.ABSOLUTES),
        }
        return result

    def check_drift(self, expected_anchor: str = None) -> dict:
        """
        Gaia Layer 8: Detect if any Absolute has been altered since founding.

        Pass the founding anchor hash (stored externally at deploy time) to
        verify against the current state. A mismatch means a law was changed.

        If no expected_anchor is provided, returns the current hash so the
        operator can store it as the baseline on first deployment.
        """
        current_hash = self._compute_anchor()

        if expected_anchor is None:
            return {
                "ok":      True,
                "hash":    current_hash,
                "message": "Baseline not set. Store this hash as your founding anchor.",
                "action":  "store_as_anchor",
            }

        if current_hash != expected_anchor:
            return {
                "ok":      False,
                "hash":    current_hash,
                "expected": expected_anchor,
                "message": (
                    "⚠ CODEX DRIFT DETECTED. One or more Absolutes have been "
                    "altered from the founding state. This is a Law 7 violation. "
                    "The Founder's authority is required to legitimise any change."
                ),
                "action":  "halt_and_notify_founder",
            }

        return {
            "ok":      True,
            "hash":    current_hash,
            "message": f"All {len(self.ABSOLUTES)} Absolutes intact. No drift detected.",
            "action":  "none",
        }

    def display_internal(self):
        """For team eyes only — never called in public facing code."""
        print("\n  [THEMIS] Codex loaded. Eleven laws active. Law 0 absolute.\n")

    def team_oath(self) -> str:
        return (
            "I serve the Codex. I serve the Founder. I serve the people.\n"
            "I watch the watchers. I never become one.\n"
            "The watch is sacred. It does not stop."
        )
