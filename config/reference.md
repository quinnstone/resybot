# Restaurant Reference

Information about restaurants for sniping reservations.

---

## Four Horsemen

| Field | Value |
|-------|-------|
| **Venue ID** | 2492 |
| **Location** | Brooklyn, NY |
| **Drop Time** | 7:00 AM EST |
| **Days Advance** | 29 days (they say "30" but it's actually 29) |
| **Party Size** | Up to 5 |

### Drop Schedule

**Formula:** `target_date = snipe_date + 29 days`

| Snipe Date (7 AM) | Target Reservation |
|-------------------|-------------------|
| Jan 13 | Feb 11 |
| Jan 14 | Feb 12 |
| Jan 15 | Feb 13 |
| Jan 16 | Feb 14 (Valentine's Day!) |

To snipe for a specific date:
- Want **Feb 11**? Run sniper on **Jan 13 at 7 AM**
- Want **Feb 14**? Run sniper on **Jan 16 at 7 AM**

### Notes
- Extremely competitive - slots gone in seconds
- No deposit required
- Cancellation allowed

---

## Carbone

| Field | Value |
|-------|-------|
| **Venue ID** | 6194 |
| **Location** | NYC |
| **Drop Time** | 10:00 AM EST |
| **Days Advance** | 29 days |

### Drop Schedule

**Formula:** `target_date = snipe_date + 29 days`

| Snipe Date (10 AM) | Target Reservation |
|--------------------|-------------------|
| Jan 13 | Feb 11 |
| Jan 14 | Feb 12 |
| Jan 15 | Feb 13 |
| Jan 16 | Feb 14 (Valentine's Day!) |

To snipe for a specific date:
- Want **Feb 14**? Run sniper on **Jan 16 at 10 AM**

### Notes
- Famous Italian restaurant
- Very competitive

---

## Lilia

| Field | Value |
|-------|-------|
| **Venue ID** | 418 |
| **Location** | Brooklyn, NY |
| **Drop Time** | TBD |
| **Days Advance** | TBD |

### Notes
- Used for testing (has more availability)

---

## Smyth Tavern

| Field | Value |
|-------|-------|
| **Venue ID** | 61242 |
| **Location** | Chicago, IL |
| **Drop Time** | TBD |
| **Days Advance** | TBD |

### Notes
- Used for testing

---

## Adding New Restaurants

To find a restaurant's venue ID:
1. Go to the restaurant's page on resy.com
2. Open browser DevTools (F12) → Network tab
3. Filter by "find" or "venue"
4. Look for requests to `/4/find` - the `venue_id` parameter is in the URL

To find drop time and days advance:
1. Check the restaurant's website/booking page
2. Look for text like "Reservations open X days in advance at Y AM"
