#!/usr/bin/env python3
"""
Resy Sniper - Optimized for VM stability

Flow:
  1. Clear memory + garbage collect
  2. Load API client
  3. Wait until 30s before drop time
  4. Login + get payment method (fresh token)
  5. Wait for exact drop time
  6. Snipe with 2 parallel requests (doubles throughput)

Usage:
  python3 sniper_optimized.py \
    --venue-url "https://resy.com/cities/ny/torrisi" \
    --target-date 2026-02-26 --drop-time "10:00" \
    --priority-times "19:30,19:45,20:00" --party-size 2

  Or with explicit venue ID:
  python3 sniper_optimized.py \
    --venue-id 64593 --venue-name "Torrisi" \
    --target-date 2026-02-26 --drop-time "10:00" \
    --priority-times "19:30,19:45,20:00" --party-size 2
"""
import sys
import time
import signal
import gc
import argparse
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

# Globals for signal handling
running = True
api = None


def clear_system_memory():
    """Free Python garbage-collected memory"""
    gc.collect()


def signal_handler(signum, frame):
    """Handle shutdown signals gracefully"""
    global running
    print(f"\n[!] Received signal {signum}, shutting down...")
    running = False
    cleanup()
    sys.exit(0)


def cleanup():
    """Clean up resources and clear memory"""
    global api
    if api:
        try:
            api.cleanup()
        except Exception:
            pass
    gc.collect()


def parse_args():
    parser = argparse.ArgumentParser(description='Resy Sniper - Optimized')
    venue_group = parser.add_mutually_exclusive_group(required=True)
    venue_group.add_argument('--venue-url',
                             help='Resy URL (e.g. https://resy.com/cities/ny/torrisi)')
    venue_group.add_argument('--venue-id', type=int,
                             help='Venue ID (use --venue-url instead)')
    parser.add_argument('--venue-name', default=None)
    parser.add_argument('--target-date', required=True)
    parser.add_argument('--priority-times', required=True)
    parser.add_argument('--party-size', type=int, default=2)
    parser.add_argument('--drop-time', required=True,
                        help='When reservations drop (HH:MM)')
    parser.add_argument('--drop-date', default=None,
                        help='Date reservations drop (YYYY-MM-DD). Defaults to today.')
    parser.add_argument('--timeout', type=int, default=300)
    return parser.parse_args()


def wait_until(target, label="target"):
    """Sleep precisely until a target datetime. Returns immediately if past."""
    remaining = (target - datetime.now()).total_seconds()

    if remaining <= 0:
        late_by = abs(remaining)
        print(f"    WARNING: {label} already passed!")
        print(f"    We are {late_by:.0f}s LATE - continuing immediately")
        if late_by > 60:
            print(f"    (Started {late_by/60:.1f} min late - slots may be gone)")
        sys.stdout.flush()
        return

    print(f"    Waiting {remaining:.0f}s until {label}...")
    sys.stdout.flush()

    # Sleep in chunks so we can respond to signals
    while remaining > 10 and running:
        time.sleep(5)
        remaining = (target - datetime.now()).total_seconds()
        if int(remaining) % 30 == 0:
            print(f"    {remaining:.0f}s remaining...")
            sys.stdout.flush()

    # Final precise wait - sleep in small increments
    while remaining > 0.05 and running:
        time.sleep(0.01)
        remaining = (target - datetime.now()).total_seconds()

    sys.stdout.flush()


def find_slot(api, venue_id, date, priority_times, party_size):
    """Find matching slot from priority list.

    Returns: (slot, config_token, matched_time, slot_count, avail_times)
    """
    try:
        slots = api.find_slots(venue_id, date, party_size)

        for target_time in priority_times:
            for slot in slots:
                slot_time = slot.get("date", {}).get("start", "")
                # Match "T19:30" to avoid "9:30" matching "19:30"
                if f"T{target_time}" in slot_time:
                    return slot, slot["config"]["token"], target_time, len(slots), None

        # Return available times for logging if no priority match
        avail_times = []
        for s in slots[:8]:
            start = s.get("date", {}).get("start", "")
            # Extract HH:MM from ISO "2026-02-27T19:30:00"
            if "T" in start:
                avail_times.append(start.split("T")[1][:5])
        return None, None, None, len(slots), avail_times

    except Exception as e:
        error_str = str(e)
        if "429" in error_str:
            return None, None, "RATE_LIMITED", 0, None
        if "500" in error_str:
            return None, None, f"SERVER_500: {error_str[:200]}", 0, None
        if "401" in error_str:
            return None, None, "ERROR: Auth failed (401) - token may be expired", 0, None
        if "403" in error_str:
            return None, None, "ERROR: Forbidden (403) - may be blocked", 0, None
        if "404" in error_str:
            return None, None, "ERROR: Not found (404) - check venue ID", 0, None
        return None, None, f"ERROR: {e}", 0, None


