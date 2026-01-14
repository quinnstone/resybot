"""
Scheduler

Manages cron jobs for scheduled snipe operations.
"""
import os
import subprocess
import sys
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from src.job_store import Job, JobStatus, JobStore


class SchedulerError(Exception):
    """Error managing scheduled jobs"""
    pass


class Scheduler:
    """Manages cron jobs for snipe scheduling"""

    # Marker to identify our cron entries
    CRON_MARKER = "# RESY_SNIPE_JOB"

    def __init__(self):
        self.project_root = Path(__file__).parent.parent.absolute()
        self.python_path = self._find_python()
        self.job_store = JobStore()

    def _find_python(self) -> str:
        """Find the Python executable, preferring venv if available"""
        venv_python = self.project_root / "venv" / "bin" / "python"
        if venv_python.exists():
            return str(venv_python)
        venv_python3 = self.project_root / "venv" / "bin" / "python3"
        if venv_python3.exists():
            return str(venv_python3)
        return sys.executable

    def calculate_snipe_datetime(
        self,
        target_date: str,
        days_advance: int,
        drop_time: str,
        timezone: str
    ) -> tuple[str, str]:
        """
        Calculate when to run the sniper.

        Args:
            target_date: The reservation date (YYYY-MM-DD)
            days_advance: How many days before reservations open
            drop_time: When reservations drop (HH:MM)
            timezone: Restaurant timezone

        Returns:
            (snipe_date, snipe_time) - date as YYYY-MM-DD, time as HH:MM:SS
            Snipe time is 10 seconds before drop to catch the exact moment
        """
        # Parse target date
        target = datetime.strptime(target_date, "%Y-%m-%d")

        # Calculate snipe date (target - days_advance)
        snipe_date = target - timedelta(days=days_advance)

        # Parse drop time and subtract 10 seconds
        drop_hour, drop_min = map(int, drop_time.split(':'))
        snipe_time = datetime(
            snipe_date.year, snipe_date.month, snipe_date.day,
            drop_hour, drop_min, 0
        ) - timedelta(seconds=10)

        # Handle day boundary (if drop is at 00:00:00, snipe would be previous day)
        snipe_date_str = snipe_time.strftime("%Y-%m-%d")
        snipe_time_str = snipe_time.strftime("%H:%M:%S")

        return snipe_date_str, snipe_time_str

    def schedule_job(self, job: Job) -> bool:
        """
        Create a cron job for the given snipe job.

        Args:
            job: The job to schedule

        Returns:
            True if successfully scheduled
        """
        if job.id is None:
            raise SchedulerError("Job must be saved to database before scheduling")

        # Parse snipe datetime
        snipe_dt = datetime.strptime(
            f"{job.snipe_date} {job.snipe_time}",
            "%Y-%m-%d %H:%M:%S"
        )

        # Build cron time fields (minute, hour, day, month, weekday)
        minute = snipe_dt.minute
        hour = snipe_dt.hour
        day = snipe_dt.day
        month = snipe_dt.month

        # Build the command
        resy_cli = self.project_root / "resy.py"
        log_file = self.project_root / "logs" / f"job_{job.id}.log"
        log_file.parent.mkdir(parents=True, exist_ok=True)

        command = (
            f"cd {self.project_root} && "
            f"{self.python_path} {resy_cli} run {job.id} "
            f">> {log_file} 2>&1"
        )

        # Build cron entry
        cron_entry = f"{minute} {hour} {day} {month} * {command} {self.CRON_MARKER}_{job.id}"

        # Add to crontab
        try:
            self._add_cron_entry(cron_entry)
            self.job_store.update_status(job.id, JobStatus.SCHEDULED)
            return True
        except Exception as e:
            raise SchedulerError(f"Failed to create cron job: {e}")

    def unschedule_job(self, job_id: int) -> bool:
        """
        Remove the cron job for a given job ID.

        Returns:
            True if cron entry was found and removed
        """
        marker = f"{self.CRON_MARKER}_{job_id}"
        return self._remove_cron_entry(marker)

    def _get_current_crontab(self) -> str:
        """Get current user's crontab"""
        try:
            result = subprocess.run(
                ['crontab', '-l'],
                capture_output=True,
                text=True
            )
            if result.returncode == 0:
                return result.stdout
            # No crontab for user
            return ""
        except FileNotFoundError:
            raise SchedulerError("crontab command not found")

    def _set_crontab(self, content: str):
        """Set the user's crontab"""
        try:
            process = subprocess.Popen(
                ['crontab', '-'],
                stdin=subprocess.PIPE,
                text=True
            )
            process.communicate(input=content)
            if process.returncode != 0:
                raise SchedulerError("Failed to set crontab")
        except FileNotFoundError:
            raise SchedulerError("crontab command not found")

    def _add_cron_entry(self, entry: str):
        """Add a cron entry to the user's crontab"""
        current = self._get_current_crontab()
        lines = current.strip().split('\n') if current.strip() else []

        # Check if entry already exists (by marker)
        marker = entry.split(self.CRON_MARKER)[-1] if self.CRON_MARKER in entry else None
        if marker:
            full_marker = f"{self.CRON_MARKER}{marker}"
            lines = [l for l in lines if full_marker not in l]

        lines.append(entry)
        self._set_crontab('\n'.join(lines) + '\n')

    def _remove_cron_entry(self, marker: str) -> bool:
        """Remove cron entries containing the marker"""
        current = self._get_current_crontab()
        if not current.strip():
            return False

        lines = current.strip().split('\n')
        new_lines = [l for l in lines if marker not in l]

        if len(new_lines) == len(lines):
            return False  # Nothing removed

        if new_lines:
            self._set_crontab('\n'.join(new_lines) + '\n')
        else:
            # Remove crontab entirely if empty
            subprocess.run(['crontab', '-r'], capture_output=True)

        return True

    def list_scheduled_cron_jobs(self) -> list[str]:
        """List all our cron entries"""
        current = self._get_current_crontab()
        if not current.strip():
            return []

        return [
            line for line in current.strip().split('\n')
            if self.CRON_MARKER in line
        ]

    def sync_with_store(self):
        """
        Sync cron jobs with job store.
        Removes cron entries for jobs that no longer exist or are completed.
        """
        # Get all our cron entries
        cron_jobs = self.list_scheduled_cron_jobs()

        for cron_line in cron_jobs:
            # Extract job ID from marker
            if self.CRON_MARKER in cron_line:
                try:
                    marker_part = cron_line.split(self.CRON_MARKER + "_")[-1]
                    job_id = int(marker_part.split()[0])

                    # Check if job still exists and is pending/scheduled
                    job = self.job_store.get_job(job_id)
                    if not job or job.status not in (JobStatus.PENDING, JobStatus.SCHEDULED):
                        self.unschedule_job(job_id)
                except (ValueError, IndexError):
                    pass


