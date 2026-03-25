#!/usr/bin/env python3
"""
GitHub Actions entry point for Resy Sniper.

Takes explicit inputs for everything needed to snipe a reservation.
No dependency on venues.json — venue ID is resolved from the URL via Resy API.

Usage:
  python run_snipe.py \
    --url "https://resy.com/cities/new-york-ny/venues/lilia" \
    --date 2026-04-24 --time "19:00-21:00" \
    --drop-date 2026-03-25 --drop-time "09:00" \
    --party-size 2
"""
import json
import os
import sys
import re
import subprocess
from datetime import datetime
from pathlib import Path


def generate_priority_times(start_time: str, end_time: str, interval: int = 15) -> list[str]:
    """Generate list of times from start to end at given interval (default 15 min)."""
    def to_minutes(t):
        h, m = map(int, t.split(':'))
        return h * 60 + m

    def to_time(mins):
        return f"{mins // 60:02d}:{mins % 60:02d}"

    times = []
    current = to_minutes(start_time)
    end = to_minutes(end_time)
    while current <= end:
        times.append(to_time(current))
        current += interval
    return times


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Resy Snipe - GitHub Actions Entry Point')
    parser.add_argument('--url', required=True, help='Resy venue URL')
    parser.add_argument('--date', required=True, help='Reservation date (YYYY-MM-DD)')
    parser.add_argument('--time', required=True, help='Time window (HH:MM-HH:MM)')
    parser.add_argument('--drop-date', required=True, help='Date reservations drop (YYYY-MM-DD)')
    parser.add_argument('--drop-time', required=True, help='Time reservations drop (HH:MM)')
    parser.add_argument('--party-size', type=int, default=2)
    parser.add_argument('--timeout', type=int, default=300)
    args = parser.parse_args()

    # Parse time window
    match = re.match(r'^(\d{1,2}:\d{2})-(\d{1,2}:\d{2})$', args.time)
    if not match:
        print(f"Error: Invalid time window '{args.time}'. Use HH:MM-HH:MM")
        sys.exit(1)
    time_start, time_end = match.groups()

    # Generate priority times at 15-minute intervals
    priority_times = generate_priority_times(time_start, time_end)

    print(f"URL:        {args.url}")
    print(f"Date:       {args.date}")
    print(f"Times:      {' > '.join(priority_times[:6])}", end="")
    if len(priority_times) > 6:
        print(f" (+{len(priority_times) - 6} more)")
    else:
        print()
    print(f"Drop:       {args.drop_date} at {args.drop_time}")
    print(f"Party:      {args.party_size}")
    print()

    # Check timing
    drop_dt = datetime.strptime(f"{args.drop_date} {args.drop_time}", "%Y-%m-%d %H:%M")
    wait_seconds = (drop_dt - datetime.now()).total_seconds()
    if wait_seconds > 5.5 * 3600:
        print(f"Drop is {wait_seconds/3600:.1f} hours away — scheduling for later.")
        _save_to_schedule(args)
        print(f"Saved to snipes.json. The scheduler will auto-trigger ~30 min before drop.")
        sys.exit(0)
    elif wait_seconds > 0:
        print(f"Drop in {wait_seconds/60:.0f} minutes.")
    else:
        print(f"Drop time passed — sniping immediately.")
    print()

    # Run sniper_optimized.py — it resolves the venue ID from the URL itself
    sniper = Path(__file__).parent / "sniper_optimized.py"
    cmd = [
        sys.executable, str(sniper),
        '--venue-url', args.url,
        '--target-date', args.date,
        '--drop-time', args.drop_time,
        '--drop-date', args.drop_date,
        '--priority-times', ','.join(priority_times),
        '--party-size', str(args.party_size),
        '--timeout', str(args.timeout),
    ]

    print(f"Running: {' '.join(cmd)}")
    print("=" * 50)
    sys.stdout.flush()

    result = subprocess.run(cmd)
    sys.exit(result.returncode)


def _save_to_schedule(args):
    """Save a snipe to snipes.json for the cron scheduler to pick up later."""
    snipes_file = Path(__file__).parent / "snipes.json"

    if snipes_file.exists():
        snipes = json.loads(snipes_file.read_text())
    else:
        snipes = []

    # Check for duplicate
    for s in snipes:
        if (s.get("venue_url") == args.url
                and s.get("drop_date") == args.drop_date
                and s.get("reservation_date") == args.date
                and s.get("status") == "pending"):
            print(f"Already scheduled — skipping duplicate.")
            return

    snipes.append({
        "venue_url": args.url,
        "reservation_date": args.date,
        "time_window": args.time,
        "drop_date": args.drop_date,
        "drop_time": args.drop_time,
        "party_size": args.party_size,
        "timezone": os.environ.get("TZ", "America/New_York"),
        "status": "pending",
    })

    snipes_file.write_text(json.dumps(snipes, indent=2) + "\n")

    # Commit and push so the cron picks it up
    subprocess.run(["git", "config", "user.name", "Resy Scheduler"], capture_output=True)
    subprocess.run(["git", "config", "user.email", "scheduler@resy-sniper"], capture_output=True)
    subprocess.run(["git", "add", str(snipes_file)], capture_output=True)
    subprocess.run(["git", "commit", "-m", "Schedule snipe [skip ci]"], capture_output=True)
    subprocess.run(["git", "push"], capture_output=True)


if __name__ == "__main__":
    main()
