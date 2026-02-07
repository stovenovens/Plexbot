"""
Request system callback handlers
Handles inline keyboard interactions for movie/TV requests
"""

import logging
from datetime import datetime
from telegram.ext import CallbackContext
from telegram.constants import ParseMode
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from httpx import AsyncClient

from config import (
    RADARR_URL, RADARR_API_KEY, SONARR_URL, SONARR_API_KEY, MELBOURNE_TZ, TMDB_BEARER_TOKEN
)
from utils.helpers import escape_md
from commands.request_commands import request_manager

logger = logging.getLogger(__name__)


async def build_movie_success_message(movie, title, radarr_id, request_tracker):
    """Build success message for movie add, including release date and search status"""
    release_date = movie.get("release_date")
    is_unreleased = request_tracker.is_release_date_future(release_date) if release_date else False

    if is_unreleased:
        release_display = request_tracker.get_release_date_display(release_date)
        return (
            f"✅ *{escape_md(title)}* has been added to Radarr\\!\n\n"
            f"📅 *Release Date:* {escape_md(release_display)}\n\n"
            f"⏳ This movie hasn't been released yet\\. "
            f"We'll start looking for it closer to the release date\\.\n\n"
            f"📬 You'll be notified when it's available\\."
        )

    # Check if indexers found any results
    result_count, search_done = await request_tracker.check_radarr_indexer_results(radarr_id)

    if search_done and result_count > 0:
        return (
            f"✅ *{escape_md(title)}* has been added to Radarr\\!\n\n"
            f"🔍 Found {result_count} release\\(s\\) \\- downloading now\\!\n\n"
            f"📬 You'll be notified when it's available\\."
        )
    elif search_done and result_count == 0:
        return (
            f"✅ *{escape_md(title)}* has been added to Radarr\\!\n\n"
            f"⚠️ No releases found yet\\. This could mean:\n"
            f"• The movie is older/niche and may be hard to find\n"
            f"• It may take time for releases to appear\n\n"
            f"📬 We'll keep checking and notify you if it becomes available\\."
        )
    else:
        return (
            f"✅ *{escape_md(title)}* has been added to Radarr\\!\n\n"
            f"📬 You'll be notified when it's available\\."
        )


async def build_tv_success_message(show, title, sonarr_id, request_tracker):
    """Build success message for TV add, including release date and search status"""
    first_air_date = show.get("first_air_date")
    is_unreleased = request_tracker.is_release_date_future(first_air_date) if first_air_date else False

    if is_unreleased:
        release_display = request_tracker.get_release_date_display(first_air_date)
        return (
            f"✅ *{escape_md(title)}* has been added to Sonarr\\!\n\n"
            f"📅 *First Air Date:* {escape_md(release_display)}\n\n"
            f"⏳ This series hasn't aired yet\\. "
            f"We'll start looking for episodes closer to the premiere\\.\n\n"
            f"📬 You'll be notified when episodes are available\\."
        )

    # Check if indexers found any results
    result_count, search_done = await request_tracker.check_sonarr_indexer_results(sonarr_id)

    if search_done and result_count > 0:
        return (
            f"✅ *{escape_md(title)}* has been added to Sonarr\\!\n\n"
            f"🔍 Found {result_count} release\\(s\\) \\- downloading now\\!\n\n"
            f"📬 You'll be notified when episodes are available\\."
        )
    elif search_done and result_count == 0:
        return (
            f"✅ *{escape_md(title)}* has been added to Sonarr\\!\n\n"
            f"⚠️ No releases found yet for the latest season\\. This could mean:\n"
            f"• Episodes may not be available yet\n"
            f"• It may take time for releases to appear\n\n"
            f"📬 We'll keep checking and notify you when available\\."
        )
    else:
        return (
            f"✅ *{escape_md(title)}* has been added to Sonarr\\!\n\n"
            f"📬 You'll be notified when episodes are available\\."
        )


