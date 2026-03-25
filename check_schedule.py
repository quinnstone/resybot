#!/usr/bin/env python3
"""
Scheduled snipe checker for GitHub Actions.

Reads snipes.json, finds any snipes dropping within the next 35 minutes,
and runs the sniper directly. Marks triggered snipes so they don't repeat.

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


def run_snipe(snipe: dict) -> int:
    """Run the sniper directly for a due snipe. Returns exit code."""
    tz = snipe.get("timezone", "America/New_York")
    env = os.environ.copy()
    env["TZ"] = tz

    cmd = [
        sys.executable, "run_snipe.py",
        "--url", snipe["venue_url"],
        "--date", snipe["reservation_date"],
        "--time", snipe["time_window"],
        "--drop-date", snipe["drop_date"],
        "--drop-time", snipe["drop_time"],
        "--party-size", str(snipe.get("party_size", 2)),
    ]

    print(f"Running: {' '.join(cmd)}")
    print("=" * 50)
    sys.stdout.flush()

    result = subprocess.run(cmd, env=env)
    return result.returncode


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
        # The sniper waits internally for the exact drop moment
        if minutes_until_drop <= 65:
            print(f"  -> DROP SOON! Will run sniper.")
            due_snipe = snipe
            break
        else:
            print(f"  -> Not yet (waiting for < 35 min window)")

    print()

    if due_snipe:
        due_snipe["status"] = "triggered"
        due_snipe["triggered_at"] = now_utc.strftime("%Y-%m-%d %H:%M UTC")
        save_snipes(snipes)
        commit_update()

        exit_code = run_snipe(due_snipe)

        # Update status based on result
        if exit_code == 0:
            due_snipe["status"] = "success"
        else:
            due_snipe["status"] = "failed"
        save_snipes(snipes)
        commit_update()

        sys.exit(exit_code)
    else:
        # Still save if we marked any as missed
        save_snipes(snipes)
        commit_update()
        print("No snipes due right now.")


if __name__ == "__main__":
    main()
