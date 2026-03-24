#!/usr/bin/env python3
"""
Sniper logic tests - validates the full E2E flow without hitting the real API.

Tests:
  1. Time matching correctness (no false positives)
  2. Booking retry on failure
  3. wait_until precision and late-start handling
  4. Error classification
  5. Full snipe loop simulation

Run with: python3 -m pytest tests/test_sniper_logic.py -v -s
"""
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))


# ── Test time matching ────────────────────────────────────

class TestFindSlot:
    """Test find_slot time matching logic"""

    def _make_slot(self, time_str):
        """Create a mock slot with ISO datetime"""
        return {
            "date": {"start": f"2026-02-27T{time_str}:00"},
            "config": {"token": f"token_{time_str}"}
        }

    def test_exact_match(self):
        from sniper_optimized import find_slot
        api = MagicMock()
        api.find_slots.return_value = [self._make_slot("19:30")]

        slot, token, matched, count, _ = find_slot(api, 1, "2026-02-27", ["19:30"], 2)

        assert slot is not None
        assert matched == "19:30"
        assert token == "token_19:30"
        assert count == 1

    def test_no_false_match_930_vs_1930(self):
        """Bug #5: '9:30' must NOT match '19:30'"""
        from sniper_optimized import find_slot
        api = MagicMock()
        api.find_slots.return_value = [self._make_slot("19:30")]

        slot, token, matched, count, avail = find_slot(api, 1, "2026-02-27", ["9:30"], 2)

        assert slot is None, "9:30 should NOT match 19:30"
        assert matched is None

    def test_priority_order_respected(self):
        from sniper_optimized import find_slot
        api = MagicMock()
        api.find_slots.return_value = [
            self._make_slot("20:00"),
            self._make_slot("19:30"),
            self._make_slot("21:00"),
        ]

        slot, token, matched, count, _ = find_slot(
            api, 1, "2026-02-27", ["19:30", "20:00", "21:00"], 2
        )

        assert matched == "19:30", "Should match first priority time, not first slot"

    def test_no_slots_returns_empty(self):
        from sniper_optimized import find_slot
        api = MagicMock()
        api.find_slots.return_value = []

        slot, token, matched, count, avail = find_slot(api, 1, "2026-02-27", ["19:30"], 2)

        assert slot is None
        assert count == 0
        assert avail == []

    def test_slots_exist_but_no_priority_match(self):
        from sniper_optimized import find_slot
        api = MagicMock()
        api.find_slots.return_value = [
            self._make_slot("17:00"),
            self._make_slot("17:30"),
        ]

        slot, token, matched, count, avail = find_slot(
            api, 1, "2026-02-27", ["19:30", "20:00"], 2
        )

        assert slot is None
        assert count == 2
        assert avail == ["17:00", "17:30"]

    def test_avail_times_extraction_robust(self):
        """Bug #6: avail_times must not break on bad data"""
        from sniper_optimized import find_slot
        api = MagicMock()
        api.find_slots.return_value = [
            {"date": {"start": ""}, "config": {"token": "x"}},
            {"date": {"start": "2026-02-27T20:00:00"}, "config": {"token": "y"}},
            {"date": {}, "config": {"token": "z"}},
        ]

        slot, token, matched, count, avail = find_slot(
            api, 1, "2026-02-27", ["19:30"], 2
        )

        assert slot is None
        assert count == 3
        assert "20:00" in avail
        assert len(avail) == 1  # empty strings filtered out


# ── Test error classification ─────────────────────────────

class TestErrorClassification:

    def test_rate_limit_detected(self):
        from sniper_optimized import find_slot
        api = MagicMock()
        api.find_slots.side_effect = Exception("Rate limited (429)")

        _, _, matched, _, _ = find_slot(api, 1, "2026-02-27", ["19:30"], 2)
        assert matched == "RATE_LIMITED"

    def test_401_detected(self):
        from sniper_optimized import find_slot
        api = MagicMock()
        api.find_slots.side_effect = Exception("Find failed: 401")

        _, _, matched, _, _ = find_slot(api, 1, "2026-02-27", ["19:30"], 2)
        assert "401" in matched

    def test_403_detected(self):
        from sniper_optimized import find_slot
        api = MagicMock()
        api.find_slots.side_effect = Exception("Find failed: 403")

        _, _, matched, _, _ = find_slot(api, 1, "2026-02-27", ["19:30"], 2)
        assert "403" in matched

    def test_generic_error(self):
        from sniper_optimized import find_slot
        api = MagicMock()
        api.find_slots.side_effect = Exception("Connection refused")

        _, _, matched, _, _ = find_slot(api, 1, "2026-02-27", ["19:30"], 2)
        assert matched.startswith("ERROR")
        assert "Connection refused" in matched


# ── Test booking retry ────────────────────────────────────