async def handle_request_callback(update, context: CallbackContext):
    """Handle all request-related callback queries"""
    query = update.callback_query
    await query.answer()  # Acknowledge the callback
    
    callback_data = query.data
    user_id = update.effective_user.id
    
    logger.info("🔄 Request callback from user %s: %s", user_id, callback_data)
    
    try:
        # Parse callback data
        if callback_data.startswith("movie_nav_"):
            await handle_movie_navigation(query, callback_data)
        elif callback_data.startswith("tv_nav_"):
            await handle_tv_navigation(query, callback_data)
        elif callback_data.startswith("add_movie_"):
            await handle_add_movie(query, callback_data)
        elif callback_data.startswith("add_tv_"):
            await handle_add_tv(query, callback_data)
        elif callback_data.startswith("cancel_search_"):
            await handle_cancel_search(query, callback_data)
        elif callback_data == "already_added":
            already_text = "✅ This content is already in Radarr/Sonarr\\!\n\n_It may still be downloading or processing\\._"
            if query.message.photo:
                await query.edit_message_caption(caption=already_text, parse_mode=ParseMode.MARKDOWN_V2)
            else:
                await query.edit_message_text(already_text, parse_mode=ParseMode.MARKDOWN_V2)
        elif callback_data == "already_on_plex":
            plex_text = "✅ This content is already available on Plex\\!\n\n🍿 You can watch it right now\\!"
            if query.message.photo:
                await query.edit_message_caption(caption=plex_text, parse_mode=ParseMode.MARKDOWN_V2)
            else:
                await query.edit_message_text(plex_text, parse_mode=ParseMode.MARKDOWN_V2)
        elif callback_data == "not_configured":
            config_text = "❌ Radarr/Sonarr not configured\\. Contact admin\\."
            if query.message.photo:
                await query.edit_message_caption(caption=config_text, parse_mode=ParseMode.MARKDOWN_V2)
            else:
                await query.edit_message_text(config_text, parse_mode=ParseMode.MARKDOWN_V2)
        elif callback_data.startswith("select_root_"):
            await handle_root_folder_selection(query, callback_data)
        elif callback_data.startswith("select_quality_"):
            await handle_quality_profile_selection(query, callback_data)
        else:
            logger.warning("⚠️ Unknown callback data: %s", callback_data)
            
    except Exception as e:
        logger.error("❌ Request callback handler error: %s", e)
        try:
            await query.edit_message_text(f"❌ Error: {str(e)}")
        except:
            pass

async def handle_movie_navigation(query, callback_data):
    """Handle movie result navigation"""
    parts = callback_data.split("_")
    if len(parts) < 4:
        return
    
    search_id = "_".join(parts[2:-1])  # Reconstruct search_id
    new_index = int(parts[-1])
    
    # Get search data
    search_data = request_manager.active_searches.get(search_id)
    if not search_data:
        expired_text = "❌ Search session expired\\. Please search again\\."
        if query.message.photo:
            await query.edit_message_caption(caption=expired_text, parse_mode=ParseMode.MARKDOWN_V2)
        else:
            await query.edit_message_text(expired_text, parse_mode=ParseMode.MARKDOWN_V2)
        return
    
    # Check user permission
    if search_data["user_id"] != query.from_user.id:
        await query.answer("❌ This is not your search\\.", show_alert=True)
        return
    
    # Get movie result
    results = search_data["results"]
    if new_index < 0 or new_index >= len(results):
        return
    
    movie = results[new_index]
    search_data["current_index"] = new_index

    # Get movie info for checks
    tmdb_id = movie.get("id")
    title = movie.get("title", "")
    year = None
    if movie.get("release_date"):
        try:
            year = int(movie["release_date"][:4])
        except (ValueError, IndexError):
            pass

    # Check Plex first (most authoritative - content is actually available)
    already_on_plex = False
    on_plex, _ = await request_manager.check_exists_in_plex(title, year, "movie")
    already_on_plex = on_plex

    # Then check Radarr if not on Plex
    already_in_radarr = False
    if tmdb_id and not already_on_plex:
        exists, _ = await request_manager.check_movie_exists_in_radarr(tmdb_id)
        already_in_radarr = exists

    # Update message
    msg = request_manager.format_movie_result(movie, new_index, len(results))
    keyboard = request_manager.create_movie_keyboard(
        movie, new_index, len(results), search_id,
        already_in_radarr=already_in_radarr, already_on_plex=already_on_plex
    )
    poster_url = request_manager.get_poster_url(movie.get("poster_path"))
    
    # Handle image updates properly
    try:
        # Get chat info from the original message
        chat_id = query.message.chat_id
        message_thread_id = query.message.message_thread_id
        
        # Delete old message and send new one with correct image
        await query.delete_message()
        
        # Import the bot from context (available in callback context)
        from config import SILENT_NOTIFICATIONS
        
        if poster_url:
            # Send new message with poster
            await query.get_bot().send_photo(
                chat_id=chat_id,
                photo=poster_url,
                caption=msg,
                message_thread_id=message_thread_id,
                parse_mode=ParseMode.MARKDOWN_V2,
                reply_markup=keyboard,
                disable_notification=SILENT_NOTIFICATIONS
            )
        else:
            # Send new message as text
            await query.get_bot().send_message(
                chat_id=chat_id,
                text=msg,
                message_thread_id=message_thread_id,
                parse_mode=ParseMode.MARKDOWN_V2,
                reply_markup=keyboard,
                disable_notification=SILENT_NOTIFICATIONS
            )
    except Exception as e:
        logger.error("❌ Failed to update movie navigation: %s", e)

