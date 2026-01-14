#!/usr/bin/env python3
"""
Resy Rate Limit Tester

Systematically tests the /find endpoint to understand rate limiting behavior.
Outputs detailed logs for analysis.

Usage:
    python rate_limit_tester.py --interval 1.0 --duration 300  # 1 req/sec for 5 min
    python rate_limit_tester.py --interval 0.5 --duration 60   # 2 req/sec for 1 min
"""
import sys
import time
import json
import argparse
from datetime import datetime
from src.api import ResyAPI, ResyAPIError
from src.config import Config

# Test parameters
VENUE_ID = 2492  # Four Horsemen
TEST_DATE = "2026-02-15"  # Pick a date ~30 days out
PARTY_SIZE = 2


def parse_args():
    parser = argparse.ArgumentParser(description='Resy Rate Limit Tester')
    parser.add_argument('--interval', type=float, default=1.0,
                        help='Seconds between requests. Default: 1.0')
    parser.add_argument('--duration', type=int, default=300,
                        help='Total test duration in seconds. Default: 300 (5 min)')
    parser.add_argument('--burst', type=int, default=0,
                        help='If set, do a burst of N requests at start, then normal interval')
    parser.add_argument('--output', type=str, default=None,
                        help='Output JSON file for detailed logs. Default: rate_limit_TIMESTAMP.json')
    parser.add_argument('--venue-id', type=int, default=VENUE_ID,
                        help=f'Venue ID to test. Default: {VENUE_ID}')
    parser.add_argument('--skip-login', action='store_true',
                        help='Skip login (test unauthenticated rate limits)')
    return parser.parse_args()


