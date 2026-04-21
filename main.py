#!/usr/bin/env python3
"""
main.py — Project Themis

The watch begins here.

Usage:
    python main.py              # Watch mode — continuous scanning
    python main.py --scan       # Single scan right now
    python main.py --status     # What Themis has found
    python main.py --export     # Export detection log
    python main.py --rights     # Know Your Rights cards
    python main.py --explain TOPIC  # Plain language explainer
    python main.py --watchdog   # Start with auto-restart wrapper

— Krone the Architect · Powers Tracey Lynn
  Project Themis · 2026
  The scales were always supposed to balance.
  Consider them balanced.
"""

import argparse
import signal
import sys

parser = argparse.ArgumentParser(
    description="Project Themis — Watch the watchers."
)
parser.add_argument("--scan",      action="store_true",
                    help="Run a single scan right now")
parser.add_argument("--status",    action="store_true",
                    help="Show detection status")
parser.add_argument("--export",    metavar="FILE",
                    help="Export detection log to file")
parser.add_argument("--rights",    metavar="SITUATION",
                    help="Know Your Rights for situation: drone, camera, imsi")
parser.add_argument("--explain",   metavar="TOPIC",
                    help="Plain language explainer: stingray, palantir, drone, etc.")
parser.add_argument("--watchdog",  action="store_true",
                    help="Start with auto-restart watchdog")
parser.add_argument("--setup",     action="store_true",
                    help="Check Android/Termux setup status")
parser.add_argument("--version",   action="store_true",
                    help="Print version and exit")
parser.add_argument("--verify",    action="store_true",
                    help="Verify audit log integrity")
args = parser.parse_args()

VERSION = "1.0.0"

if args.version:
    print(f"Project Themis v{VERSION}")
    print("The scales were always supposed to balance.")
    sys.exit(0)

# Watchdog mode — wrap with auto-restart
if args.watchdog:
    from themis.resilience import ThemisResilience
    r = ThemisResilience()
    r.watch_and_restart(__file__, sys.argv[1:])
    sys.exit(0)

if args.setup:
    from themis.termux import TermuxAdapter
    adapter = TermuxAdapter()
    adapter.print_setup_status()
    sys.exit(0)

from themis.engine import ThemisEngine

engine = ThemisEngine()

# ── Utility commands ──────────────────────────────────────────────────────────

if args.status:
    status = engine.status()
    print()
    print("  ╔══════════════════════════════════════════════════════════╗")
    print("  ║   T H E M I S   —   Status                             ║")
    print("  ╚══════════════════════════════════════════════════════════╝")
    print()
    for k, v in status.items():
        print(f"  {k:<22} {v}")
    print()
    sys.exit(0)

if args.export:
    success = engine.ledger.export(args.export)
    if success:
        print(f"\n  ✓ Detection log exported to: {args.export}")
        print(f"  This file contains a legally documentable record.")
        print(f"  Cryptographic chain in: themis_audit.log\n")
    else:
        print(f"\n  ✗ Export failed. Check permissions.\n")
    sys.exit(0)

if args.rights:
    card = engine.bridge.rights_card(args.rights)
    print(f"\n  ─── KNOW YOUR RIGHTS: {args.rights.upper()} ───")
    print(f"\n  {card}\n")
    sys.exit(0)

if args.explain:
    explanation = engine.bridge.explain(args.explain)
    print(f"\n  ─── {args.explain.upper()} ───")
    print(f"\n  {explanation}\n")
    sys.exit(0)

if args.verify:
    result = engine.logger.verify_chain()
    print(f"\n  Chain integrity: {'✓ Intact' if result['ok'] else '⚠ Compromised'}")
    print(f"  Entries: {result['entries']}")
    print(f"  {result['message']}\n")
    sys.exit(0)

# ── Graceful shutdown ─────────────────────────────────────────────────────────

def handle_shutdown(signum, frame):
    engine.stop()
    sys.exit(0)

signal.signal(signal.SIGTERM, handle_shutdown)
signal.signal(signal.SIGINT,  handle_shutdown)

# ── Start ─────────────────────────────────────────────────────────────────────

if args.scan:
    engine.start(mode="scan")
else:
    engine.start(mode="watch")