async def handle_tv_navigation(query, callback_data):
    """Handle TV show result navigation"""
    parts = callback_data.split("_")
    if len(parts) < 4:
        return
    
    search_id = "_".join(parts[2:-1])  # Reconstruct search_id
    new_index = int(parts[-1])
    
    # Get search data
    search_data = request_manager.active_searches.get(search_id)
    if not search_data:
        expired_text = "❌ Search session expired\\. Please search again\\."
        if query.message.photo:
            await query.edit_message_caption(caption=expired_text, parse_mode=ParseMode.MARKDOWN_V2)
        else:
            await query.edit_message_text(expired_text, parse_mode=ParseMode.MARKDOWN_V2)
        return
    
    # Check user permission
    if search_data["user_id"] != query.from_user.id:
        await query.answer("❌ This is not your search\\.", show_alert=True)
        return
    
    # Get TV show result
    results = search_data["results"]
    if new_index < 0 or new_index >= len(results):
        return
    
    show = results[new_index]
    search_data["current_index"] = new_index

    # Get show info for checks
    name = show.get("name", "")
    year = None
    if show.get("first_air_date"):
        try:
            year = int(show["first_air_date"][:4])
        except (ValueError, IndexError):
            pass

    # Check Plex (most authoritative - content is actually available)
    already_on_plex = False
    on_plex, _ = await request_manager.check_exists_in_plex(name, year, "show")
    already_on_plex = on_plex

    # Check Sonarr if not already on Plex (requires TVDB ID lookup from TMDB)
    already_in_sonarr = False
    if not already_on_plex:
        tmdb_id = show.get("id")
        if tmdb_id:
            tvdb_id = await request_manager.get_tvdb_id_from_tmdb(tmdb_id)
            if tvdb_id:
                exists, _ = await request_manager.check_series_exists_in_sonarr(tvdb_id)
                already_in_sonarr = exists

    # Update message
    msg = request_manager.format_tv_result(show, new_index, len(results))
    keyboard = request_manager.create_tv_keyboard(
        show, new_index, len(results), search_id,
        already_in_sonarr=already_in_sonarr, already_on_plex=already_on_plex
    )
    poster_url = request_manager.get_poster_url(show.get("poster_path"))
    
    # Handle image updates properly
    try:
        # Get chat info from the original message
        chat_id = query.message.chat_id
        message_thread_id = query.message.message_thread_id
        
        # Delete old message and send new one with correct image
        await query.delete_message()
        
        # Import the bot from context (available in callback context)
        from config import SILENT_NOTIFICATIONS
        
        if poster_url:
            # Send new message with poster
            await query.get_bot().send_photo(
                chat_id=chat_id,
                photo=poster_url,
                caption=msg,
                message_thread_id=message_thread_id,
                parse_mode=ParseMode.MARKDOWN_V2,
                reply_markup=keyboard,
                disable_notification=SILENT_NOTIFICATIONS
            )
        else:
            # Send new message as text
            await query.get_bot().send_message(
                chat_id=chat_id,
                text=msg,
                message_thread_id=message_thread_id,
                parse_mode=ParseMode.MARKDOWN_V2,
                reply_markup=keyboard,
                disable_notification=SILENT_NOTIFICATIONS
            )
    except Exception as e:
        logger.error("❌ Failed to update TV navigation: %s", e)

