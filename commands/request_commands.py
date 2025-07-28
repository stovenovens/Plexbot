"""
Request system commands
Handles movie and TV series requests via TMDB search with Sonarr/Radarr integration
Similar to Searcharr but simplified for group chat use without authentication
"""

import logging
from datetime import datetime
from telegram.ext import CallbackContext
from telegram.constants import ParseMode
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from httpx import AsyncClient

from config import (
    TMDB_BEARER_TOKEN, SONARR_URL, SONARR_API_KEY, RADARR_URL, RADARR_API_KEY,
    MELBOURNE_TZ, GROUP_CHAT_ID, BOT_TOPIC_ID, SILENT_NOTIFICATIONS
)
from utils.helpers import send_command_response, escape_md

logger = logging.getLogger(__name__)

def escape_search_message(query: str) -> str:
    """Create a properly escaped search message"""
    return f"🔍 Searching for: *{escape_md(query)}*"

class RequestManager:
    """Manages request sessions and TMDB/Sonarr/Radarr interactions"""
    
    def __init__(self):
        self.active_searches = {}  # Store search results by message_id
    
    async def search_tmdb_movie(self, query: str, page: int = 1):
        """Search for movies using TMDB API"""
        if not TMDB_BEARER_TOKEN:
            return None, "TMDB API not configured"
        
        try:
            headers = {"Authorization": f"Bearer {TMDB_BEARER_TOKEN}", "accept": "application/json"}
            async with AsyncClient() as client:
                params = {"query": query, "page": page, "language": "en-US"}
                resp = await client.get(
                    "https://api.themoviedb.org/3/search/movie", 
                    headers=headers, 
                    params=params
                )
                
                if resp.status_code == 200:
                    data = resp.json()
                    return data.get("results", []), None
                else:
                    return None, f"TMDB API error: {resp.status_code}"
                    
        except Exception as e:
            logger.error("❌ TMDB movie search failed: %s", e)
            return None, str(e)
    
    async def search_tmdb_tv(self, query: str, page: int = 1):
        """Search for TV series using TMDB API"""
        if not TMDB_BEARER_TOKEN:
            return None, "TMDB API not configured"
        
        try:
            headers = {"Authorization": f"Bearer {TMDB_BEARER_TOKEN}", "accept": "application/json"}
            async with AsyncClient() as client:
                params = {"query": query, "page": page, "language": "en-US"}
                resp = await client.get(
                    "https://api.themoviedb.org/3/search/tv", 
                    headers=headers, 
                    params=params
                )
                
                if resp.status_code == 200:
                    data = resp.json()
                    return data.get("results", []), None
                else:
                    return None, f"TMDB API error: {resp.status_code}"
                    
        except Exception as e:
            logger.error("❌ TMDB TV search failed: %s", e)
            return None, str(e)
    
    async def get_radarr_root_folders(self):
        """Get available root folders from Radarr"""
        if not (RADARR_URL and RADARR_API_KEY):
            return None, "Radarr not configured"
        
        try:
            base_url = RADARR_URL.rstrip('/')
            headers = {"X-Api-Key": RADARR_API_KEY}
            
            async with AsyncClient() as client:
                # Try v3 first, then v2, then v1
                for api_version in ["v3", "v2", "v1"]:
                    url = f"{base_url}/api/{api_version}/rootfolder"
                    try:
                        resp = await client.get(url, headers=headers)
                        if resp.status_code == 200:
                            folders = resp.json()
                            logger.info("✅ Radarr root folders fetched using API %s", api_version)
                            return folders, None
                        elif resp.status_code == 404:
                            continue
                    except Exception:
                        continue
                
                return None, "All Radarr API versions failed"
                
        except Exception as e:
            logger.error("❌ Radarr root folders fetch failed: %s", e)
            return None, str(e)
    
    async def get_radarr_quality_profiles(self):
        """Get available quality profiles from Radarr"""
        if not (RADARR_URL and RADARR_API_KEY):
            return None, "Radarr not configured"
        
        try:
            base_url = RADARR_URL.rstrip('/')
            headers = {"X-Api-Key": RADARR_API_KEY}
            
            async with AsyncClient() as client:
                # Try v3 first, then v2, then v1
                for api_version in ["v3", "v2", "v1"]:
                    url = f"{base_url}/api/{api_version}/qualityprofile"
                    try:
                        resp = await client.get(url, headers=headers)
                        if resp.status_code == 200:
                            profiles = resp.json()
                            logger.info("✅ Radarr quality profiles fetched using API %s", api_version)
                            return profiles, None
                        elif resp.status_code == 404:
                            continue
                    except Exception:
                        continue
                
                return None, "All Radarr API versions failed"
                
        except Exception as e:
            logger.error("❌ Radarr quality profiles fetch failed: %s", e)
            return None, str(e)
    
    async def get_sonarr_root_folders(self):
        """Get available root folders from Sonarr"""
        if not (SONARR_URL and SONARR_API_KEY):
            return None, "Sonarr not configured"
        
        try:
            base_url = SONARR_URL.rstrip('/')
            headers = {"X-Api-Key": SONARR_API_KEY}
            
            async with AsyncClient() as client:
                # Try v3 first, then v2, then v1
                for api_version in ["v3", "v2", "v1"]:
                    url = f"{base_url}/api/{api_version}/rootfolder"
                    try:
                        resp = await client.get(url, headers=headers)
                        if resp.status_code == 200:
                            folders = resp.json()
                            logger.info("✅ Sonarr root folders fetched using API %s", api_version)
                            return folders, None
                        elif resp.status_code == 404:
                            continue
                    except Exception:
                        continue
                
                return None, "All Sonarr API versions failed"
                
        except Exception as e:
            logger.error("❌ Sonarr root folders fetch failed: %s", e)
            return None, str(e)
    
    async def get_sonarr_quality_profiles(self):
        """Get available quality profiles from Sonarr"""
        if not (SONARR_URL and SONARR_API_KEY):
            return None, "Sonarr not configured"
        
        try:
            base_url = SONARR_URL.rstrip('/')
            headers = {"X-Api-Key": SONARR_API_KEY}
            
            async with AsyncClient() as client:
                # Try v3 first, then v2, then v1
                for api_version in ["v3", "v2", "v1"]:
                    url = f"{base_url}/api/{api_version}/qualityprofile"
                    try:
                        resp = await client.get(url, headers=headers)
                        if resp.status_code == 200:
                            profiles = resp.json()
                            logger.info("✅ Sonarr quality profiles fetched using API %s", api_version)
                            return profiles, None
                        elif resp.status_code == 404:
                            continue
                    except Exception:
                        continue
                
                return None, "All Sonarr API versions failed"
                
        except Exception as e:
            logger.error("❌ Sonarr quality profiles fetch failed: %s", e)
            return None, str(e)
    
    async def check_movie_exists_in_radarr(self, tmdb_id: int):
        """Check if movie already exists in Radarr"""
        if not (RADARR_URL and RADARR_API_KEY):
            return False, None
        
        try:
            base_url = RADARR_URL.rstrip('/')
            headers = {"X-Api-Key": RADARR_API_KEY}
            
            async with AsyncClient() as client:
                # Try v3 first, then v2, then v1
                for api_version in ["v3", "v2", "v1"]:
                    url = f"{base_url}/api/{api_version}/movie"
                    try:
                        resp = await client.get(url, headers=headers)
                        if resp.status_code == 200:
                            movies = resp.json()
                            for movie in movies:
                                if movie.get("tmdbId") == tmdb_id:
                                    return True, movie
                            return False, None
                        elif resp.status_code == 404:
                            continue
                    except Exception:
                        continue
                
                return False, None
                
        except Exception as e:
            logger.error("❌ Radarr movie check failed: %s", e)
            return False, None
    
    async def check_series_exists_in_sonarr(self, tvdb_id: int):
        """Check if TV series already exists in Sonarr"""
        if not (SONARR_URL and SONARR_API_KEY):
            return False, None
        
        try:
            base_url = SONARR_URL.rstrip('/')
            headers = {"X-Api-Key": SONARR_API_KEY}
            
            async with AsyncClient() as client:
                # Try v3 first, then v2, then v1
                for api_version in ["v3", "v2", "v1"]:
                    url = f"{base_url}/api/{api_version}/series"
                    try:
                        resp = await client.get(url, headers=headers)
                        if resp.status_code == 200:
                            series_list = resp.json()
                            for series in series_list:
                                if series.get("tvdbId") == tvdb_id:
                                    return True, series
                            return False, None
                        elif resp.status_code == 404:
                            continue
                    except Exception:
                        continue
                
                return False, None
                
        except Exception as e:
            logger.error("❌ Sonarr series check failed: %s", e)
            return False, None
    
    def get_poster_url(self, poster_path: str):
        """Get full TMDB poster URL"""
        if not poster_path:
            return None
        return f"https://image.tmdb.org/t/p/w500{poster_path}"
    
    def format_movie_result(self, movie: dict, index: int, total: int):
        """Format a movie search result for display"""
        try:
            title = movie.get("title", "Unknown Title")
            year = ""
            if movie.get("release_date"):
                try:
                    year = f" ({movie['release_date'][:4]})"
                except:
                    pass
            
            overview = movie.get("overview", "No overview available")
            if len(overview) > 300:
                overview = overview[:297] + "..."
            
            rating = movie.get("vote_average", 0)
            vote_count = movie.get("vote_count", 0)
            
            # Format rating with escaped decimal point
            rating_text = f"{rating:.1f}".replace(".", "\\.")
            
            msg = f"🎬 *Movie Result {index + 1}/{total}*\n\n"
            msg += f"*{escape_md(title)}{escape_md(year)}*\n\n"
            msg += f"⭐ {rating_text}/10 \\({vote_count:,} votes\\)\n\n"
            msg += f"{escape_md(overview)}"
            
            return msg
            
        except Exception as e:
            logger.error("❌ Error formatting movie result: %s", e)
            return f"❌ Error formatting movie result"
    
    def format_tv_result(self, show: dict, index: int, total: int):
        """Format a TV show search result for display"""
        try:
            name = show.get("name", "Unknown Title")
            year = ""
            if show.get("first_air_date"):
                try:
                    year = f" ({show['first_air_date'][:4]})"
                except:
                    pass
            
            overview = show.get("overview", "No overview available")
            if len(overview) > 300:
                overview = overview[:297] + "..."
            
            rating = show.get("vote_average", 0)
            vote_count = show.get("vote_count", 0)
            
            # Format rating with escaped decimal point
            rating_text = f"{rating:.1f}".replace(".", "\\.")
            
            msg = f"📺 *TV Series Result {index + 1}/{total}*\n\n"
            msg += f"*{escape_md(name)}{escape_md(year)}*\n\n"
            msg += f"⭐ {rating_text}/10 \\({vote_count:,} votes\\)\n\n"
            msg += f"{escape_md(overview)}"
            
            return msg
            
        except Exception as e:
            logger.error("❌ Error formatting TV result: %s", e)
            return f"❌ Error formatting TV result"
    
    def create_movie_keyboard(self, movie: dict, index: int, total: int, search_id: str, already_exists: bool = False):
        """Create inline keyboard for movie result"""
        keyboard = []
        
        # Navigation buttons (if multiple results)
        nav_row = []
        if index > 0:
            nav_row.append(InlineKeyboardButton("◀️ Previous", callback_data=f"movie_nav_{search_id}_{index-1}"))
        if index < total - 1:
            nav_row.append(InlineKeyboardButton("Next ▶️", callback_data=f"movie_nav_{search_id}_{index+1}"))
        if nav_row:
            keyboard.append(nav_row)
        
        # External links
        external_row = []
        tmdb_id = movie.get("id")
        if tmdb_id:
            external_row.append(InlineKeyboardButton("🔗 TMDB", url=f"https://www.themoviedb.org/movie/{tmdb_id}"))
        imdb_id = movie.get("imdb_id")
        if imdb_id:
            external_row.append(InlineKeyboardButton("🎭 IMDb", url=f"https://www.imdb.com/title/{imdb_id}"))
        if external_row:
            keyboard.append(external_row)
        
        # Add/Already Added button
        action_row = []
        if already_exists:
            action_row.append(InlineKeyboardButton("✅ Already Added!", callback_data="already_added"))
        else:
            if RADARR_URL and RADARR_API_KEY:
                action_row.append(InlineKeyboardButton("➕ Add Movie", callback_data=f"add_movie_{search_id}_{index}"))
            else:
                action_row.append(InlineKeyboardButton("❌ Radarr Not Configured", callback_data="not_configured"))
        
        action_row.append(InlineKeyboardButton("❌ Cancel", callback_data=f"cancel_search_{search_id}"))
        keyboard.append(action_row)
        
        return InlineKeyboardMarkup(keyboard)
    
    def create_tv_keyboard(self, show: dict, index: int, total: int, search_id: str, already_exists: bool = False):
        """Create inline keyboard for TV show result"""
        keyboard = []
        
        # Navigation buttons (if multiple results)
        nav_row = []
        if index > 0:
            nav_row.append(InlineKeyboardButton("◀️ Previous", callback_data=f"tv_nav_{search_id}_{index-1}"))
        if index < total - 1:
            nav_row.append(InlineKeyboardButton("Next ▶️", callback_data=f"tv_nav_{search_id}_{index+1}"))
        if nav_row:
            keyboard.append(nav_row)
        
        # External links
        external_row = []
        tmdb_id = show.get("id")
        if tmdb_id:
            external_row.append(InlineKeyboardButton("🔗 TMDB", url=f"https://www.themoviedb.org/tv/{tmdb_id}"))
        # Note: TV shows don't have direct IMDb IDs in TMDB API, would need additional lookup
        if external_row:
            keyboard.append(external_row)
        
        # Add/Already Added button
        action_row = []
        if already_exists:
            action_row.append(InlineKeyboardButton("✅ Already Added!", callback_data="already_added"))
        else:
            if SONARR_URL and SONARR_API_KEY:
                action_row.append(InlineKeyboardButton("➕ Add Series", callback_data=f"add_tv_{search_id}_{index}"))
            else:
                action_row.append(InlineKeyboardButton("❌ Sonarr Not Configured", callback_data="not_configured"))
        
        action_row.append(InlineKeyboardButton("❌ Cancel", callback_data=f"cancel_search_{search_id}"))
        keyboard.append(action_row)
        
        return InlineKeyboardMarkup(keyboard)

