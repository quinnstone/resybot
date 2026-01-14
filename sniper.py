#!/usr/bin/env python3
"""
Resy Reservation Sniper

Automatically snipes reservations when they become available.

Usage:
    # Run from scheduled job (cron)
    python sniper.py --job-id 1

    # Run manually with parameters
    python sniper.py --venue-id 2492 --target-date 2026-02-14 --priority-times "19:00,19:30,20:00"
"""
import sys
import time
import argparse
from datetime import datetime, timedelta
from typing import Optional
from src.api import ResyAPI, ResyAPIError
from src.config import Config

# ============================================================
# DEFAULT CONFIGURATION (can be overridden via CLI)
# ============================================================
DEFAULTS = {
    'venue_id': Config.HORSEMEN_VENUE_ID,
    'venue_name': "Restaurant",
    'target_date': "2026-02-11",
    'target_time': "19:00",
    'priority_times': None,
    'party_size': 2,
    'login_time': "06:56:50",
    'snipe_time': "06:59:50",
    'timeout': 600,
    'check_interval': 0.40,
    'account_name': "Main Account",
}


def parse_args():
    parser = argparse.ArgumentParser(description='Resy Reservation Sniper')

    # Job mode (from scheduler)
    parser.add_argument('--job-id', type=int, default=None,
                        help='Run sniper for a scheduled job ID (loads config from database)')

    # Manual mode parameters
    parser.add_argument('--venue-id', type=int, default=None,
                        help=f"Resy venue ID")
    parser.add_argument('--venue-name', default=DEFAULTS['venue_name'],
                        help=f"Venue name for logging")
    parser.add_argument('--target-date', default=None,
                        help=f"Date to book (YYYY-MM-DD)")
    parser.add_argument('--target-time', default=DEFAULTS['target_time'],
                        help=f"Single time slot to snipe (HH:MM)")
    parser.add_argument('--priority-times', default=None,
                        help='Comma-separated list of times in priority order')
    parser.add_argument('--party-size', type=int, default=DEFAULTS['party_size'],
                        help=f"Party size")
    parser.add_argument('--login-time', default=DEFAULTS['login_time'],
                        help=f"When to login (HH:MM:SS)")
    parser.add_argument('--snipe-time', default=DEFAULTS['snipe_time'],
                        help=f"When to start sniping (HH:MM:SS)")
    parser.add_argument('--timeout', type=int, default=DEFAULTS['timeout'],
                        help=f"Timeout in seconds")
    parser.add_argument('--account-name', default=DEFAULTS['account_name'],
                        help=f"Account name for logging")
    parser.add_argument('--immediate', action='store_true',
                        help='Start sniping immediately without waiting for snipe time')

    return parser.parse_args()


def load_job_config(job_id: int) -> dict:
    """Load sniper configuration from a scheduled job"""
    from src.job_store import JobStore, JobStatus

    store = JobStore()
    job = store.get_job(job_id)

    if not job:
        raise ValueError(f"Job {job_id} not found")

    if job.status not in (JobStatus.PENDING, JobStatus.SCHEDULED):
        raise ValueError(f"Job {job_id} has status {job.status.value}, cannot run")

    # Calculate login time (3 minutes before snipe time)
    snipe_dt = datetime.strptime(job.snipe_time, "%H:%M:%S")
    login_dt = snipe_dt - timedelta(minutes=3)
    login_time = login_dt.strftime("%H:%M:%S")

    return {
        'job_id': job_id,
        'venue_id': job.venue_id,
        'venue_name': job.venue_name,
        'target_date': job.target_date,
        'priority_times': job.priority_times,
        'party_size': job.party_size,
        'login_time': login_time,
        'snipe_time': job.snipe_time,
        'timeout': DEFAULTS['timeout'],
        'account_name': f"Job #{job_id}",
    }


# Parse arguments
args = parse_args()

# Determine configuration source
if args.job_id:
    # Load from scheduled job
    try:
        config = load_job_config(args.job_id)
        JOB_ID = args.job_id
        VENUE_ID = config['venue_id']
        VENUE_NAME = config['venue_name']
        TARGET_DATE = config['target_date']
        PRIORITY_TIMES = config['priority_times']
        PARTY_SIZE = config['party_size']
        LOGIN_TIME = config['login_time']
        SNIPE_TIME = config['snipe_time']
        TIMEOUT_SECONDS = config['timeout']
        ACCOUNT_NAME = config['account_name']
    except Exception as e:
        print(f"Error loading job {args.job_id}: {e}")
        sys.exit(1)
else:
    # Manual mode
    JOB_ID = None
    VENUE_ID = args.venue_id or DEFAULTS['venue_id']
    VENUE_NAME = args.venue_name
    TARGET_DATE = args.target_date or DEFAULTS['target_date']
    PARTY_SIZE = args.party_size
    LOGIN_TIME = args.login_time
    SNIPE_TIME = args.snipe_time
    TIMEOUT_SECONDS = args.timeout
    ACCOUNT_NAME = args.account_name

    # Build priority list
    if args.priority_times:
        PRIORITY_TIMES = [t.strip() for t in args.priority_times.split(',')]
    else:
        PRIORITY_TIMES = [args.target_time]

