"""
Email notifications for snipe results.
"""
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart


class NotifierError(Exception):
    pass


class EmailNotifier:
    """
    Sends email notifications via Gmail SMTP.

    Required env vars: NOTIFY_EMAIL, SMTP_EMAIL, SMTP_PASSWORD
    """

    def __init__(self):
        self.to_email = os.getenv('NOTIFY_EMAIL')
        self.from_email = os.getenv('SMTP_EMAIL')
        self.password = os.getenv('SMTP_PASSWORD')
        self.smtp_server = os.getenv('SMTP_SERVER', 'smtp.gmail.com')
        self.smtp_port = int(os.getenv('SMTP_PORT', '587'))

    def is_configured(self) -> bool:
        return all([self.to_email, self.from_email, self.password])

    def send_email(self, subject: str, body: str) -> bool:
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
