"""
Configuration — loads secrets from .env file.
"""
import os
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

API_TOKEN = os.getenv("API_TOKEN", "")
BOT_USERNAME = os.getenv("BOT_USERNAME", "abyabybot")

ABYASA_ID = int(os.getenv("ABYASA_ID", "0"))
AXEL_ID = int(os.getenv("AXEL_ID", "0"))
ELISA_ID = int(os.getenv("ELISA_ID", "0"))
RAFIF_ID = int(os.getenv("RAFIF_ID", "0"))

BARN_TELEGRAM_IDS = {
    "A": ABYASA_ID,
    "B": AXEL_ID,
}