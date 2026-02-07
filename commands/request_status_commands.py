"""
Request status commands for viewing and managing user requests
"""

import logging
from datetime import datetime
from telegram.ext import CallbackContext
from telegram.constants import ParseMode

from utils.helpers import send_command_response, escape_md
from utils.request_tracker import request_tracker

logger = logging.getLogger(__name__)


def format_request_line(req, show_release_date=False):
    """Format a single request for display"""
    title = req.get("title", "Unknown")
    year = req.get("year", "")
    media_type = "🎬" if req.get("media_type") == "movie" else "📺"
    year_str = f" \\({year}\\)" if year else ""

    line = f"{media_type} {escape_md(title)}{year_str}"

    # Add release date for unreleased content
    if show_release_date:
        release_date = req.get("release_date")
        if release_date and request_tracker.is_release_date_future(release_date):
            release_display = request_tracker.get_release_date_display(release_date)
            line += f"\n    📅 _{escape_md(release_display)}_"

    # Show subscriber count if more than 1
    subscribers = req.get("subscribers", [])
    if len(subscribers) > 1:
        line += f" \\(👥 {len(subscribers)}\\)"

    return line


async def myrequests_command(update, context: CallbackContext):
    """Show user's request history and status"""
    user = update.effective_user
    user_id = user.id
    username = user.username or user.first_name

    logger.info("📋 Request history requested by %s (%s)", username, user_id)

    try:
        # Get all requests for this user (including ones they subscribed to)
        all_requests = request_tracker.requests.get("requests", [])

        # Find requests where user is owner or subscriber
        user_requests = []
        for req in all_requests:
            # Check if user is owner
            if req.get("user_id") == user_id:
                user_requests.append(req)
            # Check if user is subscriber
            elif any(sub.get("user_id") == user_id for sub in req.get("subscribers", [])):
                user_requests.append(req)

        if not user_requests:
            msg = "📋 *Your Requests*\n\n❌ You haven't made any requests yet\\.\n\nUse `/movie` or `/series` to request content\\!"
            await send_command_response(update, context, msg, parse_mode=ParseMode.MARKDOWN_V2)
            return

        # Sort by requested date (newest first)
        user_requests.sort(key=lambda r: r.get("requested_at", ""), reverse=True)

        # Build message
        msg = f"📋 *Your Requests* \\({len(user_requests)} total\\)\n\n"

        # Group by status
        status_groups = {
            "available": [],
            "downloading": [],
            "pending": [],
            "unreleased": [],
            "failed": []
        }

        for req in user_requests:
            status = req.get("status", "pending")
            if status not in status_groups:
                status = "pending"
            status_groups[status].append(req)

        # Show available first
        if status_groups["available"]:
            msg += "*✅ Available*\n"
            for req in status_groups["available"][:5]:
                msg += format_request_line(req) + "\n"
            if len(status_groups["available"]) > 5:
                msg += f"_\\.\\.\\. and {len(status_groups['available']) - 5} more_\n"
            msg += "\n"

        # Show downloading
        if status_groups["downloading"]:
            msg += "*⏬ Downloading*\n"
            for req in status_groups["downloading"][:5]:
                msg += format_request_line(req) + "\n"
            if len(status_groups["downloading"]) > 5:
                msg += f"_\\.\\.\\. and {len(status_groups['downloading']) - 5} more_\n"
            msg += "\n"

        # Show pending (released but waiting)
        if status_groups["pending"]:
            msg += "*⏳ Searching*\n"
            for req in status_groups["pending"][:5]:
                msg += format_request_line(req) + "\n"
            if len(status_groups["pending"]) > 5:
                msg += f"_\\.\\.\\. and {len(status_groups['pending']) - 5} more_\n"
            msg += "\n"

        # Show unreleased (waiting for release)
        if status_groups["unreleased"]:
            msg += "*📅 Upcoming*\n"
            for req in status_groups["unreleased"][:5]:
                msg += format_request_line(req, show_release_date=True) + "\n"
            if len(status_groups["unreleased"]) > 5:
                msg += f"_\\.\\.\\. and {len(status_groups['unreleased']) - 5} more_\n"
            msg += "\n"

        # Show failed (if any)
        if status_groups["failed"]:
            msg += "*❌ Unavailable*\n"
            for req in status_groups["failed"][:3]:
                msg += format_request_line(req) + "\n"
            if len(status_groups["failed"]) > 3:
                msg += f"_\\.\\.\\. and {len(status_groups['failed']) - 3} more_\n"
            msg += "\n"

        msg += "_Status updated every 15 minutes_"

        await send_command_response(update, context, msg, parse_mode=ParseMode.MARKDOWN_V2)

    except Exception as e:
        logger.error("❌ Failed to get request history: %s", e)
        await send_command_response(
            update, context,
            f"❌ Failed to retrieve request history: {escape_md(str(e))}",
            parse_mode=ParseMode.MARKDOWN_V2
        )
