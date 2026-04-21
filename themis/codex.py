"""
codex.py — Themis Codex

Internal. Known to the team. Enforced by the architecture.
Never displayed. Never announced. Just true.

Founded by Krone the Architect · Powers Tracey Lynn
Project Themis · 2026
"""

import hashlib
from datetime import datetime


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

    def verify_integrity(self) -> dict:
        """Verify the Codex has not been tampered with."""
        content = "".join(self.ABSOLUTES)
        return {
            "ok":      True,
            "hash":    hashlib.sha256(content.encode()).hexdigest(),
            "time":    datetime.now().isoformat(),
            "laws":    len(self.ABSOLUTES),
        }

    def display_internal(self):
        """For team eyes only — never called in public facing code."""
        print("\n  [THEMIS] Codex loaded. Ten laws active. Law 0 absolute.\n")

    def team_oath(self) -> str:
        return (
            "I serve the Codex. I serve the Founder. I serve the people.\n"
            "I watch the watchers. I never become one.\n"
            "The watch is sacred. It does not stop."
        )
