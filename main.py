#!/usr/bin/env python3
"""
Plex Bot - Main Entry Point
Comprehensive Plex media server automation bot with request system
"""

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from config import *
from utils.logging_setup import setup_logging
from utils.server_status import scheduled_wake
from commands.media_commands import nowplaying_command, upcoming_command, hot_command, stats_command
from commands.server_commands import on_command, off_command, check_status_command
from commands.admin_commands import debug_command, testjellyfin_command, logs_command, testwake_command, info_command, welcome_command
from commands.request_commands import movie_command, series_command, tv_command
from commands.request_callbacks import handle_request_callback

# Setup logging first
setup_logging()
logger = logging.getLogger(__name__)

# Global scheduler reference for debugging
scheduler = None

async def on_startup(app):
    """Initialize scheduler and jobs on bot startup"""
    global scheduler
    scheduler = AsyncIOScheduler(timezone=MELBOURNE_TZ)
    
    # Add jobs with misfire grace period - automated wake-ups will be sent to bot topic
    scheduler.add_job(
        scheduled_wake, 
        CronTrigger(day_of_week='mon,tue,wed,thu,fri', hour=WEEKDAY_WAKE_HOUR, minute=WEEKDAY_WAKE_MINUTE), 
        args=[app.bot], 
        id='auto_on_weekday',
        misfire_grace_time=1800,  # 30 minutes grace period
        coalesce=True  # If multiple missed, only run once
    )
    scheduler.add_job(
        scheduled_wake, 
        CronTrigger(day_of_week='sat,sun', hour=WEEKEND_WAKE_HOUR, minute=WEEKEND_WAKE_MINUTE), 
        args=[app.bot], 
        id='auto_on_weekend',
        misfire_grace_time=1800,  # 30 minutes grace period
        coalesce=True  # If multiple missed, only run once
    )
    
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

def main():
    """Main function to start the bot"""
    builder = ApplicationBuilder().token(BOT_TOKEN)
    builder.post_init(on_startup)
    app = builder.build()
    
    # Register command handlers
    # Server commands
    app.add_handler(CommandHandler("on", on_command))
    app.add_handler(CommandHandler("off", off_command))
    app.add_handler(CommandHandler("status", check_status_command))
    
    # Media commands
    app.add_handler(CommandHandler("nowplaying", nowplaying_command))
    app.add_handler(CommandHandler("np", nowplaying_command))  # Alias
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("upcoming", upcoming_command))
    app.add_handler(CommandHandler("up", upcoming_command))  # Alias
    app.add_handler(CommandHandler("hot", hot_command))
    
    # Request commands
    app.add_handler(CommandHandler("movie", movie_command))
    app.add_handler(CommandHandler("series", series_command))
    app.add_handler(CommandHandler("tv", tv_command))  # Alias for series
    
    # Admin commands
    app.add_handler(CommandHandler("debug", debug_command))
    app.add_handler(CommandHandler("testjellyfin", testjellyfin_command))
    app.add_handler(CommandHandler("logs", logs_command))
    app.add_handler(CommandHandler("testwake", testwake_command))
    app.add_handler(CommandHandler("info", info_command))
    app.add_handler(CommandHandler("welcome", welcome_command))
    
    # Callback query handler for request system
    app.add_handler(CallbackQueryHandler(handle_request_callback))

    logger.info("🚀 Bot starting up...")
    app.run_polling()

if __name__ == "__main__":
    main()