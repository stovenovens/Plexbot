#!/usr/bin/env python3
"""
Plex Bot - Main Entry Point
Comprehensive Plex media server automation bot with request system
"""

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, filters
from telegram.error import NetworkError, TimedOut, RetryAfter, TelegramError
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from config import *
from utils.logging_setup import setup_logging
from utils.server_status import scheduled_wake, scheduled_shutdown
from commands.media_commands import nowplaying_command, upcoming_command, hot_command, stats_command, queue_command, search_plex_command
from commands.server_commands import on_command, off_command, check_status_command, remote_check_command
from commands.admin_commands import (
    debug_command, logs_command, testwake_command, info_command, welcome_command,
    requests_admin_command, clearrequest_command, clearrequests_command
)
from commands.request_commands import movie_command, series_command, tv_command
from commands.request_callbacks import handle_request_callback
from commands.request_status_commands import myrequests_command
from commands.moreeps_commands import moreeps_command, handle_moreeps_callback

# Setup logging first
setup_logging()
logger = logging.getLogger(__name__)

# Global scheduler reference for debugging
scheduler = None

async def on_startup(app):
    """Initialize scheduler and jobs on bot startup"""
    global scheduler
    scheduler = AsyncIOScheduler(timezone=MELBOURNE_TZ)

    # Add auto-wake jobs with misfire grace period
    scheduler.add_job(
        scheduled_wake,
        CronTrigger(day_of_week='mon,tue,wed,thu,fri', hour=WEEKDAY_WAKE_HOUR, minute=WEEKDAY_WAKE_MINUTE, timezone=MELBOURNE_TZ),
        args=[app.bot],
        id='auto_on_weekday',
        misfire_grace_time=1800,  # 30 minutes grace period
        coalesce=True  # If multiple missed, only run once
    )
    scheduler.add_job(
        scheduled_wake,
        CronTrigger(day_of_week='sat,sun', hour=WEEKEND_WAKE_HOUR, minute=WEEKEND_WAKE_MINUTE, timezone=MELBOURNE_TZ),
        args=[app.bot],
        id='auto_on_weekend',
        misfire_grace_time=1800,  # 30 minutes grace period
        coalesce=True  # If multiple missed, only run once
    )

    # Add auto-shutdown job if enabled
    if AUTO_SHUTDOWN_ENABLED:
        scheduler.add_job(
            scheduled_shutdown,
            CronTrigger(hour=AUTO_SHUTDOWN_HOUR, minute=AUTO_SHUTDOWN_MINUTE, timezone=MELBOURNE_TZ),
            args=[app.bot, app],
            id='auto_shutdown',
            misfire_grace_time=1800,  # 30 minutes grace period
            coalesce=True
        )
        logger.info("🔌 Auto-shutdown enabled at %02d:%02d daily", AUTO_SHUTDOWN_HOUR, AUTO_SHUTDOWN_MINUTE)
    else:
        logger.info("⏸️ Auto-shutdown disabled")

    # Add request tracking job - check every 15 minutes
    from utils.request_tracker import request_tracker
    async def check_requests_job(bot):
        """Periodic job to check request status"""
        await request_tracker.check_all_pending_requests(bot)

    scheduler.add_job(
        check_requests_job,
        'interval',
        minutes=15,
        args=[app.bot],
        id='check_requests',
        misfire_grace_time=300,  # 5 minutes grace period
        coalesce=True
    )
    logger.info("📬 Request tracking enabled - checking every 15 minutes")

    # Add recently added notification job - check every 5 minutes
    from utils.recently_added import recently_added_notifier
    async def check_recently_added_job(bot):
        """Periodic job to check for newly added content"""
        await recently_added_notifier.check_and_notify(bot)

    scheduler.add_job(
        check_recently_added_job,
        'interval',
        minutes=5,
        args=[app.bot],
        id='check_recently_added',
        misfire_grace_time=300,  # 5 minutes grace period
        coalesce=True
    )
    logger.info("📺 Recently added notifications enabled - checking every 5 minutes")

    scheduler.start()
    logger.info("📅 Scheduler started with %d jobs", len(scheduler.get_jobs()))
    logger.info("⏰ Jobs configured with 30-minute grace period for missed executions")

    # Log next run times for debugging
    for job in scheduler.get_jobs():
        if job.next_run_time:
            next_run = job.next_run_time.astimezone(MELBOURNE_TZ).strftime('%Y-%m-%d %H:%M:%S %Z')
            logger.info("⏰ Job '%s' next run: %s", job.id, next_run)
            logger.info("   Grace period: 30 minutes after scheduled time")
        else:
            logger.info("⏰ Job '%s' next run: Never", job.id)

    logger.info("🚀 Bot startup complete at %s", datetime.now(MELBOURNE_TZ).strftime('%Y-%m-%d %H:%M:%S %Z'))


