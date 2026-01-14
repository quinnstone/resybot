#!/usr/bin/env python3
"""
Interactive Snipe Tool

Run this to either:
- Test a snipe immediately (if slots are already released)
- Schedule a cron job for a future release
"""
import sys
import subprocess
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent))

from src.venue_resolver import VenueResolver, VenueResolverError, generate_priority_times
from src.job_store import JobStore, Job, JobStatus
from src.scheduler import Scheduler, format_snipe_datetime


def main():
    print()
    print("=" * 60)
    print("  RESY SNIPE TOOL")
    print("=" * 60)
    print()

    # First question: Are slots already available?
    print("Are reservation slots for your target date already available?")
    print()
    print("  1. YES - Slots are available now, run snipe immediately")
    print("  2. NO  - Slots release in the future, schedule a cron job")
    print()
    choice = input("Choice [1]: ").strip() or "1"

    if choice == "1":
        run_immediate_flow()
    else:
        run_scheduled_flow()


def run_immediate_flow():
    """Flow for when slots are already available"""
    print()
    print("-" * 60)
    print("  IMMEDIATE SNIPE MODE")
    print("-" * 60)
    print()

    # Get venue URL
    print("Enter the Resy URL for the restaurant:")
    url = input("URL: ").strip()
    if not url:
        print("No URL provided. Exiting.")
        sys.exit(1)

    # Resolve venue
    print()
    print("Resolving venue...")
    resolver = VenueResolver()
    try:
        venue = resolver.resolve(url, interactive=True, require_schedule_info=False)
    except VenueResolverError as e:
        print(f"Error: {e}")
        sys.exit(1)

    print(f"  Found: {venue.name} (ID: {venue.id})")

    # Get date
    print()
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    date_input = input(f"Target date (YYYY-MM-DD) [{tomorrow}]: ").strip()
    target_date = date_input if date_input else tomorrow

    # Validate date
    try:
        datetime.strptime(target_date, "%Y-%m-%d")
    except ValueError:
        print("Invalid date format. Use YYYY-MM-DD")
        sys.exit(1)

    # Get time window
    print()
    time_window = input("Time window (HH:MM-HH:MM) [19:00-21:00]: ").strip() or "19:00-21:00"
    time_start, time_end = parse_time_window(time_window)

    # Get party size
    print()
    party_input = input("Party size [2]: ").strip()
    party_size = int(party_input) if party_input else 2

    # Generate priority times (15 min increments)
    priority_times = generate_priority_times(time_start, time_end, 15)

    # Confirm and run
    print()
    print("=" * 60)
    print("  READY TO SNIPE")
    print("=" * 60)
    print(f"  Venue:       {venue.name}")
    print(f"  Date:        {target_date}")
    print(f"  Time:        {time_start} - {time_end}")
    print(f"  Party Size:  {party_size}")
    print(f"  Priority:    {' > '.join(priority_times[:5])}")
    print("=" * 60)
    print()
    print("WARNING: This will attempt to make a REAL reservation!")
    print()

    confirm = input("Start snipe now? (y/n): ").strip().lower()
    if confirm != 'y':
        print("Cancelled.")
        sys.exit(0)

    # Run sniper
    print()
    sniper_path = Path(__file__).parent / "sniper.py"
    cmd = [
        sys.executable, str(sniper_path),
        "--venue-id", str(venue.id),
        "--venue-name", venue.name,
        "--target-date", target_date,
        "--priority-times", ",".join(priority_times),
        "--party-size", str(party_size),
        "--immediate"
    ]

    result = subprocess.run(cmd)
    sys.exit(result.returncode)