async def handle_add_movie(query, callback_data):
    """Handle adding movie to Radarr"""
    from utils.request_tracker import request_tracker

    parts = callback_data.split("_")
    if len(parts) < 4:
        return

    search_id = "_".join(parts[2:-1])  # Reconstruct search_id
    index = int(parts[-1])

    # Get search data
    search_data = request_manager.active_searches.get(search_id)
    if not search_data:
        await query.edit_message_text("❌ Search session expired\\. Please search again\\.")
        return

    # Check user permission
    if search_data["user_id"] != query.from_user.id:
        await query.answer("❌ This is not your search\\.", show_alert=True)
        return

    movie = search_data["results"][index]
    tmdb_id = movie.get("id")
    user_id = query.from_user.id
    username = query.from_user.username or query.from_user.first_name

    # Check for duplicate request
    existing_request = request_tracker.find_existing_request("movie", tmdb_id)
    if existing_request:
        # Add user as subscriber to existing request
        added = request_tracker.add_subscriber(existing_request["id"], user_id, username)
        title = movie.get("title", "Unknown")
        original_user = existing_request.get("username", "someone")

        if added:
            msg = (f"👥 *{escape_md(title)}* was already requested by @{escape_md(original_user)}\\!\n\n"
                   f"✅ You've been added to the notification list\\.\n"
                   f"📬 You'll be notified when it's available\\.")
        else:
            msg = (f"ℹ️ You've already requested *{escape_md(title)}*\\!\n\n"
                   f"📬 You'll be notified when it's available\\.")

        if query.message.photo:
            await query.edit_message_caption(caption=msg, parse_mode=ParseMode.MARKDOWN_V2)
        else:
            await query.edit_message_text(msg, parse_mode=ParseMode.MARKDOWN_V2)

        # Clean up
        request_manager.active_searches.pop(search_id, None)
        return

    # Get root folders and quality profiles
    if query.message.photo:
        await query.edit_message_caption(caption="🔍 Checking Radarr configuration\\.\\.\\.", parse_mode=ParseMode.MARKDOWN_V2)
    else:
        await query.edit_message_text("🔍 Checking Radarr configuration\\.\\.\\.", parse_mode=ParseMode.MARKDOWN_V2)
    
    root_folders, root_error = await request_manager.get_radarr_root_folders()
    quality_profiles, quality_error = await request_manager.get_radarr_quality_profiles()
    
    if root_error or quality_error:
        error_msg = root_error or quality_error
        error_text = f"❌ Radarr configuration error: {escape_md(error_msg)}"
        if query.message.photo:
            await query.edit_message_caption(caption=error_text, parse_mode=ParseMode.MARKDOWN_V2)
        else:
            await query.edit_message_text(error_text, parse_mode=ParseMode.MARKDOWN_V2)
        return
    
    if not root_folders or not quality_profiles:
        error_text = "❌ No root folders or quality profiles configured in Radarr"
        if query.message.photo:
            await query.edit_message_caption(caption=error_text)
        else:
            await query.edit_message_text(error_text)
        return
    
    # Store movie data for later use
    movie_data = {
        "movie": movie,
        "search_id": search_id,
        "root_folders": root_folders,
        "quality_profiles": quality_profiles
    }
    
    # Store in active searches for callback access
    request_manager.active_searches[f"add_movie_{search_id}"] = movie_data
    
    # If only one root folder and one quality profile, add directly
    if len(root_folders) == 1 and len(quality_profiles) == 1:
        root_folder = root_folders[0]
        quality_profile = quality_profiles[0]

        success, error, radarr_id = await add_movie_to_radarr(movie, root_folder, quality_profile, user_id, username)
        if success:
            title = movie.get("title", "Unknown")
            success_text = await build_movie_success_message(movie, title, radarr_id, request_tracker)
            if query.message.photo:
                await query.edit_message_caption(caption=success_text, parse_mode=ParseMode.MARKDOWN_V2)
            else:
                await query.edit_message_text(success_text, parse_mode=ParseMode.MARKDOWN_V2)
            # Clean up
            request_manager.active_searches.pop(search_id, None)
            request_manager.active_searches.pop(f"add_movie_{search_id}", None)
        else:
            error_text = f"❌ Failed to add movie: {escape_md(error)}"
            if query.message.photo:
                await query.edit_message_caption(caption=error_text, parse_mode=ParseMode.MARKDOWN_V2)
            else:
                await query.edit_message_text(error_text, parse_mode=ParseMode.MARKDOWN_V2)
    else:
        # Show root folder selection
        await show_root_folder_selection(query, movie_data, "movie")

async def handle_add_tv(query, callback_data):
    """Handle adding TV series to Sonarr"""
    from utils.request_tracker import request_tracker

    parts = callback_data.split("_")
    if len(parts) < 4:
        return

    search_id = "_".join(parts[2:-1])  # Reconstruct search_id
    index = int(parts[-1])

    # Get search data
    search_data = request_manager.active_searches.get(search_id)
    if not search_data:
        await query.edit_message_text("❌ Search session expired\\. Please search again\\.")
        return

    # Check user permission
    if search_data["user_id"] != query.from_user.id:
        await query.answer("❌ This is not your search\\.", show_alert=True)
        return

    show = search_data["results"][index]
    tmdb_id = show.get("id")
    user_id = query.from_user.id
    username = query.from_user.username or query.from_user.first_name

    # Check for duplicate request
    existing_request = request_tracker.find_existing_request("tv", tmdb_id)
    if existing_request:
        # Add user as subscriber to existing request
        added = request_tracker.add_subscriber(existing_request["id"], user_id, username)
        title = show.get("name", "Unknown")
        original_user = existing_request.get("username", "someone")

        if added:
            msg = (f"👥 *{escape_md(title)}* was already requested by @{escape_md(original_user)}\\!\n\n"
                   f"✅ You've been added to the notification list\\.\n"
                   f"📬 You'll be notified when episodes are available\\.")
        else:
            msg = (f"ℹ️ You've already requested *{escape_md(title)}*\\!\n\n"
                   f"📬 You'll be notified when episodes are available\\.")

        if query.message.photo:
            await query.edit_message_caption(caption=msg, parse_mode=ParseMode.MARKDOWN_V2)
        else:
            await query.edit_message_text(msg, parse_mode=ParseMode.MARKDOWN_V2)

        # Clean up
        request_manager.active_searches.pop(search_id, None)
        return

    # Get root folders and quality profiles
    if query.message.photo:
        await query.edit_message_caption(caption="🔍 Checking Sonarr configuration\\.\\.\\.", parse_mode=ParseMode.MARKDOWN_V2)
    else:
        await query.edit_message_text("🔍 Checking Sonarr configuration\\.\\.\\.", parse_mode=ParseMode.MARKDOWN_V2)
    
    root_folders, root_error = await request_manager.get_sonarr_root_folders()
    quality_profiles, quality_error = await request_manager.get_sonarr_quality_profiles()
    
    if root_error or quality_error:
        error_msg = root_error or quality_error
        error_text = f"❌ Sonarr configuration error: {escape_md(error_msg)}"
        if query.message.photo:
            await query.edit_message_caption(caption=error_text, parse_mode=ParseMode.MARKDOWN_V2)
        else:
            await query.edit_message_text(error_text, parse_mode=ParseMode.MARKDOWN_V2)
        return
    
    if not root_folders or not quality_profiles:
        error_text = "❌ No root folders or quality profiles configured in Sonarr"
        if query.message.photo:
            await query.edit_message_caption(caption=error_text)
        else:
            await query.edit_message_text(error_text)
        return
    
    # Store show data for later use
    show_data = {
        "show": show,
        "search_id": search_id,
        "root_folders": root_folders,
        "quality_profiles": quality_profiles
    }
    
    # Store in active searches for callback access
    request_manager.active_searches[f"add_tv_{search_id}"] = show_data
    
    # If only one root folder and one quality profile, add directly
    if len(root_folders) == 1 and len(quality_profiles) == 1:
        root_folder = root_folders[0]
        quality_profile = quality_profiles[0]

        success, error, sonarr_id = await add_tv_to_sonarr(show, root_folder, quality_profile, user_id, username)
        if success:
            title = show.get("name", "Unknown")
            success_text = await build_tv_success_message(show, title, sonarr_id, request_tracker)
            if query.message.photo:
                await query.edit_message_caption(caption=success_text, parse_mode=ParseMode.MARKDOWN_V2)
            else:
                await query.edit_message_text(success_text, parse_mode=ParseMode.MARKDOWN_V2)
            # Clean up
            request_manager.active_searches.pop(search_id, None)
            request_manager.active_searches.pop(f"add_tv_{search_id}", None)
        else:
            error_text = f"❌ Failed to add series: {escape_md(error)}"
            if query.message.photo:
                await query.edit_message_caption(caption=error_text, parse_mode=ParseMode.MARKDOWN_V2)
            else:
                await query.edit_message_text(error_text, parse_mode=ParseMode.MARKDOWN_V2)
    else:
        # Show root folder selection
        await show_root_folder_selection(query, show_data, "tv")

