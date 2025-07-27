"""
Media information commands
Handles nowplaying, stats, upcoming, and trending commands
"""

import logging
from datetime import datetime, timedelta
from collections import defaultdict
from telegram.ext import CallbackContext
from telegram.constants import ParseMode
from httpx import AsyncClient

from config import (
    TAUTILLI_URL, TAUTILLI_API_KEY, JELLYFIN_URL, JELLYFIN_API_KEY,
    SONARR_URL, SONARR_API_KEY, RADARR_URL, RADARR_API_KEY,
    TMDB_BEARER_TOKEN, MELBOURNE_TZ
)
from utils.helpers import (
    send_command_response, escape_md, safe_format_number, format_duration
)

logger = logging.getLogger(__name__)

# --- TMDB Functions ---
async def fetch_trending():
    """Fetch trending movies and TV shows from TMDB"""
    headers = {"Authorization": f"Bearer {TMDB_BEARER_TOKEN}", "accept": "application/json"}
    async with AsyncClient() as client:
        movies_resp = await client.get(
            "https://api.themoviedb.org/3/trending/movie/week", headers=headers, params={"language": "en-US"}
        )
        shows_resp = await client.get(
            "https://api.themoviedb.org/3/trending/tv/week", headers=headers, params={"language": "en-US"}
        )
    movies = movies_resp.json().get("results", []) if movies_resp.status_code == 200 else []
    shows = shows_resp.json().get("results", []) if shows_resp.status_code == 200 else []
    return movies, shows

async def fetch_watch_providers(media_type, media_id):
    """Fetch streaming providers for media from TMDB"""
    headers = {"Authorization": f"Bearer {TMDB_BEARER_TOKEN}", "accept": "application/json"}
    url = f"https://api.themoviedb.org/3/{media_type}/{media_id}/watch/providers"
    async with AsyncClient() as client:
        resp = await client.get(url, headers=headers)
    results = resp.json().get("results", {}) if resp.status_code == 200 else {}
    au = results.get("AU", {})
    if au.get("flatrate"):
        return ", ".join(item.get("provider_name", "") for item in au["flatrate"])
    return "No streaming info"

# --- Sonarr/Radarr Functions ---
async def fetch_sonarr_upcoming(client):
    """Get upcoming TV episodes from Sonarr for this week"""
    if not (SONARR_URL and SONARR_API_KEY):
        return None
    
    try:
        # Get date range for this week (today + 7 days)
        start_date = datetime.now(MELBOURNE_TZ).date()
        end_date = start_date + timedelta(days=7)
        
        base_url = SONARR_URL.rstrip('/')
        headers = {"X-Api-Key": SONARR_API_KEY}
        params = {
            "start": start_date.isoformat(),
            "end": end_date.isoformat(),
            "unmonitored": "false"  # Only get monitored episodes
        }
        
        # Try v3 first, then fall back to v2
        episodes = None
        for api_version in ["v3", "v2", "v1"]:
            url = f"{base_url}/api/{api_version}/calendar"
            logger.debug("Trying Sonarr API %s: %s", api_version, url)
            
            try:
                resp = await client.get(url, headers=headers, params=params)
                if resp.status_code == 200:
                    episodes = resp.json()
                    logger.info("✅ Sonarr episodes fetched using API %s: %d episodes", api_version, len(episodes))
                    break
                elif resp.status_code == 404:
                    logger.debug("API %s not found, trying next version", api_version)
                    continue
                else:
                    logger.warning("API %s returned status %d", api_version, resp.status_code)
                    continue
            except Exception as e:
                logger.debug("API %s failed: %s", api_version, e)
                continue
        
        if not episodes:
            logger.error("❌ All Sonarr API versions failed")
            return None
        
        # Now fetch series information to get the actual series names
        try:
            series_url = f"{base_url}/api/{api_version}/series"
            series_resp = await client.get(series_url, headers=headers)
            if series_resp.status_code == 200:
                series_data = series_resp.json()
                # Create a lookup dictionary: seriesId -> series title
                series_lookup = {series.get("id"): series.get("title", "Unknown Series") for series in series_data}
                logger.info("✅ Fetched %d series for lookup", len(series_lookup))
                
                # Add series information to episodes
                for episode in episodes:
                    series_id = episode.get("seriesId")
                    if series_id and series_id in series_lookup:
                        episode["seriesTitle"] = series_lookup[series_id]
                    else:
                        episode["seriesTitle"] = "Unknown Series"
                        logger.debug("No series found for episode with seriesId: %s", series_id)
            else:
                logger.warning("Could not fetch series data, status: %d", series_resp.status_code)
                # Fallback: set all to unknown
                for episode in episodes:
                    episode["seriesTitle"] = "Unknown Series"
        except Exception as e:
            logger.error("Error fetching series data: %s", e)
            # Fallback: set all to unknown
            for episode in episodes:
                episode["seriesTitle"] = "Unknown Series"
        
        return episodes
        
    except Exception as e:
        logger.error("❌ Sonarr fetch failed: %s", e)
        return None

