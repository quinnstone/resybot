#!/usr/bin/env python3
"""
Resy Snipe Scheduler - Interactive Setup

Usage:
  python3 schedule.py          - Schedule a new snipe
  python3 schedule.py list     - View scheduled snipes
  python3 schedule.py clear    - Remove all scheduled snipes
"""
import subprocess
import requests
import re
import sys

API_KEY = "VbWk7s3L4KiK5fzlO7JD3Q5EYolJI7n5"
KEEPALIVE_MARKER = "# RESY_KEEPALIVE"


def ensure_keepalive():
    """Ensure keep-alive cron job exists to prevent VM from going idle"""
    result = subprocess.run(['crontab', '-l'], capture_output=True, text=True)
    current = result.stdout if result.returncode == 0 else ""

    if KEEPALIVE_MARKER in current:
        return  # Already exists

    # Add keep-alive that runs every 10 minutes
    keepalive_line = f"*/10 * * * * /bin/true {KEEPALIVE_MARKER}"

    if current.strip():
        new_crontab = current.strip() + "\n" + keepalive_line
    else:
        new_crontab = keepalive_line

    subprocess.run(f"echo '{new_crontab}' | crontab -", shell=True)

def get_venue_info(url):
    """Extract venue info from Resy URL"""
    match = re.search(r'/venues/([^/?]+)', url)
    if not match:
        return None, None, None
    slug = match.group(1)

    match = re.search(r'/cities/([^/]+)/', url)
    location = match.group(1) if match else "new-york-ny"

    try:
        r = requests.get('https://api.resy.com/3/venue',
            params={'url_slug': slug, 'location': location},
            headers={'Authorization': f'ResyAPI api_key="{API_KEY}"'},
            timeout=10)
        d = r.json()
        return d.get('id', {}).get('resy'), d.get('name'), slug
    except:
        return None, None, slug

def generate_times(start, end, interval=15):
    """Generate time slots between start and end"""
    times = []
    sh, sm = map(int, start.split(':'))
    eh, em = map(int, end.split(':'))
    current = sh * 60 + sm
    end_min = eh * 60 + em
    while current <= end_min:
        times.append(f"{current // 60:02d}:{current % 60:02d}")
        current += interval
    return times

def parse_cron_jobs(include_past=False):
    """Parse cron jobs into readable format"""
    from datetime import datetime

    result = subprocess.run(['crontab', '-l'], capture_output=True, text=True)
    if result.returncode != 0 or not result.stdout.strip():
        return []

    now = datetime.now()
    jobs = []

    for line in result.stdout.strip().split('\n'):
        if 'sniper' not in line or KEEPALIVE_MARKER in line:
            continue

        # Extract venue name
        venue_match = re.search(r'--venue-name "([^"]+)"', line)
        venue = venue_match.group(1) if venue_match else "Unknown"

        # Extract target date
        date_match = re.search(r'--target-date (\S+)', line)
        target_date = date_match.group(1) if date_match else "Unknown"

        # Extract time window from priority times
        times_match = re.search(r'--priority-times "([^"]+)"', line)
        if times_match:
            times = times_match.group(1).split(',')
            time_window = f"{times[0]}-{times[-1]}"
        else:
            time_window = "Unknown"

        # Extract party size
        party_match = re.search(r'--party-size (\d+)', line)
        party_size = party_match.group(1) if party_match else "2"

        # Extract cron schedule (when it runs)
        cron_parts = line.split()[:5]
        is_past = False
        if len(cron_parts) >= 5:
            minute, hour, day, month = cron_parts[0], cron_parts[1], cron_parts[2], cron_parts[3]
            run_time = f"{month.zfill(2)}/{day.zfill(2)} at {hour.zfill(2)}:{minute.zfill(2)}"

            # Check if this job is in the past
            try:
                job_datetime = datetime(now.year, int(month), int(day), int(hour), int(minute))
                is_past = job_datetime < now
            except:
                is_past = False
        else:
            run_time = "Unknown"

        if not is_past or include_past:
            jobs.append({
                'venue': venue,
                'target_date': target_date,
                'time_window': time_window,
                'party_size': party_size,
                'run_time': run_time,
                'raw': line,
                'is_past': is_past
            })

    return jobs


def cleanup_past_jobs():
    """Remove past jobs from crontab"""
    result = subprocess.run(['crontab', '-l'], capture_output=True, text=True)
    if result.returncode != 0 or not result.stdout.strip():
        return

    jobs = parse_cron_jobs(include_past=False)
    future_lines = [job['raw'] for job in jobs]

    # Also keep non-sniper cron jobs and keep-alive
    for line in result.stdout.strip().split('\n'):
        if ('sniper' not in line or KEEPALIVE_MARKER in line) and line.strip():
            future_lines.append(line)

    if future_lines:
        new_crontab = '\n'.join(future_lines)
        subprocess.run(f"echo '{new_crontab}' | crontab -", shell=True)
    else:
        subprocess.run(['crontab', '-r'], capture_output=True)

