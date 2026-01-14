# Resy Sniper

Automated reservation sniper for Resy restaurants. Input a restaurant URL and desired time window, and the tool will schedule a cron job to snipe reservations the moment they're released.

## Features

- **URL-based scheduling** - Just paste a Resy restaurant URL
- **Automatic venue detection** - Looks up venue IDs via Resy's API
- **Cron job automation** - Schedules snipes to run at exact release times
- **15-minute time increments** - Searches time windows in 15-min slots
- **Priority-based booking** - Tries earliest times first within your window
- **Email notifications** - Get notified on success or failure

## Quick Start

```bash
# Activate virtual environment
source venv/bin/activate

# Run the interactive snipe tool
python test_snipe.py
```

## Configuration

Create a `.env` file with your credentials:

```
RESY_EMAIL=your_email@example.com
RESY_PASSWORD=your_password
NOTIFY_EMAIL=your_email@example.com
```

## Usage

### Interactive Tool (Recommended)

```bash
python test_snipe.py
```

The tool will ask:
1. **Are slots already available?**
   - **YES** - Runs snipe immediately
   - **NO** - Schedules a cron job for the release time

2. Restaurant URL (e.g., `https://resy.com/cities/new-york-ny/venues/torrisi`)
3. Target reservation date
4. Release date/time (for scheduled mode)
5. Time window (e.g., `19:00-21:00`)
6. Party size

### CLI Commands

```bash
# List all scheduled jobs
python resy.py list

# Cancel a job
python resy.py cancel <job_id>

# Manually run a job
python resy.py run <job_id>

# View known venues
python resy.py venues
```

### Manual Snipe

```bash
python sniper.py \
  --venue-id 64593 \
  --venue-name "Torrisi" \
  --target-date 2026-02-13 \
  --priority-times "19:00,19:15,19:30,19:45,20:00" \
  --party-size 2 \
  --immediate
```

## How It Works

### Immediate Mode
1. Finds available slots for your date
2. Books the first available slot within your time window
3. Prioritizes earlier times

### Scheduled Mode
1. Creates a job in the SQLite database
2. Schedules a cron job for 10 seconds before release time
3. At release time, the sniper:
   - Logs into your Resy account
   - Polls for available slots
   - Books the first matching slot
   - Sends email notification

## Known Venues

| Venue | Drop Time | Days Advance |
|-------|-----------|--------------|
| Carbone | 10:00 AM | 29 days |
| Torrisi | 10:00 AM | 30 days |
| Lilia | 9:00 AM | 30 days |
| Don Angie | 9:00 AM | 30 days |
| I Sodi | 12:00 PM | 28 days |
| 4 Charles Prime Rib | 9:00 AM | 21 days |

New venues are automatically added when you use them.

## Project Structure

```
base/
├── test_snipe.py      # Interactive snipe tool (main entry point)
├── sniper.py          # Core sniper logic
├── resy.py            # CLI for managing jobs
├── src/
│   ├── venue_resolver.py  # URL parsing & venue lookup
│   ├── job_store.py       # SQLite job persistence
│   ├── scheduler.py       # Cron job management
│   ├── notifier.py        # Email notifications
│   └── resy_client.py     # Resy API client
├── data/
│   ├── venues.json        # Known venue database
│   └── jobs.db            # SQLite job database
└── logs/                  # Job execution logs
```

## Requirements

- Python 3.10+
- macOS or Linux (for cron)
- Active Resy account with payment method

## Troubleshooting

**403 "Invalid account" error**
- Verify your Resy credentials in `.env`
- Check that your Resy account has a valid payment method
- Your account may be flagged - try logging in manually

**Venue not found**
- The tool will search Resy's API automatically
- If not found, you'll be prompted to enter the venue ID manually

**Cron job not running**
- Your computer must be ON and awake at the scheduled time
- Check logs in `logs/job_<id>.log`
- Verify cron is enabled: `crontab -l`