async def fetch_radarr_upcoming(client):
    """Get upcoming movie releases from Radarr for the next month"""
    if not (RADARR_URL and RADARR_API_KEY):
        return None
    
    try:
        # Get date range for upcoming releases - next month (30 days)
        start_date = datetime.now(MELBOURNE_TZ).date()
        end_date = start_date + timedelta(days=30)  # Get 1 month ahead
        
        base_url = RADARR_URL.rstrip('/')
        headers = {"X-Api-Key": RADARR_API_KEY}
        params = {
            "start": start_date.isoformat(),
            "end": end_date.isoformat(),
            "unmonitored": "false"  # Only get monitored movies
        }
        
        # Try v3 first, then fall back to v2
        for api_version in ["v3", "v2", "v1"]:
            url = f"{base_url}/api/{api_version}/calendar"
            logger.debug("Trying Radarr API %s: %s", api_version, url)
            
            try:
                resp = await client.get(url, headers=headers, params=params)
                if resp.status_code == 200:
                    movies = resp.json()
                    logger.info("✅ Radarr movies fetched using API %s: %d movies", api_version, len(movies))
                    return movies
                elif resp.status_code == 404:
                    logger.debug("API %s not found, trying next version", api_version)
                    continue
                else:
                    logger.warning("API %s returned status %d", api_version, resp.status_code)
                    continue
            except Exception as e:
                logger.debug("API %s failed: %s", api_version, e)
                continue
        
        logger.error("❌ All Radarr API versions failed")
        return None
        
    except Exception as e:
        logger.error("❌ Radarr fetch failed: %s", e)
        return None

def format_sonarr_episode(episode):
    """Format a Sonarr episode for display"""
    try:
        # Get series title (now populated by fetch function)
        series_title = episode.get("seriesTitle", "Unknown Series")
        
        season_num = episode.get("seasonNumber", 0)
        episode_num = episode.get("episodeNumber", 0)
        episode_title = episode.get("title", "TBA")
        
        # Debug logging
        logger.debug("Formatting episode: Series='%s', S%02dE%02d, Title='%s'", 
                    series_title, season_num, episode_num, episode_title)
        
        # Air date
        air_date_str = episode.get("airDate", "")
        if air_date_str:
            try:
                air_date = datetime.fromisoformat(air_date_str.replace('Z', '+00:00'))
                air_date_local = air_date.astimezone(MELBOURNE_TZ)
                formatted_date = air_date_local.strftime("%a %b %d")
            except:
                formatted_date = air_date_str
        else:
            formatted_date = "TBA"
        
        # Check if downloaded
        has_file = episode.get("hasFile", False)
        status = "📁" if has_file else "⏳"
        
        # Format: "Series S01E05: Episode Title - Mon Jan 15 📁"
        series_safe = escape_md(series_title)
        episode_safe = escape_md(episode_title)
        date_safe = escape_md(formatted_date)
        
        return f"\\- {series_safe} S{season_num:02d}E{episode_num:02d}\\: {episode_safe} \\- {date_safe} {status}"
        
    except Exception as e:
        logger.error("Error formatting Sonarr episode: %s", e)
        return f"\\- Unknown Series \\- Error formatting"

