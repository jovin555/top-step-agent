"""
TopStep Signal Bot — entry point.
Runs the signal scanner on a fixed interval.

Usage:
    python main.py              # scan every 15 minutes (default)
    python main.py 5            # scan every 5 minutes
"""
import sys
import time
from datetime import datetime, timezone

INTERVAL_MINUTES = int(sys.argv[1]) if len(sys.argv) > 1 else 15


def tick():
    print(f"\n[{datetime.now(timezone.utc).strftime('%H:%M:%S')} UTC] Running signal scan...")
    from bot.scanner import run
    try:
        run()
    except Exception as e:
        print(f"Scanner error: {e}")


if __name__ == "__main__":
    print(f"TopStep Signal Bot started — scanning every {INTERVAL_MINUTES} minutes.")
    print("Press Ctrl+C to stop.\n")
    tick()
    while True:
        time.sleep(INTERVAL_MINUTES * 60)
        tick()
