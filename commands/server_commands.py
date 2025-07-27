"""
Server control commands
Handles server wake, shutdown, and status commands
"""

import logging
import paramiko
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
    """Manual wake-on-LAN command"""
    try:
        send_magic_packet(PLEX_MAC, ip_address=PLEX_BROADCAST_IP)
        logger.info("✅ Manual WOL packet sent to %s via %s", PLEX_MAC, PLEX_BROADCAST_IP)
        await send_command_response(update, context, "🔌 Sent Wake-on-LAN packet.")
    except Exception as e:
        logger.error("❌ Manual WOL failed: %s", e)
        await send_command_response(update, context, f"❌ Wake-on-LAN failed: {str(e)}")

async def off_command(update, context: CallbackContext):
    """Shutdown server command (authorized users only)"""
    user_id = update.effective_user.id
    if user_id not in OFF_USER_IDS:
        return await send_command_response(update, context, "❌ Not authorized.")
    
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(PLEX_SERVER_IP, username=PLEX_SSH_USER, password=PLEX_SSH_PASSWORD)
        stdin, stdout, stderr = ssh.exec_command('sudo -S shutdown -h now', get_pty=True)
        stdin.write(PLEX_SSH_PASSWORD + '\n')
        stdin.flush()
        ssh.close()
        logger.info("✅ Shutdown command sent to %s", PLEX_SERVER_IP)
        await send_command_response(update, context, "🔌 Plex server is shutting down.")
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