# Global request manager instance
request_manager = RequestManager()

async def send_command_response_with_markup(update, context: CallbackContext, message: str, parse_mode=None, reply_markup=None, photo_url=None):
    """Send command response with reply markup and optional photo support"""
    try:
        # Always send to bot topic for cleaner general chat
        if photo_url:
            # Send photo with caption
            await context.bot.send_photo(
                chat_id=GROUP_CHAT_ID,
                photo=photo_url,
                caption=message,
                message_thread_id=BOT_TOPIC_ID,
                parse_mode=parse_mode,
                reply_markup=reply_markup,
                disable_notification=SILENT_NOTIFICATIONS
            )
        else:
            # Send text message
            await context.bot.send_message(
                chat_id=GROUP_CHAT_ID,
                text=message,
                message_thread_id=BOT_TOPIC_ID,
                parse_mode=parse_mode,
                reply_markup=reply_markup,
                disable_notification=SILENT_NOTIFICATIONS
            )
        
        # If command was issued outside bot topic, send a redirect message
        if update.message and update.message.message_thread_id != BOT_TOPIC_ID:
            redirect_msg = f"👀 Response sent to bot topic"
            await update.message.reply_text(redirect_msg, disable_notification=SILENT_NOTIFICATIONS)
            
    except Exception as e:
        logger.error("❌ Failed to send command response: %s", e)
        # Fallback: send to where command was issued
        try:
            if update.message:
                if photo_url:
                    await update.message.reply_photo(photo=photo_url, caption=message, parse_mode=parse_mode, reply_markup=reply_markup, disable_notification=SILENT_NOTIFICATIONS)
                else:
                    await update.message.reply_text(message, parse_mode=parse_mode, reply_markup=reply_markup, disable_notification=SILENT_NOTIFICATIONS)
        except Exception as fallback_error:
            logger.error("❌ Failed to send response even as fallback: %s", fallback_error)

