#!/usr/bin/env python3
"""
Resy Sniper CLI

Schedule and manage reservation snipes.

Usage:
    python resy.py schedule "https://resy.com/cities/new-york-ny/venues/carbone" \\
        --date 2026-02-14 --time "19:00-21:00" --party-size 2

    python resy.py list
    python resy.py cancel 1
    python resy.py venues
"""
import sys
import re
from datetime import datetime
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from src.venue_resolver import VenueResolver, VenueResolverError, generate_priority_times
from src.job_store import JobStore, Job, JobStatus
from src.scheduler import Scheduler, SchedulerError, format_snipe_datetime


def print_header(text: str):
    print()
    print("=" * 60)
    print(f"  {text}")
    print("=" * 60)


def validate_date(date_str: str) -> str:
    """Validate and normalize date string"""
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        if dt.date() < datetime.now().date():
            print(f"Error: Date {date_str} is in the past")
            sys.exit(1)
        return date_str
    except ValueError:
        print(f"Error: Invalid date format '{date_str}'. Use YYYY-MM-DD")
        sys.exit(1)


def validate_time_window(time_str: str) -> tuple[str, str]:
    """Validate and parse time window (HH:MM-HH:MM)"""
    match = re.match(r'^(\d{1,2}:\d{2})-(\d{1,2}:\d{2})$', time_str)
    if not match:
        print(f"Error: Invalid time window '{time_str}'. Use format HH:MM-HH:MM (e.g., 19:00-21:00)")
        sys.exit(1)

    start, end = match.groups()

    # Normalize to HH:MM
    def normalize(t):
        h, m = t.split(':')
        return f"{int(h):02d}:{m}"

    start = normalize(start)
    end = normalize(end)

    # Validate times
    try:
        start_dt = datetime.strptime(start, "%H:%M")
        end_dt = datetime.strptime(end, "%H:%M")
        if start_dt >= end_dt:
            print(f"Error: Start time must be before end time")
            sys.exit(1)
    except ValueError:
        print(f"Error: Invalid time format in '{time_str}'")
        sys.exit(1)

    return start, end


def cmd_schedule(url: str, date: str, time_window: str, party_size: int):
    """Schedule a new reservation snipe"""
    print_header("SCHEDULING RESY SNIPE")

    # Validate inputs
    date = validate_date(date)
    time_start, time_end = validate_time_window(time_window)

    # Resolve venue
    print(f"\nResolving venue from URL...")
    resolver = VenueResolver()
    try:
        venue = resolver.resolve(url, interactive=True)
    except VenueResolverError as e:
        print(f"Error: {e}")
        sys.exit(1)

    print(f"  Venue:        {venue.name}")
    print(f"  Venue ID:     {venue.id}")
    print(f"  Drop Time:    {venue.drop_time} ({venue.timezone})")
    print(f"  Days Advance: {venue.days_advance}")

    # Generate priority times
    priority_times = generate_priority_times(time_start, time_end, venue.slot_interval)
    print(f"\n  Target Date:  {date}")
    print(f"  Time Window:  {time_start} - {time_end}")
    print(f"  Party Size:   {party_size}")
    print(f"  Priority:     {' > '.join(priority_times[:5])}", end="")
    if len(priority_times) > 5:
        print(f" (+{len(priority_times) - 5} more)")
    else:
        print()

    # Calculate snipe datetime
    scheduler = Scheduler()
    snipe_date, snipe_time = scheduler.calculate_snipe_datetime(
        target_date=date,
        days_advance=venue.days_advance,
        drop_time=venue.drop_time,
        timezone=venue.timezone
    )

    snipe_display = format_snipe_datetime(snipe_date, snipe_time, venue.timezone)
    print(f"\n  Snipe Time:   {snipe_display}")

    # Check if snipe date is in the past
    snipe_dt = datetime.strptime(f"{snipe_date} {snipe_time}", "%Y-%m-%d %H:%M:%S")
    if snipe_dt < datetime.now():
        print(f"\n  Warning: Snipe time is in the past!")
        print(f"  The reservation window may have already opened.")
        response = input("\n  Continue anyway? (y/n): ").strip().lower()
        if response != 'y':
            print("  Cancelled.")
            sys.exit(0)

    # Confirm
    print()
    response = input("  Create this snipe job? (y/n): ").strip().lower()
    if response != 'y':
        print("  Cancelled.")
        sys.exit(0)

    # Create job
    job = Job(
        id=None,
        venue_id=venue.id,
        venue_name=venue.name,
        venue_slug=venue.slug,
        target_date=date,
        time_start=time_start,
        time_end=time_end,
        party_size=party_size,
        priority_times=priority_times,
        snipe_date=snipe_date,
        snipe_time=snipe_time,
        timezone=venue.timezone,
        status=JobStatus.PENDING,
        created_at=datetime.now().isoformat()
    )

    store = JobStore()
    job_id = store.add_job(job)
    job.id = job_id

    print(f"\n  Job created with ID: {job_id}")

    # Schedule launchd job
    print(f"  Scheduling launchd job...")
    try:
        scheduler.schedule_job(job)
        print(f"  Cron job scheduled!")
    except SchedulerError as e:
        print(f"  Warning: Could not create launchd job: {e}")
        print(f"  You can run manually: python resy.py run {job_id}")

    print_header("SNIPE SCHEDULED")
    print(f"\n  Job ID:     {job_id}")
    print(f"  Venue:      {venue.name}")
    print(f"  Target:     {date} ({time_start}-{time_end})")
    print(f"  Snipe:      {snipe_display}")
    print(f"\n  Your machine must be running at the snipe time!")
    print()