def find_slot_parallel(executor, api, venue_id, date, priority_times, party_size):
    """Fire 2 parallel find_slot requests. Return first successful result.

    Doubles throughput during Resy server overload at drop time.
    If one request gets a 500, the other might get through.
    Uses a shared executor to avoid thread creation/teardown overhead.
    """
    futures = [
        executor.submit(find_slot, api, venue_id, date, priority_times, party_size)
        for _ in range(2)
    ]

    best = None
    for future in as_completed(futures):
        result = future.result()
        slot, config_id, matched, slot_count, avail_times = result

        # If we found a bookable slot, return immediately
        if slot:
            return result

        # Prefer a successful (non-error) result over errors
        if best is None:
            best = result
        elif matched is None and best[2] is not None:
            # This result succeeded (no error), prefer it
            best = result

    return best


def attempt_booking(api, config_id, target_date, party_size, payment_id):
    """Attempt to book a slot. Returns (success, result_or_error)."""
    try:
        details = api.get_booking_details(config_id, target_date, party_size)
        result = api.book(details["book_token"], payment_id)
        return True, result
    except Exception as e:
        return False, str(e)


def log_memory():
    """Log current memory usage (Linux only)"""
    try:
        with open('/proc/self/status') as f:
            for line in f:
                if line.startswith('VmRSS:'):
                    rss_kb = int(line.split()[1])
                    print(f"    [mem] RSS: {rss_kb // 1024}MB")
                    return
    except Exception:
        pass


def login_with_retry(api, max_attempts=3):
    """Login with retry logic. Returns True on success."""
    for attempt in range(1, max_attempts + 1):
        try:
            api.login()
            return True
        except Exception as e:
            ts = datetime.now().strftime("%H:%M:%S")
            print(f"    [{ts}] Login attempt {attempt}/{max_attempts} failed: {e}")
            sys.stdout.flush()
            if attempt < max_attempts:
                time.sleep(2 * attempt)
                api.reset_session()
    return False


