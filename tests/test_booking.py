#!/usr/bin/env python3
"""
Full Booking Test

WARNING: This script will make a REAL reservation!
         You MUST cancel it afterward on resy.com

Usage:
    python -m pytest tests/test_booking.py -v -s
"""
import sys
import pytest
from src.api import ResyAPI, ResyAPIError
from src.config import Config


# Test configuration
VENUE_ID = Config.TEST_VENUE_ID_1  # Lilia
TARGET_DATE = "2026-01-20"
TARGET_TIME = "21:15"
PARTY_SIZE = 2


class TestFullBookingFlow:
    """Full booking flow test - requires manual confirmation"""
    
    @pytest.fixture
    def api(self):
        api = ResyAPI()
        if not api.config.RESY_EMAIL or not api.config.RESY_PASSWORD:
            pytest.skip("No credentials configured in .env")
        return api
    
    @pytest.mark.integration
    def test_full_booking_flow(self, api):
        """
        Test the complete booking flow.
        
        NOTE: This test requires manual confirmation and will
        skip the actual booking step unless explicitly confirmed.
        """
        # Step 1: Login
        print("\n[1/4] Logging in...")
        api.login()
        print("      Login successful")
        
        # Step 2: Find slots
        print(f"\n[2/4] Searching for slots on {TARGET_DATE}...")
        slots = api.find_slots(
            venue_id=VENUE_ID,
            date=TARGET_DATE,
            party_size=PARTY_SIZE
        )
        print(f"      Found {len(slots)} total slots")
        
        # Find the target time slot
        matching = [s for s in slots if TARGET_TIME in s.get("date", {}).get("start", "")]
        
        if not matching:
            print(f"\nNo slot available at {TARGET_TIME}")
            print("   Available times:")
            for s in slots[:10]:
                print(f"      - {s['date']['start']}")
            pytest.skip(f"No slot at {TARGET_TIME}")
        
        slot = matching[0]
        config_id = slot["config"]["token"]
        print(f"      Found slot: {slot['date']['start']}")
        
        # Step 3: Get booking details
        print("\n[3/4] Getting booking details...")
        details = api.get_booking_details(
            config_id=config_id,
            date=TARGET_DATE,
            party_size=PARTY_SIZE
        )
        book_token = details["book_token"]
        payment_required = details.get('payment_required', False)
        print(f"      Got book_token")
        print(f"      Payment required: {payment_required}")
        
        # Verify we got what we need
        assert book_token is not None
        assert len(book_token) > 0
        
        print("\n[4/4] BOOKING SKIPPED (test mode)")
        print("      To make a real booking, run test_full_booking.py directly")


def main():
    """Interactive booking test - run directly to make real reservations"""
    print("=" * 60)
    print("FULL BOOKING TEST - Lilia")
    print("=" * 60)
    print(f"   Venue ID:    {VENUE_ID}")
    print(f"   Date:        {TARGET_DATE}")
    print(f"   Time:        {TARGET_TIME}")
    print(f"   Party Size:  {PARTY_SIZE}")
    print("=" * 60)
    print()
    print("WARNING: This will make a REAL reservation!")
    print("   You will need to CANCEL it on resy.com afterward.")
    print()
    
    confirm = input("Type 'yes' to proceed with booking: ").strip().lower()
    if confirm != "yes":
        print("Booking cancelled.")
        sys.exit(0)
    
    print()
    print("-" * 60)
    
    try:
        api = ResyAPI()
        
        print("\n[1/4] Logging in...")
        api.login()
        print("      Login successful")
        
        print(f"\n[2/4] Searching for slots on {TARGET_DATE}...")
        slots = api.find_slots(
            venue_id=VENUE_ID,
            date=TARGET_DATE,
            party_size=PARTY_SIZE
        )
        print(f"      Found {len(slots)} total slots")
        
        matching = [s for s in slots if TARGET_TIME in s.get("date", {}).get("start", "")]
        
        if not matching:
            print(f"\nNo slot available at {TARGET_TIME}")
            print("   Available times:")
            for s in slots[:10]:
                print(f"      - {s['date']['start']}")
            sys.exit(1)
        
        slot = matching[0]
        config_id = slot["config"]["token"]
        print(f"      Found slot: {slot['date']['start']}")
        
        print("\n[3/4] Getting booking details...")
        details = api.get_booking_details(
            config_id=config_id,
            date=TARGET_DATE,
            party_size=PARTY_SIZE
        )
        book_token = details["book_token"]
        payment_required = details.get('payment_required', False)
        print(f"      Got book_token")
        print(f"      Payment required: {payment_required}")
        
        payment_method_id = None
        if payment_required:
            print("      Fetching payment method...")
            payment_method_id = api.get_default_payment_method_id()
            if not payment_method_id:
                print("      No payment method found!")
                sys.exit(1)
        
        print()
        print("=" * 60)
        print("READY TO BOOK")
        print("=" * 60)
        print(f"   Date:       {TARGET_DATE}")
        print(f"   Time:       {slot['date']['start']}")
        print(f"   Party:      {PARTY_SIZE} people")
        print("=" * 60)
        print()
        
        final_confirm = input("Type 'BOOK' to confirm reservation: ").strip()
        if final_confirm != "BOOK":
            print("Booking cancelled.")
            sys.exit(0)
        
        print("\n[4/4] Booking reservation...")
        confirmation = api.book(book_token, payment_method_id=payment_method_id)
        
        print()
        print("=" * 60)
        print("RESERVATION CONFIRMED!")
        print("=" * 60)
        print(f"   Reservation ID: {confirmation.get('reservation_id')}")
        print("=" * 60)
        print()
        print("IMPORTANT: Go to resy.com and CANCEL this reservation!")
        print()
        
    except ResyAPIError as e:
        print(f"\nAPI Error: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        sys.exit(1)


if __name__ == "__main__":
    main()