def format_radarr_movie(movie):
    """Format a Radarr movie for display with release type information - upcoming releases in next month"""
    try:
        # Basic info
        title = movie.get("title", "Unknown Movie")
        year = movie.get("year", "")
        
        # Get all release dates
        cinema_date = movie.get("inCinemas", "")
        digital_date = movie.get("digitalRelease", "")
        physical_date = movie.get("physicalRelease", "")
        
        # Check if downloaded
        has_file = movie.get("hasFile", False)
        status = "📁" if has_file else "⏳"
        
        # Process dates and determine what to show
        releases = []
        now = datetime.now(MELBOURNE_TZ).date()
        month_from_now = now + timedelta(days=30)  # Show next month instead of next week
        
        # Parse and categorize dates - ONLY include future dates in next month
        for date_str, release_type, emoji in [
            (cinema_date, "Cinema", "🎬"),
            (digital_date, "Digital", "💻"), 
            (physical_date, "Physical", "📀")
        ]:
            if date_str:
                try:
                    release_date = datetime.fromisoformat(date_str.replace('Z', '+00:00')).date()
                    
                    # Only include future releases within the next month
                    if now <= release_date <= month_from_now:
                        formatted_date = release_date.strftime("%b %d")
                        
                        releases.append({
                            'date': release_date,
                            'type': release_type,
                            'emoji': emoji,
                            'display': formatted_date,
                            'is_future': True  # All releases here are future
                        })
                except:
                    continue
        
        # If no upcoming releases in the next month, don't show this movie
        if not releases:
            return None
        
        # Sort releases by date
        releases.sort(key=lambda x: x['date'])
        
        # Build the display string
        title_safe = escape_md(title)
        year_safe = escape_md(f"({year})" if year else "")
        
        # Show the earliest release
        main_release = releases[0]
        main_display = f"{main_release['emoji']} {escape_md(main_release['display'])}"
        
        # Add additional releases if there are multiple
        if len(releases) > 1:
            other_releases = releases[1:]
            if other_releases:
                other_display = ", ".join([f"{r['emoji']}{escape_md(r['display'])}" for r in other_releases[:2]])
                release_info = f"{main_display} \\| {other_display}"
            else:
                release_info = main_display
        else:
            release_info = main_display
            
        return f"\\- {title_safe} {year_safe} \\- {release_info} {status}"
        
    except Exception as e:
        logger.error("Error formatting Radarr movie: %s", e)
        return f"\\- {escape_md(movie.get('title', 'Unknown'))} \\- Error formatting"

# --- Jellyfin Functions ---
async def fetch_jellyfin_sessions(client):
    """Get active sessions from Jellyfin"""
    if not (JELLYFIN_URL and JELLYFIN_API_KEY):
        return None
    
    try:
        base_url = JELLYFIN_URL.rstrip('/')
        url = f"{base_url}/Sessions?api_key={JELLYFIN_API_KEY}"
        logger.debug("Fetching Jellyfin sessions from: %s", url.replace(JELLYFIN_API_KEY, "***"))
        
        resp = await client.get(url)
        resp.raise_for_status()
        sessions = resp.json()
        
        logger.info("✅ Jellyfin sessions fetched successfully: %d sessions", len(sessions))
        return sessions
        
    except Exception as e:
        logger.error("❌ Jellyfin sessions fetch failed: %s", e)
        return None

