"""
More Episodes command
Allows users to add more seasons/episodes to TV shows already in Sonarr
"""

import logging
from datetime import datetime
from telegram.ext import CallbackContext
from telegram.constants import ParseMode
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from httpx import AsyncClient

from config import SONARR_URL, SONARR_API_KEY, SILENT_NOTIFICATIONS, GROUP_CHAT_ID, BOT_TOPIC_ID
from utils.helpers import send_command_response, escape_md

logger = logging.getLogger(__name__)

# Store active moreeps sessions
moreeps_sessions = {}


async def get_sonarr_api_version():
    """Detect working Sonarr API version"""
    if not (SONARR_URL and SONARR_API_KEY):
        return None

    base_url = SONARR_URL.rstrip('/')
    headers = {"X-Api-Key": SONARR_API_KEY}

    async with AsyncClient(timeout=10.0) as client:
        for api_version in ["v3", "v2", "v1"]:
            try:
                url = f"{base_url}/api/{api_version}/system/status"
                resp = await client.get(url, headers=headers)
                if resp.status_code == 200:
                    return api_version
            except Exception:
                continue
    return None


async def search_sonarr_series(query: str):
    """Search for a TV series in Sonarr's library by title"""
    if not (SONARR_URL and SONARR_API_KEY):
        return None, "Sonarr not configured"

    try:
        base_url = SONARR_URL.rstrip('/')
        headers = {"X-Api-Key": SONARR_API_KEY}

        async with AsyncClient(timeout=10.0) as client:
            for api_version in ["v3", "v2", "v1"]:
                try:
                    url = f"{base_url}/api/{api_version}/series"
                    resp = await client.get(url, headers=headers)
                    if resp.status_code == 200:
                        all_series = resp.json()

                        # Search by title (case-insensitive partial match)
                        query_lower = query.lower().strip()
                        matches = []
                        for series in all_series:
                            title = series.get("title", "").lower()
                            # Exact match gets priority
                            if title == query_lower:
                                matches.insert(0, series)
                            elif query_lower in title:
                                matches.append(series)

                        return matches, None
                    elif resp.status_code == 404:
                        continue
                except Exception:
                    continue

            return None, "Server is offline. Please use /on to wake it up, then try again."

    except Exception as e:
        logger.error("Failed to search Sonarr series: %s", e)
        return None, str(e)


async def get_sonarr_series_details(sonarr_id: int):
    """Get full series details from Sonarr including seasons"""
    if not (SONARR_URL and SONARR_API_KEY):
        return None, "Sonarr not configured"

    try:
        base_url = SONARR_URL.rstrip('/')
        headers = {"X-Api-Key": SONARR_API_KEY}

        async with AsyncClient(timeout=10.0) as client:
            for api_version in ["v3", "v2", "v1"]:
                try:
                    url = f"{base_url}/api/{api_version}/series/{sonarr_id}"
                    resp = await client.get(url, headers=headers)
                    if resp.status_code == 200:
                        return resp.json(), None
                    elif resp.status_code == 404:
                        continue
                except Exception:
                    continue

            return None, "Server is offline. Please use /on to wake it up, then try again."

    except Exception as e:
        logger.error("Failed to get series details: %s", e)
        return None, str(e)


async def get_sonarr_episodes(sonarr_id: int):
    """Get all episodes for a series from Sonarr"""
    if not (SONARR_URL and SONARR_API_KEY):
        return None, "Sonarr not configured"

    try:
        base_url = SONARR_URL.rstrip('/')
        headers = {"X-Api-Key": SONARR_API_KEY}

        async with AsyncClient(timeout=10.0) as client:
            for api_version in ["v3", "v2", "v1"]:
                try:
                    url = f"{base_url}/api/{api_version}/episode?seriesId={sonarr_id}"
                    resp = await client.get(url, headers=headers)
                    if resp.status_code == 200:
                        return resp.json(), None
                    elif resp.status_code == 404:
                        continue
                except Exception:
                    continue

            return None, "Server is offline. Please use /on to wake it up, then try again."

    except Exception as e:
        logger.error("Failed to get episodes: %s", e)
        return None, str(e)