def run_scheduled_flow():
    """Flow for scheduling a future snipe"""
    print()
    print("-" * 60)
    print("  SCHEDULED SNIPE MODE")
    print("-" * 60)
    print()

    # Get venue URL
    print("Enter the Resy URL for the restaurant:")
    url = input("URL: ").strip()
    if not url:
        print("No URL provided. Exiting.")
        sys.exit(1)

    # Resolve venue
    print()
    print("Resolving venue...")
    resolver = VenueResolver()
    try:
        venue = resolver.resolve(url, interactive=True, require_schedule_info=False)
    except VenueResolverError as e:
        print(f"Error: {e}")
        sys.exit(1)

    print(f"  Found: {venue.name} (ID: {venue.id})")

    # Get target reservation date
    print()
    print("What date do you want to reserve?")
    target_date = input("Target date (YYYY-MM-DD): ").strip()
    try:
        datetime.strptime(target_date, "%Y-%m-%d")
    except ValueError:
        print("Invalid date format. Use YYYY-MM-DD")
        sys.exit(1)

    # Get release date
    print()
    print("When will slots for this date be released?")
    release_date = input("Release date (YYYY-MM-DD): ").strip()
    try:
        release_dt = datetime.strptime(release_date, "%Y-%m-%d")
    except ValueError:
        print("Invalid date format. Use YYYY-MM-DD")
        sys.exit(1)

    # Get release time
    print()
    print("What time will slots be released?")
    print("(Use 24-hour format, e.g., 00:00 for midnight, 09:00 for 9am)")
    release_time = input("Release time (HH:MM) [00:00]: ").strip() or "00:00"
    try:
        h, m = release_time.split(":")
        release_time = f"{int(h):02d}:{int(m):02d}"
        datetime.strptime(release_time, "%H:%M")
    except (ValueError, AttributeError):
        print("Invalid time format. Use HH:MM")
        sys.exit(1)

    # Get time window for reservation
    print()
    print("What time window do you want for the reservation?")
    time_window = input("Time window (HH:MM-HH:MM) [19:00-21:00]: ").strip() or "19:00-21:00"
    time_start, time_end = parse_time_window(time_window)

    # Get party size
    print()
    party_input = input("Party size [2]: ").strip()
    party_size = int(party_input) if party_input else 2

    # Generate priority times (15 min increments)
    priority_times = generate_priority_times(time_start, time_end, 15)

    # Calculate snipe time (10 seconds before release)
    release_full = datetime.strptime(f"{release_date} {release_time}:00", "%Y-%m-%d %H:%M:%S")
    snipe_dt = release_full - timedelta(seconds=10)
    snipe_date = snipe_dt.strftime("%Y-%m-%d")
    snipe_time = snipe_dt.strftime("%H:%M:%S")

    # Check if snipe time is in the past
    if snipe_dt < datetime.now():
        print()
        print(f"ERROR: Release time {release_date} {release_time} is in the past!")
        print("Use immediate mode instead if slots are already available.")
        sys.exit(1)

    time_until = (snipe_dt - datetime.now()).total_seconds()
    hours_until = time_until / 3600

    # Confirm
    print()
    print("=" * 60)
    print("  SNIPE SCHEDULE")
    print("=" * 60)
    print(f"  Venue:          {venue.name}")
    print(f"  Target Date:    {target_date}")
    print(f"  Time Window:    {time_start} - {time_end}")
    print(f"  Party Size:     {party_size}")
    print(f"  Priority:       {' > '.join(priority_times[:5])}")
    print()
    print(f"  Release:        {release_date} at {release_time}")
    print(f"  Snipe At:       {snipe_date} at {snipe_time} ({hours_until:.1f} hours from now)")
    print("=" * 60)
    print()
    print("WARNING: Your computer must be ON at the scheduled time!")
    print()

    confirm = input("Schedule this snipe? (y/n): ").strip().lower()
    if confirm != 'y':
        print("Cancelled.")
        sys.exit(0)

    # Create job
    job = Job(
        id=None,
        venue_id=venue.id,
        venue_name=venue.name,
        venue_slug=venue.slug,
        target_date=target_date,
        time_start=time_start,
        time_end=time_end,
        party_size=party_size,
        priority_times=priority_times,
        snipe_date=snipe_date,
        snipe_time=snipe_time,
        timezone="America/New_York",
        status=JobStatus.PENDING,
        created_at=datetime.now().isoformat()
    )

    # Save to database
    store = JobStore()
    job_id = store.add_job(job)
    job.id = job_id

    print()
    print(f"  Job created with ID: {job_id}")

    # Schedule cron job
    scheduler = Scheduler()
    try:
        scheduler.schedule_job(job)
        print(f"  Cron job scheduled!")
    except Exception as e:
        print(f"  Warning: Could not create cron job: {e}")
        print(f"  You can run manually: python resy.py run {job_id}")

    print()
    print("=" * 60)
    print("  SNIPE SCHEDULED!")
    print("=" * 60)
    print(f"  Job ID:       {job_id}")
    print(f"  Venue:        {venue.name}")
    print(f"  Target Date:  {target_date}")
    print(f"  Snipe At:     {snipe_date} at {snipe_time}")
    print()
    print("  IMPORTANT: Your computer must be running at the snipe time!")
    print()
    print(f"  To view jobs:    python resy.py list")
    print(f"  To cancel:       python resy.py cancel {job_id}")
    print("=" * 60)
    print()


def parse_time_window(time_window: str) -> tuple[str, str]:
    """Parse and validate time window string"""
    try:
        time_start, time_end = time_window.split("-")
        time_start = time_start.strip()
        time_end = time_end.strip()
        # Normalize to HH:MM
        h, m = time_start.split(":")
        time_start = f"{int(h):02d}:{m}"
        h, m = time_end.split(":")
        time_end = f"{int(h):02d}:{m}"
        return time_start, time_end
    except (ValueError, AttributeError):
        print("Invalid time window format. Use HH:MM-HH:MM")
        sys.exit(1)


if __name__ == "__main__":
    main()
