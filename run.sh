#!/bin/bash
#
# Four Horsemen Sniper Launcher
#
# Launches both account snipers in parallel with logging.
# Run this at 6:50 AM and let it do its thing.
#
# Usage:
#   ./run.sh              # Uses default date
#   ./run.sh 2026-02-14   # Custom date (Valentine's Day!)
#

TARGET_DATE="${1:-2026-02-11}"

cd "$(dirname "$0")"
source venv/bin/activate

echo "============================================================"
echo "FOUR HORSEMEN SNIPER"
echo "============================================================"
echo "   Target Date:  $TARGET_DATE"
echo "   Login Time:   06:56:50"
echo "   Snipe Time:   06:59:50 (10 sec early for recon)"
echo "   Poll Rate:    400ms"
echo "   Timeout:      10 minutes"
echo "============================================================"
echo ""

mkdir -p logs

echo "Starting Account 1..."
(
    export $(cat config/accounts/account1.env | xargs)
    python3 -u sniper.py \
        --target-date "$TARGET_DATE" \
        --priority-times "19:00,19:30,18:30,20:00,20:30" \
        --login-time "06:56:50" \
        --snipe-time "06:59:50" \
        --timeout 600 \
        --account-name "Account1"
) > logs/sniper1.log 2>&1 &
echo "   PID: $!"

echo "Starting Account 2..."
(
    export $(cat config/accounts/account2.env | xargs)
    python3 -u sniper.py \
        --target-date "$TARGET_DATE" \
        --priority-times "20:00,20:30,19:30,19:00,21:00" \
        --login-time "06:56:50" \
        --snipe-time "06:59:50" \
        --timeout 600 \
        --account-name "Account2"
) > logs/sniper2.log 2>&1 &
echo "   PID: $!"

echo ""
echo "Both snipers running!"
echo ""
echo "View logs:"
echo "   tail -f logs/sniper1.log"
echo "   tail -f logs/sniper2.log"
echo ""
echo "Stop snipers:"
echo "   pkill -f sniper.py"
echo ""

# Show live output from both
tail -f logs/sniper1.log logs/sniper2.log