def format_snipe_datetime(snipe_date: str, snipe_time: str, timezone: str) -> str:
    """Format snipe datetime for display"""
    dt = datetime.strptime(f"{snipe_date} {snipe_time}", "%Y-%m-%d %H:%M:%S")
    tz_abbrev = {
        'America/New_York': 'ET',
        'America/Chicago': 'CT',
        'America/Denver': 'MT',
        'America/Los_Angeles': 'PT'
    }.get(timezone, timezone)
    return dt.strftime(f"%b %d, %Y at %I:%M:%S %p {tz_abbrev}")


if __name__ == "__main__":
    # Test scheduler
    scheduler = Scheduler()

    # Test snipe datetime calculation
    snipe_date, snipe_time = scheduler.calculate_snipe_datetime(
        target_date="2026-02-14",
        days_advance=29,
        drop_time="10:00",
        timezone="America/New_York"
    )
    print(f"Target: Feb 14, 2026")
    print(f"Snipe:  {snipe_date} at {snipe_time}")
    print(f"Display: {format_snipe_datetime(snipe_date, snipe_time, 'America/New_York')}")

    # List current cron jobs
    print("\nCurrent Resy cron jobs:")
    for job in scheduler.list_scheduled_cron_jobs():
        print(f"  {job[:80]}...")
