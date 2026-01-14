# Four Horsemen Reservation Sniper

Automatically snipes reservations at Four Horsemen (Brooklyn) when they become available at 7:00 AM EST.

## How It Works

Four Horsemen releases reservations 30 days in advance at exactly 7:00 AM EST. This sniper:

1. Logs in to your Resy account before the drop
2. Starts polling at 6:59:50 AM to catch the exact moment slots appear
3. Books the first available slot from your priority list
4. Logs detailed timing data for analysis

## Setup

### 1. Create virtual environment

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure accounts

Create credential files in `config/accounts/`:

```bash
# config/accounts/account1.env
RESY_EMAIL=your@email.com
RESY_PASSWORD=yourpassword

# config/accounts/account2.env (optional second account)
RESY_EMAIL=backup@email.com
RESY_PASSWORD=backuppassword
```

### 3. Test your credentials

```bash
source venv/bin/activate
export $(cat config/accounts/account1.env | xargs)
python3 -c "from src.api import ResyAPI; api = ResyAPI(); api.login(); print('Login OK')"
```

## Usage

### Run the sniper

```bash
# Default date (Feb 11)
./run.sh

# Custom date
./run.sh 2026-02-14
```

### Run manually (single account)

```bash
source venv/bin/activate
export $(cat config/accounts/account1.env | xargs)
python3 sniper.py --target-date 2026-02-14 --priority-times "19:00,19:30,20:00"
```

### Options

```
--target-date     Date to book (YYYY-MM-DD)
--priority-times  Comma-separated times in order of preference
--party-size      Number of guests (default: 2)
--login-time      When to login (default: 06:56:50)
--snipe-time      When to start sniping (default: 06:59:50)
--timeout         Timeout in seconds (default: 600)
--account-name    Name for logging
```

## Project Structure

```
four_horsemen/
├── config/accounts/    # Resy credentials (.env files)
├── src/
│   ├── api.py          # Resy API client
│   ├── config.py       # Configuration loader
│   └── utils.py        # Utilities
├── tests/              # Test suite
├── logs/               # Runtime logs (gitignored)
├── sniper.py           # Main sniper script
├── run.sh              # Launcher for both accounts
└── requirements.txt
```

## Running Tests

```bash
source venv/bin/activate
pytest tests/ -v -s
```

## Tips

- Run from a stable internet connection
- Have both accounts configured for redundancy
- Set different priority times for each account
- Check logs after each attempt to analyze timing