class TestAttemptBooking:

    def test_successful_booking(self):
        from sniper_optimized import attempt_booking
        api = MagicMock()
        api.get_booking_details.return_value = {"book_token": "tok123"}
        api.book.return_value = {"reservation_id": "res456"}

        success, result = attempt_booking(api, "cfg1", "2026-02-27", 2, 12345)

        assert success is True
        assert result["reservation_id"] == "res456"
        api.get_booking_details.assert_called_once_with("cfg1", "2026-02-27", 2)
        api.book.assert_called_once_with("tok123", 12345)

    def test_slot_taken_returns_failure(self):
        """Bug #4: booking failure must not crash, must return False"""
        from sniper_optimized import attempt_booking
        api = MagicMock()
        api.get_booking_details.side_effect = Exception("Slot no longer available")

        success, result = attempt_booking(api, "cfg1", "2026-02-27", 2, 12345)

        assert success is False
        assert "Slot no longer available" in result

    def test_book_412_returns_failure(self):
        from sniper_optimized import attempt_booking
        api = MagicMock()
        api.get_booking_details.return_value = {"book_token": "tok123"}
        api.book.side_effect = Exception("Slot taken by someone else")

        success, result = attempt_booking(api, "cfg1", "2026-02-27", 2, 12345)

        assert success is False
        assert "Slot taken" in result


# ── Test wait_until ───────────────────────────────────────

class TestWaitUntil:

    def test_past_time_returns_immediately(self, capsys):
        from sniper_optimized import wait_until
        past = datetime.now() - timedelta(seconds=30)

        start = time.time()
        wait_until(past, label="test")
        elapsed = time.time() - start

        assert elapsed < 0.5, "Should return immediately for past time"
        output = capsys.readouterr().out
        assert "LATE" in output

    def test_future_time_waits(self, capsys):
        from sniper_optimized import wait_until
        future = datetime.now() + timedelta(seconds=1)

        start = time.time()
        wait_until(future, label="test")
        elapsed = time.time() - start

        assert 0.8 < elapsed < 2.0, f"Should wait ~1s, waited {elapsed:.2f}s"


# ── Test full snipe simulation ────────────────────────────

class TestFullSnipeSimulation:
    """Simulates the full snipe loop without real API"""

    def test_find_then_book_success(self):
        """Simulate: find returns slot on 3rd attempt, booking succeeds"""
        from sniper_optimized import find_slot, attempt_booking

        api = MagicMock()

        # First 2 calls: no slots yet, 3rd call: slot available
        api.find_slots.side_effect = [
            [],  # Attempt 1: empty
            [],  # Attempt 2: empty
            [{"date": {"start": "2026-02-27T19:30:00"}, "config": {"token": "cfg_abc"}}],
        ]
        api.get_booking_details.return_value = {"book_token": "book_xyz"}
        api.book.return_value = {"reservation_id": "res_123"}

        # Simulate loop
        for attempt in range(1, 4):
            slot, config_id, matched, count, avail = find_slot(
                api, 64593, "2026-02-27", ["19:30", "20:00"], 2
            )
            if slot:
                success, result = attempt_booking(api, config_id, "2026-02-27", 2, 33538398)
                assert success
                assert result["reservation_id"] == "res_123"
                assert matched == "19:30"
                assert attempt == 3
                break
        else:
            assert False, "Should have found and booked"

    def test_find_then_book_retry_on_412(self):
        """Simulate: slot found, booking fails (412), retry finds another"""
        from sniper_optimized import find_slot, attempt_booking

        api = MagicMock()

        # Call 1: slot found
        # Call 2: slot found again after retry
        api.find_slots.side_effect = [
            [{"date": {"start": "2026-02-27T19:30:00"}, "config": {"token": "cfg_1"}}],
            [{"date": {"start": "2026-02-27T20:00:00"}, "config": {"token": "cfg_2"}}],
        ]
        # First book: 412, second: success
        api.get_booking_details.side_effect = [
            Exception("Slot no longer available"),
            {"book_token": "book_2"},
        ]
        api.book.return_value = {"reservation_id": "res_999"}

        booked = False
        for attempt in range(1, 5):
            slot, config_id, matched, count, avail = find_slot(
                api, 64593, "2026-02-27", ["19:30", "20:00"], 2
            )
            if slot:
                success, result = attempt_booking(api, config_id, "2026-02-27", 2, 33538398)
                if success:
                    booked = True
                    assert result["reservation_id"] == "res_999"
                    break
                # Failed - continue loop (simulating retry)

        assert booked, "Should have eventually booked"

    def test_error_recovery_with_reauth(self):
        """Simulate: errors trigger re-authentication"""
        from sniper_optimized import find_slot

        api = MagicMock()
        api.find_slots.side_effect = [
            Exception("Find failed: 401"),
            Exception("Find failed: 401"),
            Exception("Find failed: 401"),
            Exception("Find failed: 401"),
            # After re-auth, success:
            [{"date": {"start": "2026-02-27T19:30:00"}, "config": {"token": "cfg_ok"}}],
        ]

        errors = 0
        for attempt in range(1, 6):
            slot, config_id, matched, count, avail = find_slot(
                api, 64593, "2026-02-27", ["19:30"], 2
            )
            if matched and matched.startswith("ERROR"):
                errors += 1
                if errors > 3:
                    # Simulate re-auth
                    api.login()
                    errors = 0
                continue
            if slot:
                assert matched == "19:30"
                break
        else:
            assert False, "Should have recovered and found slot"

        api.login.assert_called_once()


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v", "-s"])
