#!/usr/bin/env python3
"""
Scheduled snipe checker for GitHub Actions.

Reads snipes.json, finds any snipes dropping within the next 65 minutes,
and dispatches a workflow_dispatch run with the snipe parameters.
The cron job itself always completes in seconds.

Runs on a 30-minute cron as part of snipe.yml.
"""
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


SNIPES_FILE = Path(__file__).parent / "snipes.json"
WORKFLOW_FILE = "snipe.yml"


def load_snipes() -> list[dict]:
    if not SNIPES_FILE.exists():
        return []
    return json.loads(SNIPES_FILE.read_text())


def save_snipes(snipes: list[dict]):
    SNIPES_FILE.write_text(json.dumps(snipes, indent=2) + "\n")


def commit_update():
    """Commit updated snipes.json back to the repo."""
    subprocess.run(["git", "config", "user.name", "Resy Scheduler"], capture_output=True)
    subprocess.run(["git", "config", "user.email", "scheduler@resy-sniper"], capture_output=True)
    subprocess.run(["git", "add", str(SNIPES_FILE)], capture_output=True)

    result = subprocess.run(["git", "diff", "--cached", "--quiet"], capture_output=True)
    if result.returncode == 0:
        return  # No changes

    subprocess.run(
        ["git", "commit", "-m", "Update snipe status [skip ci]"],
        capture_output=True
    )
    subprocess.run(["git", "push"], capture_output=True)


def dispatch_snipe(snipe: dict) -> bool:
    """Trigger a workflow_dispatch run for this snipe. Returns True on success."""
    result = subprocess.run(
        [
            "gh", "workflow", "run", WORKFLOW_FILE,
            "-f", f"venue_url={snipe['venue_url']}",
            "-f", f"reservation_date={snipe['reservation_date']}",
            "-f", f"time_window={snipe['time_window']}",
            "-f", f"drop_date={snipe['drop_date']}",
            "-f", f"drop_time={snipe['drop_time']}",
            "-f", f"party_size={snipe.get('party_size', 2)}",
            "-f", f"timezone={snipe.get('timezone', 'America/New_York')}",
        ],
        capture_output=True,
        text=True,
    )

    if result.returncode == 0:
        print(f"  -> Dispatched workflow_dispatch successfully")
        return True
    else:
        print(f"  -> Failed to dispatch: {result.stderr.strip()}")
        return False


def main():
    snipes = load_snipes()
    pending = [s for s in snipes if s.get("status") == "pending"]

    if not pending:
        print("No pending snipes.")
        return

    now_utc = datetime.now(ZoneInfo("UTC"))
    print(f"Checking {len(pending)} pending snipe(s) at {now_utc.strftime('%Y-%m-%d %H:%M UTC')}")
    print()

    due_snipe = None

    for snipe in snipes:
        if snipe.get("status") != "pending":
            continue

        # Parse drop datetime in the snipe's timezone
        tz = ZoneInfo(snipe.get("timezone", "America/New_York"))
        drop_dt = datetime.strptime(
            f"{snipe['drop_date']} {snipe['drop_time']}",
            "%Y-%m-%d %H:%M"
        ).replace(tzinfo=tz)

        minutes_until_drop = (drop_dt - now_utc).total_seconds() / 60
        venue = snipe["venue_url"].rstrip("/").split("/")[-1].split("?")[0]

        print(f"  {venue}: drop {snipe['drop_date']} {snipe['drop_time']} "
              f"({minutes_until_drop:.0f} min away)")

        # Mark missed snipes (dropped more than 10 min ago)
        if minutes_until_drop < -10:
            print(f"  -> Drop passed, marking as missed")
            snipe["status"] = "missed"
            continue

        # Trigger if drop is within next 65 min (covers two 30-min cron cycles + jitter)
        if minutes_until_drop <= 65:
            print(f"  -> DROP SOON! Dispatching sniper.")
            due_snipe = snipe
            break
        else:
            print(f"  -> Not yet (waiting for < 65 min window)")

    print()

    if due_snipe:
        if dispatch_snipe(due_snipe):
            due_snipe["status"] = "dispatched"
            due_snipe["dispatched_at"] = now_utc.strftime("%Y-%m-%d %H:%M UTC")
        else:
            due_snipe["status"] = "dispatch_failed"

    save_snipes(snipes)
    commit_update()


if __name__ == "__main__":
    main()