CHECK_INTERVAL = DEFAULTS['check_interval']
IMMEDIATE_MODE = args.immediate


def wait_until(target_time_str: str):
    """Wait until a specific time today (HH:MM:SS format)"""
    now = datetime.now()
    target = datetime.strptime(target_time_str, "%H:%M:%S").replace(
        year=now.year, month=now.month, day=now.day
    )
    
    if target <= now:
        print(f"   Target time {target_time_str} already passed, starting immediately")
        return
    
    wait_seconds = (target - now).total_seconds()
    print(f"   Waiting {wait_seconds:.1f} seconds until {target_time_str}...")
    
    # Coarse wait (sleep in 1-second intervals)
    while datetime.now() < target - timedelta(seconds=0.1):
        remaining = (target - datetime.now()).total_seconds()
        if remaining > 10:
            print(f"   {remaining:.0f}s remaining...", end='\r')
        time.sleep(0.5)
    
    # Fine wait (busy loop for precision)
    while datetime.now() < target:
        pass
    
    print(f"\n   GO TIME! {datetime.now().strftime('%H:%M:%S.%f')}")


def find_target_slot(api: ResyAPI, venue_id: int, date: str, priority_times: list, party_size: int):
    """
    Find the best available slot from priority list.
    Returns (slot, config_id, matched_time, all_slots, error_type) 
    
    error_type can be: None (success), "rate_limit" (429), or "error" (other)
    """
    try:
        slots = api.find_slots(venue_id, date, party_size)
        
        # Check each priority time in order
        for target_time in priority_times:
            for slot in slots:
                slot_time = slot.get("date", {}).get("start", "")
                if target_time in slot_time:
                    config_id = slot["config"]["token"]
                    return slot, config_id, target_time, slots, None
        
        return None, None, None, slots, None
    except ResyAPIError as e:
        error_str = str(e)
        if "429" in error_str or "Rate Limit" in error_str:
            return None, None, None, [], "rate_limit"
        print(f"   API error: {e}")
        return None, None, None, [], "error"


def update_job_status(status, result=None):
    """Update job status in database if running in job mode"""
    if JOB_ID:
        try:
            from src.job_store import JobStore, JobStatus
            store = JobStore()
            store.update_status(JOB_ID, status, result)
        except Exception as e:
            print(f"Warning: Failed to update job status: {e}")


def send_notification(success: bool, result: str):
    """Send SMS notification if configured"""
    if JOB_ID:
        try:
            from src.job_store import JobStore
            from src.notifier import notify_result
            store = JobStore()
            job = store.get_job(JOB_ID)
            if job:
                notify_result(job, success, result)
        except Exception as e:
            print(f"Warning: Failed to send notification: {e}")