def cmd_list():
    """List all scheduled snipe jobs"""
    store = JobStore()
    jobs = store.list_jobs()

    print_header("SCHEDULED SNIPES")

    if not jobs:
        print("\n  No snipes scheduled.")
        print("  Use 'python resy.py schedule <url> --date <date> --time <window>' to add one.")
        print()
        return

    print()
    print(f"  {'ID':<4} {'VENUE':<20} {'DATE':<12} {'TIME':<13} {'SNIPE':<20} {'STATUS':<10}")
    print(f"  {'-'*4} {'-'*20} {'-'*12} {'-'*13} {'-'*20} {'-'*10}")

    for job in jobs:
        venue = job.venue_name[:18] + ".." if len(job.venue_name) > 20 else job.venue_name
        time_window = f"{job.time_start}-{job.time_end}"
        snipe = f"{job.snipe_date} {job.snipe_time[:5]}"
        status = job.status.value

        # Color status
        if job.status == JobStatus.SUCCESS:
            status = f"\033[92m{status}\033[0m"  # Green
        elif job.status == JobStatus.FAILED:
            status = f"\033[91m{status}\033[0m"  # Red
        elif job.status == JobStatus.RUNNING:
            status = f"\033[93m{status}\033[0m"  # Yellow

        print(f"  {job.id:<4} {venue:<20} {job.target_date:<12} {time_window:<13} {snipe:<20} {status:<10}")

    print()


def cmd_cancel(job_id: int):
    """Cancel a scheduled snipe job"""
    store = JobStore()
    job = store.get_job(job_id)

    if not job:
        print(f"Error: Job {job_id} not found")
        sys.exit(1)

    if job.status not in (JobStatus.PENDING, JobStatus.SCHEDULED):
        print(f"Error: Job {job_id} cannot be cancelled (status: {job.status.value})")
        sys.exit(1)

    print_header("CANCEL SNIPE")
    print(f"\n  Job ID:  {job_id}")
    print(f"  Venue:   {job.venue_name}")
    print(f"  Date:    {job.target_date}")

    response = input("\n  Cancel this job? (y/n): ").strip().lower()
    if response != 'y':
        print("  Aborted.")
        sys.exit(0)

    # Remove launchd job
    scheduler = Scheduler()
    scheduler.unschedule_job(job_id)

    # Update status
    store.update_status(job_id, JobStatus.CANCELLED)

    print(f"\n  Job {job_id} cancelled.")
    print()


def cmd_run(job_id: int):
    """Run a snipe job (called by launchd or manually)"""
    import subprocess

    store = JobStore()
    job = store.get_job(job_id)

    if not job:
        print(f"Error: Job {job_id} not found")
        sys.exit(1)

    # Run sniper.py with job ID
    sniper_path = Path(__file__).parent / "sniper.py"
    cmd = [sys.executable, str(sniper_path), "--job-id", str(job_id)]

    print(f"Running sniper for job {job_id}...")
    result = subprocess.run(cmd)
    sys.exit(result.returncode)


