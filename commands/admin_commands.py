"""
Admin and debug commands
Handles debug, logs, info, welcome, and test commands
Updated to include request system information
"""

import logging
from datetime import datetime
from telegram.ext import CallbackContext
from telegram.constants import ParseMode
from httpx import AsyncClient
from wakeonlan import send_magic_packet

from config import (
    OFF_USER_IDS, MELBOURNE_TZ, GROUP_CHAT_ID, BOT_TOPIC_ID,
    WEEKDAY_WAKE_HOUR, WEEKDAY_WAKE_MINUTE, WEEKEND_WAKE_HOUR, WEEKEND_WAKE_MINUTE,
    PLEX_MAC, PLEX_BROADCAST_IP, TAUTILLI_URL, SONARR_URL, RADARR_URL,
    TMDB_BEARER_TOKEN
)
from utils.helpers import send_command_response, send_to_bot_topic, escape_md
from utils.server_status import scheduled_wake

logger = logging.getLogger(__name__)

async def debug_command(update, context: CallbackContext):
    """Debug command to check bot status and scheduler"""
    try:
        current_time = datetime.now(MELBOURNE_TZ).strftime('%Y-%m-%d %H:%M:%S %Z')
        msg = f"🔍 *Bot Debug Info*\n"
        msg += f"\\- Current time: {escape_md(current_time)}\n"
        msg += f"\\- Plex MAC: {escape_md(PLEX_MAC)}\n"
        msg += f"\\- Broadcast IP: {escape_md(PLEX_BROADCAST_IP)}\n"
        msg += f"\\- Group Chat ID: {escape_md(str(GROUP_CHAT_ID))}\n"
        msg += f"\\- Bot Topic ID: {escape_md(str(BOT_TOPIC_ID))}\n"
        msg += f"\\- Weekday wake: {WEEKDAY_WAKE_HOUR:02d}:{WEEKDAY_WAKE_MINUTE:02d}\n"
        msg += f"\\- Weekend wake: {WEEKEND_WAKE_HOUR:02d}:{WEEKEND_WAKE_MINUTE:02d}\n"
        msg += f"\\- Tautulli URL: {escape_md(TAUTILLI_URL[:50] + '...' if len(TAUTILLI_URL) > 50 else TAUTILLI_URL)}\n"
        msg += f"\\- Sonarr URL: {escape_md(SONARR_URL[:50] + '...' if len(SONARR_URL) > 50 else SONARR_URL) if SONARR_URL else 'Not configured'}\n"
        msg += f"\\- Radarr URL: {escape_md(RADARR_URL[:50] + '...' if len(RADARR_URL) > 50 else RADARR_URL) if RADARR_URL else 'Not configured'}\n"
        
        # Request system status
        msg += f"\n🎬 *Request System Status*\n"
        msg += f"\\- TMDB API: {'✅ Configured' if TMDB_BEARER_TOKEN else '❌ Not configured'}\n"
        msg += f"\\- Movie requests: {'✅ Available' if (RADARR_URL and TMDB_BEARER_TOKEN) else '❌ Unavailable'}\n"
        msg += f"\\- TV requests: {'✅ Available' if (SONARR_URL and TMDB_BEARER_TOKEN) else '❌ Unavailable'}\n"
        
        # Enhanced scheduler detection - check if the application has a scheduler
        msg += f"\n📅 *Scheduler Status*\n"
        
        try:
            # Try to access the application's job queue to detect scheduler
            # This is a more reliable way to check if scheduler is running
            scheduler_found = False
            app = context.application
            
            # Check if the application has any running jobs (indicates scheduler is active)
            if hasattr(app, 'job_queue') and app.job_queue:
                msg += f"\\- Job queue: Active\n"
                scheduler_found = True
            
            # Alternative method: check if we can find scheduler in sys.modules
            import sys
            if 'main' in sys.modules:
                main_module = sys.modules['main']
                if hasattr(main_module, 'scheduler') and main_module.scheduler:
                    scheduler = main_module.scheduler
                    if scheduler.running:
                        jobs = scheduler.get_jobs()
                        msg += f"\\- Active jobs: {len(jobs)}\n"
                        
                        for job in jobs:
                            if job.next_run_time:
                                next_run = job.next_run_time.astimezone(MELBOURNE_TZ).strftime('%Y-%m-%d %H:%M:%S %Z')
                                msg += f"\\- {escape_md(job.id)}: {escape_md(next_run)}\n"
                                msg += f"  \\(30min grace period\\)\n"
                            else:
                                msg += f"\\- {escape_md(job.id)}: Never\n"
                        scheduler_found = True
                    else:
                        msg += f"\\- Scheduler created but not running\n"
                else:
                    msg += f"\\- Scheduler object not found in main module\n"
            
            # If we couldn't detect the scheduler through normal means, 
            # check for recent auto-wake activity in logs as evidence
            if not scheduler_found:
                try:
                    # Check if we can find recent scheduler activity in logs
                    # This is indirect but indicates the scheduler was working recently
                    import subprocess
                    result = subprocess.run(
                        ['journalctl', '-u', 'plexbot', '--since', '24 hours ago', '--grep', 'Auto-wake job triggered'],
                        capture_output=True, text=True, timeout=5
                    )
                    if result.returncode == 0 and result.stdout.strip():
                        msg += f"\\- Recent auto\\-wake activity detected in logs\n"
                        msg += f"\\- Scheduler appears to be working \\(indirect detection\\)\n"
                    else:
                        msg += f"\\- No recent scheduler activity detected\n"
                        msg += f"\\- Scheduler status uncertain\n"
                except Exception:
                    msg += f"\\- Scheduler status: Unable to detect\n"
                    msg += f"\\- \\(Import/detection limitations\\)\n"
            
        except Exception as e:
            msg += f"\\- Scheduler detection failed: {escape_md(str(e))}\n"
            msg += f"\\- Note: Scheduler may be working despite detection issues\n"
            
        await send_command_response(update, context, msg, parse_mode=ParseMode.MARKDOWN_V2)
    except Exception as e:
        logger.error("❌ Debug command failed: %s", e)
        await send_command_response(update, context, f"❌ Debug failed: {e}")