def format_jellyfin_session(session):
    """Format a Jellyfin session for display"""
    try:
        user = session.get("UserName", "Unknown")
        now_playing = session.get("NowPlayingItem", {})
        
        if now_playing:
            media_type = now_playing.get("Type", "").lower()
            name = now_playing.get("Name", "Unknown")
            
            if media_type == "episode":
                series = now_playing.get("SeriesName", "")
                season = now_playing.get("ParentIndexNumber", "")
                episode = now_playing.get("IndexNumber", "")
                if series and season and episode:
                    title = f"{series} S{season:02d}E{episode:02d}: {name}"
                elif series:
                    title = f"{series}: {name}"
                else:
                    title = name
            else:
                title = name
        else:
            title = "Idle"
        
        play_state = session.get("PlayState", {})
        is_paused = play_state.get("IsPaused", False)
        state = "Paused" if is_paused else "Playing"
        device = session.get("DeviceName", "Unknown Device")
        
        user_safe = escape_md(user)
        title_safe = escape_md(title)
        state_safe = escape_md(state)
        device_safe = escape_md(device)
        
        return f"\\- {user_safe} – {title_safe} – {device_safe} \\({state_safe}\\)"
        
    except Exception as e:
        logger.error("Error formatting Jellyfin session: %s", e)
        return f"\\- {escape_md(session.get('UserName', 'Unknown'))} – Error formatting session"

# --- Tautulli Functions ---
def get_stream_type(session_data):
    """Determine the stream type from Tautulli session data"""
    try:
        transcode_decision = session_data.get("transcode_decision", "").lower()
        if transcode_decision == "transcode":
            return "Transcoding"
        elif transcode_decision in ["copy", "direct play"]:
            return "Direct Play"
        
        stream_container = session_data.get("stream_container_decision", "").lower()
        if stream_container == "copy":
            return "Direct Play"
        elif stream_container == "transcode":
            return "Transcoding"
        
        transcode_video = session_data.get("transcode_video_decision", "").lower()
        transcode_audio = session_data.get("transcode_audio_decision", "").lower()
        
        if transcode_video == "transcode" or transcode_audio == "transcode":
            return "Transcoding"
        elif transcode_video == "copy" and transcode_audio == "copy":
            return "Direct Play"
        elif "direct stream" in transcode_video or "direct stream" in transcode_audio:
            return "Direct Stream"
        
        return "Direct Play"  # Default assumption
        
    except Exception as e:
        logger.error("Error determining stream type: %s", e)
        return "Unknown"

async def fetch_tautulli_stats(client, time_range=7):
    """Fetch viewing statistics from Tautulli"""
    try:
        base_url = TAUTILLI_URL.rstrip('/')
        
        # Test connectivity
        logger.info("🔍 Testing Tautulli API connectivity...")
        test_url = f"{base_url}/api/v2?apikey={TAUTILLI_API_KEY}&cmd=get_activity"
        test_resp = await client.get(test_url)
        test_resp.raise_for_status()
        logger.info("✅ Tautulli API connection successful")
        
        # Get history data
        logger.info("📊 Fetching Tautulli history...")
        history_url = f"{base_url}/api/v2?apikey={TAUTILLI_API_KEY}&cmd=get_history&length=200"
        history_resp = await client.get(history_url)
        history_resp.raise_for_status()
        history_result = history_resp.json()
        
        if history_result.get("response", {}).get("result") != "success":
            logger.error("❌ Tautulli history API returned error")
            return None, None
            
        history_data = history_result.get("response", {}).get("data", {}).get("data", [])
        logger.info("✅ Retrieved %d history items", len(history_data))
        
        # Try to get user stats
        user_data = None
        try:
            logger.info("📊 Fetching user watch time stats...")
            user_stats_url = f"{base_url}/api/v2?apikey={TAUTILLI_API_KEY}&cmd=get_user_watch_time_stats&time_range={time_range}"
            user_resp = await client.get(user_stats_url)
            
            if user_resp.status_code == 200:
                user_result = user_resp.json()
                if user_result.get("response", {}).get("result") == "success":
                    user_data = user_result.get("response", {}).get("data", [])
                    logger.info("✅ Retrieved user stats for %d users", len(user_data))
        except Exception:
            logger.warning("⚠️ User stats API not available")
        
        return user_data, history_data
        
    except Exception as e:
        logger.error("❌ Failed to fetch Tautulli stats: %s", e)
        return None, None

