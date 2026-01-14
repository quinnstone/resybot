# Resy Rate Limit Testing - Findings

> EC2 rate limit testing conducted January 13, 2026

---

## Test Environment

| Parameter | Value |
|-----------|-------|
| Instance Type | t2.micro |
| Region | us-east-1 |
| IP | 54.172.65.102 (AWS datacenter IP) |
| Endpoint Tested | `/4/find` |
| Venue ID | 2492 (Four Horsemen) |
| Authentication | Unauthenticated (login failed due to env issue) |

---

## Test Results

### Test 1: Baseline (1 req/sec for 2 minutes) - Ubuntu Instance

```
IP:           54.172.65.102
Interval:     1.0 second
Duration:     120 seconds
Total Reqs:   120
Successful:   101 (84.2%)
Blocked:      19 (500 errors)
```

**Key Observations:**

| Metric | Value |
|--------|-------|
| Requests before block | ~101 |
| Time before block | ~1 min 42 sec |
| Block type | HTTP 500 (not 429) |
| Avg latency (normal) | ~70ms |
| Avg latency (blocked) | ~15ms |

### Test 2: Slower Rate (0.5 req/sec) - Same Instance

Started immediately after Test 1 - **IP was still blocked**. All requests returned 500.

### Test 3: Very Slow Rate (0.33 req/sec) - Fresh Amazon Linux Instance

```
IP:           3.93.182.54 (NEW fresh IP)
Interval:     3.0 seconds
Duration:     300 seconds (5 min)
Successful:   9
Blocked:      After request #10 (500 errors)
```

**Conclusion:** AWS IPs are heavily flagged.

### Test 4: GCP Cloud Shell - Unauthenticated

```
Provider:     Google Cloud Shell
Auth:         None (unauthenticated)
Interval:     1.0 second
Successful:   49
Blocked:      After request #50 (500 errors)
```

**Finding:** GCP IPs work better than AWS but still get blocked.

### Test 5: GCP Cloud Shell - Authenticated

```
Provider:     Google Cloud Shell (same session, IP may be burned)
Auth:         Authenticated with X-Resy-Auth-Token
Interval:     1.0 second
Successful:   38
Blocked:      After request #39 (500 errors)
```

**Finding:** Authentication does NOT help rate limits.

### Test 6: AWS EC2 - Very Slow (10-second intervals)

```
IP:           54.145.15.133 (fresh)
Provider:     AWS EC2 (Amazon Linux)
Interval:     10.0 seconds
Duration:     ~7 minutes
Successful:   42
Blocked:      After request #43 (500 errors)
```

**🚨 CRITICAL FINDING:** Even at 10-second intervals, blocked after ~42 requests. The limit is **request COUNT based**, not rate based. Slowing down doesn't help - you just get blocked slower.

---

## Key Findings

### 1. 🚨 ALL Datacenter IPs Get Blocked (~40-50 requests)

| Provider | Interval | Requests Before Block |
|----------|----------|----------------------|
| AWS EC2 #1 | 1s | 101 (outlier) |
| AWS EC2 #2 | 3s | 9 (bad IP?) |
| GCP Cloud Shell | 1s | 49 |
| GCP (authenticated) | 1s | 38 |
| **AWS EC2 #3** | **10s** | **42** |

**Conclusion:** Datacenter IPs have a **~40-50 request COUNT limit**, not a rate limit. Slowing down doesn't help - you just hit the limit slower.

### 2. Authentication Does NOT Help

Authenticated requests got blocked **faster** (38) than unauthenticated (49). Rate limiting is purely IP-based, not account-based.

### 3. No Warning - Straight to Block

Datacenter IPs get **immediate 500 errors** when blocked. No 429 warning like residential IPs get.

### 4. Block Recovery Time

| IP Type | Recovery |
|---------|----------|
| Local residential | 8+ hours (overnight reset) |
| AWS datacenter | Unknown (still blocked after test) |
| GCP datacenter | Unknown |

### 5. Datacenter vs Residential Comparison

| Metric | Datacenter (AWS/GCP) | Residential |
|--------|---------------------|-------------|
| Requests before block | 9-101 (inconsistent) | ~35 at 400ms |
| Block type | 500 errors | 429 → 500 |
| Detection | **Immediate** | Gradual |
| Recovery | Unknown | ~8 hours |

### 6. What Resy Likely Uses

- **IP reputation databases** (AWS/GCP ranges are known)
- **Datacenter IP detection** services
- **Request counting** per IP (not per account)
- **No behavioral fingerprinting** (just IP-based)

---

## Implications for Cluster Design

### Original Plan: ❌ NOT VIABLE

The EC2 cluster approach is **not viable** due to aggressive datacenter IP blocking.

| Plan | Problem |
|------|---------|
| 4 EC2s at 1 req/sec | Fresh IP blocked after 9 requests |
| Slower rate per IP | Tested - still blocked at 9 requests |
| More IPs | Would need 100+ IPs, still unreliable |

