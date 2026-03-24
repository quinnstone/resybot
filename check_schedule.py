#!/usr/bin/env python3
"""
Scheduler script for GitHub Actions.

Reads snipes.json, finds any snipes dropping within the next 35 minutes,
triggers the snipe workflow for them, and marks them as triggered.

Runs on a 30-minute cron via scheduler.yml.
"""
import json
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo


SNIPES_FILE = Path(__file__).parent / "snipes.json"


def load_snipes() -> list[dict]:
    if not SNIPES_FILE.exists():
        return []
    return json.loads(SNIPES_FILE.read_text())


def save_snipes(snipes: list[dict]):
    SNIPES_FILE.write_text(json.dumps(snipes, indent=2) + "\n")


def trigger_workflow(snipe: dict) -> bool:
    """Trigger the snipe.yml workflow via gh CLI."""
    cmd = [
        "gh", "workflow", "run", "snipe.yml",
        "-f", f"venue_url={snipe['venue_url']}",
        "-f", f"reservation_date={snipe['reservation_date']}",
        "-f", f"time_window={snipe['time_window']}",
        "-f", f"drop_date={snipe['drop_date']}",
        "-f", f"drop_time={snipe['drop_time']}",
        "-f", f"party_size={str(snipe.get('party_size', 2))}",
        "-f", f"timezone={snipe.get('timezone', 'America/New_York')}",
    ]

    print(f"  Triggering: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        print(f"  ERROR: {result.stderr}")
        return False

    print(f"  Triggered successfully!")
    return True


def commit_snipes_update():
    """Commit the updated snipes.json back to the repo."""
    subprocess.run(["git", "config", "user.name", "Resy Scheduler"], capture_output=True)
    subprocess.run(["git", "config", "user.email", "scheduler@resy-sniper"], capture_output=True)
    subprocess.run(["git", "add", str(SNIPES_FILE)], capture_output=True)

    result = subprocess.run(
        ["git", "diff", "--cached", "--quiet"],
        capture_output=True
    )
    if result.returncode == 0:
        # No changes to commit
        return

    subprocess.run(
        ["git", "commit", "-m", "Update snipe status [skip ci]"],
        capture_output=True
    )
    subprocess.run(["git", "push"], capture_output=True)


def main():
    snipes = load_snipes()
    if not snipes:
        print("No snipes scheduled.")
        return

    now_utc = datetime.now(ZoneInfo("UTC"))
    triggered_any = False

    print(f"Checking {len(snipes)} snipe(s) at {now_utc.strftime('%Y-%m-%d %H:%M UTC')}")
    print()

    for snipe in snipes:
        if snipe.get("status") != "pending":
            continue

        # Parse drop datetime in the snipe's timezone
        tz = ZoneInfo(snipe.get("timezone", "America/New_York"))
        drop_dt = datetime.strptime(
            f"{snipe['drop_date']} {snipe['drop_time']}",
            "%Y-%m-%d %H:%M"
        ).replace(tzinfo=tz)

        # How far away is the drop?
        minutes_until_drop = (drop_dt - now_utc).total_seconds() / 60

        venue = snipe["venue_url"].rstrip("/").split("/")[-1]
        print(f"  {venue}: drop {snipe['drop_date']} {snipe['drop_time']} "
              f"({minutes_until_drop:.0f} min away)")

        # Trigger if drop is within next 35 minutes (covers 30-min cron + 5-min jitter)
        # but not already past by more than 5 minutes
        if -5 < minutes_until_drop <= 35:
            print(f"  -> DROP IMMINENT! Triggering snipe workflow...")
            if trigger_workflow(snipe):
                snipe["status"] = "triggered"
                snipe["triggered_at"] = now_utc.strftime("%Y-%m-%d %H:%M UTC")
                triggered_any = True
        elif minutes_until_drop <= -5:
            print(f"  -> Drop already passed, marking as missed")
            snipe["status"] = "missed"
            triggered_any = True
        else:
            print(f"  -> Not yet (waiting for < 35 min window)")

    print()

    if triggered_any:
        save_snipes(snipes)
        commit_snipes_update()
        print("Updated snipes.json")


if __name__ == "__main__":
    main()