async def handle_cancel_search(query, callback_data):
    """Handle search cancellation"""
    parts = callback_data.split("_")
    if len(parts) < 3:
        logger.warning("⚠️ Invalid cancel callback data: %s", callback_data)
        return

    search_id = "_".join(parts[2:])  # Reconstruct search_id

    # Get search data
    search_data = request_manager.active_searches.get(search_id)
    if search_data and search_data["user_id"] != query.from_user.id:
        logger.warning("⚠️ User %s tried to cancel search %s owned by %s",
                      query.from_user.id, search_id, search_data["user_id"])
        return

    # Clean up search data
    request_manager.active_searches.pop(search_id, None)

    # Handle both photo and text messages
    cancel_text = "❌ Search cancelled\\."
    try:
        if query.message.photo:
            await query.edit_message_caption(caption=cancel_text, parse_mode=ParseMode.MARKDOWN_V2)
        else:
            await query.edit_message_text(cancel_text, parse_mode=ParseMode.MARKDOWN_V2)
        logger.info("✅ Search cancelled: %s", search_id)
    except Exception as e:
        # Message may have already been edited or deleted
        logger.warning("⚠️ Could not update message for cancelled search %s: %s", search_id, e)

async def show_root_folder_selection(query, media_data, media_type):
    """Show root folder selection keyboard"""
    root_folders = media_data["root_folders"]
    search_id = media_data["search_id"]
    
    if media_type == "movie":
        title = media_data["movie"].get("title", "Unknown")
    else:
        title = media_data["show"].get("name", "Unknown")
    
    msg = f"📁 *Select Root Folder for:*\n{escape_md(title)}"
    
    keyboard = []
    for folder in root_folders:
        folder_path = folder.get("path", "Unknown Path")
        folder_id = folder.get("id")
        free_space = folder.get("freeSpace", 0)
        
        # Format free space
        if free_space > 0:
            free_gb = free_space / (1024**3)
            if free_gb > 1024:
                free_str = f" ({free_gb/1024:.1f}TB free)"
            else:
                free_str = f" ({free_gb:.1f}GB free)"
        else:
            free_str = ""
        
        button_text = f"{folder_path}{free_str}"
        if len(button_text) > 50:
            button_text = folder_path[:47] + "..."
        
        keyboard.append([InlineKeyboardButton(
            button_text, 
            callback_data=f"select_root_{media_type}_{search_id}_{folder_id}"
        )])
    
    keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data=f"cancel_search_{search_id}")])
    
    await query.edit_message_text(msg, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=InlineKeyboardMarkup(keyboard))