async def testrequest_command(update, context: CallbackContext):
    """Test request system APIs (TMDB, Sonarr, Radarr)"""
    try:
        await send_command_response(update, context, "🔍 Testing request system APIs\\.\\.\\.", parse_mode=ParseMode.MARKDOWN_V2)
        
        results = []
        
        # Test TMDB API
        if TMDB_BEARER_TOKEN:
            try:
                headers = {"Authorization": f"Bearer {TMDB_BEARER_TOKEN}", "accept": "application/json"}
                async with AsyncClient() as client:
                    resp = await client.get("https://api.themoviedb.org/3/trending/movie/week", headers=headers)
                    if resp.status_code == 200:
                        results.append("✅ TMDB API: Working")
                    else:
                        results.append(f"❌ TMDB API: Failed ({resp.status_code})")
            except Exception as e:
                results.append(f"❌ TMDB API: Error ({str(e)[:30]}...)")
        else:
            results.append("❌ TMDB API: Not configured")
        
        # Test Radarr API
        if RADARR_URL:
            try:
                from commands.request_commands import request_manager
                folders, error = await request_manager.get_radarr_root_folders()
                if error:
                    results.append(f"❌ Radarr API: {error}")
                else:
                    results.append(f"✅ Radarr API: {len(folders)} root folders")
            except Exception as e:
                results.append(f"❌ Radarr API: Error ({str(e)[:30]}...)")
        else:
            results.append("❌ Radarr API: Not configured")
        
        # Test Sonarr API
        if SONARR_URL:
            try:
                from commands.request_commands import request_manager
                folders, error = await request_manager.get_sonarr_root_folders()
                if error:
                    results.append(f"❌ Sonarr API: {error}")
                else:
                    results.append(f"✅ Sonarr API: {len(folders)} root folders")
            except Exception as e:
                results.append(f"❌ Sonarr API: Error ({str(e)[:30]}...)")
        else:
            results.append("❌ Sonarr API: Not configured")
        
        # Format results
        msg = "🧪 *Request System API Test Results*\n\n"
        for result in results:
            msg += f"{escape_md(result)}\n"
        
        # Add recommendations
        working_apis = len([r for r in results if r.startswith("✅")])
        if working_apis == 3:
            msg += f"\n🎉 All APIs working\\! Request system fully functional\\."
        elif working_apis >= 1:
            msg += f"\n⚠️ {working_apis}/3 APIs working\\. Check configuration for failed APIs\\."
        else:
            msg += f"\n❌ No APIs working\\. Check all configurations\\."
        
        await send_command_response(update, context, msg, parse_mode=ParseMode.MARKDOWN_V2)
        
    except Exception as e:
        logger.error("❌ Request system test failed: %s", e)
        await send_command_response(update, context, f"❌ Test failed: {escape_md(str(e))}", parse_mode=ParseMode.MARKDOWN_V2)