async def set_episode_monitoring(episode_ids: list, monitored: bool = True):
    """Set monitoring status for specific episodes in Sonarr"""
    if not (SONARR_URL and SONARR_API_KEY):
        return False, "Sonarr not configured"

    try:
        base_url = SONARR_URL.rstrip('/')
        headers = {"X-Api-Key": SONARR_API_KEY, "Content-Type": "application/json"}

        async with AsyncClient(timeout=10.0) as client:
            for api_version in ["v3", "v2", "v1"]:
                try:
                    url = f"{base_url}/api/{api_version}/episode/monitor"
                    data = {
                        "episodeIds": episode_ids,
                        "monitored": monitored
                    }
                    resp = await client.put(url, headers=headers, json=data)
                    if resp.status_code in [200, 202]:
                        logger.info("Set monitoring for %d episodes to %s", len(episode_ids), monitored)
                        return True, None
                    elif resp.status_code == 404:
                        continue
                    else:
                        logger.error("Sonarr episode monitor API %s returned %d: %s",
                                    api_version, resp.status_code, resp.text)
                        continue
                except Exception:
                    continue

            return False, "Server is offline. Please use /on to wake it up, then try again."

    except Exception as e:
        logger.error("Failed to set episode monitoring: %s", e)
        return False, str(e)


async def trigger_episode_search(episode_ids: list):
    """Trigger a search for specific episodes in Sonarr"""
    if not (SONARR_URL and SONARR_API_KEY):
        return False, "Sonarr not configured"

    try:
        base_url = SONARR_URL.rstrip('/')
        headers = {"X-Api-Key": SONARR_API_KEY, "Content-Type": "application/json"}

        async with AsyncClient(timeout=10.0) as client:
            for api_version in ["v3", "v2", "v1"]:
                try:
                    url = f"{base_url}/api/{api_version}/command"
                    data = {
                        "name": "EpisodeSearch",
                        "episodeIds": episode_ids
                    }
                    resp = await client.post(url, headers=headers, json=data)
                    if resp.status_code in [200, 201]:
                        logger.info("Triggered search for %d episodes", len(episode_ids))
                        return True, None
                    elif resp.status_code == 404:
                        continue
                    else:
                        logger.error("Sonarr command API %s returned %d: %s",
                                    api_version, resp.status_code, resp.text)
                        continue
                except Exception:
                    continue

            return False, "Server is offline. Please use /on to wake it up, then try again."

    except Exception as e:
        logger.error("Failed to trigger episode search: %s", e)
        return False, str(e)