async def handle_root_folder_selection(query, callback_data):
    """Handle root folder selection"""
    parts = callback_data.split("_")
    if len(parts) < 5:
        return
    
    media_type = parts[2]  # "movie" or "tv"
    search_id = "_".join(parts[3:-1])  # Reconstruct search_id
    folder_id = int(parts[-1])
    
    # Get media data
    media_data = request_manager.active_searches.get(f"add_{media_type}_{search_id}")
    if not media_data:
        await query.edit_message_text("❌ Session expired\\. Please search again\\.")
        return
    
    # Find selected root folder
    selected_folder = None
    for folder in media_data["root_folders"]:
        if folder.get("id") == folder_id:
            selected_folder = folder
            break
    
    if not selected_folder:
        await query.edit_message_text("❌ Invalid root folder selection\\.")
        return
    
    # Store selected root folder
    media_data["selected_root_folder"] = selected_folder
    
    # Show quality profile selection
    await show_quality_profile_selection(query, media_data, media_type)

async def show_quality_profile_selection(query, media_data, media_type):
    """Show quality profile selection keyboard"""
    quality_profiles = media_data["quality_profiles"]
    search_id = media_data["search_id"]
    
    if media_type == "movie":
        title = media_data["movie"].get("title", "Unknown")
    else:
        title = media_data["show"].get("name", "Unknown")
    
    msg = f"⚙️ *Select Quality Profile for:*\n{escape_md(title)}"
    
    keyboard = []
    for profile in quality_profiles:
        profile_name = profile.get("name", "Unknown Profile")
        profile_id = profile.get("id")
        
        keyboard.append([InlineKeyboardButton(
            profile_name, 
            callback_data=f"select_quality_{media_type}_{search_id}_{profile_id}"
        )])
    
    keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data=f"cancel_search_{search_id}")])
    
    await query.edit_message_text(msg, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=InlineKeyboardMarkup(keyboard))

async def handle_quality_profile_selection(query, callback_data):
    """Handle quality profile selection and add media"""
    from utils.request_tracker import request_tracker

    parts = callback_data.split("_")
    if len(parts) < 5:
        return

    media_type = parts[2]  # "movie" or "tv"
    search_id = "_".join(parts[3:-1])  # Reconstruct search_id
    profile_id = int(parts[-1])

    # Get media data
    media_data = request_manager.active_searches.get(f"add_{media_type}_{search_id}")
    if not media_data:
        await query.edit_message_text("❌ Session expired\\. Please search again\\.")
        return

    # Find selected quality profile
    selected_profile = None
    for profile in media_data["quality_profiles"]:
        if profile.get("id") == profile_id:
            selected_profile = profile
            break

    if not selected_profile:
        await query.edit_message_text("❌ Invalid quality profile selection\\.")
        return

    # Add media to Radarr/Sonarr
    if query.message.photo:
        await query.edit_message_caption(caption="➕ Adding to library\\.\\.\\.", parse_mode=ParseMode.MARKDOWN_V2)
    else:
        await query.edit_message_text("➕ Adding to library\\.\\.\\.", parse_mode=ParseMode.MARKDOWN_V2)

    root_folder = media_data["selected_root_folder"]

    # Get user info for tracking
    user_id = query.from_user.id
    username = query.from_user.username or query.from_user.first_name

    if media_type == "movie":
        movie = media_data["movie"]
        success, error, media_id = await add_movie_to_radarr(movie, root_folder, selected_profile, user_id, username)
        title = movie.get("title", "Unknown")
    else:
        show = media_data["show"]
        success, error, media_id = await add_tv_to_sonarr(show, root_folder, selected_profile, user_id, username)
        title = show.get("name", "Unknown")

    if success:
        if media_type == "movie":
            success_text = await build_movie_success_message(movie, title, media_id, request_tracker)
        else:
            success_text = await build_tv_success_message(show, title, media_id, request_tracker)
        if query.message.photo:
            await query.edit_message_caption(caption=success_text, parse_mode=ParseMode.MARKDOWN_V2)
        else:
            await query.edit_message_text(success_text, parse_mode=ParseMode.MARKDOWN_V2)
    else:
        error_text = f"❌ Failed to add {media_type}: {escape_md(error)}"
        if query.message.photo:
            await query.edit_message_caption(caption=error_text, parse_mode=ParseMode.MARKDOWN_V2)
        else:
            await query.edit_message_text(error_text, parse_mode=ParseMode.MARKDOWN_V2)
    
    # Clean up
    request_manager.active_searches.pop(search_id, None)
    request_manager.active_searches.pop(f"add_{media_type}_{search_id}", None)

