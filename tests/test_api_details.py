"""
API Booking Details Tests

Tests for ResyAPI get_booking_details functionality.
Run with: pytest tests/test_api_details.py -v -s
"""
import pytest
from src.api import ResyAPI, ResyAPIError
from src.config import Config


class TestGetBookingDetailsIntegration:
    """Integration tests for get_booking_details"""
    
    @pytest.fixture
    def authenticated_api(self):
        api = ResyAPI()
        if not api.config.RESY_EMAIL or not api.config.RESY_PASSWORD:
            pytest.skip("No credentials configured in .env")
        api.login()
        return api
    
    @pytest.mark.integration
    def test_get_booking_details_smyth_tavern(self, authenticated_api):
        """
        Test getting book_token for Smyth Tavern.
        
        NOTE: This does NOT make a reservation - just gets the token.
        """
        venue_id = Config.TEST_VENUE_ID_2
        target_date = "2026-01-17"
        target_time = "20:30"
        party_size = 2
        
        print(f"\nTarget: Smyth Tavern, {target_date} @ {target_time}")
        
        slots = authenticated_api.find_slots(
            venue_id=venue_id,
            date=target_date,
            party_size=party_size
        )
        
        matching = [s for s in slots if target_time in s.get("date", {}).get("start", "")]
        
        if not matching:
            pytest.skip(f"No {target_time} slot available on {target_date}")
        
        slot = matching[0]
        config_id = slot["config"]["token"]
        print(f"   Found slot: {slot['date']['start']}")
        print(f"   config_id: {config_id[:60]}...")
        
        details = authenticated_api.get_booking_details(
            config_id=config_id,
            date=target_date,
            party_size=party_size
        )
        
        assert "book_token" in details
        assert details["book_token"] is not None
        assert len(details["book_token"]) > 0
        
        print(f"\nGot booking details!")
        print(f"   book_token: {details['book_token'][:60]}...")
        print(f"   Payment required: {details.get('payment_required', 'N/A')}")
        print(f"   Deposit amount: ${details.get('deposit_amount', 0)}")
        
        return details
    
    @pytest.mark.integration
    def test_get_booking_details_returns_dict(self, authenticated_api):
        """Test that get_booking_details returns proper structure"""
        venue_id = Config.TEST_VENUE_ID_2
        target_date = "2026-01-17"
        party_size = 2
        
        slots = authenticated_api.find_slots(venue_id, target_date, party_size)
        if not slots:
            pytest.skip("No slots available")
        
        config_id = slots[0]["config"]["token"]
        
        details = authenticated_api.get_booking_details(config_id, target_date, party_size)
        
        assert isinstance(details, dict)
        assert "book_token" in details
        assert "payment_required" in details
        
        print("Response structure valid")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
