"""
Configuration settings for Plex Bot
All environment variables and constants
"""

import os
import logging
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Get logger
logger = logging.getLogger(__name__)

# --- Telegram Configuration ---
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
GROUP_CHAT_ID = int(os.getenv("GROUP_CHAT_ID", "0"))
BOT_TOPIC_ID = int(os.getenv("BOT_TOPIC_ID", "15980"))  # Dedicated bot topic

# Silent notifications setting (True = silent, False = with sound)
SILENT_NOTIFICATIONS = os.getenv("SILENT_NOTIFICATIONS", "true").lower() == "true"

# Auto-wake schedule configuration
WEEKDAY_WAKE_HOUR = int(os.getenv("WEEKDAY_WAKE_HOUR", "17"))
WEEKDAY_WAKE_MINUTE = int(os.getenv("WEEKDAY_WAKE_MINUTE", "30"))
WEEKEND_WAKE_HOUR = int(os.getenv("WEEKEND_WAKE_HOUR", "18"))
WEEKEND_WAKE_MINUTE = int(os.getenv("WEEKEND_WAKE_MINUTE", "0"))

# Auto-shutdown configuration
AUTO_SHUTDOWN_ENABLED = os.getenv("AUTO_SHUTDOWN_ENABLED", "false").lower() == "true"
AUTO_SHUTDOWN_HOUR = int(os.getenv("AUTO_SHUTDOWN_HOUR", "1"))
AUTO_SHUTDOWN_MINUTE = int(os.getenv("AUTO_SHUTDOWN_MINUTE", "0"))
AUTO_SHUTDOWN_RECHECK_MINUTES = int(os.getenv("AUTO_SHUTDOWN_RECHECK_MINUTES", "30"))

# Telegram user IDs allowed to run /off and admin commands
OFF_USER_IDS = {int(uid) for uid in os.getenv("OFF_USER_IDS", "").split(",") if uid.strip()}

# --- API Tokens ---
TMDB_BEARER_TOKEN = os.getenv("TMDB_API_READ_TOKEN", "")

# Tautulli configuration
TAUTILLI_URL = os.getenv("TAUTILLI_URL", "")
TAUTILLI_API_KEY = os.getenv("TAUTILLI_API_KEY", "")

# Sonarr/Radarr API config
SONARR_URL = os.getenv("SONARR_URL", "")
SONARR_API_KEY = os.getenv("SONARR_API_KEY", "")
RADARR_URL = os.getenv("RADARR_URL", "")
RADARR_API_KEY = os.getenv("RADARR_API_KEY", "")

# --- Hardware Configuration ---
# Wake-on-LAN
PLEX_MAC = os.getenv("PLEX_SERVER_MAC", "")
PLEX_BROADCAST_IP = os.getenv("PLEX_SERVER_BROADCAST", "192.168.1.255")

# SSH shutdown config
PLEX_SSH_USER = os.getenv("PLEX_SSH_USER", "")
PLEX_SERVER_IP = os.getenv("PLEX_SERVER_IP", "")
PLEX_SSH_PASSWORD = os.getenv("PLEX_SSH_PASSWORD", None)

# --- Other Settings ---
# Timezone
MELBOURNE_TZ = ZoneInfo("Australia/Melbourne")

# --- Validation ---
# Validate required vars
if not (BOT_TOKEN and GROUP_CHAT_ID and TMDB_BEARER_TOKEN and TAUTILLI_URL and TAUTILLI_API_KEY):
    logger.error("Missing required environment variables. Check .env configuration.")
    exit(1)

# Validate WOL config
if not PLEX_MAC or not PLEX_BROADCAST_IP:
    logger.warning("⚠️ Wake-on-LAN not configured properly")

# Log configuration
logger.info("📱 Bot topic ID configured: %s", BOT_TOPIC_ID)
logger.info("🔇 Silent notifications: %s", SILENT_NOTIFICATIONS)
logger.info("⏰ Auto-wake schedule - Weekdays: %02d:%02d, Weekends: %02d:%02d", 
            WEEKDAY_WAKE_HOUR, WEEKDAY_WAKE_MINUTE, WEEKEND_WAKE_HOUR, WEEKEND_WAKE_MINUTE)