async def moreeps_command(update, context: CallbackContext):
    """Search Sonarr library for a TV show to add more episodes"""
    if not (SONARR_URL and SONARR_API_KEY):
        await send_command_response(
            update, context,
            "❌ Sonarr is not configured\\. Cannot manage episodes\\.",
            parse_mode=ParseMode.MARKDOWN_V2
        )
        return

    if not context.args:
        await send_command_response(
            update, context,
            "❌ Please provide a TV series title to look up\\.\n\nExample: `/moreeps Breaking Bad`",
            parse_mode=ParseMode.MARKDOWN_V2
        )
        return

    query = " ".join(context.args)
    user = update.effective_user
    user_id = user.id

    logger.info("📺 More episodes requested by %s (%s): '%s'",
                user.username or user.first_name, user_id, query)

    try:
        await send_command_response(
            update, context,
            f"🔍 Searching Sonarr library for: *{escape_md(query)}*",
            parse_mode=ParseMode.MARKDOWN_V2
        )

        # Search Sonarr library
        matches, error = await search_sonarr_series(query)

        if error:
            await send_command_response(
                update, context,
                f"❌ Search failed: {escape_md(error)}",
                parse_mode=ParseMode.MARKDOWN_V2
            )
            return

        if not matches:
            await send_command_response(
                update, context,
                f"❌ No series found in Sonarr matching: *{escape_md(query)}*\n\n"
                f"_The show must already be in Sonarr\\. Use `/series` to add a new show first\\._",
                parse_mode=ParseMode.MARKDOWN_V2
            )
            return

        # If exactly one match, go straight to season selection
        if len(matches) == 1:
            series = matches[0]
            await show_series_seasons(update, context, series, user_id)
            return

        # Multiple matches - let user pick
        session_id = f"moreeps_{user_id}_{int(datetime.now().timestamp())}"
        moreeps_sessions[session_id] = {
            "user_id": user_id,
            "matches": matches
        }

        msg = f"📺 *Found {len(matches)} series matching \\'{escape_md(query)}\\'*\n\nSelect a show:"

        keyboard = []
        for i, series in enumerate(matches[:10]):  # Limit to 10 results
            title = series.get("title", "Unknown")
            year = series.get("year", "")
            year_str = f" ({year})" if year else ""
            seasons = len(series.get("seasons", []))
            button_text = f"{title}{year_str} ({seasons} seasons)"
            if len(button_text) > 60:
                button_text = button_text[:57] + "..."

            keyboard.append([InlineKeyboardButton(
                button_text,
                callback_data=f"moreeps_pick_{session_id}_{i}"
            )])

        keyboard.append([InlineKeyboardButton(
            "❌ Cancel",
            callback_data=f"moreeps_cancel_{session_id}"
        )])

        # Send to bot topic with reply markup
        try:
            await context.bot.send_message(
                chat_id=GROUP_CHAT_ID,
                text=msg,
                message_thread_id=BOT_TOPIC_ID,
                parse_mode=ParseMode.MARKDOWN_V2,
                reply_markup=InlineKeyboardMarkup(keyboard),
                disable_notification=SILENT_NOTIFICATIONS
            )
        except Exception as e:
            logger.error("Failed to send moreeps selection: %s", e)
            await send_command_response(
                update, context,
                f"❌ Failed to show results: {escape_md(str(e))}",
                parse_mode=ParseMode.MARKDOWN_V2
            )

    except Exception as e:
        logger.error("More episodes command failed: %s", e)
        await send_command_response(
            update, context,
            f"❌ Failed to search: {escape_md(str(e))}",
            parse_mode=ParseMode.MARKDOWN_V2
        )


