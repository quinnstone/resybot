import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    RESY_EMAIL = os.getenv("RESY_EMAIL")
    RESY_PASSWORD = os.getenv("RESY_PASSWORD")
