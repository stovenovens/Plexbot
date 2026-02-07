"""
Server status checking and wake functionality
Handles WOL, server status detection, and scheduled tasks
"""

import logging
import paramiko
import time
from datetime import datetime
from httpx import AsyncClient
from wakeonlan import send_magic_packet
from telegram import Bot

from config import (
    PLEX_SERVER_IP, PLEX_MAC, PLEX_BROADCAST_IP, MELBOURNE_TZ, BOT_TOPIC_ID,
    PLEX_SSH_USER, PLEX_SSH_PASSWORD, TAUTILLI_URL, TAUTILLI_API_KEY,
    AUTO_SHUTDOWN_RECHECK_MINUTES
)
from utils.helpers import send_to_bot_topic

logger = logging.getLogger(__name__)

async def check_server_status():
    """Check if the Plex server is actually running by testing the actual server IP"""
    try:
        # Check the actual Plex server directly
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
                return False, f"Plex check failed: {str(e)}"

        # If we get here, no server IP configured
        logger.error("❌ No Plex server IP configured")
        return False, "No server IP configured"

    except Exception as e:
        logger.error("❌ Error checking server status: %s", e)
        return False, f"Check failed: {str(e)}"

async def scheduled_wake(bot: Bot):
    """Scheduled wake function called by the scheduler"""
    melbourne_time = datetime.now(MELBOURNE_TZ)
    logger.info("⏰ Auto-wake job triggered at %s (Melbourne time)", melbourne_time.strftime('%Y-%m-%d %H:%M:%S %Z'))
    
    # Log system status
    logger.info("🔍 Pre-wake check - MAC: %s, Broadcast: %s, Topic ID: %s",
                PLEX_MAC, PLEX_BROADCAST_IP, BOT_TOPIC_ID if BOT_TOPIC_ID else "Not configured")
    
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

async def check_active_streams():
    """Check if there are any active streams on Plex via Tautulli"""
    try:
        if not (TAUTILLI_URL and TAUTILLI_API_KEY):
            logger.warning("⚠️ Tautulli not configured - cannot check for active streams")
            return False, "Tautulli not configured"

        async with AsyncClient(timeout=10.0) as client:
            taut_url = TAUTILLI_URL.rstrip('/') + f"/api/v2?apikey={TAUTILLI_API_KEY}&cmd=get_activity"
            resp = await client.get(taut_url)
            resp.raise_for_status()
            taut_data = resp.json().get("response", {}).get("data", {})
            sessions = taut_data.get("sessions", [])

            stream_count = len(sessions)

            if stream_count > 0:
                # Get details of active streams
                stream_details = []
                for s in sessions[:3]:  # Show first 3 streams
                    user = s.get("username", "Unknown")
                    title = s.get("title", "Unknown")
                    stream_details.append(f"{user} watching {title}")

                logger.info("🎥 Active streams detected: %d stream(s)", stream_count)
                for detail in stream_details:
                    logger.info("   - %s", detail)

                return True, f"{stream_count} active stream(s)"
            else:
                logger.info("✅ No active streams detected")
                return False, "No active streams"

    except Exception as e:
        logger.error("❌ Failed to check active streams: %s", e)
        # On error, assume there might be streams (safe default)
        return True, f"Error checking streams: {str(e)}"

def execute_shutdown():
    """Execute server shutdown via SSH - synchronous version for scheduler"""
    try:
        logger.info("🔌 Attempting to shutdown server %s", PLEX_SERVER_IP)

        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        # Connect with timeout
        ssh.connect(
            PLEX_SERVER_IP,
            username=PLEX_SSH_USER,
            password=PLEX_SSH_PASSWORD,
            timeout=10
        )

        # Try multiple shutdown methods
        shutdown_commands = [
            'sudo -S shutdown -h now',
            'sudo -S poweroff',
            'sudo -S systemctl poweroff'
        ]

        success = False
        for i, cmd in enumerate(shutdown_commands):
            try:
                logger.info("🔌 Trying shutdown method %d: %s", i + 1, cmd)

                stdin, stdout, stderr = ssh.exec_command(cmd, get_pty=True, timeout=30)

                # Send password
                stdin.write(PLEX_SSH_PASSWORD + '\n')
                stdin.flush()

                # Wait for command to process
                time.sleep(2)

                # Check output
                error_output = stderr.read().decode('utf-8').strip()
                stdout_output = stdout.read().decode('utf-8').strip()

                logger.info("🔌 Command output: stdout='%s', stderr='%s'", stdout_output, error_output)

                # If no critical errors, consider successful
                if not error_output or 'shutdown scheduled' in error_output.lower() or len(error_output) < 50:
                    logger.info("✅ Shutdown command successful with method %d", i + 1)
                    success = True
                    break
                else:
                    logger.warning("⚠️ Method %d failed with error: %s", i + 1, error_output)

            except Exception as cmd_error:
                logger.warning("⚠️ Shutdown method %d failed: %s", i + 1, str(cmd_error))
                continue

        ssh.close()

        if success:
            logger.info("✅ Shutdown command sent successfully")
            return True, "Shutdown initiated"
        else:
            logger.error("❌ All shutdown methods failed")
            return False, "All shutdown methods failed"

    except Exception as e:
        logger.error("❌ Shutdown execution failed: %s", e)
        return False, f"Shutdown failed: {str(e)}"