def main():
    print("=" * 60)
    print(f"RESY SNIPER - {ACCOUNT_NAME}")
    print("=" * 60)
    if JOB_ID:
        print(f"   Job ID:      {JOB_ID}")
    print(f"   Venue:       {VENUE_NAME} (ID: {VENUE_ID})")
    print(f"   Date:        {TARGET_DATE}")
    print(f"   Priority:    {' > '.join(PRIORITY_TIMES)}")
    print(f"   Party Size:  {PARTY_SIZE}")
    if not IMMEDIATE_MODE:
        print(f"   Login Time:  {LOGIN_TIME}")
        print(f"   Snipe Time:  {SNIPE_TIME}")
    else:
        print(f"   Mode:        IMMEDIATE")
    print(f"   Timeout:     {TIMEOUT_SECONDS}s")
    print("=" * 60)
    print()

    # Update job status to running
    if JOB_ID:
        from src.job_store import JobStatus
        update_job_status(JobStatus.RUNNING)

    try:
        api = ResyAPI()

        # Step 1: Wait until login time (skip if immediate mode)
        if IMMEDIATE_MODE:
            print("[1] Immediate mode - skipping wait")
        else:
            print(f"[1] Waiting until {LOGIN_TIME} to login...")
            wait_until(LOGIN_TIME)
        
        # Step 2: Login
        print("\n[2] Logging in...")
        api.login()
        print("    Logged in!")
        
        # Step 3: Pre-fetch payment method
        print("\n[3] Getting payment method...")
        payment_method_id = api.get_default_payment_method_id()
        if payment_method_id:
            methods = api.get_payment_methods()
            for m in methods:
                if m['id'] == payment_method_id:
                    print(f"    Ready: {m['type'].upper()} ending in {m['display']}")
        
        # Step 4: Wait until snipe time (skip if immediate mode)
        if IMMEDIATE_MODE:
            print("\n[4] Immediate mode - starting snipe now")
        else:
            print(f"\n[4] Waiting until {SNIPE_TIME} to start sniping...")
            wait_until(SNIPE_TIME)
        
        # Step 5: SNIPE!
        print("\n[5] SNIPING MODE ACTIVATED!")
        print(f"    Priority list: {' > '.join(PRIORITY_TIMES)}")
        print(f"    Checking every {CHECK_INTERVAL*1000:.0f}ms")
        print()
        print("    RECON LOG (timestamp | slots | times)")
        print("    " + "-" * 50)
        
        start_time = time.time()
        attempts = 0
        first_sighting = False
        rate_limit_count = 0
        
        while True:
            attempts += 1
            elapsed = time.time() - start_time
            timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
            
            # Timeout check
            if elapsed > TIMEOUT_SECONDS:
                error_msg = f"Timeout after {TIMEOUT_SECONDS}s ({attempts} attempts)"
                print(f"\n[X] TIMEOUT after {TIMEOUT_SECONDS}s ({attempts} attempts)")
                print(f"    Could not find any of: {', '.join(PRIORITY_TIMES)}")
                if JOB_ID:
                    from src.job_store import JobStatus
                    update_job_status(JobStatus.FAILED, error_msg)
                    send_notification(False, error_msg)
                sys.exit(1)
            
            # Try to find a slot from priority list
            slot, config_id, matched_time, all_slots, error_type = find_target_slot(api, VENUE_ID, TARGET_DATE, PRIORITY_TIMES, PARTY_SIZE)
            
            # Handle rate limiting with backoff
            if error_type == "rate_limit":
                rate_limit_count += 1
                print(f"    {timestamp} | RATE LIMITED (429) - backing off 2s... (#{rate_limit_count})")
                sys.stdout.flush()
                time.sleep(2)  # Back off for 2 seconds
                continue
            
            # Enhanced discovery logging
            slot_count = len(all_slots)
            if slot_count > 0:
                slot_times = [s.get("date", {}).get("start", "?")[-5:] for s in all_slots[:8]]
                times_str = ",".join(slot_times)
                if len(all_slots) > 8:
                    times_str += f"...+{len(all_slots)-8}"
                
                if not first_sighting:
                    first_sighting = True
                    print(f"    {timestamp} | slots={slot_count:2d} | FIRST SIGHTING! {times_str}")
                else:
                    print(f"    {timestamp} | slots={slot_count:2d} | {times_str}")
            else:
                # Only log every 5th zero-slot result to reduce noise
                if attempts % 5 == 1:
                    print(f"    {timestamp} | slots=0  | --")
            sys.stdout.flush()
            
            if slot:
                print(f"\n\n[!] SLOT FOUND after {attempts} attempts ({elapsed:.1f}s)!")
                print(f"    Matched: {matched_time} (priority #{PRIORITY_TIMES.index(matched_time) + 1})")
                print(f"    Time: {slot['date']['start']}")
                
                # Get booking details
                print("\n[6] Getting booking details...")
                details = api.get_booking_details(config_id, TARGET_DATE, PARTY_SIZE)
                book_token = details["book_token"]
                print(f"    Got book_token")
                print(f"    Payment required: {details.get('payment_required', False)}")
                
                # BOOK IT!
                print("\n[7] BOOKING NOW!")
                confirmation = api.book(book_token, payment_method_id=payment_method_id)
                
                reservation_id = confirmation.get('reservation_id')
                print()
                print("=" * 60)
                print("RESERVATION CONFIRMED!")
                print("=" * 60)
                print(f"    Venue:          {VENUE_NAME}")
                print(f"    Date:           {TARGET_DATE}")
                print(f"    Time:           {slot['date']['start']}")
                print(f"    Reservation ID: {reservation_id}")
                print("=" * 60)
                print()
                print(f"Sniped in {elapsed:.2f}s after {attempts} attempts!")

                # Update job status and send notification
                if JOB_ID:
                    from src.job_store import JobStatus
                    update_job_status(JobStatus.SUCCESS, str(reservation_id))
                    send_notification(True, str(reservation_id))

                sys.exit(0)
            
            # Wait before next attempt
            time.sleep(CHECK_INTERVAL)
    
    except ResyAPIError as e:
        error_msg = f"API Error: {e}"
        print(f"\n[X] {error_msg}")
        if JOB_ID:
            from src.job_store import JobStatus
            update_job_status(JobStatus.FAILED, error_msg)
            send_notification(False, error_msg)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n\n[X] Interrupted by user")
        if JOB_ID:
            from src.job_store import JobStatus
            update_job_status(JobStatus.FAILED, "Interrupted by user")
        sys.exit(1)
    except Exception as e:
        error_msg = f"Unexpected error: {e}"
        print(f"\n[X] {error_msg}")
        if JOB_ID:
            from src.job_store import JobStatus
            update_job_status(JobStatus.FAILED, error_msg)
            send_notification(False, error_msg)
        raise


if __name__ == "__main__":
    main()
