"""
API Find Slots Tests

Tests for ResyAPI find_slots functionality.
Run with: pytest tests/test_api_find.py -v -s
"""
import pytest
from datetime import date, timedelta
from src.api import ResyAPI, ResyAPIError
from src.config import Config


class TestFindSlotsUnit:
    """Unit tests for find_slots"""
    
    def test_find_slots_method_exists(self):
        api = ResyAPI()
        assert callable(api.find_slots)


class TestFindSlotsIntegration:
    """Integration tests - require real credentials"""
    
    @pytest.fixture
    def authenticated_api(self):
        api = ResyAPI()
        if not api.config.RESY_EMAIL or not api.config.RESY_PASSWORD:
            pytest.skip("No credentials configured in .env")
        api.login()
        return api
    
    @pytest.fixture
    def tomorrow(self):
        return (date.today() + timedelta(days=1)).isoformat()
    
    @pytest.mark.integration
    def test_find_slots_smyth_tavern(self, authenticated_api, tomorrow):
        """Test finding slots at Smyth Tavern"""
        venue_id = Config.TEST_VENUE_ID_2
        if not venue_id or venue_id == 0:
            pytest.skip("TEST_VENUE_ID_2 not configured")
        
        print(f"\nTesting Smyth Tavern (venue_id={venue_id})")
        
        for days_ahead in range(1, 8):
            check_date = (date.today() + timedelta(days=days_ahead)).isoformat()
            slots = authenticated_api.find_slots(
                venue_id=venue_id,
                date=check_date,
                party_size=2
            )
            
            if slots:
                print(f"Found {len(slots)} slots on {check_date}:")
                for i, slot in enumerate(slots[:5]):
                    time_str = slot.get("date", {}).get("start", "unknown")
                    print(f"   {i+1}. {time_str}")
                return
            else:
                print(f"   No slots on {check_date}")
        
        print("No availability found in next 7 days")
    
    @pytest.mark.integration
    def test_find_slots_lilia(self, authenticated_api, tomorrow):
        """Test finding slots at Lilia"""
        venue_id = Config.TEST_VENUE_ID_1
        if not venue_id or venue_id == 0:
            pytest.skip("TEST_VENUE_ID_1 not configured")
        
        print(f"\nTesting Lilia (venue_id={venue_id})")
        
        slots = authenticated_api.find_slots(
            venue_id=venue_id,
            date=tomorrow,
            party_size=2
        )
        
        print(f"Lilia queried successfully")
        print(f"   Available slots tomorrow: {len(slots)}")
    
    @pytest.mark.integration  
    def test_slot_structure(self, authenticated_api):
        """Test that slots have expected structure"""
        venue_id = Config.TEST_VENUE_ID_2
        if not venue_id or venue_id == 0:
            pytest.skip("TEST_VENUE_ID_2 not configured")
        
        slots = []
        for days_ahead in range(1, 14):
            check_date = (date.today() + timedelta(days=days_ahead)).isoformat()
            slots = authenticated_api.find_slots(venue_id=venue_id, date=check_date, party_size=2)
            if slots:
                break
        
        if not slots:
            pytest.skip("No slots available to test structure")
        
        slot = slots[0]
        print(f"\nSample slot structure:")
        print(f"   Keys: {list(slot.keys())}")
        
        assert "config" in slot
        assert "token" in slot["config"]
        assert "date" in slot
        
        print(f"   config.token: {slot['config']['token'][:50]}...")
        print(f"   date.start: {slot.get('date', {}).get('start', 'N/A')}")


class TestFindSlotsAtFourHorsemen:
    """Tests for Four Horsemen venue"""
    
    @pytest.fixture
    def authenticated_api(self):
        api = ResyAPI()
        if not api.config.RESY_EMAIL or not api.config.RESY_PASSWORD:
            pytest.skip("No credentials configured")
        api.login()
        return api
    
    @pytest.mark.integration
    def test_four_horsemen_venue_exists(self, authenticated_api):
        """Verify we can query Four Horsemen"""
        venue_id = Config.HORSEMEN_VENUE_ID
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        
        slots = authenticated_api.find_slots(
            venue_id=venue_id,
            date=tomorrow,
            party_size=2
        )
        
        print(f"Four Horsemen (venue_id={venue_id}) queried successfully")
        print(f"   Available slots: {len(slots)}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