async def show_series_seasons(update, context_or_query, series, user_id):
    """Show season list for a series with monitoring status"""
    sonarr_id = series.get("id")
    title = series.get("title", "Unknown")

    # Get full series details with seasons
    series_data, error = await get_sonarr_series_details(sonarr_id)
    if error:
        msg = f"❌ Failed to get series details: {escape_md(error)}"
        if hasattr(context_or_query, 'edit_message_text'):
            await context_or_query.edit_message_text(msg, parse_mode=ParseMode.MARKDOWN_V2)
        else:
            await send_command_response(update, context_or_query, msg, parse_mode=ParseMode.MARKDOWN_V2)
        return

    # Get episode data to determine status per season
    episodes, ep_error = await get_sonarr_episodes(sonarr_id)
    if ep_error:
        episodes = []

    # Build season info
    seasons = series_data.get("seasons", [])
    # Filter out "specials" (season 0) for cleaner display
    regular_seasons = [s for s in seasons if s.get("seasonNumber", 0) > 0]

    if not regular_seasons:
        msg = f"❌ No seasons found for *{escape_md(title)}*"
        if hasattr(context_or_query, 'edit_message_text'):
            await context_or_query.edit_message_text(msg, parse_mode=ParseMode.MARKDOWN_V2)
        else:
            await send_command_response(update, context_or_query, msg, parse_mode=ParseMode.MARKDOWN_V2)
        return

    # Create session
    session_id = f"moreeps_{user_id}_{int(datetime.now().timestamp())}"
    moreeps_sessions[session_id] = {
        "user_id": user_id,
        "sonarr_id": sonarr_id,
        "title": title,
        "series_data": series_data,
        "episodes": episodes
    }

    # Group episodes by season for status info
    season_eps = {}
    for ep in episodes:
        sn = ep.get("seasonNumber", 0)
        if sn == 0:
            continue
        if sn not in season_eps:
            season_eps[sn] = {"total": 0, "monitored": 0, "has_file": 0}
        season_eps[sn]["total"] += 1
        if ep.get("monitored", False):
            season_eps[sn]["monitored"] += 1
        if ep.get("hasFile", False):
            season_eps[sn]["has_file"] += 1

    msg = f"📺 *{escape_md(title)}*\n\n"
    msg += "Select a season to manage episodes:\n\n"

    keyboard = []

    for season in sorted(regular_seasons, key=lambda s: s.get("seasonNumber", 0)):
        sn = season.get("seasonNumber", 0)
        monitored = season.get("monitored", False)

        # Get episode counts for this season
        ep_info = season_eps.get(sn, {"total": 0, "monitored": 0, "has_file": 0})
        total_eps = ep_info["total"]
        downloaded = ep_info["has_file"]
        mon_count = ep_info["monitored"]

        # Status indicator
        if downloaded == total_eps and total_eps > 0:
            status = "✅"  # All downloaded
        elif downloaded > 0:
            status = "⏬"  # Partially downloaded
        elif mon_count > 0:
            status = "👁️"  # Monitored but not downloaded
        else:
            status = "⬜"  # Not monitored

        button_text = f"{status} Season {sn} ({downloaded}/{total_eps} eps)"

        keyboard.append([InlineKeyboardButton(
            button_text,
            callback_data=f"moreeps_season_{session_id}_{sn}"
        )])

    # Add "Monitor All Seasons" button
    keyboard.append([InlineKeyboardButton(
        "📦 Monitor All Seasons",
        callback_data=f"moreeps_allseasons_{session_id}"
    )])

    keyboard.append([InlineKeyboardButton(
        "❌ Cancel",
        callback_data=f"moreeps_cancel_{session_id}"
    )])

    msg += "_Legend: ✅ Complete ⏬ Partial 👁️ Monitored ⬜ Not monitored_"

    if hasattr(context_or_query, 'edit_message_text'):
        # This is a callback query
        await context_or_query.edit_message_text(
            msg,
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:
        # This is from the command directly - send via bot topic
        await context_or_query.bot.send_message(
            chat_id=GROUP_CHAT_ID,
            text=msg,
            message_thread_id=BOT_TOPIC_ID,
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=InlineKeyboardMarkup(keyboard),
            disable_notification=SILENT_NOTIFICATIONS
        )


async def show_season_episodes(query, session_id, season_number):
    """Show episodes for a specific season with monitoring status"""
    session = moreeps_sessions.get(session_id)
    if not session:
        await query.edit_message_text("❌ Session expired\\. Please try `/moreeps` again\\.",
                                       parse_mode=ParseMode.MARKDOWN_V2)
        return

    title = session.get("title", "Unknown")
    episodes = session.get("episodes", [])

    # Get episodes for this season
    season_episodes = [
        ep for ep in episodes
        if ep.get("seasonNumber") == season_number
    ]

    if not season_episodes:
        await query.edit_message_text(
            f"❌ No episodes found for *{escape_md(title)}* Season {season_number}",
            parse_mode=ParseMode.MARKDOWN_V2
        )
        return

    # Sort by episode number
    season_episodes.sort(key=lambda e: e.get("episodeNumber", 0))

    msg = f"📺 *{escape_md(title)}* \\- Season {season_number}\n\n"

    # Count stats
    total = len(season_episodes)
    monitored = sum(1 for ep in season_episodes if ep.get("monitored", False))
    downloaded = sum(1 for ep in season_episodes if ep.get("hasFile", False))
    unmonitored_without_file = [
        ep for ep in season_episodes
        if not ep.get("monitored", False) and not ep.get("hasFile", False)
    ]

    msg += f"📊 {downloaded}/{total} downloaded \\| {monitored}/{total} monitored\n\n"

    # Show episode list (compact)
    for ep in season_episodes:
        ep_num = ep.get("episodeNumber", 0)
        ep_title = ep.get("title", "TBA")
        has_file = ep.get("hasFile", False)
        is_monitored = ep.get("monitored", False)

        if has_file:
            status = "✅"
        elif is_monitored:
            status = "👁️"
        else:
            status = "⬜"

        # Truncate long episode titles
        if len(ep_title) > 30:
            ep_title = ep_title[:27] + "..."

        msg += f"{status} E{ep_num:02d} \\- {escape_md(ep_title)}\n"

    keyboard = []

    # "Monitor All Episodes" in this season
    keyboard.append([InlineKeyboardButton(
        "📦 Monitor All Episodes in Season",
        callback_data=f"moreeps_monall_{session_id}_{season_number}"
    )])

    # "Monitor Unmonitored Episodes" (only those without files)
    if unmonitored_without_file:
        keyboard.append([InlineKeyboardButton(
            f"➕ Monitor {len(unmonitored_without_file)} Missing Episode(s)",
            callback_data=f"moreeps_monmissing_{session_id}_{season_number}"
        )])

    # Back to seasons
    keyboard.append([InlineKeyboardButton(
        "◀️ Back to Seasons",
        callback_data=f"moreeps_back_{session_id}"
    )])

    keyboard.append([InlineKeyboardButton(
        "❌ Cancel",
        callback_data=f"moreeps_cancel_{session_id}"
    )])

    await query.edit_message_text(
        msg,
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def handle_moreeps_callback(update, context: CallbackContext):
    """Handle all moreeps-related callback queries"""
    query = update.callback_query
    await query.answer()

    callback_data = query.data
    user_id = update.effective_user.id

    logger.info("🔄 Moreeps callback from user %s: %s", user_id, callback_data)

    try:
        if callback_data.startswith("moreeps_pick_"):
            # User picked a series from search results
            await handle_series_pick(query, callback_data, user_id, update, context)

        elif callback_data.startswith("moreeps_season_"):
            # User picked a season to view episodes
            await handle_season_pick(query, callback_data, user_id)

        elif callback_data.startswith("moreeps_allseasons_"):
            # Monitor all seasons
            await handle_monitor_all_seasons(query, callback_data, user_id)

        elif callback_data.startswith("moreeps_monall_"):
            # Monitor all episodes in a season
            await handle_monitor_all_in_season(query, callback_data, user_id)

        elif callback_data.startswith("moreeps_monmissing_"):
            # Monitor only missing/unmonitored episodes
            await handle_monitor_missing_in_season(query, callback_data, user_id)

        elif callback_data.startswith("moreeps_back_"):
            # Go back to season list
            await handle_back_to_seasons(query, callback_data, user_id)

        elif callback_data.startswith("moreeps_cancel_"):
            # Cancel
            await handle_moreeps_cancel(query, callback_data, user_id)

        else:
            logger.warning("Unknown moreeps callback: %s", callback_data)

    except Exception as e:
        logger.error("Moreeps callback error: %s", e)
        try:
            await query.edit_message_text(f"❌ Error: {str(e)}")
        except:
            pass


async def handle_series_pick(query, callback_data, user_id, update, context):
    """Handle user picking a series from multiple search results"""
    # Parse: moreeps_pick_{session_id}_{index}
    parts = callback_data.split("_")
    # moreeps_pick_{session_id}_{index}
    # session_id contains the user_id and timestamp, so reconstruct it
    index = int(parts[-1])
    session_id = "_".join(parts[2:-1])

    session = moreeps_sessions.get(session_id)
    if not session:
        await query.edit_message_text("❌ Session expired\\. Please try `/moreeps` again\\.",
                                       parse_mode=ParseMode.MARKDOWN_V2)
        return

    if session["user_id"] != user_id:
        await query.answer("❌ This is not your search.", show_alert=True)
        return

    matches = session.get("matches", [])
    if index >= len(matches):
        await query.edit_message_text("❌ Invalid selection\\.", parse_mode=ParseMode.MARKDOWN_V2)
        return

    series = matches[index]

    # Clean up the pick session
    moreeps_sessions.pop(session_id, None)

    # Show seasons for this series
    await show_series_seasons(update, query, series, user_id)


async def handle_season_pick(query, callback_data, user_id):
    """Handle user picking a season to view episodes"""
    # Parse: moreeps_season_{session_id}_{season_number}
    parts = callback_data.split("_")
    season_number = int(parts[-1])
    session_id = "_".join(parts[2:-1])

    session = moreeps_sessions.get(session_id)
    if not session:
        await query.edit_message_text("❌ Session expired\\. Please try `/moreeps` again\\.",
                                       parse_mode=ParseMode.MARKDOWN_V2)
        return

    if session["user_id"] != user_id:
        await query.answer("❌ This is not your search.", show_alert=True)
        return

    await show_season_episodes(query, session_id, season_number)


async def handle_monitor_all_seasons(query, callback_data, user_id):
    """Monitor all episodes across all seasons"""
    # Parse: moreeps_allseasons_{session_id}
    parts = callback_data.split("_")
    session_id = "_".join(parts[2:])

    session = moreeps_sessions.get(session_id)
    if not session:
        await query.edit_message_text("❌ Session expired\\. Please try `/moreeps` again\\.",
                                       parse_mode=ParseMode.MARKDOWN_V2)
        return

    if session["user_id"] != user_id:
        await query.answer("❌ This is not your search.", show_alert=True)
        return

    title = session.get("title", "Unknown")
    episodes = session.get("episodes", [])

    await query.edit_message_text(
        f"🔄 Monitoring all seasons of *{escape_md(title)}*\\.\\.\\.",
        parse_mode=ParseMode.MARKDOWN_V2
    )

    # Get all non-special episode IDs that aren't already monitored
    episode_ids = [
        ep["id"] for ep in episodes
        if ep.get("seasonNumber", 0) > 0 and not ep.get("monitored", False)
    ]

    if not episode_ids:
        await query.edit_message_text(
            f"✅ All episodes of *{escape_md(title)}* are already monitored\\!",
            parse_mode=ParseMode.MARKDOWN_V2
        )
        moreeps_sessions.pop(session_id, None)
        return

    # Set monitoring
    success, error = await set_episode_monitoring(episode_ids, True)
    if not success:
        await query.edit_message_text(
            f"❌ Failed to set monitoring: {escape_md(error)}",
            parse_mode=ParseMode.MARKDOWN_V2
        )
        return

    # Trigger search for the newly monitored episodes
    # Only search for episodes that don't have files
    search_ids = [
        ep["id"] for ep in episodes
        if ep.get("seasonNumber", 0) > 0 and not ep.get("hasFile", False) and ep["id"] in episode_ids
    ]

    search_msg = ""
    if search_ids:
        search_success, _ = await trigger_episode_search(search_ids)
        if search_success:
            search_msg = f"\n🔍 Searching for {len(search_ids)} missing episode\\(s\\)\\.\\.\\."

    await query.edit_message_text(
        f"✅ *{escape_md(title)}*\n\n"
        f"📦 Monitoring set for {len(episode_ids)} episode\\(s\\) across all seasons\\!"
        f"{search_msg}\n\n"
        f"📬 You'll be notified when episodes are available\\.",
        parse_mode=ParseMode.MARKDOWN_V2
    )

    # Clean up
    moreeps_sessions.pop(session_id, None)


async def handle_monitor_all_in_season(query, callback_data, user_id):
    """Monitor all episodes in a specific season"""
    # Parse: moreeps_monall_{session_id}_{season_number}
    parts = callback_data.split("_")
    season_number = int(parts[-1])
    session_id = "_".join(parts[2:-1])

    session = moreeps_sessions.get(session_id)
    if not session:
        await query.edit_message_text("❌ Session expired\\. Please try `/moreeps` again\\.",
                                       parse_mode=ParseMode.MARKDOWN_V2)
        return

    if session["user_id"] != user_id:
        await query.answer("❌ This is not your search.", show_alert=True)
        return

    title = session.get("title", "Unknown")
    episodes = session.get("episodes", [])

    # Get unmonitored episodes in this season
    season_eps = [
        ep for ep in episodes
        if ep.get("seasonNumber") == season_number and not ep.get("monitored", False)
    ]

    if not season_eps:
        await query.edit_message_text(
            f"✅ All episodes in *{escape_md(title)}* Season {season_number} are already monitored\\!",
            parse_mode=ParseMode.MARKDOWN_V2
        )
        return

    episode_ids = [ep["id"] for ep in season_eps]

    await query.edit_message_text(
        f"🔄 Monitoring all episodes in *{escape_md(title)}* Season {season_number}\\.\\.\\.",
        parse_mode=ParseMode.MARKDOWN_V2
    )

    # Set monitoring
    success, error = await set_episode_monitoring(episode_ids, True)
    if not success:
        await query.edit_message_text(
            f"❌ Failed to set monitoring: {escape_md(error)}",
            parse_mode=ParseMode.MARKDOWN_V2
        )
        return

    # Trigger search for episodes without files
    search_ids = [ep["id"] for ep in season_eps if not ep.get("hasFile", False)]

    search_msg = ""
    if search_ids:
        search_success, _ = await trigger_episode_search(search_ids)
        if search_success:
            search_msg = f"\n🔍 Searching for {len(search_ids)} missing episode\\(s\\)\\.\\.\\."

    await query.edit_message_text(
        f"✅ *{escape_md(title)}* \\- Season {season_number}\n\n"
        f"📦 Monitoring set for {len(episode_ids)} episode\\(s\\)\\!"
        f"{search_msg}\n\n"
        f"📬 You'll be notified when episodes are available\\.",
        parse_mode=ParseMode.MARKDOWN_V2
    )

    # Clean up
    moreeps_sessions.pop(session_id, None)


async def handle_monitor_missing_in_season(query, callback_data, user_id):
    """Monitor only missing (unmonitored + no file) episodes in a season"""
    # Parse: moreeps_monmissing_{session_id}_{season_number}
    parts = callback_data.split("_")
    season_number = int(parts[-1])
    session_id = "_".join(parts[2:-1])

    session = moreeps_sessions.get(session_id)
    if not session:
        await query.edit_message_text("❌ Session expired\\. Please try `/moreeps` again\\.",
                                       parse_mode=ParseMode.MARKDOWN_V2)
        return

    if session["user_id"] != user_id:
        await query.answer("❌ This is not your search.", show_alert=True)
        return

    title = session.get("title", "Unknown")
    episodes = session.get("episodes", [])

    # Get unmonitored episodes without files in this season
    missing_eps = [
        ep for ep in episodes
        if ep.get("seasonNumber") == season_number
        and not ep.get("monitored", False)
        and not ep.get("hasFile", False)
    ]

    if not missing_eps:
        await query.edit_message_text(
            f"✅ No missing episodes to monitor in *{escape_md(title)}* Season {season_number}\\!",
            parse_mode=ParseMode.MARKDOWN_V2
        )
        return

    episode_ids = [ep["id"] for ep in missing_eps]

    await query.edit_message_text(
        f"🔄 Monitoring {len(missing_eps)} missing episode\\(s\\) in *{escape_md(title)}* Season {season_number}\\.\\.\\.",
        parse_mode=ParseMode.MARKDOWN_V2
    )

    # Set monitoring
    success, error = await set_episode_monitoring(episode_ids, True)
    if not success:
        await query.edit_message_text(
            f"❌ Failed to set monitoring: {escape_md(error)}",
            parse_mode=ParseMode.MARKDOWN_V2
        )
        return

    # Trigger search
    search_success, _ = await trigger_episode_search(episode_ids)

    search_msg = ""
    if search_success:
        search_msg = f"\n🔍 Searching for {len(episode_ids)} episode\\(s\\)\\.\\.\\."

    await query.edit_message_text(
        f"✅ *{escape_md(title)}* \\- Season {season_number}\n\n"
        f"➕ Monitoring set for {len(episode_ids)} missing episode\\(s\\)\\!"
        f"{search_msg}\n\n"
        f"📬 You'll be notified when episodes are available\\.",
        parse_mode=ParseMode.MARKDOWN_V2
    )

    # Clean up
    moreeps_sessions.pop(session_id, None)


async def handle_back_to_seasons(query, callback_data, user_id):
    """Go back to season list"""
    # Parse: moreeps_back_{session_id}
    parts = callback_data.split("_")
    session_id = "_".join(parts[2:])

    session = moreeps_sessions.get(session_id)
    if not session:
        await query.edit_message_text("❌ Session expired\\. Please try `/moreeps` again\\.",
                                       parse_mode=ParseMode.MARKDOWN_V2)
        return

    if session["user_id"] != user_id:
        await query.answer("❌ This is not your search.", show_alert=True)
        return

    # Refresh episode data from Sonarr (in case monitoring changed)
    sonarr_id = session.get("sonarr_id")
    if sonarr_id:
        episodes, ep_error = await get_sonarr_episodes(sonarr_id)
        if not ep_error:
            session["episodes"] = episodes

    # Rebuild the series object from session data
    series_data = session.get("series_data", {})
    title = session.get("title", "Unknown")
    episodes = session.get("episodes", [])

    # Get seasons from series_data
    seasons = series_data.get("seasons", [])
    regular_seasons = [s for s in seasons if s.get("seasonNumber", 0) > 0]

    # Group episodes by season for status info
    season_eps = {}
    for ep in episodes:
        sn = ep.get("seasonNumber", 0)
        if sn == 0:
            continue
        if sn not in season_eps:
            season_eps[sn] = {"total": 0, "monitored": 0, "has_file": 0}
        season_eps[sn]["total"] += 1
        if ep.get("monitored", False):
            season_eps[sn]["monitored"] += 1
        if ep.get("hasFile", False):
            season_eps[sn]["has_file"] += 1

    msg = f"📺 *{escape_md(title)}*\n\n"
    msg += "Select a season to manage episodes:\n\n"

    keyboard = []
    for season in sorted(regular_seasons, key=lambda s: s.get("seasonNumber", 0)):
        sn = season.get("seasonNumber", 0)

        ep_info = season_eps.get(sn, {"total": 0, "monitored": 0, "has_file": 0})
        total_eps = ep_info["total"]
        downloaded = ep_info["has_file"]
        mon_count = ep_info["monitored"]

        if downloaded == total_eps and total_eps > 0:
            status = "✅"
        elif downloaded > 0:
            status = "⏬"
        elif mon_count > 0:
            status = "👁️"
        else:
            status = "⬜"

        button_text = f"{status} Season {sn} ({downloaded}/{total_eps} eps)"

        keyboard.append([InlineKeyboardButton(
            button_text,
            callback_data=f"moreeps_season_{session_id}_{sn}"
        )])

    keyboard.append([InlineKeyboardButton(
        "📦 Monitor All Seasons",
        callback_data=f"moreeps_allseasons_{session_id}"
    )])

    keyboard.append([InlineKeyboardButton(
        "❌ Cancel",
        callback_data=f"moreeps_cancel_{session_id}"
    )])

    msg += "_Legend: ✅ Complete ⏬ Partial 👁️ Monitored ⬜ Not monitored_"

    await query.edit_message_text(
        msg,
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def handle_moreeps_cancel(query, callback_data, user_id):
    """Cancel moreeps session"""
    # Parse: moreeps_cancel_{session_id}
    parts = callback_data.split("_")
    session_id = "_".join(parts[2:])

    session = moreeps_sessions.get(session_id)
    if session and session["user_id"] != user_id:
        await query.answer("❌ This is not your search.", show_alert=True)
        return

    moreeps_sessions.pop(session_id, None)

    await query.edit_message_text(
        "❌ Cancelled\\.",
        parse_mode=ParseMode.MARKDOWN_V2
    )
