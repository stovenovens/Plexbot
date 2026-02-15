"""
Server control commands
Handles server wake, shutdown, and status commands
Updated for Ubuntu 24.04 compatibility
"""

import logging
import paramiko
import time
from telegram.ext import CallbackContext
from telegram.constants import ParseMode
from wakeonlan import send_magic_packet

from config import (
    OFF_USER_IDS, PLEX_MAC, PLEX_BROADCAST_IP, 
    PLEX_SERVER_IP, PLEX_SSH_USER, PLEX_SSH_PASSWORD
)
from utils.helpers import send_command_response, escape_md
from utils.server_status import check_server_status

logger = logging.getLogger(__name__)

async def on_command(update, context: CallbackContext):
    """Manual wake-on-LAN command - checks status first"""
    try:
        is_online, status_message = await check_server_status()

        if is_online:
            logger.info("✅ Server already online - skipping WOL")
            await send_command_response(update, context, "✅ Server is already online\\!", parse_mode=ParseMode.MARKDOWN_V2)
            return

        send_magic_packet(PLEX_MAC, ip_address=PLEX_BROADCAST_IP)
        logger.info("✅ Manual WOL packet sent to %s via %s", PLEX_MAC, PLEX_BROADCAST_IP)
        await send_command_response(update, context, "🔌 Server is currently offline \\- sending wake command\\!", parse_mode=ParseMode.MARKDOWN_V2)
    except Exception as e:
        logger.error("❌ Manual WOL failed: %s", e)
        await send_command_response(update, context, f"❌ Wake\\-on\\-LAN failed: {escape_md(str(e))}", parse_mode=ParseMode.MARKDOWN_V2)

async def off_command(update, context: CallbackContext):
    """Shutdown server command (authorized users only)"""
    user_id = update.effective_user.id
    if user_id not in OFF_USER_IDS:
        return await send_command_response(update, context, "❌ Not authorized.")
    
    try:
        logger.info("🔌 Attempting to shutdown server %s", PLEX_SERVER_IP)
        
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        
        # Connect with longer timeout for Ubuntu 24.04
        ssh.connect(
            PLEX_SERVER_IP, 
            username=PLEX_SSH_USER, 
            password=PLEX_SSH_PASSWORD,
            timeout=10
        )
        
        # Try multiple shutdown methods for Ubuntu 24.04 compatibility
        shutdown_commands = [
            'sudo -S shutdown -h now',     # Traditional method
            'sudo -S poweroff',             # Alternative method
            'sudo -S systemctl poweroff'    # Systemd method
        ]
        
        success = False
        for i, cmd in enumerate(shutdown_commands):
            try:
                logger.info("🔌 Trying shutdown method %d: %s", i + 1, cmd)
                
                stdin, stdout, stderr = ssh.exec_command(cmd, get_pty=True, timeout=30)
                
                # Send password
                stdin.write(PLEX_SSH_PASSWORD + '\n')
                stdin.flush()
                
                # Wait a bit for command to process
                time.sleep(2)
                
                # Check if command executed (stderr should be empty or contain expected output)
                error_output = stderr.read().decode('utf-8').strip()
                stdout_output = stdout.read().decode('utf-8').strip()
                
                logger.info("🔌 Command output: stdout='%s', stderr='%s'", stdout_output, error_output)
                
                # If no critical errors, consider it successful
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
            logger.info("✅ Shutdown command sent to %s", PLEX_SERVER_IP)
            await send_command_response(update, context, "🔌 Plex server is shutting down.")
        else:
            logger.error("❌ All shutdown methods failed")
            await send_command_response(update, context, "❌ Shutdown failed - all methods exhausted.")
            
    except paramiko.AuthenticationException:
        logger.error("❌ SSH Authentication failed")
        await send_command_response(update, context, "❌ SSH authentication failed.")
    except paramiko.SSHException as ssh_error:
        logger.error("❌ SSH connection failed: %s", ssh_error)
        await send_command_response(update, context, "❌ SSH connection failed.")
    except Exception as e:
        logger.error("❌ Shutdown failed: %s", e)
        await send_command_response(update, context, "❌ Shutdown failed.")

async def check_status_command(update, context: CallbackContext):
    """Manually check server status without waking"""
    try:
        await send_command_response(update, context, "🔍 Checking server status\\.\\.\\.", parse_mode=ParseMode.MARKDOWN_V2)
        
        is_online, status_message = await check_server_status()
        
        if is_online:
            msg = f"✅ *Server Status: ONLINE*\n\n"
            msg += f"Status: {escape_md(status_message)}\n"
            msg += "Server is responding to requests\\."
        else:
            msg = f"❌ *Server Status: OFFLINE*\n\n"
            msg += f"Status: {escape_md(status_message)}\n"
            msg += "Use `/on` to wake the server\\."
        
        await send_command_response(update, context, msg, parse_mode=ParseMode.MARKDOWN_V2)
        
    except Exception as e:
        logger.error("❌ Status check command failed: %s", e)
        await send_command_response(update, context, f"❌ Status check failed: {escape_md(str(e))}", parse_mode=ParseMode.MARKDOWN_V2)