async def add_movie_to_radarr(movie, root_folder, quality_profile, user_id=None, username=None):
    """Add movie to Radarr and track the request"""
    if not (RADARR_URL and RADARR_API_KEY):
        return False, "Radarr not configured", None

    try:
        base_url = RADARR_URL.rstrip('/')
        headers = {"X-Api-Key": RADARR_API_KEY, "Content-Type": "application/json"}

        # Get or create user tag for tracking
        tag_ids = []
        if username:
            tag_id = await get_or_create_radarr_tag(username)
            if tag_id:
                tag_ids.append(tag_id)

        # Prepare movie data
        movie_data = {
            "title": movie.get("title", ""),
            "year": 0,
            "tmdbId": movie.get("id"),
            "titleSlug": "",
            "monitored": True,
            "minimumAvailability": "announced",
            "rootFolderPath": root_folder.get("path"),
            "qualityProfileId": quality_profile.get("id"),
            "tags": tag_ids,
            "addOptions": {
                "searchForMovie": True
            }
        }

        # Extract year from release date
        if movie.get("release_date"):
            try:
                movie_data["year"] = int(movie["release_date"][:4])
            except:
                pass

        # Generate title slug (simple version)
        title = movie.get("title", "")
        year = movie_data["year"]
        movie_data["titleSlug"] = f"{title.lower().replace(' ', '-')}-{year}".replace("'", "").replace(":", "")

        async with AsyncClient() as client:
            # Try v3 first, then v2, then v1
            for api_version in ["v3", "v2", "v1"]:
                url = f"{base_url}/api/{api_version}/movie"
                try:
                    resp = await client.post(url, headers=headers, json=movie_data)
                    if resp.status_code in [200, 201]:
                        result = resp.json()
                        radarr_id = result.get("id")
                        logger.info("✅ Movie added to Radarr using API %s: %s (ID: %s)", api_version, title, radarr_id)

                        # Track the request if user info provided
                        if user_id and username and radarr_id:
                            from utils.request_tracker import request_tracker
                            request_tracker.add_request(
                                media_type="movie",
                                title=title,
                                year=year,
                                user_id=user_id,
                                username=username,
                                tmdb_id=movie.get("id"),
                                radarr_id=radarr_id,
                                release_date=movie.get("release_date")
                            )

                        return True, None, radarr_id
                    elif resp.status_code == 404:
                        continue
                    else:
                        error_text = resp.text if resp.text else f"HTTP {resp.status_code}"
                        logger.error("❌ Radarr API %s returned %d: %s", api_version, resp.status_code, error_text)
                        continue
                except Exception as e:
                    logger.debug("API %s failed: %s", api_version, e)
                    continue

            return False, "Server is offline. Please use /on to wake it up, then try again.", None

    except Exception as e:
        logger.error("❌ Failed to add movie to Radarr: %s", e)
        return False, str(e), None

async def add_tv_to_sonarr(show, root_folder, quality_profile, user_id=None, username=None):
    """Add TV series to Sonarr with only latest season monitored and track the request"""
    if not (SONARR_URL and SONARR_API_KEY):
        return False, "Sonarr not configured", None

    try:
        # First, we need to get TVDB ID from TMDB
        tmdb_id = show.get("id")
        tvdb_id = await get_tvdb_id_from_tmdb(tmdb_id)

        if not tvdb_id:
            return False, "Could not find TVDB ID for this series", None

        base_url = SONARR_URL.rstrip('/')
        headers = {"X-Api-Key": SONARR_API_KEY, "Content-Type": "application/json"}

        # Get or create user tag for tracking
        tag_ids = []
        if username:
            tag_id = await get_or_create_sonarr_tag(username)
            if tag_id:
                tag_ids.append(tag_id)

        # Prepare series data
        series_data = {
            "title": show.get("name", ""),
            "tvdbId": tvdb_id,
            "titleSlug": "",
            "monitored": True,
            "seasonFolder": True,
            "rootFolderPath": root_folder.get("path"),
            "qualityProfileId": quality_profile.get("id"),
            "tags": tag_ids,
            "addOptions": {
                "searchForMissingEpisodes": True,
                "monitor": "latestSeason"  # Only monitor latest season
            }
        }

        # Generate title slug (simple version)
        title = show.get("name", "")
        series_data["titleSlug"] = title.lower().replace(' ', '-').replace("'", "").replace(":", "")

        # Get year from first air date
        year = 0
        if show.get("first_air_date"):
            try:
                year = int(show["first_air_date"][:4])
            except:
                pass

        async with AsyncClient() as client:
            # Try v3 first, then v2, then v1
            for api_version in ["v3", "v2", "v1"]:
                url = f"{base_url}/api/{api_version}/series"
                try:
                    resp = await client.post(url, headers=headers, json=series_data)
                    if resp.status_code in [200, 201]:
                        result = resp.json()
                        sonarr_id = result.get("id")
                        logger.info("✅ Series added to Sonarr using API %s: %s (ID: %s, latest season only)", api_version, title, sonarr_id)

                        # Track the request if user info provided
                        if user_id and username and sonarr_id:
                            from utils.request_tracker import request_tracker
                            request_tracker.add_request(
                                media_type="tv",
                                title=title,
                                year=year,
                                user_id=user_id,
                                username=username,
                                tmdb_id=tmdb_id,
                                tvdb_id=tvdb_id,
                                sonarr_id=sonarr_id,
                                release_date=show.get("first_air_date")
                            )

                        return True, None, sonarr_id
                    elif resp.status_code == 404:
                        continue
                    else:
                        error_text = resp.text if resp.text else f"HTTP {resp.status_code}"
                        logger.error("❌ Sonarr API %s returned %d: %s", api_version, resp.status_code, error_text)
                        continue
                except Exception as e:
                    logger.debug("API %s failed: %s", api_version, e)
                    continue

            return False, "Server is offline. Please use /on to wake it up, then try again.", None

    except Exception as e:
        logger.error("❌ Failed to add series to Sonarr: %s", e)
        return False, str(e), None