async def movie_command(update, context: CallbackContext):
    """Search for movies to request"""
    if not context.args:
        await send_command_response(update, context, "❌ Please provide a movie title to search for\\.\n\nExample: `/movie Inception`", parse_mode=ParseMode.MARKDOWN_V2)
        return
    
    query = " ".join(context.args)
    user = update.effective_user
    
    logger.info("🎬 Movie search requested by %s (%s): '%s'", 
                user.username or user.first_name, user.id, query)
    
    try:
        await send_command_response(update, context, escape_search_message(f"movie: {query}"), parse_mode=ParseMode.MARKDOWN_V2)
        
        # Search TMDB
        results, error = await request_manager.search_tmdb_movie(query)
        
        if error:
            await send_command_response(update, context, f"❌ Search failed: {escape_md(error)}", parse_mode=ParseMode.MARKDOWN_V2)
            return
        
        if not results:
            await send_command_response(update, context, f"❌ No movies found for: *{escape_md(query)}*", parse_mode=ParseMode.MARKDOWN_V2)
            return
        
        # Store search results
        search_id = f"movie_{user.id}_{int(datetime.now().timestamp())}"
        request_manager.active_searches[search_id] = {
            "type": "movie",
            "query": query,
            "results": results,
            "user_id": user.id,
            "current_index": 0
        }
        
        # Check if first result already exists in Radarr
        first_movie = results[0]
        tmdb_id = first_movie.get("id")
        already_exists = False
        if tmdb_id:
            exists, _ = await request_manager.check_movie_exists_in_radarr(tmdb_id)
            already_exists = exists
        
        # Format and send first result
        msg = request_manager.format_movie_result(first_movie, 0, len(results))
        keyboard = request_manager.create_movie_keyboard(first_movie, 0, len(results), search_id, already_exists)
        poster_url = request_manager.get_poster_url(first_movie.get("poster_path"))
        
        await send_command_response_with_markup(update, context, msg, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=keyboard, photo_url=poster_url)
        
    except Exception as e:
        logger.error("❌ Movie search command failed: %s", e)
        await send_command_response(update, context, f"❌ Search failed: {escape_md(str(e))}", parse_mode=ParseMode.MARKDOWN_V2)

