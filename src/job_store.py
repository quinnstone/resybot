"""
Job Store

SQLite-backed storage for scheduled snipe jobs.
"""
import sqlite3
import json
from pathlib import Path
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Optional, List
from enum import Enum


class JobStatus(Enum):
    PENDING = "pending"
    SCHEDULED = "scheduled"  # Cron job created
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class Job:
    """A scheduled snipe job"""
    id: Optional[int]
    venue_id: int
    venue_name: str
    venue_slug: str
    target_date: str  # YYYY-MM-DD
    time_start: str   # HH:MM
    time_end: str     # HH:MM
    party_size: int
    priority_times: List[str]  # Generated from time window
    snipe_date: str   # YYYY-MM-DD - when cron runs
    snipe_time: str   # HH:MM:SS - when cron runs
    timezone: str
    status: JobStatus
    created_at: str
    result: Optional[str] = None  # Reservation ID or error message

    def to_dict(self) -> dict:
        d = asdict(self)
        d['status'] = self.status.value
        d['priority_times'] = json.dumps(self.priority_times)
        return d

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> 'Job':
        return cls(
            id=row['id'],
            venue_id=row['venue_id'],
            venue_name=row['venue_name'],
            venue_slug=row['venue_slug'],
            target_date=row['target_date'],
            time_start=row['time_start'],
            time_end=row['time_end'],
            party_size=row['party_size'],
            priority_times=json.loads(row['priority_times']),
            snipe_date=row['snipe_date'],
            snipe_time=row['snipe_time'],
            timezone=row['timezone'],
            status=JobStatus(row['status']),
            created_at=row['created_at'],
            result=row['result']
        )


class JobStore:
    """SQLite-backed job storage"""

    DB_PATH = Path(__file__).parent.parent / "data" / "jobs.db"

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or self.DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        """Create tables if they don't exist"""
        with self._get_conn() as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    venue_id INTEGER NOT NULL,
                    venue_name TEXT NOT NULL,
                    venue_slug TEXT NOT NULL,
                    target_date TEXT NOT NULL,
                    time_start TEXT NOT NULL,
                    time_end TEXT NOT NULL,
                    party_size INTEGER NOT NULL,
                    priority_times TEXT NOT NULL,
                    snipe_date TEXT NOT NULL,
                    snipe_time TEXT NOT NULL,
                    timezone TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at TEXT NOT NULL,
                    result TEXT
                )
            ''')
            conn.commit()

    def add_job(self, job: Job) -> int:
        """
        Add a new job to the store.

        Args:
            job: Job object (id will be ignored/auto-generated)

        Returns:
            The auto-generated job ID
        """
        with self._get_conn() as conn:
            cursor = conn.execute('''
                INSERT INTO jobs (
                    venue_id, venue_name, venue_slug, target_date,
                    time_start, time_end, party_size, priority_times,
                    snipe_date, snipe_time, timezone, status, created_at, result
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                job.venue_id,
                job.venue_name,
                job.venue_slug,
                job.target_date,
                job.time_start,
                job.time_end,
                job.party_size,
                json.dumps(job.priority_times),
                job.snipe_date,
                job.snipe_time,
                job.timezone,
                job.status.value,
                job.created_at,
                job.result
            ))
            conn.commit()
            return cursor.lastrowid

    def get_job(self, job_id: int) -> Optional[Job]:
        """Get a job by ID"""
        with self._get_conn() as conn:
            row = conn.execute(
                'SELECT * FROM jobs WHERE id = ?', (job_id,)
            ).fetchone()
            if row:
                return Job.from_row(row)
            return None

    def list_jobs(self, status: Optional[JobStatus] = None) -> List[Job]:
        """
        List all jobs, optionally filtered by status.

        Returns jobs ordered by snipe_date/snipe_time ascending.
        """
        with self._get_conn() as conn:
            if status:
                rows = conn.execute(
                    'SELECT * FROM jobs WHERE status = ? ORDER BY snipe_date, snipe_time',
                    (status.value,)
                ).fetchall()
            else:
                rows = conn.execute(
                    'SELECT * FROM jobs ORDER BY snipe_date, snipe_time'
                ).fetchall()
            return [Job.from_row(row) for row in rows]

    def list_pending_jobs(self) -> List[Job]:
        """List jobs that are pending or scheduled"""
        with self._get_conn() as conn:
            rows = conn.execute('''
                SELECT * FROM jobs
                WHERE status IN ('pending', 'scheduled')
                ORDER BY snipe_date, snipe_time
            ''').fetchall()
            return [Job.from_row(row) for row in rows]

    def update_status(self, job_id: int, status: JobStatus, result: Optional[str] = None):
        """Update job status and optionally set result"""
        with self._get_conn() as conn:
            if result is not None:
                conn.execute(
                    'UPDATE jobs SET status = ?, result = ? WHERE id = ?',
                    (status.value, result, job_id)
                )
            else:
                conn.execute(
                    'UPDATE jobs SET status = ? WHERE id = ?',
                    (status.value, job_id)
                )
            conn.commit()

    def delete_job(self, job_id: int) -> bool:
        """
        Delete a job by ID.

        Returns True if job was deleted, False if not found.
        """
        with self._get_conn() as conn:
            cursor = conn.execute('DELETE FROM jobs WHERE id = ?', (job_id,))
            conn.commit()
            return cursor.rowcount > 0

    def get_jobs_for_date(self, snipe_date: str) -> List[Job]:
        """Get all jobs scheduled for a specific snipe date"""
        with self._get_conn() as conn:
            rows = conn.execute(
                'SELECT * FROM jobs WHERE snipe_date = ? ORDER BY snipe_time',
                (snipe_date,)
            ).fetchall()
            return [Job.from_row(row) for row in rows]


if __name__ == "__main__":
    # Test the job store
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        store = JobStore(Path(tmpdir) / "test.db")

        # Create a test job
        job = Job(
            id=None,
            venue_id=6194,
            venue_name="Carbone",
            venue_slug="carbone",
            target_date="2026-02-14",
            time_start="19:00",
            time_end="21:00",
            party_size=2,
            priority_times=["19:00", "19:30", "20:00", "20:30", "21:00"],
            snipe_date="2026-01-16",
            snipe_time="09:59:50",
            timezone="America/New_York",
            status=JobStatus.PENDING,
            created_at=datetime.now().isoformat()
        )

        # Add job
        job_id = store.add_job(job)
        print(f"Created job with ID: {job_id}")

        # Retrieve job
        retrieved = store.get_job(job_id)
        print(f"Retrieved: {retrieved.venue_name} on {retrieved.target_date}")

        # List jobs
        jobs = store.list_jobs()
        print(f"Total jobs: {len(jobs)}")

        # Update status
        store.update_status(job_id, JobStatus.SCHEDULED)
        updated = store.get_job(job_id)
        print(f"Updated status: {updated.status}")

        print("\nAll tests passed!")
