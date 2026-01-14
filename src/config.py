import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    # Resy Credentials
    RESY_EMAIL = os.getenv("RESY_EMAIL")
    RESY_PASSWORD = os.getenv("RESY_PASSWORD")
    RESY_VENUE_URL = os.getenv("RESY_VENUE_URL", "https://resy.com/cities/new-york-ny/venues/the-four-horsemen")
    PARTY_SIZE = int(os.getenv("PARTY_SIZE", "2"))
    TARGET_DATE = os.getenv("TARGET_DATE")

    # Venue IDs - found via browser network tab on resy.com
    HORSEMEN_VENUE_ID = int(os.getenv("HORSEMEN_VENUE_ID", "2492"))  # Four Horsemen
    TEST_VENUE_ID_1 = int(os.getenv("TEST_VENUE_ID_1", "0"))  # Lilia
    TEST_VENUE_ID_2 = int(os.getenv("TEST_VENUE_ID_2", "0"))  # Smyth Tavern

    # Twilio SMS Notifications (optional)
    TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
    TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
    TWILIO_FROM_NUMBER = os.getenv("TWILIO_FROM_NUMBER")
    NOTIFY_PHONE_NUMBER = os.getenv("NOTIFY_PHONE_NUMBER")

    # Validation
    @classmethod
    def validate(cls):
        missing = []
        if not cls.RESY_EMAIL: missing.append("RESY_EMAIL")
        if not cls.RESY_PASSWORD: missing.append("RESY_PASSWORD")
        if not cls.TARGET_DATE: missing.append("TARGET_DATE")

        if missing:
            raise ValueError(f"Missing required environment variables: {', '.join(missing)}")

    @classmethod
    def is_sms_configured(cls) -> bool:
        """Check if SMS notifications are configured"""
        return all([
            cls.TWILIO_ACCOUNT_SID,
            cls.TWILIO_AUTH_TOKEN,
            cls.TWILIO_FROM_NUMBER,
            cls.NOTIFY_PHONE_NUMBER
        ])
