"""
Server status checking and wake functionality
Handles WOL, server status detection, and scheduled tasks
"""

import logging
from datetime import datetime
from httpx import AsyncClient
from wakeonlan import send_magic_packet
from telegram import Bot

from config import (
    TAUTILLI_URL, TAUTILLI_API_KEY, JELLYFIN_URL, JELLYFIN_API_KEY,
    PLEX_SERVER_IP, PLEX_MAC, PLEX_BROADCAST_IP, MELBOURNE_TZ, BOT_TOPIC_ID
)
from utils.helpers import send_to_bot_topic

logger = logging.getLogger(__name__)

async def check_server_status():
    """Check if the Plex server is already running by testing multiple endpoints"""
    try:
        # Try multiple methods to check server status
        checks = []
        
        # Method 1: Try Tautulli (most reliable if configured)
        if TAUTILLI_URL and TAUTILLI_API_KEY:
            try:
                async with AsyncClient(timeout=5.0) as client:
                    taut_url = TAUTILLI_URL.rstrip('/') + f"/api/v2?apikey={TAUTILLI_API_KEY}&cmd=get_activity"
                    resp = await client.get(taut_url)
                    if resp.status_code == 200:
                        checks.append(("Tautulli", True))
                        logger.debug("✅ Server check via Tautulli: Online")
                    else:
                        checks.append(("Tautulli", False))
                        logger.debug("❌ Server check via Tautulli: Offline (status %d)", resp.status_code)
            except Exception as e:
                checks.append(("Tautulli", False))
                logger.debug("❌ Server check via Tautulli: Offline (%s)", str(e))
        
        # Method 2: Try Jellyfin (if configured)
        if JELLYFIN_URL and JELLYFIN_API_KEY:
            try:
                async with AsyncClient(timeout=5.0) as client:
                    jellyfin_url = JELLYFIN_URL.rstrip('/') + f"/Sessions?api_key={JELLYFIN_API_KEY}"
                    resp = await client.get(jellyfin_url)
                    if resp.status_code == 200:
                        checks.append(("Jellyfin", True))
                        logger.debug("✅ Server check via Jellyfin: Online")
                    else:
                        checks.append(("Jellyfin", False))
                        logger.debug("❌ Server check via Jellyfin: Offline (status %d)", resp.status_code)
            except Exception as e:
                checks.append(("Jellyfin", False))
                logger.debug("❌ Server check via Jellyfin: Offline (%s)", str(e))
        
        # Method 3: Try direct Plex server ping (if we have the IP)
        if PLEX_SERVER_IP:
            try:
                async with AsyncClient(timeout=3.0) as client:
                    # Try common Plex port
                    plex_url = f"http://{PLEX_SERVER_IP}:32400/identity"
                    resp = await client.get(plex_url)
                    if resp.status_code == 200:
                        checks.append(("Plex Direct", True))
                        logger.debug("✅ Server check via Plex Direct: Online")
                    else:
                        checks.append(("Plex Direct", False))
                        logger.debug("❌ Server check via Plex Direct: Offline (status %d)", resp.status_code)
            except Exception as e:
                checks.append(("Plex Direct", False))
                logger.debug("❌ Server check via Plex Direct: Offline (%s)", str(e))
        
        # Evaluate results
        if not checks:
            logger.warning("⚠️ No server check methods available - proceeding with wake")
            return False, "No check methods configured"
        
        # Server is considered online if ANY method succeeds
        online_checks = [check for check in checks if check[1]]
        if online_checks:
            online_methods = [check[0] for check in online_checks]
            logger.info("✅ Server is already online (verified via: %s)", ", ".join(online_methods))
            return True, f"Online via {', '.join(online_methods)}"
        else:
            offline_methods = [check[0] for check in checks]
            logger.info("❌ Server appears to be offline (checked: %s)", ", ".join(offline_methods))
            return False, f"Offline - checked {', '.join(offline_methods)}"
            
    except Exception as e:
        logger.error("❌ Error checking server status: %s", e)
        return False, f"Check failed: {str(e)}"

async def scheduled_wake(bot: Bot):
    """Scheduled wake function called by the scheduler"""
    melbourne_time = datetime.now(MELBOURNE_TZ)
    logger.info("⏰ Auto-wake job triggered at %s (Melbourne time)", melbourne_time.strftime('%Y-%m-%d %H:%M:%S %Z'))
    
    # Log system status
    logger.info("🔍 Pre-wake check - MAC: %s, Broadcast: %s, Topic ID: %s", 
                PLEX_MAC, PLEX_BROADCAST_IP, BOT_TOPIC_ID)
    
    try:
        # Check if server is already running
        logger.info("🔍 Checking if server is already online...")
        is_online, status_message = await check_server_status()
        
        if is_online:
            # Server is already running - skip wake command and notification
            logger.info("✅ Server already online - skipping wake command and notification")
            return
        
        # Server is offline - proceed with wake
        logger.info("📤 Server offline - sending WOL packet...")
        send_magic_packet(PLEX_MAC, ip_address=PLEX_BROADCAST_IP)
        logger.info("✅ WOL packet sent successfully to %s via %s", PLEX_MAC, PLEX_BROADCAST_IP)
        
        # Send Telegram notification to bot topic
        logger.info("📱 Sending Telegram notification to bot topic %s...", BOT_TOPIC_ID)
        message_text = f"🔌 Plex server auto-start at {melbourne_time.strftime('%H:%M')} ({status_message})"
        await send_to_bot_topic(bot, message_text)
        
    except Exception as e:
        logger.error("❌ Auto-wake failed: %s", e, exc_info=True)  # Include full traceback
        try:
            error_message = f"❌ Auto-wake failed at {melbourne_time.strftime('%H:%M')}: {str(e)}"
            await send_to_bot_topic(bot, error_message)
            logger.info("✅ Error notification sent to bot topic")
        except Exception as telegram_error:
            logger.error("❌ Failed to send error notification to bot topic: %s", telegram_error)