async def get_tvdb_id_from_tmdb(tmdb_id):
    """Get TVDB ID from TMDB external IDs endpoint"""
    if not TMDB_BEARER_TOKEN:
        return None
    
    try:
        headers = {"Authorization": f"Bearer {TMDB_BEARER_TOKEN}", "accept": "application/json"}
        async with AsyncClient() as client:
            url = f"https://api.themoviedb.org/3/tv/{tmdb_id}/external_ids"
            resp = await client.get(url, headers=headers)
            
            if resp.status_code == 200:
                external_ids = resp.json()
                tvdb_id = external_ids.get("tvdb_id")
                return tvdb_id
            else:
                logger.error("❌ TMDB external IDs fetch failed: %d", resp.status_code)
                return None
                
    except Exception as e:
        logger.error("❌ Error getting TVDB ID from TMDB: %s", e)
        return None


async def get_or_create_radarr_tag(username: str) -> int:
    """
    Get or create a tag in Radarr for tracking who requested the content.
    Tag format: plexbot-username

    Returns:
        Tag ID if successful, None otherwise
    """
    if not (RADARR_URL and RADARR_API_KEY):
        return None

    tag_label = f"plexbot-{username.lower()}"

    try:
        base_url = RADARR_URL.rstrip('/')
        headers = {"X-Api-Key": RADARR_API_KEY, "Content-Type": "application/json"}

        async with AsyncClient(timeout=10.0) as client:
            for api_version in ["v3", "v2", "v1"]:
                try:
                    # First, get existing tags
                    tags_url = f"{base_url}/api/{api_version}/tag"
                    resp = await client.get(tags_url, headers=headers)

                    if resp.status_code == 200:
                        tags = resp.json()
                        # Check if tag already exists
                        for tag in tags:
                            if tag.get("label", "").lower() == tag_label:
                                logger.debug("Found existing Radarr tag: %s (ID: %d)", tag_label, tag["id"])
                                return tag["id"]

                        # Tag doesn't exist, create it
                        create_resp = await client.post(
                            tags_url,
                            headers=headers,
                            json={"label": tag_label}
                        )

                        if create_resp.status_code in [200, 201]:
                            new_tag = create_resp.json()
                            logger.info("✅ Created Radarr tag: %s (ID: %d)", tag_label, new_tag["id"])
                            return new_tag["id"]
                        else:
                            logger.error("❌ Failed to create Radarr tag: %d", create_resp.status_code)
                            return None

                    elif resp.status_code == 404:
                        continue
                except Exception as e:
                    logger.debug("Radarr tag API %s failed: %s", api_version, e)
                    continue

            return None

    except Exception as e:
        logger.error("❌ Error getting/creating Radarr tag: %s", e)
        return None


async def get_or_create_sonarr_tag(username: str) -> int:
    """
    Get or create a tag in Sonarr for tracking who requested the content.
    Tag format: plexbot-username

    Returns:
        Tag ID if successful, None otherwise
    """
    if not (SONARR_URL and SONARR_API_KEY):
        return None

    tag_label = f"plexbot-{username.lower()}"

    try:
        base_url = SONARR_URL.rstrip('/')
        headers = {"X-Api-Key": SONARR_API_KEY, "Content-Type": "application/json"}

        async with AsyncClient(timeout=10.0) as client:
            for api_version in ["v3", "v2", "v1"]:
                try:
                    # First, get existing tags
                    tags_url = f"{base_url}/api/{api_version}/tag"
                    resp = await client.get(tags_url, headers=headers)

                    if resp.status_code == 200:
                        tags = resp.json()
                        # Check if tag already exists
                        for tag in tags:
                            if tag.get("label", "").lower() == tag_label:
                                logger.debug("Found existing Sonarr tag: %s (ID: %d)", tag_label, tag["id"])
                                return tag["id"]

                        # Tag doesn't exist, create it
                        create_resp = await client.post(
                            tags_url,
                            headers=headers,
                            json={"label": tag_label}
                        )

                        if create_resp.status_code in [200, 201]:
                            new_tag = create_resp.json()
                            logger.info("✅ Created Sonarr tag: %s (ID: %d)", tag_label, new_tag["id"])
                            return new_tag["id"]
                        else:
                            logger.error("❌ Failed to create Sonarr tag: %d", create_resp.status_code)
                            return None

                    elif resp.status_code == 404:
                        continue
                except Exception as e:
                    logger.debug("Sonarr tag API %s failed: %s", api_version, e)
                    continue

            return None

    except Exception as e:
        logger.error("❌ Error getting/creating Sonarr tag: %s", e)
        return None