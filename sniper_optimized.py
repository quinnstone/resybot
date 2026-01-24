#!/usr/bin/env python3
"""
Resy Sniper - Optimized for VM stability

Key optimizations:
- Signal handlers for graceful shutdown
- Memory-efficient polling with periodic GC
- Adaptive polling rate (slower initially, faster near drop)
- Connection reset after errors
- Reduced logging to minimize I/O
- No busy-wait loops (uses efficient sleep)
- Resource cleanup on exit
- System memory clearing before and after snipe
"""
import sys
import time
import signal
import gc
import os
import argparse
from datetime import datetime

# Globals for signal handling
running = True
api = None


def clear_system_memory():
    """Clear system memory caches (requires running as user with sudo or appropriate permissions)"""
    try:
        # Sync filesystems
        os.system('sync')
        # Try to drop caches (may fail without sudo, that's ok)
        try:
            with open('/proc/sys/vm/drop_caches', 'w') as f:
                f.write('3')
        except PermissionError:
            # Try with sudo (will work if user has passwordless sudo)
            os.system('sudo sh -c "echo 3 > /proc/sys/vm/drop_caches" 2>/dev/null')
        gc.collect()
    except:
        pass  # Non-critical, continue anyway


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
        except:
            pass
    gc.collect()
    clear_system_memory()


def parse_args():
    parser = argparse.ArgumentParser(description='Resy Sniper - Optimized')
    parser.add_argument('--venue-id', type=int, required=True)
    parser.add_argument('--venue-name', default="Restaurant")
    parser.add_argument('--target-date', required=True)
    parser.add_argument('--priority-times', required=True)
    parser.add_argument('--party-size', type=int, default=2)
    parser.add_argument('--timeout', type=int, default=600)
    return parser.parse_args()


def find_slot(api, venue_id, date, priority_times, party_size):
    """Find matching slot from priority list"""
    try:
        slots = api.find_slots(venue_id, date, party_size)

        for target_time in priority_times:
            for slot in slots:
                slot_time = slot.get("date", {}).get("start", "")
                if target_time in slot_time:
                    return slot, slot["config"]["token"], target_time, len(slots), None

        # Return available times for logging if no match
        avail_times = [s.get("date", {}).get("start", "")[-8:-3] for s in slots[:8]]
        return None, None, None, len(slots), avail_times

    except Exception as e:
        error_str = str(e)
        if "429" in error_str:
            return None, None, "RATE_LIMITED", 0, None
        return None, None, f"ERROR: {e}", 0, None


def main():
    global running, api

    # Register signal handlers
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    args = parse_args()

    VENUE_ID = args.venue_id
    VENUE_NAME = args.venue_name
    TARGET_DATE = args.target_date
    PRIORITY_TIMES = [t.strip() for t in args.priority_times.split(',')]
    PARTY_SIZE = args.party_size
    TIMEOUT = args.timeout

    # Clear memory before starting
    print("[0] Clearing system memory...")
    clear_system_memory()

    print("=" * 50)
    print("RESY SNIPER [OPTIMIZED]")
    print("=" * 50)
    print(f"  Venue:    {VENUE_NAME} ({VENUE_ID})")
    print(f"  Date:     {TARGET_DATE}")
    print(f"  Times:    {PRIORITY_TIMES[0]} - {PRIORITY_TIMES[-1]}")
    print(f"  Party:    {PARTY_SIZE}")
    print(f"  Timeout:  {TIMEOUT}s")
    print("=" * 50)
    sys.stdout.flush()

    # Import here to delay loading until needed
    from src.api_optimized import ResyAPI, ResyAPIError

    try:
        api = ResyAPI()

        # Login
        print("\n[1] Logging in...")
        sys.stdout.flush()
        api.login()
        print("    OK")

        # Get payment method
        print("[2] Getting payment method...")
        sys.stdout.flush()
        payment_id = api.get_default_payment_method_id()
        print(f"    OK (ID: {payment_id})")

        # Sniping
        print(f"[3] Sniping...")
        sys.stdout.flush()

        start = time.time()
        attempts = 0
        errors = 0
        last_gc = time.time()
        last_log = 0

        while running:
            attempts += 1
            elapsed = time.time() - start

            # Timeout check
            if elapsed > TIMEOUT:
                print(f"\n[X] TIMEOUT ({attempts} attempts)")
                print("    Clearing memory...")
                cleanup()
                sys.exit(1)

            # Periodic garbage collection (every 30s)
            if time.time() - last_gc > 30:
                gc.collect()
                last_gc = time.time()

            # Find slot
            slot, config_id, matched, slot_count, avail_times = find_slot(
                api, VENUE_ID, TARGET_DATE, PRIORITY_TIMES, PARTY_SIZE
            )

            # Handle errors
            if matched == "RATE_LIMITED":
                errors += 1
                print(f"    [{elapsed:.0f}s] Rate limited, waiting 2s...")
                sys.stdout.flush()
                time.sleep(2)
                if errors > 5:
                    api.reset_session()
                    errors = 0
                continue
            elif matched and matched.startswith("ERROR"):
                errors += 1
                if errors > 3:
                    api.reset_session()
                    errors = 0
                time.sleep(0.5)
                continue

            errors = 0  # Reset error count on success

            # Log progress (every 2 seconds to reduce I/O)
            if time.time() - last_log > 2 or slot_count > 0:
                ts = datetime.now().strftime("%H:%M:%S")
                if slot_count > 0 and matched is None and avail_times:
                    # Show what times ARE available vs what we want
                    avail_str = ','.join(avail_times[:5])
                    if len(avail_times) > 5:
                        avail_str += f"...+{len(avail_times)-5}"
                    print(f"    [{ts}] slots={slot_count} | AVAIL: {avail_str} | WANT: {PRIORITY_TIMES[0]}-{PRIORITY_TIMES[-1]}")
                else:
                    print(f"    [{ts}] slots={slot_count}")
                sys.stdout.flush()
                last_log = time.time()

            # Found a slot!
            if slot:
                print(f"\n[!] FOUND: {matched} ({attempts} attempts, {elapsed:.1f}s)")
                sys.stdout.flush()

                # Get booking details
                print("[4] Getting details...")
                details = api.get_booking_details(config_id, TARGET_DATE, PARTY_SIZE)

                # Book it
                print("[5] BOOKING...")
                sys.stdout.flush()
                result = api.book(details["book_token"], payment_id)

                print()
                print("=" * 50)
                print("SUCCESS!")
                print("=" * 50)
                print(f"  Venue:   {VENUE_NAME}")
                print(f"  Date:    {TARGET_DATE}")
                print(f"  Time:    {matched}")
                print(f"  ID:      {result.get('reservation_id')}")
                print("=" * 50)
                print("\n[6] Clearing memory...")
                sys.stdout.flush()

                cleanup()
                print("    Done. Exiting.")
                sys.exit(0)

            # Adaptive sleep: faster polling as time goes on
            if elapsed < 5:
                time.sleep(0.5)  # Slow start
            elif elapsed < 30:
                time.sleep(0.3)  # Medium
            else:
                time.sleep(0.25)  # Fast polling after 30s

    except Exception as e:
        print(f"\n[X] Error: {e}")
        print("    Clearing memory...")
        sys.stdout.flush()
        cleanup()
        sys.exit(1)


if __name__ == "__main__":
    main()