def main():
    args = parse_args()
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = args.output or f"rate_limit_{timestamp}.json"
    
    print("=" * 60)
    print("RESY RATE LIMIT TESTER")
    print("=" * 60)
    print(f"   Interval:    {args.interval}s ({1/args.interval:.1f} req/sec)")
    print(f"   Duration:    {args.duration}s")
    print(f"   Max reqs:    ~{int(args.duration / args.interval)}")
    print(f"   Venue ID:    {args.venue_id}")
    print(f"   Output:      {output_file}")
    if args.burst:
        print(f"   Burst:       {args.burst} requests at start")
    print("=" * 60)
    print()
    
    # Initialize API
    api = ResyAPI()
    
    if not args.skip_login:
        print("[1] Logging in...")
        try:
            api.login()
            print("    Logged in successfully!")
        except ResyAPIError as e:
            print(f"    Login failed: {e}")
            print("    Continuing without auth (may affect rate limits)")
    else:
        print("[1] Skipping login (testing unauthenticated)")
    
    print()
    print("[2] Starting rate limit test...")
    print()
    print("    timestamp          | req# | status | latency | notes")
    print("    " + "-" * 55)
    
    results = {
        "test_params": {
            "interval": args.interval,
            "duration": args.duration,
            "venue_id": args.venue_id,
            "burst": args.burst,
            "authenticated": not args.skip_login,
            "start_time": datetime.now().isoformat(),
        },
        "requests": [],
        "summary": {}
    }
    
    start_time = time.time()
    request_count = 0
    success_count = 0
    rate_limit_count = 0
    error_count = 0
    first_429_at = None
    consecutive_429s = 0
    max_consecutive_429s = 0
    
    # Burst phase (if requested)
    if args.burst > 0:
        print(f"    --- BURST PHASE: {args.burst} rapid requests ---")
        for i in range(args.burst):
            request_count += 1
            req_start = time.time()
            timestamp_str = datetime.now().strftime("%H:%M:%S.%f")[:-3]
            
            try:
                # Raw request to capture status code
                resp = api.session.get(
                    f"{api.BASE_URL}/4/find",
                    headers=api.headers,
                    params={
                        "lat": 0, "long": 0,
                        "day": TEST_DATE,
                        "party_size": PARTY_SIZE,
                        "venue_id": args.venue_id,
                    },
                    timeout=10
                )
                latency = (time.time() - req_start) * 1000
                status = resp.status_code
                
                if status == 200:
                    success_count += 1
                    consecutive_429s = 0
                    note = "OK"
                elif status == 429:
                    rate_limit_count += 1
                    consecutive_429s += 1
                    max_consecutive_429s = max(max_consecutive_429s, consecutive_429s)
                    if first_429_at is None:
                        first_429_at = request_count
                    note = f"RATE LIMITED (consecutive: {consecutive_429s})"
                else:
                    error_count += 1
                    consecutive_429s = 0
                    note = f"ERROR: {resp.text[:50]}"
                    
            except Exception as e:
                latency = (time.time() - req_start) * 1000
                status = 0
                error_count += 1
                note = f"EXCEPTION: {str(e)[:30]}"
            
            results["requests"].append({
                "n": request_count,
                "time": timestamp_str,
                "elapsed": time.time() - start_time,
                "status": status,
                "latency_ms": round(latency, 1),
                "note": note
            })
            
            print(f"    {timestamp_str} | {request_count:4d} | {status:6d} | {latency:6.0f}ms | {note}")
            sys.stdout.flush()
        
        print(f"    --- END BURST, switching to {args.interval}s interval ---")
    
    # Steady state phase
    while (time.time() - start_time) < args.duration:
        request_count += 1
        req_start = time.time()
        timestamp_str = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        
        try:
            resp = api.session.get(
                f"{api.BASE_URL}/4/find",
                headers=api.headers,
                params={
                    "lat": 0, "long": 0,
                    "day": TEST_DATE,
                    "party_size": PARTY_SIZE,
                    "venue_id": args.venue_id,
                },
                timeout=10
            )
            latency = (time.time() - req_start) * 1000
            status = resp.status_code
            
            if status == 200:
                success_count += 1
                consecutive_429s = 0
                note = "OK"
            elif status == 429:
                rate_limit_count += 1
                consecutive_429s += 1
                max_consecutive_429s = max(max_consecutive_429s, consecutive_429s)
                if first_429_at is None:
                    first_429_at = request_count
                note = f"RATE LIMITED (consecutive: {consecutive_429s})"
            elif status == 500:
                error_count += 1
                note = "SERVER ERROR (may indicate IP block)"
            else:
                error_count += 1
                consecutive_429s = 0
                note = f"ERROR: {resp.text[:50]}"
                
        except Exception as e:
            latency = (time.time() - req_start) * 1000
            status = 0
            error_count += 1
            note = f"EXCEPTION: {str(e)[:30]}"
        
        results["requests"].append({
            "n": request_count,
            "time": timestamp_str,
            "elapsed": round(time.time() - start_time, 2),
            "status": status,
            "latency_ms": round(latency, 1),
            "note": note
        })
        
        print(f"    {timestamp_str} | {request_count:4d} | {status:6d} | {latency:6.0f}ms | {note}")
        sys.stdout.flush()
        
        # Sleep for remaining interval time
        elapsed_this_req = time.time() - req_start
        sleep_time = max(0, args.interval - elapsed_this_req)
        if sleep_time > 0:
            time.sleep(sleep_time)
    
    # Summary
    total_time = time.time() - start_time
    actual_rate = request_count / total_time if total_time > 0 else 0
    
    results["summary"] = {
        "total_requests": request_count,
        "successful": success_count,
        "rate_limited": rate_limit_count,
        "errors": error_count,
        "first_429_at_request": first_429_at,
        "max_consecutive_429s": max_consecutive_429s,
        "total_time_seconds": round(total_time, 2),
        "actual_rate": round(actual_rate, 3),
        "success_rate": round(success_count / request_count * 100, 1) if request_count > 0 else 0
    }
    
    print()
    print("=" * 60)
    print("TEST COMPLETE - SUMMARY")
    print("=" * 60)
    print(f"   Total requests:     {request_count}")
    print(f"   Successful (200):   {success_count}")
    print(f"   Rate limited (429): {rate_limit_count}")
    print(f"   Errors:             {error_count}")
    print(f"   Success rate:       {results['summary']['success_rate']}%")
    print(f"   Actual rate:        {actual_rate:.2f} req/sec")
    if first_429_at:
        print(f"   First 429 at:       request #{first_429_at}")
        print(f"   Max consecutive:    {max_consecutive_429s} 429s in a row")
    print("=" * 60)
    
    # Save detailed results
    with open(output_file, 'w') as f:
        json.dump(results, f, indent=2)
    print(f"\nDetailed results saved to: {output_file}")


if __name__ == "__main__":
    main()