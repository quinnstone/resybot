"""
Scheduler

Manages launchd jobs for scheduled snipe operations on macOS.
"""
import os
import plistlib
import subprocess
import sys
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional

from src.job_store import Job, JobStatus, JobStore


class SchedulerError(Exception):
    """Error managing scheduled jobs"""
    pass


class Scheduler:
    """Manages launchd jobs for snipe scheduling"""

    # Prefix for our launchd job labels
    LAUNCHD_PREFIX = "com.resy.snipe.job"

    def __init__(self):
        self.project_root = Path(__file__).parent.parent.absolute()
        self.python_path = self._find_python()
        self.job_store = JobStore()
        self.launch_agents_dir = Path.home() / "Library" / "LaunchAgents"
        self.launch_agents_dir.mkdir(parents=True, exist_ok=True)

    def _find_python(self) -> str:
        """Find the Python executable, preferring venv if available"""
        venv_python = self.project_root / "venv" / "bin" / "python"
        if venv_python.exists():
            return str(venv_python)
        venv_python3 = self.project_root / "venv" / "bin" / "python3"
        if venv_python3.exists():
            return str(venv_python3)
        return sys.executable

    def _get_plist_path(self, job_id: int) -> Path:
        """Get the plist file path for a job"""
        return self.launch_agents_dir / f"{self.LAUNCHD_PREFIX}.{job_id}.plist"

    def _get_label(self, job_id: int) -> str:
        """Get the launchd label for a job"""
        return f"{self.LAUNCHD_PREFIX}.{job_id}"

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
        Create a launchd job for the given snipe job.

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

        # Build the command arguments
        resy_cli = self.project_root / "resy.py"
        log_file = self.project_root / "logs" / f"job_{job.id}.log"
        log_file.parent.mkdir(parents=True, exist_ok=True)

        label = self._get_label(job.id)
        plist_path = self._get_plist_path(job.id)

        # Create the launchd plist
        plist_content = {
            'Label': label,
            'ProgramArguments': [
                self.python_path,
                str(resy_cli),
                'run',
                str(job.id)
            ],
            'WorkingDirectory': str(self.project_root),
            'StartCalendarInterval': {
                'Month': snipe_dt.month,
                'Day': snipe_dt.day,
                'Hour': snipe_dt.hour,
                'Minute': snipe_dt.minute,
            },
            'StandardOutPath': str(log_file),
            'StandardErrorPath': str(log_file),
            'EnvironmentVariables': {
                'PATH': '/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin',
                'HOME': str(Path.home()),
            },
        }

        try:
            # Unload existing job if present
            self._unload_job(label)

            # Write plist file
            with open(plist_path, 'wb') as f:
                plistlib.dump(plist_content, f)

            # Load the job
            result = subprocess.run(
                ['launchctl', 'load', str(plist_path)],
                capture_output=True,
                text=True
            )

            if result.returncode != 0:
                raise SchedulerError(f"Failed to load launchd job: {result.stderr}")

            self.job_store.update_status(job.id, JobStatus.SCHEDULED)
            return True

        except Exception as e:
            raise SchedulerError(f"Failed to create launchd job: {e}")

    def unschedule_job(self, job_id: int) -> bool:
        """
        Remove the launchd job for a given job ID.

        Returns:
            True if job was found and removed
        """
        label = self._get_label(job_id)
        plist_path = self._get_plist_path(job_id)

        unloaded = self._unload_job(label)

        # Remove plist file
        if plist_path.exists():
            plist_path.unlink()
            return True

        return unloaded

    def _unload_job(self, label: str) -> bool:
        """Unload a launchd job by label"""
        result = subprocess.run(
            ['launchctl', 'remove', label],
            capture_output=True,
            text=True
        )
        return result.returncode == 0

    def list_scheduled_launchd_jobs(self) -> list[dict]:
        """List all our launchd jobs"""
        jobs = []

        # Check for plist files
        for plist_file in self.launch_agents_dir.glob(f"{self.LAUNCHD_PREFIX}.*.plist"):
            try:
                with open(plist_file, 'rb') as f:
                    plist_data = plistlib.load(f)
                    jobs.append({
                        'label': plist_data.get('Label'),
                        'path': str(plist_file),
                        'schedule': plist_data.get('StartCalendarInterval', {})
                    })
            except Exception:
                pass

        return jobs

    def is_job_loaded(self, job_id: int) -> bool:
        """Check if a launchd job is currently loaded"""
        label = self._get_label(job_id)
        result = subprocess.run(
            ['launchctl', 'list', label],
            capture_output=True,
            text=True
        )
        return result.returncode == 0

    def sync_with_store(self):
        """
        Sync launchd jobs with job store.
        Removes launchd entries for jobs that no longer exist or are completed.
        """
        for plist_file in self.launch_agents_dir.glob(f"{self.LAUNCHD_PREFIX}.*.plist"):
            try:
                # Extract job ID from filename
                parts = plist_file.stem.split('.')
                job_id = int(parts[-1])

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


# Keep backward compatibility for removing old cron jobs
def remove_legacy_cron_jobs():
    """Remove any old cron-based Resy jobs"""
    try:
        result = subprocess.run(['crontab', '-l'], capture_output=True, text=True)
        if result.returncode != 0:
            return

        lines = result.stdout.strip().split('\n')
        new_lines = [l for l in lines if 'RESY_SNIPE_JOB' not in l]

        if len(new_lines) < len(lines):
            if new_lines:
                process = subprocess.Popen(['crontab', '-'], stdin=subprocess.PIPE, text=True)
                process.communicate(input='\n'.join(new_lines) + '\n')
            else:
                subprocess.run(['crontab', '-r'], capture_output=True)
            print("  Removed legacy cron jobs")
    except Exception:
        pass


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

    # List current launchd jobs
    print("\nCurrent Resy launchd jobs:")
    for job in scheduler.list_scheduled_launchd_jobs():
        print(f"  {job['label']}: {job['schedule']}")