def cmd_venues():
    """List known venues"""
    resolver = VenueResolver()

    print_header("KNOWN VENUES")
    print()
    print(f"  {'SLUG':<25} {'NAME':<20} {'DROP':<8} {'ADVANCE':<8}")
    print(f"  {'-'*25} {'-'*20} {'-'*8} {'-'*8}")

    for slug, data in sorted(resolver.venues_db.items()):
        name = data['name'][:18] + ".." if len(data['name']) > 20 else data['name']
        print(f"  {slug:<25} {name:<20} {data['drop_time']:<8} {data['days_advance']} days")

    print()
    print("  To add a new venue, schedule a snipe with its URL.")
    print("  You'll be prompted for drop time and days advance.")
    print()


def cmd_test_snipe(job_id: int):
    """Test a snipe job immediately (for debugging)"""
    import subprocess

    store = JobStore()
    job = store.get_job(job_id)

    if not job:
        print(f"Error: Job {job_id} not found")
        sys.exit(1)

    print_header("TEST SNIPE (IMMEDIATE MODE)")
    print(f"\n  This will run the sniper immediately without waiting for snipe time.")
    print(f"  Job ID:  {job_id}")
    print(f"  Venue:   {job.venue_name}")
    print(f"  Date:    {job.target_date}")
    print(f"\n  WARNING: This will attempt to make a REAL reservation!")

    response = input("\n  Continue? (y/n): ").strip().lower()
    if response != 'y':
        print("  Aborted.")
        sys.exit(0)

    # Run sniper.py with job ID and immediate flag
    sniper_path = Path(__file__).parent / "sniper.py"
    cmd = [sys.executable, str(sniper_path), "--job-id", str(job_id), "--immediate"]

    print()
    result = subprocess.run(cmd)
    sys.exit(result.returncode)


def print_usage():
    print("""
Resy Sniper CLI

Usage:
  python resy.py schedule <url> --date <YYYY-MM-DD> --time <HH:MM-HH:MM> [--party-size N]
  python resy.py list
  python resy.py cancel <job_id>
  python resy.py run <job_id>
  python resy.py test <job_id>
  python resy.py venues

Commands:
  schedule    Schedule a new reservation snipe
  list        List all scheduled snipes
  cancel      Cancel a scheduled snipe
  run         Run a snipe job (used by launchd)
  test        Test run a snipe immediately (for debugging)
  venues      List known venues

Examples:
  python resy.py schedule "https://resy.com/cities/new-york-ny/venues/carbone" \\
      --date 2026-02-14 --time "19:00-21:00" --party-size 2

  python resy.py list
  python resy.py cancel 1
""")


def main():
    if len(sys.argv) < 2:
        print_usage()
        sys.exit(0)

    command = sys.argv[1].lower()

    if command == "schedule":
        # Parse schedule arguments
        if len(sys.argv) < 3:
            print("Error: URL required")
            print("Usage: python resy.py schedule <url> --date <date> --time <window>")
            sys.exit(1)

        url = sys.argv[2]
        date = None
        time_window = None
        party_size = 2

        i = 3
        while i < len(sys.argv):
            arg = sys.argv[i]
            if arg in ("--date", "-d"):
                date = sys.argv[i + 1]
                i += 2
            elif arg in ("--time", "-t"):
                time_window = sys.argv[i + 1]
                i += 2
            elif arg in ("--party-size", "-p"):
                party_size = int(sys.argv[i + 1])
                i += 2
            else:
                print(f"Unknown argument: {arg}")
                sys.exit(1)

        if not date:
            print("Error: --date required")
            sys.exit(1)
        if not time_window:
            print("Error: --time required")
            sys.exit(1)

        cmd_schedule(url, date, time_window, party_size)

    elif command == "list":
        cmd_list()

    elif command == "cancel":
        if len(sys.argv) < 3:
            print("Error: Job ID required")
            print("Usage: python resy.py cancel <job_id>")
            sys.exit(1)
        job_id = int(sys.argv[2])
        cmd_cancel(job_id)

    elif command == "run":
        if len(sys.argv) < 3:
            print("Error: Job ID required")
            print("Usage: python resy.py run <job_id>")
            sys.exit(1)
        job_id = int(sys.argv[2])
        cmd_run(job_id)

    elif command == "test":
        if len(sys.argv) < 3:
            print("Error: Job ID required")
            print("Usage: python resy.py test <job_id>")
            sys.exit(1)
        job_id = int(sys.argv[2])
        cmd_test_snipe(job_id)

    elif command == "venues":
        cmd_venues()

    elif command in ("help", "-h", "--help"):
        print_usage()

    else:
        print(f"Unknown command: {command}")
        print_usage()
        sys.exit(1)


if __name__ == "__main__":
    main()