def show_scheduled_jobs():
    """Display scheduled snipes in a clean format"""
    # Auto-cleanup past jobs
    cleanup_past_jobs()

    jobs = parse_cron_jobs()

    print()
    print("=" * 60)
    print("  SCHEDULED SNIPES")
    print("=" * 60)

    if not jobs:
        print("\n  No snipes scheduled.\n")
        return

    print()
    print(f"  {'#':<3} {'VENUE':<20} {'DATE':<12} {'TIME':<13} {'RUNS':<15}")
    print(f"  {'-'*3} {'-'*20} {'-'*12} {'-'*13} {'-'*15}")

    for i, job in enumerate(jobs, 1):
        venue = job['venue'][:18] + '..' if len(job['venue']) > 20 else job['venue']
        print(f"  {i:<3} {venue:<20} {job['target_date']:<12} {job['time_window']:<13} {job['run_time']:<15}")

    print()

def clear_jobs():
    """Remove all scheduled snipes"""
    jobs = parse_cron_jobs()
    if not jobs:
        print("\nNo snipes to clear.\n")
        return

    show_scheduled_jobs()
    confirm = input("Remove all scheduled snipes? (y/n): ").strip().lower()
    if confirm == 'y':
        subprocess.run(['crontab', '-r'], capture_output=True)
        print("\nAll snipes cleared.\n")
    else:
        print("\nCancelled.\n")

def schedule_new():
    """Schedule a new snipe interactively"""
    print()
    print("=" * 60)
    print("  NEW SNIPE")
    print("=" * 60)
    print()

    # Get Resy URL
    url = input("  Resy URL: ").strip()
    if not url:
        print("  Error: URL required")
        sys.exit(1)

    print("\n  Looking up venue...")
    venue_id, venue_name, slug = get_venue_info(url)

    if not venue_id:
        print(f"  Could not find venue ID automatically.")
        venue_id = input("  Enter venue ID manually: ").strip()
        venue_name = input("  Enter venue name: ").strip()
    else:
        print(f"  Found: {venue_name} (ID: {venue_id})")

    print()
    target_date = input("  Reservation date (YYYY-MM-DD): ").strip()

    print()
    drop_date = input("  Drop date (YYYY-MM-DD): ").strip()
    drop_time = input("  Drop time (HH:MM): ").strip()

    print()
    time_start = input("  Time window start (HH:MM): ").strip()
    time_end = input("  Time window end (HH:MM): ").strip()

    party_size = input("  Party size [2]: ").strip() or "2"

    # Generate priority times
    times = generate_times(time_start, time_end)
    priority_times = ",".join(times)

    # Calculate cron time (1 min before drop for memory efficiency)
    year, month, day = drop_date.split('-')
    hour, minute = drop_time.split(':')
    cron_min = int(minute) - 1
    cron_hour = int(hour)
    if cron_min < 0:
        cron_min += 60
        cron_hour -= 1

    # Build cron command (uses optimized sniper)
    cmd = f'cd /home/opc/resy-sniper && /usr/bin/python3 sniper_optimized.py --venue-id {venue_id} --venue-name "{venue_name}" --target-date {target_date} --priority-times "{priority_times}" --party-size {party_size} >> /home/opc/resy-sniper/snipe.log 2>&1'
    cron_line = f'{cron_min} {cron_hour} {int(day)} {int(month)} * {cmd}'

    # Show summary
    print()
    print("-" * 60)
    print(f"  Venue:        {venue_name}")
    print(f"  Date:         {target_date}")
    print(f"  Time:         {time_start} - {time_end}")
    print(f"  Party:        {party_size}")
    print(f"  Snipe runs:   {drop_date} at {cron_hour:02d}:{cron_min:02d}")
    print("-" * 60)

    confirm = input("\n  Schedule this snipe? (y/n): ").strip().lower()
    if confirm != 'y':
        print("  Cancelled.\n")
        sys.exit(0)

    # Check for existing cron jobs
    result = subprocess.run(['crontab', '-l'], capture_output=True, text=True)
    existing = result.stdout.strip() if result.returncode == 0 else ""

    # Add new cron job
    if existing:
        new_crontab = existing + "\n" + cron_line
    else:
        new_crontab = cron_line

    subprocess.run(f'echo \'{new_crontab}\' | crontab -', shell=True)

    # Ensure keep-alive is active
    ensure_keepalive()

    print("\n  Snipe scheduled!")
    show_scheduled_jobs()

def main():
    if len(sys.argv) > 1:
        cmd = sys.argv[1].lower()
        if cmd == 'list':
            show_scheduled_jobs()
        elif cmd == 'clear':
            clear_jobs()
        elif cmd == 'help':
            print(__doc__)
        else:
            print(f"Unknown command: {cmd}")
            print("Use: list, clear, or no argument to schedule")
    else:
        schedule_new()

if __name__ == "__main__":
    main()