def calculate_user_stats_from_history(history_data, days=7):
    """Calculate user stats from history data if API doesn't provide them"""
    if not history_data:
        return []
    
    cutoff_date = datetime.now() - timedelta(days=days)
    user_stats = defaultdict(lambda: {"total_time": 0, "total_plays": 0})
    
    for item in history_data:
        try:
            item_date = datetime.fromtimestamp(int(item.get("date", 0)))
            if item_date < cutoff_date:
                continue
                
            user = item.get("user", "Unknown")
            duration = int(item.get("duration", 0) or 0)
            
            user_stats[user]["total_time"] += duration
            user_stats[user]["total_plays"] += 1
            
        except (ValueError, TypeError):
            continue
    
    return [{"user": user, **stats} for user, stats in user_stats.items()]

def analyze_most_watched_content(history_data, days=7):
    """Analyze history data to find most watched content"""
    if not history_data:
        return []
    
    cutoff_date = datetime.now() - timedelta(days=days)
    content_plays = defaultdict(lambda: {"plays": 0, "users": set(), "duration": 0})
    
    for item in history_data:
        try:
            item_date = datetime.fromtimestamp(int(item.get("date", 0)))
            if item_date < cutoff_date:
                continue
                
            title = item.get("full_title") or item.get("title", "Unknown")
            user = item.get("user", "Unknown")
            duration = int(item.get("duration", 0) or 0)
            
            content_plays[title]["plays"] += 1
            content_plays[title]["users"].add(user)
            content_plays[title]["duration"] += duration
            
        except (ValueError, TypeError):
            continue
    
    return sorted([(title, data) for title, data in content_plays.items()], 
                  key=lambda x: x[1]["plays"], reverse=True)[:10]

# --- Command Functions ---
async def nowplaying_command(update, context: CallbackContext):
    """Show current playing sessions"""
    try:
        async with AsyncClient() as client:
            lines = ["🎥 *Now Playing*"]
            
            # Tautulli data (Plex)
            try:
                taut_url = TAUTILLI_URL.rstrip('/') + f"/api/v2?apikey={TAUTILLI_API_KEY}&cmd=get_activity"
                taut_resp = await client.get(taut_url)
                taut_resp.raise_for_status()
                taut_data = taut_resp.json().get("response", {}).get("data", {})
                sessions = taut_data.get("sessions", [])

                if sessions:
                    lines.append("\n*Plex:*")
                    for s in sessions:
                        user = escape_md(s.get("username", "Unknown"))
                        show = s.get("grandparent_title") or s.get("parent_title") or ""
                        ep = s.get("title", "")
                        full = f"{show}: {ep}" if show else ep
                        title = escape_md(full)
                        
                        stream_type = get_stream_type(s)
                        stream = escape_md(stream_type)
                        state = escape_md(s.get("state", ""))
                        
                        lines.append(f"\\- {user} – {title} – {stream} \\({state}\\)")

                    # WAN bandwidth
                    wan_kbps = taut_data.get("wan_bandwidth", 0)
                    if wan_kbps > 0:
                        wan_mbps = wan_kbps / 1000
                        wan_text = safe_format_number(wan_mbps, 1)
                        lines.append(f"\\- WAN upload: {wan_text} Mbps")
                else:
                    lines.append("\n*Plex:* No active streams")
                    
                logger.info("✅ Tautulli data fetched successfully")
                
            except Exception as e:
                logger.error("❌ Tautulli fetch failed: %s", e)
                lines.append("\n*Plex:* Data unavailable")

            # Jellyfin data
            jellyfin_sessions = await fetch_jellyfin_sessions(client)
            if jellyfin_sessions is not None:
                active_sessions = [s for s in jellyfin_sessions if s.get("NowPlayingItem") or s.get("PlayState", {}).get("PositionTicks", 0) > 0]
                
                if active_sessions:
                    lines.append("\n*Jellyfin:*")
                    for session in active_sessions:
                        formatted_session = format_jellyfin_session(session)
                        lines.append(formatted_session)
                else:
                    lines.append("\n*Jellyfin:* No active streams")
            else:
                if JELLYFIN_URL and JELLYFIN_API_KEY:
                    lines.append("\n*Jellyfin:* Data unavailable")

        msg = "\n".join(lines)
        
        try:
            await send_command_response(update, context, msg, parse_mode=ParseMode.MARKDOWN_V2)
        except Exception as markdown_error:
            logger.error("❌ Markdown parsing error: %s", markdown_error)
            plain_msg = msg.replace("\\", "").replace("*", "").replace("_", "")
            await send_command_response(update, context, f"🎥 Now Playing\n\n{plain_msg}")
        
    except Exception as e:
        logger.error("❌ Error in nowplaying command: %s", e)
        await send_command_response(update, context, "❌ Could not fetch now playing data. Check logs for details.")

