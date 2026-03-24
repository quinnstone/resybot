#!/bin/bash
# Lightweight cron cleanup - removes past snipe jobs + clears memory
# Called every 10 min by keepalive cron

NOW_MONTH=$(date +%-m)
NOW_DAY=$(date +%-d)
NOW_HOUR=$(date +%-H)
NOW_MIN=$(date +%-M)

CURRENT=$(crontab -l 2>/dev/null) || exit 0
KEEP=""

while IFS= read -r line; do
    # Always keep non-sniper lines (keepalive, etc)
    if [[ "$line" != *"sniper_optimized"* ]]; then
        KEEP="${KEEP}${line}"$'\n'
        continue
    fi

    # Parse cron fields: min hour day month
    CMIN=$(echo "$line" | awk '{print $1}')
    CHOUR=$(echo "$line" | awk '{print $2}')
    CDAY=$(echo "$line" | awk '{print $3}')
    CMONTH=$(echo "$line" | awk '{print $4}')

    # Keep if job is in the future
    if [ "$CMONTH" -gt "$NOW_MONTH" ] 2>/dev/null; then
        KEEP="${KEEP}${line}"$'\n'
    elif [ "$CMONTH" -eq "$NOW_MONTH" ] && [ "$CDAY" -gt "$NOW_DAY" ] 2>/dev/null; then
        KEEP="${KEEP}${line}"$'\n'
    elif [ "$CMONTH" -eq "$NOW_MONTH" ] && [ "$CDAY" -eq "$NOW_DAY" ] && [ "$CHOUR" -gt "$NOW_HOUR" ] 2>/dev/null; then
        KEEP="${KEEP}${line}"$'\n'
    elif [ "$CMONTH" -eq "$NOW_MONTH" ] && [ "$CDAY" -eq "$NOW_DAY" ] && [ "$CHOUR" -eq "$NOW_HOUR" ] && [ "$CMIN" -ge "$NOW_MIN" ] 2>/dev/null; then
        KEEP="${KEEP}${line}"$'\n'
    fi
    # Otherwise: past job, drop it
done <<< "$CURRENT"

# Only update if something changed
if [ "$KEEP" != "$CURRENT"$'\n' ]; then
    echo "$KEEP" | crontab -
fi

# Clear memory
sync
sudo sh -c "echo 3 > /proc/sys/vm/drop_caches" 2>/dev/null
