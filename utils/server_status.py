"""
Server status checking and wake functionality
Handles WOL, server status detection, and scheduled tasks
Fixed to properly check Plex server IP instead of relying on external Tautulli
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
    """Check if the Plex server is actually running by testing the actual server IP"""
    try:
        # Priority 1: Check the actual Plex server directly (most reliable)
        if PLEX_SERVER_IP:
            try:
                async with AsyncClient(timeout=5.0) as client:
                    # Try common Plex ports
                    for port in [32400, 32401]:  # Try main port and alt port
                        try:
                            plex_url = f"http://{PLEX_SERVER_IP}:{port}/identity"
                            resp = await client.get(plex_url)
                            if resp.status_code == 200:
                                logger.info("✅ Plex server online - Direct check successful on port %s", port)
                                return True, f"Direct Plex check (port {port})"
                        except Exception:
                            continue  # Try next port
                    
                    # If direct Plex check fails, server is definitely offline
                    logger.info("❌ Plex server offline - Direct check failed on all ports")
                    return False, "Direct Plex check failed"
                    
            except Exception as e:
                logger.debug("❌ Direct Plex check failed: %s", e)
                # Continue to secondary checks
        
        # Priority 2: Check Jellyfin on the same server (if configured and on same IP)
        if JELLYFIN_URL and JELLYFIN_API_KEY and PLEX_SERVER_IP in JELLYFIN_URL:
            try:
                async with AsyncClient(timeout=5.0) as client:
                    jellyfin_url = JELLYFIN_URL.rstrip('/') + f"/Sessions?api_key={JELLYFIN_API_KEY}"
                    resp = await client.get(jellyfin_url)
                    if resp.status_code == 200:
                        logger.info("✅ Server online via Jellyfin check (same server)")
                        return True, "Jellyfin check (same server)"
            except Exception as e:
                logger.debug("❌ Jellyfin check failed: %s", e)
        
        # If we get here, all checks on the actual server failed
        logger.info("❌ Server appears to be offline - all checks on %s failed", PLEX_SERVER_IP)
        return False, f"All checks on {PLEX_SERVER_IP} failed"
        
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
        # Check if server is actually running
        logger.info("🔍 Checking if Plex server (%s) is actually online...", PLEX_SERVER_IP)
        is_online, status_message = await check_server_status()
        
        if is_online:
            # Server is already running - skip wake command and notification
            logger.info("✅ Plex server already online - skipping wake command and notification")
            logger.info("✅ Status: %s", status_message)
            return
        
        # Server is offline - proceed with wake
        logger.info("📤 Plex server offline - sending WOL packet...")
        logger.info("📤 Status: %s", status_message)
        send_magic_packet(PLEX_MAC, ip_address=PLEX_BROADCAST_IP)
        logger.info("✅ WOL packet sent successfully to %s via %s", PLEX_MAC, PLEX_BROADCAST_IP)
        
        # Send Telegram notification to bot topic
        logger.info("📱 Sending Telegram notification to bot topic %s...", BOT_TOPIC_ID)
        message_text = f"🔌 Plex server auto-start at {melbourne_time.strftime('%H:%M')} (Server was offline)"
        await send_to_bot_topic(bot, message_text)
        
    except Exception as e:
        logger.error("❌ Auto-wake failed: %s", e, exc_info=True)  # Include full traceback
        try:
            error_message = f"❌ Auto-wake failed at {melbourne_time.strftime('%H:%M')}: {str(e)}"
            await send_to_bot_topic(bot, error_message)
            logger.info("✅ Error notification sent to bot topic")
        except Exception as telegram_error:
            logger.error("❌ Failed to send error notification to bot topic: %s", telegram_error)