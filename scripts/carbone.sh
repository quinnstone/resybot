#!/bin/bash
#
# Carbone Sniper (Both Accounts)
#
# Run this 5 minutes before 10:00 AM EST
#
# Usage:
#   ./scripts/carbone.sh                           # Default times (10 AM drop)
#   ./scripts/carbone.sh 2026-02-14                # Custom date
#   ./scripts/carbone.sh 2026-02-14 --now          # Test NOW (login in 30s, snipe in 2min)
#   ./scripts/carbone.sh 2026-02-14 14:30:00       # Custom snipe time
#

TARGET_DATE="${1:-2026-02-11}"
VENUE_ID=6194

# Check for --now flag or custom time
if [[ "$2" == "--now" ]]; then
    # Calculate times relative to now
    LOGIN_TIME=$(date -v+30S +%H:%M:%S)
    SNIPE_TIME=$(date -v+2M +%H:%M:%S)
    echo "TEST MODE: Login at $LOGIN_TIME, Snipe at $SNIPE_TIME"
elif [[ -n "$2" ]]; then
    # Custom snipe time provided
    SNIPE_TIME="$2"
    # Login 3 min before snipe
    LOGIN_TIME=$(date -j -f "%H:%M:%S" "$SNIPE_TIME" -v-3M +%H:%M:%S)
else
    # Default: 10 AM drop
    SNIPE_TIME="09:59:50"
    LOGIN_TIME="09:56:50"
fi

cd "$(dirname "$0")/.."
source venv/bin/activate

echo "============================================================"
echo "CARBONE SNIPER"
echo "============================================================"
echo "   Venue ID:    $VENUE_ID"
echo "   Target Date: $TARGET_DATE"
echo "   Login Time:  $LOGIN_TIME"
echo "   Snipe Time:  $SNIPE_TIME"
echo "============================================================"
echo ""

mkdir -p logs

echo "Starting Account 1..."
(
    export $(cat config/accounts/account1.env | xargs)
    python3 -u sniper.py \
        --venue-id "$VENUE_ID" \
        --venue-name "Carbone" \
        --target-date "$TARGET_DATE" \
        --priority-times "19:00,19:30,18:30,20:00,20:30" \
        --login-time "$LOGIN_TIME" \
        --snipe-time "$SNIPE_TIME" \
        --timeout 600 \
        --account-name "Carbone-Acct1"
) > logs/carbone1.log 2>&1 &
echo "   PID: $!"

echo "Starting Account 2..."
(
    export $(cat config/accounts/account2.env | xargs)
    python3 -u sniper.py \
        --venue-id "$VENUE_ID" \
        --venue-name "Carbone" \
        --target-date "$TARGET_DATE" \
        --priority-times "20:00,20:30,19:30,19:00,21:00" \
        --login-time "$LOGIN_TIME" \
        --snipe-time "$SNIPE_TIME" \
        --timeout 600 \
        --account-name "Carbone-Acct2"
) > logs/carbone2.log 2>&1 &
echo "   PID: $!"

echo ""
echo "Both snipers running!"
echo ""
echo "View logs:"
echo "   tail -f logs/carbone1.log"
echo "   tail -f logs/carbone2.log"
echo ""

tail -f logs/carbone1.log logs/carbone2.log