async def stats_command(update, context: CallbackContext):
    """Show weekly viewing statistics"""
    try:
        async with AsyncClient() as client:
            await send_command_response(update, context, "📊 Fetching weekly stats\\.\\.\\.", parse_mode=ParseMode.MARKDOWN_V2)
            
            user_stats, history_data = await fetch_tautulli_stats(client)
            
            if not history_data:
                await send_command_response(update, context, "❌ Could not fetch statistics\\. Check Tautulli connection\\.", parse_mode=ParseMode.MARKDOWN_V2)
                return
            
            # Calculate from history if needed
            if not user_stats and history_data:
                logger.info("📊 User stats API unavailable, calculating from history data...")
                user_stats = calculate_user_stats_from_history(history_data)
                logger.info("✅ Calculated stats for %d users from history", len(user_stats))
            
            # Build message
            end_date = datetime.now(MELBOURNE_TZ)
            start_date = end_date - timedelta(days=7)
            date_range = f"{start_date.strftime('%d %b')} \\- {end_date.strftime('%d %b %Y')}"
            
            msg = f"📊 *Weekly Stats* \\({date_range}\\)\n\n"
            
            # Top Users section
            if user_stats:
                msg += "*🏆 Top Users \\(Watch Time\\):*\n"
                sorted_users = sorted(user_stats, key=lambda x: int(x.get("total_time", 0) or 0), reverse=True)
                
                for i, user in enumerate(sorted_users[:5], 1):
                    username = escape_md(user.get("user", "Unknown"))
                    total_time = int(user.get("total_time", 0) or 0)
                    plays = user.get("total_plays", 0)
                    duration_str = escape_md(format_duration(total_time))
                    
                    emoji = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}\\."
                    msg += f"{emoji} {username} – {duration_str} \\({plays} plays\\)\n"
                
                if not sorted_users:
                    msg += "No viewing data available\\.\n"
            else:
                msg += "*🏆 Top Users:* Data unavailable\n"
            
            # Most Watched Content section
            most_watched = analyze_most_watched_content(history_data)
            msg += "\n*🎬 Most Watched Content:*\n"
            
            if most_watched:
                for i, (title, data) in enumerate(most_watched[:5], 1):
                    title_clean = escape_md(title[:50] + "..." if len(title) > 50 else title)
                    plays = data["plays"]
                    unique_users = len(data["users"])
                    total_duration = format_duration(data["duration"])
                    
                    emoji = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}\\."
                    msg += f"{emoji} {title_clean}\n"
                    msg += f"   {plays} plays by {unique_users} user{'s' if unique_users != 1 else ''} \\({escape_md(total_duration)}\\)\n"
            else:
                msg += "No content data available\\.\n"
            
            # Summary stats
            if user_stats and history_data:
                total_users = len([u for u in user_stats if int(u.get("total_time", 0) or 0) > 0])
                total_plays = sum(int(u.get("total_plays", 0) or 0) for u in user_stats)
                total_time = sum(int(u.get("total_time", 0) or 0) for u in user_stats)
                
                msg += f"\n*📈 Week Summary:*\n"
                msg += f"\\- Active users: {total_users}\n"
                msg += f"\\- Total plays: {total_plays}\n"
                msg += f"\\- Total watch time: {escape_md(format_duration(total_time))}"
            
            try:
                await send_command_response(update, context, msg, parse_mode=ParseMode.MARKDOWN_V2)
            except Exception as markdown_error:
                logger.error("❌ Markdown parsing error: %s", markdown_error)
                plain_msg = msg.replace("\\", "").replace("*", "").replace("_", "")
                await send_command_response(update, context, f"📊 Weekly Stats\n\n{plain_msg}")
            
    except Exception as e:
        logger.error("❌ Error in stats command: %s", e)
        await send_command_response(update, context, "❌ Could not fetch statistics\\. Check logs for details\\.", parse_mode=ParseMode.MARKDOWN_V2)