async def logs_command(update, context: CallbackContext):
    """Show recent log entries from current session"""
    user_id = update.effective_user.id
    if user_id not in OFF_USER_IDS:  # Only authorized users
        return await send_command_response(update, context, "❌ Not authorized.")
    
    try:
        # Read the entire current session log file
        with open('bot.log', 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        # Get last 20 lines
        recent_lines = lines[-20:] if len(lines) > 20 else lines
        
        if not recent_lines:
            await send_command_response(update, context, "📝 No log entries found\\.", parse_mode=ParseMode.MARKDOWN_V2)
            return
        
        # Format log entries
        log_text = "📝 *Recent Log Entries \\(Last 20\\)*\n\n```\n"
        for line in recent_lines:
            # Remove newlines and limit line length
            clean_line = line.strip()
            if len(clean_line) > 80:
                clean_line = clean_line[:77] + "..."
            log_text += clean_line + "\n"
        log_text += "```"
        
        await send_command_response(update, context, log_text, parse_mode=ParseMode.MARKDOWN_V2)
        
    except FileNotFoundError:
        await send_command_response(update, context, "❌ Log file not found\\.", parse_mode=ParseMode.MARKDOWN_V2)
    except Exception as e:
        logger.error("❌ Logs command failed: %s", e)
        await send_command_response(update, context, f"❌ Failed to read logs: {escape_md(str(e))}", parse_mode=ParseMode.MARKDOWN_V2)

async def testwake_command(update, context: CallbackContext):
    """Test wake-on-LAN functionality"""
    user_id = update.effective_user.id
    if user_id not in OFF_USER_IDS:  # Only authorized users
        return await send_command_response(update, context, "❌ Not authorized.")
    
    try:
        await send_command_response(update, context, "🔍 Testing Wake\\-on\\-LAN\\.\\.\\.", parse_mode=ParseMode.MARKDOWN_V2)
        
        # Send WOL packet
        send_magic_packet(PLEX_MAC, ip_address=PLEX_BROADCAST_IP)
        logger.info("✅ Test WOL packet sent to %s via %s", PLEX_MAC, PLEX_BROADCAST_IP)
        
        msg = "✅ *Wake\\-on\\-LAN Test*\n\n"
        msg += f"Packet sent to: {escape_md(PLEX_MAC)}\n"
        msg += f"Via broadcast: {escape_md(PLEX_BROADCAST_IP)}\n"
        msg += "Check server status in a few moments\\."
        
        await send_command_response(update, context, msg, parse_mode=ParseMode.MARKDOWN_V2)
        
    except Exception as e:
        logger.error("❌ Test WOL failed: %s", e)
        await send_command_response(update, context, f"❌ Test failed: {escape_md(str(e))}", parse_mode=ParseMode.MARKDOWN_V2)

async def info_command(update, context: CallbackContext):
    """Show bot information and available commands"""
    try:
        msg = "🤖 *Plex Bot Information*\n\n"
        
        msg += "*Request Commands:*\n"
        msg += "\\- `/movie <title>` \\- Search for movies to request\n"
        msg += "\\- `/series <title>` or `/tv <title>` \\- Search for TV series\n"
        msg += "\\- `/myrequests` or `/requests` \\- View your request history\n\n"
        
        msg += "*Server Commands:*\n"
        msg += "\\- `/on` \\- Wake server\n"
        msg += "\\- `/off` \\- Shutdown server \\(authorized users\\)\n"
        msg += "\\- `/status` \\- Check server status\n\n"
        
        msg += "*Media Commands:*\n"
        msg += "\\- `/nowplaying` or `/np` \\- Current streams\n"
        msg += "\\- `/stats` \\- Weekly viewing statistics\n"
        msg += "\\- `/hot` \\- Trending content\n"
        msg += "\\- `/upcoming` or `/up` \\- Upcoming releases\n"
        msg += "\\- `/queue` \\- View download queue status\n"
        msg += "\\- `/search <title>` \\- Search Plex library\n\n"
        
        msg += "*Admin Commands:*\n"
        msg += "\\- `/debug` \\- Bot status info\n"
        msg += "\\- `/testrequest` \\- Test request system APIs\n"
        msg += "\\- `/testwake` \\- Test Wake\\-on\\-LAN\n"
        msg += "\\- `/logs` \\- Recent log entries\n"
        msg += "\\- `/listrequests` \\- View all tracked requests\n"
        msg += "\\- `/clearrequest <id>` \\- Remove a specific request\n"
        msg += "\\- `/clearrequests` \\- Clear all completed requests\n"
        msg += "\\- `/info` \\- This help message\n\n"
        
        msg += "*Request System Features:*\n"
        msg += "\\- No authentication required for group members\n"
        msg += "\\- TMDB search with interactive navigation\n"
        msg += "\\- Automatic Radarr/Sonarr integration\n"
        msg += "\\- Smart detection of existing content\n"
        msg += "\\- Support for multiple root folders/quality profiles\n"
        msg += "\\- Request tracking with automatic notifications\n"
        msg += "\\- Status updates every 15 minutes\n\n"
        
        msg += "*Automated Features:*\n"
        msg += f"\\- Auto\\-wake weekdays: {WEEKDAY_WAKE_HOUR:02d}:{WEEKDAY_WAKE_MINUTE:02d}\n"
        msg += f"\\- Auto\\-wake weekends: {WEEKEND_WAKE_HOUR:02d}:{WEEKEND_WAKE_MINUTE:02d}\n"
        msg += "\\- Smart server detection \\(skips wake if already online\\)\n"
        msg += "\\- 30\\-minute grace period for missed schedules\n"
        msg += "\\- New content notifications \\(checks every 5 mins\\)\n"
        msg += "\\- Smart duplicate detection \\(no double notifications\\)"
        
        await send_command_response(update, context, msg, parse_mode=ParseMode.MARKDOWN_V2)
        
    except Exception as e:
        logger.error("❌ Info command failed: %s", e)
        await send_command_response(update, context, f"❌ Failed to show info: {escape_md(str(e))}", parse_mode=ParseMode.MARKDOWN_V2)

async def welcome_command(update, context: CallbackContext):
    """Welcome message with bot overview"""
    try:
        current_time = datetime.now(MELBOURNE_TZ).strftime('%H:%M %Z')
        
        msg = "👋 *Welcome to Plex Bot\\!*\n\n"
        msg += f"🕐 Current time: {escape_md(current_time)}\n\n"
        msg += "This bot manages your Plex server with automated wake\\-up, "
        msg += "media tracking, convenient remote control, and an integrated request system\\.\n\n"
        msg += "*Quick Start:*\n"
        msg += "\\- `/status` \\- Check if server is online\n"
        msg += "\\- `/on` \\- Wake server if needed\n"
        msg += "\\- `/np` \\- See what's currently playing\n"
        msg += "\\- `/movie <title>` \\- Request a movie\n"
        msg += "\\- `/series <title>` \\- Request a TV series\n"
        msg += "\\- `/info` \\- View all available commands\n\n"
        msg += "*Request System:*\n"
        msg += "Search and request movies/TV shows directly from TMDB\\. "
        msg += "Content is automatically added to Radarr/Sonarr for download\\. "
        msg += "No authentication required \\- works for all group members\\!\n\n"
        msg += "The server will automatically wake at scheduled times "
        msg += "\\(weekdays 4:30 PM, weekends 10:00 AM\\)\\.\n\n"
        msg += "Use `/debug` to check bot configuration and status\\."
        
        await send_command_response(update, context, msg, parse_mode=ParseMode.MARKDOWN_V2)

    except Exception as e:
        logger.error("❌ Welcome command failed: %s", e)
        await send_command_response(update, context, f"❌ Failed to show welcome: {escape_md(str(e))}", parse_mode=ParseMode.MARKDOWN_V2)


async def requests_admin_command(update, context: CallbackContext):
    """List all tracked requests (admin command)"""
    user_id = update.effective_user.id
    if user_id not in OFF_USER_IDS:
        return await send_command_response(update, context, "❌ Not authorized.")

    try:
        from utils.request_tracker import request_tracker

        all_requests = request_tracker.requests.get("requests", [])

        if not all_requests:
            await send_command_response(update, context, "📭 No requests in the database\\.", parse_mode=ParseMode.MARKDOWN_V2)
            return

        # Group by status
        pending = [r for r in all_requests if not r.get("notified", False) and r.get("status") != "unreleased"]
        unreleased = [r for r in all_requests if r.get("status") == "unreleased"]
        completed = [r for r in all_requests if r.get("notified", False)]

        msg = "📋 *All Tracked Requests*\n\n"

        if pending:
            msg += f"*🔄 Pending \\({len(pending)}\\):*\n"
            for req in pending[:10]:  # Limit to 10
                media_emoji = "🎬" if req["media_type"] == "movie" else "📺"
                title = escape_md(req.get("title", "Unknown"))
                user = escape_md(req.get("username", "Unknown"))
                status = escape_md(req.get("status", "pending"))
                req_id = escape_md(req.get("id", "")[:20])
                msg += f"{media_emoji} {title} \\- @{user}\n"
                msg += f"   Status: {status} \\| ID: `{req_id}`\n"
            if len(pending) > 10:
                msg += f"   _\\.\\.\\. and {len(pending) - 10} more_\n"
            msg += "\n"

        if unreleased:
            msg += f"*📅 Unreleased \\({len(unreleased)}\\):*\n"
            for req in unreleased[:5]:
                media_emoji = "🎬" if req["media_type"] == "movie" else "📺"
                title = escape_md(req.get("title", "Unknown"))
                release = req.get("release_date", "Unknown")
                req_id = escape_md(req.get("id", "")[:20])
                msg += f"{media_emoji} {title} \\- {escape_md(release)}\n"
                msg += f"   ID: `{req_id}`\n"
            if len(unreleased) > 5:
                msg += f"   _\\.\\.\\. and {len(unreleased) - 5} more_\n"
            msg += "\n"

        if completed:
            msg += f"*✅ Completed \\({len(completed)}\\):*\n"
            for req in completed[:5]:
                media_emoji = "🎬" if req["media_type"] == "movie" else "📺"
                title = escape_md(req.get("title", "Unknown"))
                req_id = escape_md(req.get("id", "")[:20])
                msg += f"{media_emoji} {title}\n"
                msg += f"   ID: `{req_id}`\n"
            if len(completed) > 5:
                msg += f"   _\\.\\.\\. and {len(completed) - 5} more_\n"
            msg += "\n"

        msg += f"*Total: {len(all_requests)} requests*\n\n"
        msg += "_Use `/clearrequest <id>` to remove a specific request_\n"
        msg += "_Use `/clearrequests` to remove all completed requests_"

        await send_command_response(update, context, msg, parse_mode=ParseMode.MARKDOWN_V2)

    except Exception as e:
        logger.error("❌ Requests admin command failed: %s", e)
        await send_command_response(update, context, f"❌ Failed to list requests: {escape_md(str(e))}", parse_mode=ParseMode.MARKDOWN_V2)


async def clearrequest_command(update, context: CallbackContext):
    """Remove a specific request by ID"""
    user_id = update.effective_user.id
    if user_id not in OFF_USER_IDS:
        return await send_command_response(update, context, "❌ Not authorized.")

    if not context.args:
        await send_command_response(
            update, context,
            "❌ Please provide a request ID\\.\n\nUsage: `/clearrequest <id>`\n\nUse `/requests` to see all request IDs\\.",
            parse_mode=ParseMode.MARKDOWN_V2
        )
        return

    request_id = context.args[0]

    try:
        from utils.request_tracker import request_tracker

        # Find and remove the request
        original_count = len(request_tracker.requests["requests"])
        request_tracker.requests["requests"] = [
            r for r in request_tracker.requests["requests"]
            if not r.get("id", "").startswith(request_id)
        ]
        new_count = len(request_tracker.requests["requests"])

        removed = original_count - new_count

        if removed > 0:
            request_tracker._save_requests()
            await send_command_response(
                update, context,
                f"✅ Removed {removed} request\\(s\\) matching `{escape_md(request_id)}`",
                parse_mode=ParseMode.MARKDOWN_V2
            )
            logger.info("🗑️ Admin %s removed %d request(s) matching '%s'",
                       update.effective_user.username, removed, request_id)
        else:
            await send_command_response(
                update, context,
                f"❌ No request found matching `{escape_md(request_id)}`\n\nUse `/requests` to see all request IDs\\.",
                parse_mode=ParseMode.MARKDOWN_V2
            )

    except Exception as e:
        logger.error("❌ Clear request command failed: %s", e)
        await send_command_response(update, context, f"❌ Failed to remove request: {escape_md(str(e))}", parse_mode=ParseMode.MARKDOWN_V2)


async def clearrequests_command(update, context: CallbackContext):
    """Clear all completed/notified requests"""
    user_id = update.effective_user.id
    if user_id not in OFF_USER_IDS:
        return await send_command_response(update, context, "❌ Not authorized.")

    try:
        from utils.request_tracker import request_tracker

        # Count completed requests
        original_count = len(request_tracker.requests["requests"])
        completed_count = len([r for r in request_tracker.requests["requests"] if r.get("notified", False)])

        if completed_count == 0:
            await send_command_response(
                update, context,
                "📭 No completed requests to clear\\.",
                parse_mode=ParseMode.MARKDOWN_V2
            )
            return

        # Remove completed requests
        request_tracker.requests["requests"] = [
            r for r in request_tracker.requests["requests"]
            if not r.get("notified", False)
        ]
        request_tracker._save_requests()

        remaining = len(request_tracker.requests["requests"])

        await send_command_response(
            update, context,
            f"✅ Cleared {completed_count} completed request\\(s\\)\\.\n\n"
            f"📋 {remaining} pending request\\(s\\) remaining\\.",
            parse_mode=ParseMode.MARKDOWN_V2
        )
        logger.info("🗑️ Admin %s cleared %d completed requests",
                   update.effective_user.username, completed_count)

    except Exception as e:
        logger.error("❌ Clear requests command failed: %s", e)
        await send_command_response(update, context, f"❌ Failed to clear requests: {escape_md(str(e))}", parse_mode=ParseMode.MARKDOWN_V2)