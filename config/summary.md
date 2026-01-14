# Resy Sniper - Session Summary

> Knowledge captured from building and testing this reservation sniper.

---

## Project Overview

A bot to automatically secure hard-to-get Resy reservations (Four Horsemen, Carbone, etc.) at the exact moment they become available.

**Approach**: Direct API calls (not browser automation) to avoid captchas.

---

## Resy API Details

### Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/3/auth/password` | POST | Login with email/password |
| `/4/find` | GET | Search available slots |
| `/3/details` | GET | Get `book_token` for a slot |
| `/3/book` | POST | Finalize reservation |
| `/2/user/payment_methods` | GET | List saved payment methods |

### Authentication

```
Headers required:
  Authorization: ResyAPI api_key="VbWk7s3L4KiK5fzlO7JD3Q5EYolJI7n5"
  X-Resy-Auth-Token: <from login response>
```

- `api_key` is static (same for everyone)
- `auth_token` obtained from login, used for authenticated requests

### Key IDs

| ID Type | Description | Example |
|---------|-------------|---------|
| `venue_id` | Restaurant identifier | 2492 (Four Horsemen) |
| `config_id` | Specific time slot token | From `/find` response |
| `book_token` | Booking authorization | From `/details` response |
| `payment_method_id` | Saved credit card | From `/payment_methods` |

---

## Rate Limiting & Bot Detection

### What We Learned

1. **Endpoint-specific limits**: `/find` has stricter limits than `/auth`
2. **429 errors**: Hit after ~35 rapid requests at 400ms intervals
3. **500 errors**: Often follow 429s - indicates temporary IP block
4. **Block scope**: IP + endpoint (not account-based)
5. **Block Duration**: Unkown

### EC2 vs Local

| Environment | Latency to Resy | Bot Detection |
|-------------|-----------------|---------------|
| EC2 (us-east-1) | ~70ms | **HIGH** - Datacenter IPs flagged quickly |
| Local (residential) | ~200ms | Lower - Residential IPs harder to block |

**Conclusion**: EC2 is faster but gets blocked immediately. Local is safer despite higher latency.

### Safe Polling Rates

| Interval | Risk Level | Notes |
|----------|------------|-------|
| 150ms | 🔴 High | Will get 429'd quickly |
| 400ms | 🟡 Medium | Can work but risky during drops |
| 600ms | 🟢 Safer | Recommended for real runs |
| 1000ms | 🟢 Safe | Very conservative |

---

## Timing Strategy

### Drop Times

| Restaurant | Drop Time | Days Advance |
|------------|-----------|--------------|
| Four Horsemen | 7:00 AM EST | 29 days |
| Carbone | 10:00 AM EST | 29 days |

### Recommended Timeline

```
T-5 min:  Start script
T-3 min:  Login completes
T-10 sec: Begin polling (start early to catch release)
T+0:      Official drop time
T+10 min: Timeout (slots usually gone by then)
```

### Important Notes

- Resy servers can release slots a few seconds early
- Don't start polling too early - wastes rate limit budget
- Have login complete BEFORE snipe time begins

---

## Bugs & Fixes

### Bug 1: Venue ID Not Passed

**Problem**: `sniper.py` had hardcoded `VENUE_ID` and scripts didn't override it.

**Symptom**: Carbone script was querying Four Horsemen venue.

**Fix**: Added `--venue-id` and `--venue-name` CLI arguments.

### Bug 2: Script Argument Parsing

**Problem**: `--now` flag in shell scripts had quoting issues.

**Fix**: Proper handling in updated shell scripts.

### Bug 3: Late Script Start

**Problem**: Starting script after login time means missing the window.

**Lesson**: Always start 5+ minutes early and verify startup logs show correct venue.

---

## Best Practices

### Before a Real Run

1. ✅ Test API access the night before (confirm not blocked)
2. ✅ Don't over-test on drop day - save rate limit budget
3. ✅ Verify correct venue ID in startup logs
4. ✅ Start script 5+ minutes early
5. ✅ Have mobile hotspot ready as backup IP

### During the Run

1. ✅ Watch for "FIRST SIGHTING" in logs
2. ✅ If 429 errors, the 2-second backoff kicks in automatically
3. ✅ Don't restart scripts mid-run (wastes budget on re-login)

### If Blocked

1. Try mobile hotspot (different IP)
2. Wait 30-60 minutes
3. Overnight reset almost guaranteed

---

## File Structure

```
four_horsemen/
├── sniper.py              # Main sniper script
├── src/
│   ├── api.py             # Resy API client
│   ├── config.py          # Environment config
│   └── utils.py           # Logging utilities
├── scripts/
│   ├── horsemen.sh        # Four Horsemen launcher (both accounts)
│   └── carbone.sh         # Carbone launcher (both accounts)
├── config/
│   ├── accounts/          # .env files per account
│   ├── reference.md       # Restaurant IDs and drop times
│   └── summary.md         # This file
├── tests/                 # API tests
└── logs/                  # Runtime logs
```

---

## Quick Commands

```bash
# Test if API is working
python3 -c "
from src.api import ResyAPI
api = ResyAPI()
api.login()
slots = api.find_slots(2492, '2026-02-10', 2)
print(f'Found {len(slots)} slots')
"

# Run Four Horsemen sniper (start 5 min before 7 AM)
./scripts/horsemen.sh 2026-02-12

# Run Carbone sniper (start 5 min before 10 AM)
./scripts/carbone.sh 2026-02-12

# Quick test with --now flag
./scripts/horsemen.sh 2026-02-12 --now

# Watch logs
tail -f logs/horsemen1.log logs/horsemen2.log
```

---

## Open Questions / Future Work

- [ ] Can we use multiple IPs (proxy rotation) to avoid rate limits?
- [ ] Is there a way to predict exact slot release time more precisely?
- [ ] Do slots ever release a few seconds late (not just early)?
- [ ] Account-level rate limits vs IP-level - more testing needed


- [ ] Can we build a aws system where we rotate ips or have a unified log to determine drop times accuratley?
---

*Last updated: January 12, 2026*