def main():
    global running, api

    # Register signal handlers
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    args = parse_args()

    TARGET_DATE = args.target_date
    PRIORITY_TIMES = [t.strip() for t in args.priority_times.split(',')]
    PARTY_SIZE = args.party_size
    DROP_TIME = args.drop_time
    TIMEOUT = args.timeout

    # Parse drop datetime
    drop_hour, drop_minute = map(int, DROP_TIME.split(':'))
    if args.drop_date:
        drop_base = datetime.strptime(args.drop_date, "%Y-%m-%d")
    else:
        drop_base = datetime.now()
    drop_dt = drop_base.replace(
        hour=drop_hour, minute=drop_minute, second=0, microsecond=0
    )
    login_dt = drop_dt - timedelta(seconds=90)

    # ── PHASE 1: Clear memory ────────────────────────
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"\n[1] [{ts}] Clearing system memory...")
    sys.stdout.flush()
    clear_system_memory()
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"    [{ts}] OK")
    sys.stdout.flush()

    # ── PHASE 2: Load API ────────────────────────────
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[2] [{ts}] Loading API...")
    sys.stdout.flush()
    from src.api_optimized import ResyAPI, ResyAPIError
    api = ResyAPI()
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"    [{ts}] OK")

    # ── Resolve venue ────────────────────────────────
    if args.venue_url:
        ts = datetime.now().strftime("%H:%M:%S")
        print(f"[*] [{ts}] Resolving venue URL...")
        sys.stdout.flush()
        VENUE_ID, VENUE_NAME = api.resolve_venue(args.venue_url)
        ts = datetime.now().strftime("%H:%M:%S")
        print(f"    [{ts}] {VENUE_NAME} (ID: {VENUE_ID})")
    else:
        VENUE_ID = args.venue_id
        VENUE_NAME = args.venue_name or "Restaurant"

    # ── PRE-FLIGHT CHECK ─────────────────────────────
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[*] [{ts}] Pre-flight check...")
    sys.stdout.flush()
    if not login_with_retry(api):
        print(f"    FATAL: Cannot authenticate with Resy. Aborting.")
        sys.exit(1)
    payment_id = api.get_default_payment_method_id()
    if not payment_id:
        print(f"    FATAL: No payment method on account. Aborting.")
        sys.exit(1)
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"    [{ts}] OK - auth + payment verified (ID: {payment_id})")
    # Clear pre-flight token so we get a fresh one at drop time
    api.auth_token = None
    sys.stdout.flush()

    print("=" * 50)
    print("RESY SNIPER [OPTIMIZED]")
    print("=" * 50)
    print(f"  Venue:    {VENUE_NAME} ({VENUE_ID})")
    print(f"  Date:     {TARGET_DATE}")
    print(f"  Times:    {PRIORITY_TIMES[0]} - {PRIORITY_TIMES[-1]}")
    print(f"  Party:    {PARTY_SIZE}")
    print(f"  Drop:     {DROP_TIME}")
    print(f"  Login:    {login_dt.strftime('%H:%M:%S')} (90s before drop)")
    print(f"  Timeout:  {TIMEOUT}s")
    print(f"  Mode:     2x parallel requests")
    print("=" * 50)
    sys.stdout.flush()

    # Create thread pool once — reused for all polling cycles
    executor = ThreadPoolExecutor(max_workers=2)

    try:
        # ── PHASE 3: Wait until 90s before drop ─────
        print(f"[3] Waiting for drop...")
        sys.stdout.flush()
        wait_until(login_dt, label=f"90s before {DROP_TIME}")

        # ── PHASE 4: Login (fresh token with retry) ──
        ts = datetime.now().strftime("%H:%M:%S")
        print(f"[4] [{ts}] Logging in (fresh token)...")
        sys.stdout.flush()
        if not login_with_retry(api):
            print(f"    FATAL: Login failed after retries. Aborting.")
            _notify_failure(VENUE_NAME, TARGET_DATE, "Login failed before drop")
            sys.exit(1)
        ts = datetime.now().strftime("%H:%M:%S")
        print(f"    [{ts}] OK")

        # ── PHASE 5: Get payment method ─────────────
        ts = datetime.now().strftime("%H:%M:%S")
        print(f"[5] [{ts}] Getting payment method...")
        sys.stdout.flush()
        payment_id = api.get_default_payment_method_id()
        if not payment_id:
            raise ResyAPIError("No payment method found on account")
        ts = datetime.now().strftime("%H:%M:%S")
        print(f"    [{ts}] OK (ID: {payment_id})")

        # ── PHASE 6: Wait for exact drop time ───────
        now = datetime.now()
        remaining_to_drop = (drop_dt - now).total_seconds()
        if remaining_to_drop > 0:
            print(f"[6] Waiting {remaining_to_drop:.1f}s for exact drop...")
            sys.stdout.flush()
            wait_until(drop_dt, label=DROP_TIME)
            print(f"    DROP TIME - GO!")
        else:
            print(f"[6] Drop time reached - GO!")
        sys.stdout.flush()

        # ── PHASE 7: Snipe! (2 parallel requests) ───
        print(f"[7] Sniping (2x parallel)...")
        sys.stdout.flush()

        start = time.time()
        attempts = 0
        errors_500 = 0
        errors_other = 0
        consecutive_rate_limits = 0
        last_gc = time.time()
        last_log = 0

        while running:
            attempts += 2  # 2 requests per cycle
            elapsed = time.time() - start

            # Timeout check
            if elapsed > TIMEOUT:
                print(f"\n[X] TIMEOUT ({attempts} attempts, {elapsed:.0f}s)")
                log_memory()
                _notify_failure(VENUE_NAME, TARGET_DATE, f"Timeout after {attempts} attempts")
                cleanup()
                sys.exit(1)

            # Periodic garbage collection (every 30s) + memory logging
            if time.time() - last_gc > 30:
                gc.collect()
                last_gc = time.time()
                log_memory()

            # Find slot (2 parallel requests via shared executor)
            slot, config_id, matched, slot_count, avail_times = find_slot_parallel(
                executor, api, VENUE_ID, TARGET_DATE, PRIORITY_TIMES, PARTY_SIZE
            )

            # Handle rate limiting
            if matched == "RATE_LIMITED":
                consecutive_rate_limits += 1
                backoff = min(consecutive_rate_limits, 5)
                print(f"    [{elapsed:.0f}s] Rate limited, waiting {backoff}s...")
                sys.stdout.flush()
                time.sleep(backoff)
                if consecutive_rate_limits > 8:
                    api.reset_session()
                    consecutive_rate_limits = 0
                continue

            # Handle 500 - Resy server overloaded (common at drop time)
            elif matched and matched.startswith("SERVER_500"):
                errors_500 += 1
                if errors_500 == 1:
                    ts = datetime.now().strftime("%H:%M:%S")
                    print(f"    [{ts}] {matched}")
                    sys.stdout.flush()
                elif errors_500 % 20 == 0:
                    ts = datetime.now().strftime("%H:%M:%S")
                    print(f"    [{ts}] Resy server 500 - retrying... ({errors_500} in a row)")
                    sys.stdout.flush()

                # Escalation: after 100 consecutive 500s, reset session + re-auth
                if errors_500 == 100:
                    ts = datetime.now().strftime("%H:%M:%S")
                    print(f"    [{ts}] 100 consecutive 500s - resetting session + re-auth...")
                    sys.stdout.flush()
                    api.reset_session()
                    login_with_retry(api, max_attempts=2)
                elif errors_500 == 300:
                    ts = datetime.now().strftime("%H:%M:%S")
                    print(f"    [{ts}] 300 consecutive 500s - second reset + re-auth...")
                    sys.stdout.flush()
                    api.reset_session()
                    login_with_retry(api, max_attempts=2)

                time.sleep(0.2)  # Fast retry - server may recover any moment
                continue

            # Handle auth/other errors - re-auth may help
            elif matched and matched.startswith("ERROR"):
                errors_other += 1
                ts = datetime.now().strftime("%H:%M:%S")
                print(f"    [{ts}] {matched} (attempt {attempts}, errors={errors_other})")
                sys.stdout.flush()
                if errors_other > 3:
                    print(f"    [{ts}] Re-authenticating...")
                    sys.stdout.flush()
                    api.reset_session()
                    if login_with_retry(api, max_attempts=2):
                        print(f"    [{ts}] Re-auth OK")
                    else:
                        print(f"    [{ts}] Re-auth failed")
                    errors_other = 0
                time.sleep(1)
                continue

            # Reset counters on successful API call
            errors_500 = 0
            errors_other = 0
            consecutive_rate_limits = 0

            # Log progress (every 2s to reduce I/O)
            if time.time() - last_log > 2 or slot_count > 0:
                ts = datetime.now().strftime("%H:%M:%S")
                if slot_count > 0 and matched is None and avail_times:
                    avail_str = ','.join(avail_times[:5])
                    if len(avail_times) > 5:
                        avail_str += f"...+{len(avail_times)-5}"
                    print(f"    [{ts}] slots={slot_count} | AVAIL: {avail_str} | WANT: {PRIORITY_TIMES[0]}-{PRIORITY_TIMES[-1]}")
                else:
                    print(f"    [{ts}] slots={slot_count}")
                sys.stdout.flush()
                last_log = time.time()

            # ── Found a slot - attempt booking ───────
            if slot:
                print(f"\n[!] FOUND: {matched} ({attempts} attempts, {elapsed:.1f}s)")
                sys.stdout.flush()

                print(f"[8] Booking {matched}...")
                sys.stdout.flush()
                success, result = attempt_booking(
                    api, config_id, TARGET_DATE, PARTY_SIZE, payment_id
                )

                if success:
                    res_id = result.get('reservation_id', 'unknown')
                    print()
                    print("=" * 50)
                    print("SUCCESS!")
                    print("=" * 50)
                    print(f"  Venue:   {VENUE_NAME}")
                    print(f"  Date:    {TARGET_DATE}")
                    print(f"  Time:    {matched}")
                    print(f"  ID:      {res_id}")
                    print("=" * 50)
                    sys.stdout.flush()

                    _notify_success(VENUE_NAME, TARGET_DATE, matched, res_id)
                    executor.shutdown(wait=False)
                    cleanup()
                    sys.exit(0)
                else:
                    # Booking failed (slot taken, etc) - keep trying
                    print(f"    Booking failed: {result}")
                    print(f"    Retrying...")
                    sys.stdout.flush()
                    time.sleep(0.3)
                    continue

            # Polling rate with parallel: ~4 requests/sec total
            time.sleep(0.3)

    except Exception as e:
        print(f"\n[X] Error: {e}")
        sys.stdout.flush()
        _notify_failure(VENUE_NAME, TARGET_DATE, str(e))
        executor.shutdown(wait=False)
        cleanup()
        sys.exit(1)


def _notify_success(venue_name, target_date, matched_time, reservation_id):
    """Send success notification (best-effort)"""
    try:
        from src.notifier import EmailNotifier
        notifier = EmailNotifier()
        if notifier.is_configured():
            notifier.send_email(
                f"RESY SUCCESS - {venue_name} {target_date}",
                f"Booked {venue_name} on {target_date} at {matched_time}\n"
                f"Reservation ID: {reservation_id}"
            )
            print("[Notifier] Success email sent")
    except Exception as e:
        print(f"[Notifier] Failed to send: {e}")


def _notify_failure(venue_name, target_date, error):
    """Send failure notification (best-effort)"""
    try:
        from src.notifier import EmailNotifier
        notifier = EmailNotifier()
        if notifier.is_configured():
            notifier.send_email(
                f"RESY FAILED - {venue_name} {target_date}",
                f"Failed to book {venue_name} on {target_date}\nError: {error}"
            )
            print("[Notifier] Failure email sent")
    except Exception as e:
        print(f"[Notifier] Failed to send: {e}")


if __name__ == "__main__":
    main()