async def hot_command(update, context: CallbackContext):
    """Show what's hot this week"""
    try:
        await send_command_response(update, context, "🔥 Fetching what's hot this week\\.\\.\\.", parse_mode=ParseMode.MARKDOWN_V2)
        logger.info("🔥 Manual hot command triggered by user %s", update.effective_user.username or update.effective_user.id)
        
        movies, shows = await fetch_trending()
        today = datetime.now(MELBOURNE_TZ).strftime("%d %b %Y")
        date_md = escape_md(f"({today})")
        msg = f"🎬 *What's Hot This Week* {date_md}\n\n*Movies:*\n"
        
        for m in movies[:7]:
            title = escape_md(m.get("title", "Unknown"))
            rel_date = escape_md(f"({m.get('release_date','?')})")
            rating = safe_format_number(m.get("vote_average", 0), 1)
            providers = escape_md(await fetch_watch_providers("movie", m.get("id", 0)))
            msg += f"\\- {title} {rel_date} – ⭐ {rating} \\| {providers}\n"
            
        msg += "\n*TV Shows:*\n"
        for s in shows[:5]:
            name = escape_md(s.get("name", "Unknown"))
            air_date = escape_md(f"({s.get('first_air_date','?')})")
            rating = safe_format_number(s.get("vote_average", 0), 1)
            providers = escape_md(await fetch_watch_providers("tv", s.get("id", 0)))
            msg += f"\\- {name} {air_date} – ⭐ {rating} \\| {providers}\n"
        
        await send_command_response(update, context, msg, parse_mode=ParseMode.MARKDOWN_V2)
        logger.info("✅ Manual hot message sent successfully")
        
    except Exception as e:
        logger.error("❌ Hot command failed: %s", e)
        await send_command_response(update, context, "❌ Could not fetch trending content\\. Check logs for details\\.", parse_mode=ParseMode.MARKDOWN_V2)