async def error_handler(update, context):
    """Global error handler for the bot - handles transient network errors gracefully"""
    error = context.error

    # Handle transient network errors at WARNING level (these auto-recover)
    if isinstance(error, NetworkError):
        logger.warning("⚠️ Telegram network error (will retry): %s", str(error))
        return

    if isinstance(error, TimedOut):
        logger.warning("⚠️ Telegram request timed out (will retry)")
        return

    if isinstance(error, RetryAfter):
        logger.warning("⚠️ Telegram rate limit hit, retry after %d seconds", error.retry_after)
        return

    # For other Telegram errors, log at ERROR level but without full traceback
    if isinstance(error, TelegramError):
        logger.error("❌ Telegram error: %s", str(error))
        return

    # For unexpected errors, log the full exception
    logger.exception("❌ Unhandled exception: %s", str(error))


def main():
    """Main function to start the bot"""
    builder = ApplicationBuilder().token(BOT_TOKEN)
    builder.post_init(on_startup)
    app = builder.build()

    # Register global error handler for graceful error handling
    app.add_error_handler(error_handler)

    # Create a filter to only accept commands from the correct chat
    bot_topic_filter = filters.Chat(GROUP_CHAT_ID) & filters.UpdateType.MESSAGE

    # Custom filter class to check message thread ID (only active when BOT_TOPIC_ID is set)
    class BotTopicFilter(filters.MessageFilter):
        def filter(self, message):
            # If no topic configured, allow all messages
            if BOT_TOPIC_ID is None:
                return True
            # Allow messages with the bot topic ID or no topic ID (for backwards compatibility)
            if hasattr(message, 'message_thread_id') and message.message_thread_id is not None:
                is_bot_topic = message.message_thread_id == BOT_TOPIC_ID
                if not is_bot_topic:
                    logger.info("⛔ Command ignored - not from bot topic (thread_id: %s)", message.message_thread_id)
                return is_bot_topic
            # If no thread_id, allow (for non-topic groups or backwards compatibility)
            return True

    # Combine filters: must be in correct chat AND (optionally) in bot topic
    topic_filter = bot_topic_filter & BotTopicFilter()

    # Register command handlers - all restricted to bot topic
    # Server commands
    app.add_handler(CommandHandler("on", on_command, filters=topic_filter))
    app.add_handler(CommandHandler("off", off_command, filters=topic_filter))
    app.add_handler(CommandHandler("status", check_status_command, filters=topic_filter))
    app.add_handler(CommandHandler("remotecheck", remote_check_command, filters=topic_filter))

    # Media commands
    app.add_handler(CommandHandler("nowplaying", nowplaying_command, filters=topic_filter))
    app.add_handler(CommandHandler("np", nowplaying_command, filters=topic_filter))  # Alias
    app.add_handler(CommandHandler("stats", stats_command, filters=topic_filter))
    app.add_handler(CommandHandler("upcoming", upcoming_command, filters=topic_filter))
    app.add_handler(CommandHandler("up", upcoming_command, filters=topic_filter))  # Alias
    app.add_handler(CommandHandler("hot", hot_command, filters=topic_filter))
    app.add_handler(CommandHandler("queue", queue_command, filters=topic_filter))
    app.add_handler(CommandHandler("search", search_plex_command, filters=topic_filter))

    # Request commands
    app.add_handler(CommandHandler("movie", movie_command, filters=topic_filter))
    app.add_handler(CommandHandler("series", series_command, filters=topic_filter))
    app.add_handler(CommandHandler("tv", tv_command, filters=topic_filter))  # Alias for series
    app.add_handler(CommandHandler("myrequests", myrequests_command, filters=topic_filter))
    app.add_handler(CommandHandler("requests", myrequests_command, filters=topic_filter))  # Alias
    app.add_handler(CommandHandler("moreeps", moreeps_command, filters=topic_filter))

    # Admin commands
    app.add_handler(CommandHandler("debug", debug_command, filters=topic_filter))
    app.add_handler(CommandHandler("logs", logs_command, filters=topic_filter))
    app.add_handler(CommandHandler("testwake", testwake_command, filters=topic_filter))
    app.add_handler(CommandHandler("info", info_command, filters=topic_filter))
    app.add_handler(CommandHandler("welcome", welcome_command, filters=topic_filter))
    app.add_handler(CommandHandler("listrequests", requests_admin_command, filters=topic_filter))
    app.add_handler(CommandHandler("clearrequest", clearrequest_command, filters=topic_filter))
    app.add_handler(CommandHandler("clearrequests", clearrequests_command, filters=topic_filter))

    # Callback query handlers (pattern-filtered to avoid conflicts)
    app.add_handler(CallbackQueryHandler(handle_moreeps_callback, pattern=r"^moreeps_"))
    app.add_handler(CallbackQueryHandler(handle_request_callback))

    logger.info("🚀 Bot starting up...")
    app.run_polling()

if __name__ == "__main__":
    main()