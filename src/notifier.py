"""
Notifier

Sends email notifications for snipe results.
"""
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional
from src.job_store import Job, JobStatus


class NotifierError(Exception):
    """Error sending notification"""
    pass


class EmailNotifier:
    """
    Sends email notifications via SMTP (Gmail).

    Required environment variables:
        NOTIFY_EMAIL: Email address to send notifications to
        SMTP_EMAIL: Gmail address to send from
        SMTP_PASSWORD: Gmail App Password (not your regular password)
    """

    def __init__(self):
        self.to_email = os.getenv('NOTIFY_EMAIL')
        self.from_email = os.getenv('SMTP_EMAIL')
        self.password = os.getenv('SMTP_PASSWORD')
        self.smtp_server = os.getenv('SMTP_SERVER', 'smtp.gmail.com')
        self.smtp_port = int(os.getenv('SMTP_PORT', '587'))

    def is_configured(self) -> bool:
        """Check if email is configured"""
        return all([
            self.to_email,
            self.from_email,
            self.password
        ])

    def send_email(self, subject: str, body: str) -> bool:
        """
        Send an email.

        Args:
            subject: Email subject
            body: Email body (plain text)

        Returns:
            True if sent successfully

        Raises:
            NotifierError if sending fails
        """
        if not self.is_configured():
            raise NotifierError(
                "Email not configured. Set NOTIFY_EMAIL, SMTP_EMAIL, "
                "and SMTP_PASSWORD environment variables."
            )

        try:
            msg = MIMEMultipart()
            msg['From'] = self.from_email
            msg['To'] = self.to_email
            msg['Subject'] = subject

            msg.attach(MIMEText(body, 'plain'))

            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                server.starttls()
                server.login(self.from_email, self.password)
                server.send_message(msg)

            return True
        except Exception as e:
            raise NotifierError(f"Failed to send email: {e}")

    def notify_success(self, job: Job, reservation_id: str):
        """Send success notification"""
        subject = f"RESY SUCCESS - {job.venue_name} on {job.target_date}"
        body = f"""Your reservation has been confirmed!

Venue: {job.venue_name}
Date: {job.target_date}
Time Window: {job.time_start} - {job.time_end}
Party Size: {job.party_size}
Reservation ID: {reservation_id}

This reservation was automatically booked by Resy Sniper.
"""
        self._safe_send(subject, body)

    def notify_failure(self, job: Job, error: str):
        """Send failure notification"""
        subject = f"RESY FAILED - {job.venue_name} on {job.target_date}"
        body = f"""Failed to book reservation.

Venue: {job.venue_name}
Date: {job.target_date}
Time Window: {job.time_start} - {job.time_end}
Party Size: {job.party_size}

Error: {error}

You may want to try booking manually on resy.com.
"""
        self._safe_send(subject, body)

    def notify_job_scheduled(self, job: Job, snipe_datetime: str):
        """Send notification when a job is scheduled"""
        subject = f"Resy Snipe Scheduled - {job.venue_name}"
        body = f"""Your snipe has been scheduled!

Venue: {job.venue_name}
Target Date: {job.target_date}
Time Window: {job.time_start} - {job.time_end}
Party Size: {job.party_size}

Snipe will run at: {snipe_datetime}

Make sure your computer is running at this time!
"""
        self._safe_send(subject, body)

    def _safe_send(self, subject: str, body: str):
        """Send email, logging errors instead of raising"""
        if not self.is_configured():
            print(f"[Notifier] Email not configured, skipping notification")
            return

        try:
            self.send_email(subject, body)
            print(f"[Notifier] Email sent successfully to {self.to_email}")
        except NotifierError as e:
            print(f"[Notifier] Failed to send email: {e}")


class ConsoleNotifier:
    """Fallback notifier that just prints to console"""

    def notify_success(self, job: Job, reservation_id: str):
        print("\n" + "=" * 50)
        print("SUCCESS! RESERVATION CONFIRMED")
        print("=" * 50)
        print(f"  Venue:          {job.venue_name}")
        print(f"  Date:           {job.target_date}")
        print(f"  Reservation ID: {reservation_id}")
        print("=" * 50)

    def notify_failure(self, job: Job, error: str):
        print("\n" + "=" * 50)
        print("FAILED - RESERVATION NOT BOOKED")
        print("=" * 50)
        print(f"  Venue: {job.venue_name}")
        print(f"  Date:  {job.target_date}")
        print(f"  Error: {error}")
        print("=" * 50)


def get_notifier() -> EmailNotifier:
    """Get the configured notifier"""
    return EmailNotifier()


def notify_result(job: Job, success: bool, result: str):
    """
    Send notification about job result.

    Tries email first, falls back to console.
    """
    email = EmailNotifier()
    console = ConsoleNotifier()

    if success:
        console.notify_success(job, result)
        if email.is_configured():
            email.notify_success(job, result)
    else:
        console.notify_failure(job, result)
        if email.is_configured():
            email.notify_failure(job, result)


if __name__ == "__main__":
    # Test notification
    notifier = EmailNotifier()
    print(f"Email configured: {notifier.is_configured()}")

    if notifier.is_configured():
        print("Sending test email...")
        try:
            notifier.send_email(
                "Test - Resy Sniper",
                "This is a test email from Resy Sniper."
            )
            print("Test email sent!")
        except NotifierError as e:
            print(f"Failed: {e}")
    else:
        print("\nTo configure email notifications, set these environment variables:")
        print("  NOTIFY_EMAIL=quinnstone99@gmail.com")
        print("  SMTP_EMAIL=your_gmail@gmail.com")
        print("  SMTP_PASSWORD=your_app_password")