async def upcoming_command(update, context: CallbackContext):
    """Show upcoming TV episodes and movies for this week"""
    try:
        async with AsyncClient() as client:
            await send_command_response(update, context, "📅 Fetching upcoming releases\\.\\.\\.", parse_mode=ParseMode.MARKDOWN_V2)
            
            # Fetch data from both services
            sonarr_episodes = await fetch_sonarr_upcoming(client)
            radarr_movies = await fetch_radarr_upcoming(client)
            
            # Build message
            today = datetime.now(MELBOURNE_TZ)
            week_end = today + timedelta(days=7)
            month_end = today + timedelta(days=30)
            
            # Different date ranges for TV (week) and Movies (month)
            tv_date_range = f"{today.strftime('%b %d')} \\- {week_end.strftime('%b %d, %Y')}"
            movie_date_range = f"{today.strftime('%b %d')} \\- {month_end.strftime('%b %d, %Y')}"
            
            msg = f"📅 *Upcoming Releases*\n\n"
            
            # TV Episodes section
            if sonarr_episodes is not None:
                if sonarr_episodes:
                    msg += f"*📺 TV Episodes* \\({tv_date_range}\\):\n"
                    # Sort by air date
                    sorted_episodes = sorted(sonarr_episodes, 
                                           key=lambda x: x.get("airDate", "9999-12-31"))
                    
                    for episode in sorted_episodes[:10]:  # Limit to 10 episodes
                        formatted_episode = format_sonarr_episode(episode)
                        msg += formatted_episode + "\n"
                    
                    if len(sorted_episodes) > 10:
                        msg += f"\\.\\.\\. and {len(sorted_episodes) - 10} more episodes\n"
                        
                    msg += "\n"
                else:
                    msg += f"*📺 TV Episodes* \\({tv_date_range}\\): None scheduled\n\n"
            else:
                if SONARR_URL and SONARR_API_KEY:
                    msg += f"*📺 TV Episodes* \\({tv_date_range}\\): Data unavailable\n\n"
            
            # Movies section
            if radarr_movies is not None:
                if radarr_movies:
                    msg += f"*🎬 Movies* \\({movie_date_range}\\):\n"
                    # Sort by earliest relevant release date
                    def get_sort_date(movie):
                        """Get the earliest upcoming release date for sorting"""
                        now = datetime.now(MELBOURNE_TZ).date()
                        dates = []
                        
                        for date_str in [movie.get("inCinemas", ""), 
                                       movie.get("digitalRelease", ""), 
                                       movie.get("physicalRelease", "")]:
                            if date_str:
                                try:
                                    release_date = datetime.fromisoformat(date_str.replace('Z', '+00:00')).date()
                                    if release_date >= now:  # Future dates only for sorting
                                        dates.append(release_date)
                                except:
                                    continue
                        
                        return min(dates) if dates else datetime(9999, 12, 31).date()
                    
                    sorted_movies = sorted(radarr_movies, key=get_sort_date)
                    
                    # Format movies and filter out None results (movies with no upcoming releases)
                    formatted_movies = []
                    for movie in sorted_movies:
                        formatted_movie = format_radarr_movie(movie)
                        if formatted_movie is not None:  # Only include movies with upcoming releases
                            formatted_movies.append(formatted_movie)
                    
                    if formatted_movies:
                        for formatted_movie in formatted_movies[:15]:  # Show more movies since it's a month
                            msg += formatted_movie + "\n"
                        
                        if len(formatted_movies) > 15:
                            msg += f"\\.\\.\\. and {len(formatted_movies) - 15} more movies\n"
                        msg += "\n"
                    else:
                        msg += "No upcoming releases this month\n\n"
                else:
                    msg += f"*🎬 Movies* \\({movie_date_range}\\): None scheduled\n\n"
            else:
                if RADARR_URL and RADARR_API_KEY:
                    msg += f"*🎬 Movies* \\({movie_date_range}\\): Data unavailable\n\n"
            
            # Updated Legend
            msg += "*Legend:*\n"
            msg += "📁 Downloaded \\| ⏳ Awaiting release\n"
            msg += "🎬 Cinema \\| 💻 Digital \\| 📀 Physical"
            
            # Check if no services configured
            if not (SONARR_URL or RADARR_URL):
                msg = "❌ No Sonarr/Radarr configured\\. Check environment variables\\."
            
            try:
                await send_command_response(update, context, msg, parse_mode=ParseMode.MARKDOWN_V2)
            except Exception as markdown_error:
                logger.error("❌ Markdown parsing error in upcoming: %s", markdown_error)
                # Send as plain text if markdown fails
                plain_msg = msg.replace("\\", "").replace("*", "").replace("_", "")
                await send_command_response(update, context, f"📅 Upcoming Releases\n\n{plain_msg}")
            
    except Exception as e:
        logger.error("❌ Error in upcoming command: %s", e)
        await send_command_response(update, context, "❌ Could not fetch upcoming releases\\. Check logs for details\\.", parse_mode=ParseMode.MARKDOWN_V2)
