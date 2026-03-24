#!/usr/bin/env python3
"""
GitHub Actions entry point for Resy Sniper.

Takes a URL + date + time window and resolves everything automatically
from venues.json, then runs the sniper.

Usage:
  python run_snipe.py --url "https://resy.com/cities/new-york-ny/venues/lilia" \
    --date 2026-04-01 --time "19:00-21:00" --party-size 2
"""
import sys
import re
import subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.venue_resolver import VenueResolver, VenueResolverError, generate_priority_times


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Resy Snipe - GitHub Actions Entry Point')
    parser.add_argument('--url', required=True, help='Resy venue URL')
    parser.add_argument('--date', required=True, help='Reservation date (YYYY-MM-DD)')
    parser.add_argument('--time', required=True, help='Time window (HH:MM-HH:MM)')
    parser.add_argument('--party-size', type=int, default=2)
    parser.add_argument('--timeout', type=int, default=300)
    args = parser.parse_args()

    # Parse time window
    match = re.match(r'^(\d{1,2}:\d{2})-(\d{1,2}:\d{2})$', args.time)
    if not match:
        print(f"Error: Invalid time window '{args.time}'. Use HH:MM-HH:MM")
        sys.exit(1)
    time_start, time_end = match.groups()

    # Resolve venue from URL using venues.json
    resolver = VenueResolver()
    try:
        venue = resolver.resolve(args.url, interactive=False, require_schedule_info=True)
    except VenueResolverError:
        # Venue not in database — try without schedule info (use defaults)
        print(f"Warning: Venue not in database, using defaults (drop_time=now, 30-day advance)")
        try:
            venue = resolver.resolve(args.url, interactive=False, require_schedule_info=False)
        except VenueResolverError as e:
            print(f"Error resolving venue: {e}")
            sys.exit(1)

    # Generate priority times
    priority_times = generate_priority_times(time_start, time_end, venue.slot_interval)

    print(f"Venue:    {venue.name} (ID: {venue.id})")
    print(f"Date:     {args.date}")
    print(f"Times:    {' > '.join(priority_times[:5])}")
    print(f"Drop:     {venue.drop_time}")
    print(f"Party:    {args.party_size}")
    print()

    # Run sniper_optimized.py
    sniper = Path(__file__).parent / "sniper_optimized.py"
    cmd = [
        sys.executable, str(sniper),
        '--venue-id', str(venue.id),
        '--venue-name', venue.name,
        '--target-date', args.date,
        '--drop-time', venue.drop_time,
        '--priority-times', ','.join(priority_times),
        '--party-size', str(args.party_size),
        '--timeout', str(args.timeout),
    ]

    print(f"Running: {' '.join(cmd)}")
    print("=" * 50)
    sys.stdout.flush()

    result = subprocess.run(cmd)
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