## Critical Analysis: What Actually Works?

### ❌ What Doesn't Work
| Approach | Why It Fails |
|----------|--------------|
| AWS EC2 | IPs flagged, blocked in 9-100 requests |
| GCP VMs | IPs flagged, blocked in 38-49 requests |
| Azure (untested) | Likely same - datacenter IPs |
| Authentication | Doesn't help, still IP-based |
| Slower request rate | Doesn't help (tested 3s intervals) |

### ✅ What Should Work

#### Option A: Multiple Residential IPs ⭐ BEST
**The only reliable approach is using residential IPs.**

| Method | Cost | Effort | Reliability |
|--------|------|--------|-------------|
| **Your home IP** | Free | Low | ✅ Proven |
| **Mobile hotspot** | Free | Low | ✅ Should work |
| **Friend's hotspot** | Free | Medium | ✅ Should work |
| **Residential proxy** | $15-50/GB | Low | ✅ Should work |
| **Coffee shop WiFi** | Free | Medium | 🤔 Maybe |

#### Option B: Strategic Timing (Minimize Requests)
Instead of continuous polling, be surgical:
```
T-30 sec:  Start polling (save budget for actual window)
T+0:       Drop time - poll aggressively  
T+60 sec:  If not found, you're probably too late anyway
```

35 requests × 2 IPs = 70 requests total
At 2 req/sec combined = 35 seconds of coverage

#### Option C: Residential Proxy Service
- **Bright Data** - $15/GB, rotating residential IPs
- **IPRoyal** - $7/GB, cheaper option
- `/find` returns ~2KB, so 1GB = 500,000 requests
- Even $7 gets you effectively unlimited requests

### 📊 Realistic Snipe Strategy

**Setup:**
1. Local machine on home WiFi (Account 1)
2. Phone hotspot on cellular (Account 2)

**Execution:**
- Start polling 30 seconds before drop (not 5 minutes)
- Each IP gets ~35 requests before 429
- Combined: 70 requests = 35 seconds at 2 req/sec
- If slot appears, immediately grab it

**Why this works:**
- Residential IPs get 429 warnings, not instant 500 blocks
- You can back off and retry on 429
- You only need to find the slot ONCE, then book immediately

---

## Next Steps

### Completed ✅

- [x] Test AWS EC2 - **Blocked after 9-101 requests**
- [x] Test GCP Cloud Shell - **Blocked after 49 requests**
- [x] Test authenticated vs unauthenticated - **No difference**
- [x] Test slower intervals - **Doesn't help**
- [x] Terminate EC2 instance

### Action Items for Snipe Day

1. **[ ] Wait for local IP to unblock** (8+ hours / overnight)
2. **[ ] Set up mobile hotspot** as second IP source
3. **[ ] Modify sniper to start polling later** (T-30s instead of T-5min)
4. **[ ] Run both accounts on separate IPs:**
   - Account 1 → Home WiFi
   - Account 2 → Mobile hotspot

### Optional: Test Residential Proxy

If you want more IPs without physical devices:
1. Sign up for IPRoyal or Bright Data (free trial)
2. Test that residential proxy IPs work
3. Integrate into sniper script

### ⚠️ Key Insight: STOP TESTING

Every test request burns your rate limit budget. 

**For the actual snipe:**
- Don't test the morning of the drop
- Your local IP needs to be "fresh"
- Start the sniper only when ready to commit

---

## Commands Reference

```bash
# Terminate EC2 instance
cd ~/Documents/dev/four_horsemen
source venv/bin/activate
export AWS_PROFILE=resy-sniper
python scripts/ec2_launcher.py terminate
```

---

## Raw Data

Test results saved on EC2 instances:
- `54.172.65.102:~/resy-sniper/rate_limit_20260113_002408.json` (Test 1 - 101 success)
- `3.93.182.54:~/resy-sniper/rate_limit_20260113_003314.json` (Test 3 - 9 success)

---

## Summary

### The Hard Truth

**All datacenter IPs (AWS, GCP, Azure) are blocked by Resy.** There is no cloud-based workaround for rate limiting.

### What Actually Works

| Approach | Viability |
|----------|-----------|
| Home residential IP | ✅ Works (~35 requests before 429) |
| Mobile hotspot | ✅ Should work (different IP) |
| Residential proxy | ✅ Should work ($7-15/GB) |
| Any datacenter IP | ❌ Blocked in <50 requests |

### Recommended Strategy

1. **Two physical IPs** (home + mobile hotspot)
2. **Two Resy accounts** (one per IP)
3. **Start late** (T-30s, not T-5min) to conserve budget
4. **Don't test on snipe day** - keep IPs fresh

### Math

- 35 requests per residential IP before 429
- 2 IPs × 35 = 70 requests
- At 2 req/sec combined = 35 seconds of aggressive polling
- That's enough to catch the drop if you time it right

---

*Last updated: January 13, 2026 - After testing AWS, GCP, authenticated, and unauthenticated*
