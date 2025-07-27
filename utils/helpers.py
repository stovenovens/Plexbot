"""
Helper functions and utilities
Shared functionality used across the bot
"""

import logging
from telegram.ext import CallbackContext
from telegram.constants import ParseMode
from telegram import Bot
from config import GROUP_CHAT_ID, BOT_TOPIC_ID, SILENT_NOTIFICATIONS

logger = logging.getLogger(__name__)

def escape_md(text: str) -> str:
    """Escape markdown V2 special characters"""
    if text is None:
        return ""
    text = str(text)  # Convert to string in case it's a number
    for ch in ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']:
        text = text.replace(ch, f"\\{ch}")
    return text

def safe_format_number(number, decimal_places=1):
    """Safely format a number for Markdown V2"""
    try:
        if decimal_places == 0:
            formatted = f"{number:.0f}"
        else:
            formatted = f"{number:.{decimal_places}f}"
        return escape_md(formatted)
    except (ValueError, TypeError):
        return escape_md(str(number))

def format_duration(seconds):
    """Convert seconds to human readable duration"""
    if not seconds or seconds == 0:
        return "0m"
    
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    
    if hours > 0:
        return f"{hours}h {minutes}m"
    else:
        return f"{minutes}m"

async def send_command_response(update, context: CallbackContext, message: str, parse_mode=None, silent=None):
    """Send command response to bot topic instead of where command was issued"""
    # Use config setting if not explicitly specified
    if silent is None:
        silent = SILENT_NOTIFICATIONS
        
    try:
        # Always send to bot topic for cleaner general chat
        await context.bot.send_message(
            chat_id=GROUP_CHAT_ID,
            text=message,
            message_thread_id=BOT_TOPIC_ID,
            parse_mode=parse_mode,
            disable_notification=silent  # Make notifications silent
        )
        logger.info("✅ Command response sent to bot topic (silent: %s)", silent)
        
        # If command was issued outside bot topic, send a redirect message
        if update.message.message_thread_id != BOT_TOPIC_ID:
            redirect_msg = f"👀 Response sent to bot topic"
            await update.message.reply_text(redirect_msg, disable_notification=silent)
            logger.info("✅ Redirect message sent to original location (silent: %s)", silent)
            
    except Exception as e:
        logger.error("❌ Failed to send command response: %s", e)
        # Fallback: send to where command was issued
        try:
            await update.message.reply_text(message, parse_mode=parse_mode, disable_notification=silent)
            logger.info("✅ Command response sent as fallback to original location (silent: %s)", silent)
        except Exception as fallback_error:
            logger.error("❌ Failed to send response even as fallback: %s", fallback_error)

async def send_to_bot_topic(bot: Bot, message: str, parse_mode=None, silent=None):
    """Send a message to the dedicated bot topic"""
    # Use config setting if not explicitly specified
    if silent is None:
        silent = SILENT_NOTIFICATIONS
        
    try:
        await bot.send_message(
            chat_id=GROUP_CHAT_ID,
            text=message,
            message_thread_id=BOT_TOPIC_ID,
            parse_mode=parse_mode,
            disable_notification=silent  # Make notifications silent
        )
        logger.info("✅ Message sent to bot topic successfully (silent: %s)", silent)
    except Exception as e:
        logger.error("❌ Failed to send message to bot topic: %s", e)
        # Fallback: send to main group without topic
        try:
            await bot.send_message(
                chat_id=GROUP_CHAT_ID,
                text=message,
                parse_mode=parse_mode,
                disable_notification=silent  # Make notifications silent
            )
            logger.info("✅ Message sent to main group as fallback (silent: %s)", silent)
        except Exception as fallback_error:
            logger.error("❌ Failed to send message even as fallback: %s", fallback_error)