async def scheduled_shutdown(bot: Bot, app):
    """Scheduled shutdown function - checks for active streams before shutting down"""
    melbourne_time = datetime.now(MELBOURNE_TZ)
    logger.info("⏰ Auto-shutdown job triggered at %s (Melbourne time)", melbourne_time.strftime('%Y-%m-%d %H:%M:%S %Z'))

    try:
        # Check if server is actually online
        logger.info("🔍 Checking if Plex server is online...")
        is_online, status_message = await check_server_status()

        if not is_online:
            logger.info("✅ Server already offline - no shutdown needed")
            logger.info("✅ Status: %s", status_message)
            return

        logger.info("🔍 Server is online - checking for active streams...")

        # Check for active streams
        has_streams, stream_status = await check_active_streams()

        if has_streams:
            # There are active streams - schedule recheck
            logger.info("⏸️ Active streams detected - delaying shutdown")
            logger.info("⏸️ Stream status: %s", stream_status)
            logger.info("⏸️ Will recheck in %d minutes", AUTO_SHUTDOWN_RECHECK_MINUTES)

            # Send notification about delayed shutdown
            message_text = f"⏸️ Auto-shutdown delayed at {melbourne_time.strftime('%H:%M')}\n{stream_status}\nWill check again in {AUTO_SHUTDOWN_RECHECK_MINUTES} minutes"
            await send_to_bot_topic(bot, message_text)

            # Schedule a recheck
            from apscheduler.triggers.date import DateTrigger
            from datetime import timedelta

            recheck_time = datetime.now(MELBOURNE_TZ) + timedelta(minutes=AUTO_SHUTDOWN_RECHECK_MINUTES)
            logger.info("📅 Scheduling recheck at %s", recheck_time.strftime('%Y-%m-%d %H:%M:%S %Z'))

            # Access scheduler from app
            if hasattr(app, 'job_queue') and app.job_queue:
                # Use job_queue for one-time jobs
                app.job_queue.run_once(
                    lambda context: scheduled_shutdown(bot, app),
                    when=AUTO_SHUTDOWN_RECHECK_MINUTES * 60,  # seconds
                    name='auto_shutdown_recheck'
                )
                logger.info("✅ Recheck scheduled via job_queue")
            else:
                # Fallback: use main scheduler if available
                import sys
                if 'main' in sys.modules:
                    main_module = sys.modules['main']
                    if hasattr(main_module, 'scheduler') and main_module.scheduler:
                        scheduler = main_module.scheduler
                        scheduler.add_job(
                            scheduled_shutdown,
                            DateTrigger(run_date=recheck_time),
                            args=[bot, app],
                            id=f'auto_shutdown_recheck_{recheck_time.timestamp()}',
                            replace_existing=False
                        )
                        logger.info("✅ Recheck scheduled via main scheduler")

            return

        # No active streams - proceed with shutdown
        logger.info("✅ No active streams - proceeding with shutdown")
        logger.info("✅ Stream status: %s", stream_status)

        # Execute shutdown
        success, shutdown_status = execute_shutdown()

        if success:
            message_text = f"🔌 Auto-shutdown at {melbourne_time.strftime('%H:%M')}\nNo active streams detected\nServer shutting down..."
            logger.info("✅ Shutdown successful - sending notification")
        else:
            message_text = f"❌ Auto-shutdown failed at {melbourne_time.strftime('%H:%M')}\n{shutdown_status}"
            logger.error("❌ Shutdown failed: %s", shutdown_status)

        await send_to_bot_topic(bot, message_text)

    except Exception as e:
        logger.error("❌ Auto-shutdown failed: %s", e, exc_info=True)
        try:
            error_message = f"❌ Auto-shutdown error at {melbourne_time.strftime('%H:%M')}: {str(e)}"
            await send_to_bot_topic(bot, error_message)
            logger.info("✅ Error notification sent to bot topic")
        except Exception as telegram_error:
            logger.error("❌ Failed to send error notification: %s", telegram_error)