async def series_command(update, context: CallbackContext):
    """Search for TV series to request"""
    if not context.args:
        await send_command_response(update, context, "❌ Please provide a TV series title to search for\\.\n\nExample: `/series Breaking Bad`", parse_mode=ParseMode.MARKDOWN_V2)
        return
    
    query = " ".join(context.args)
    user = update.effective_user
    
    logger.info("📺 TV series search requested by %s (%s): '%s'", 
                user.username or user.first_name, user.id, query)
    
    try:
        await send_command_response(update, context, escape_search_message(f"TV series: {query}"), parse_mode=ParseMode.MARKDOWN_V2)
        
        # Search TMDB
        results, error = await request_manager.search_tmdb_tv(query)
        
        if error:
            await send_command_response(update, context, f"❌ Search failed: {escape_md(error)}", parse_mode=ParseMode.MARKDOWN_V2)
            return
        
        if not results:
            await send_command_response(update, context, f"❌ No TV series found for: *{escape_md(query)}*", parse_mode=ParseMode.MARKDOWN_V2)
            return
        
        # Store search results
        search_id = f"tv_{user.id}_{int(datetime.now().timestamp())}"
        request_manager.active_searches[search_id] = {
            "type": "tv",
            "query": query,
            "results": results,
            "user_id": user.id,
            "current_index": 0
        }
        
        # Check if first result already exists in Sonarr (would need TVDB ID lookup)
        first_show = results[0]
        already_exists = False
        # Note: TMDB TV results don't include TVDB IDs directly, would need additional API call
        # For now, we'll skip the existence check for TV shows
        
        # Format and send first result
        msg = request_manager.format_tv_result(first_show, 0, len(results))
        keyboard = request_manager.create_tv_keyboard(first_show, 0, len(results), search_id, already_exists)
        poster_url = request_manager.get_poster_url(first_show.get("poster_path"))
        
        await send_command_response_with_markup(update, context, msg, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=keyboard, photo_url=poster_url)
        
    except Exception as e:
        logger.error("❌ TV series search command failed: %s", e)
        await send_command_response(update, context, f"❌ Search failed: {escape_md(str(e))}", parse_mode=ParseMode.MARKDOWN_V2)

# Alias commands
tv_command = series_command  # /tv is an alias for /series