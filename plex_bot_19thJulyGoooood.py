import logging
import os
import asyncio
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from telegram.ext import ApplicationBuilder, CallbackContext, CommandHandler
from telegram.constants import ParseMode
from telegram import Bot
from httpx import AsyncClient
from wakeonlan import send_magic_packet
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import paramiko

# Load environment variables
load_dotenv()

def setup_logging():
    """Setup logging that clears the log file each session"""
    
    # Create formatter
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # Root logger configuration
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    
    # Remove any existing handlers to avoid duplicates
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    # File handler that overwrites the log file each session (mode='w')
    file_handler = logging.FileHandler(
        'bot.log',  # In the same directory as the script
        mode='w',   # This clears the file each time
        encoding='utf-8'
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)
    
    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    
    # Add handlers to root logger
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)
    
    # Suppress noisy third-party loggers
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.INFO)  # Keep scheduler logs
    
    # Log startup message with session info
    melbourne_time = datetime.now(ZoneInfo("Australia/Melbourne"))
    logging.info("=" * 60)
    logging.info("🤖 PLEX BOT SESSION START")
    logging.info("🕐 Session started: %s", melbourne_time.strftime('%Y-%m-%d %H:%M:%S %Z'))
    logging.info("📁 Log file: %s", os.path.abspath('bot.log'))
    logging.info("📝 This log file is cleared each session")
    logging.info("=" * 60)

# Setup logging first
setup_logging()

# Add shutdown handler
import atexit
import signal

def log_shutdown():
    melbourne_time = datetime.now(ZoneInfo("Australia/Melbourne"))
    logging.info("=" * 60)
    logging.info("🛑 PLEX BOT SESSION END")
    logging.info("🕐 Session ended: %s", melbourne_time.strftime('%Y-%m-%d %H:%M:%S %Z'))
    logging.info("📊 Session duration logged above")
    logging.info("=" * 60)

# Register shutdown handlers
atexit.register(log_shutdown)
signal.signal(signal.SIGTERM, lambda signum, frame: log_shutdown())
signal.signal(signal.SIGINT, lambda signum, frame: log_shutdown())

# Now get logger
logger = logging.getLogger(__name__)

# --- Config ---
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
GROUP_CHAT_ID = int(os.getenv("GROUP_CHAT_ID", "0"))
TMDB_BEARER_TOKEN = os.getenv("TMDB_API_READ_TOKEN", "")
# Full base URL for Tautulli (including http:// or https://)
TAUTILLI_URL = os.getenv("TAUTILLI_URL", "")
TAUTILLI_API_KEY = os.getenv("TAUTILLI_API_KEY", "")
# Jellyfin API config
JELLYFIN_URL = os.getenv("JELLYFIN_URL", "http://192.168.1.30:8096")
JELLYFIN_API_KEY = os.getenv("JELLYFIN_API_KEY", "c43fe8ff99054aa59eb5173703cef999")
# Sonarr/Radarr API config
SONARR_URL = os.getenv("SONARR_URL", "")
SONARR_API_KEY = os.getenv("SONARR_API_KEY", "")
RADARR_URL = os.getenv("RADARR_URL", "")
RADARR_API_KEY = os.getenv("RADARR_API_KEY", "")
# Telegram user IDs allowed to run /off
OFF_USER_IDS = {int(uid) for uid in os.getenv("OFF_USER_IDS", "").split(",") if uid.strip()}

# Wake-on-LAN
PLEX_MAC = os.getenv("PLEX_SERVER_MAC", "40:8d:5c:52:48:29")
PLEX_BROADCAST_IP = os.getenv("PLEX_SERVER_BROADCAST", "192.168.1.255")

# SSH shutdown config
PLEX_SSH_USER = os.getenv("PLEX_SSH_USER", "")
PLEX_SERVER_IP = os.getenv("PLEX_SERVER_IP", "")
PLEX_SSH_PASSWORD = os.getenv("PLEX_SSH_PASSWORD", None)

# Timezone
MELBOURNE_TZ = ZoneInfo("Australia/Melbourne")

# Validate required vars
if not (BOT_TOKEN and GROUP_CHAT_ID and TMDB_BEARER_TOKEN and TAUTILLI_URL and TAUTILLI_API_KEY):
    logger.error("Missing required environment variables. Check .env configuration.")
    exit(1)

# Validate WOL config
if not PLEX_MAC or not PLEX_BROADCAST_IP:
    logger.warning("⚠️ Wake-on-LAN not configured properly")

# --- TMDB Fetchers ---
async def fetch_trending():
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
    headers = {"Authorization": f"Bearer {TMDB_BEARER_TOKEN}", "accept": "application/json"}
    url = f"https://api.themoviedb.org/3/{media_type}/{media_id}/watch/providers"
    async with AsyncClient() as client:
        resp = await client.get(url, headers=headers)
    results = resp.json().get("results", {}) if resp.status_code == 200 else {}
    au = results.get("AU", {})
    if au.get("flatrate"):
        return ", ".join(item.get("provider_name", "") for item in au["flatrate"])
    return "No streaming info"

# --- Sonarr/Radarr Fetchers ---
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

# --- Markdown escape ---
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

# --- Message formatting ---
async def format_message() -> str:
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
    return msg

# --- Sonarr/Radarr formatting ---
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

# --- Enhanced /nowplaying with Jellyfin support ---
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
        # User info
        user = session.get("UserName", "Unknown")
        
        # What they're watching
        now_playing = session.get("NowPlayingItem", {})
        if now_playing:
            media_type = now_playing.get("Type", "").lower()
            name = now_playing.get("Name", "Unknown")
            
            # For TV shows, include series name
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
        
        # Playback info
        play_state = session.get("PlayState", {})
        is_paused = play_state.get("IsPaused", False)
        state = "Paused" if is_paused else "Playing"
        
        # Device info
        device = session.get("DeviceName", "Unknown Device")
        
        # Format the line
        user_safe = escape_md(user)
        title_safe = escape_md(title)
        state_safe = escape_md(state)
        device_safe = escape_md(device)
        
        return f"\\- {user_safe} – {title_safe} – {device_safe} \\({state_safe}\\)"
        
    except Exception as e:
        logger.error("Error formatting Jellyfin session: %s", e)
        return f"\\- {escape_md(session.get('UserName', 'Unknown'))} – Error formatting session"

def get_stream_type(session_data):
    """Determine the stream type from Tautulli session data"""
    try:
        # Debug logging to see what fields are available
        logger.debug("Session data keys: %s", list(session_data.keys()))
        
        # Check for transcoding first - most reliable indicator
        transcode_decision = session_data.get("transcode_decision", "").lower()
        if transcode_decision == "transcode":
            return "Transcoding"
        elif transcode_decision == "copy":
            return "Direct Play"
        elif transcode_decision == "direct play":
            return "Direct Play"
        
        # Check stream container decision
        stream_container = session_data.get("stream_container_decision", "").lower()
        if stream_container == "copy":
            return "Direct Play"
        elif stream_container == "transcode":
            return "Transcoding"
        
        # Check individual transcode decisions
        transcode_video = session_data.get("transcode_video_decision", "").lower()
        transcode_audio = session_data.get("transcode_audio_decision", "").lower()
        
        if transcode_video == "transcode" or transcode_audio == "transcode":
            return "Transcoding"
        elif transcode_video == "copy" and transcode_audio == "copy":
            return "Direct Play"
        elif "direct stream" in transcode_video or "direct stream" in transcode_audio:
            return "Direct Stream"
        
        # Check if it's direct play based on codec info
        video_decision = session_data.get("video_decision", "").lower()
        audio_decision = session_data.get("audio_decision", "").lower()
        
        if video_decision == "direct play" or audio_decision == "direct play":
            return "Direct Play"
        elif video_decision == "transcode" or audio_decision == "transcode":
            return "Transcoding"
        
        # Check stream_type field
        stream_type = session_data.get("stream_type", "")
        if stream_type:
            return stream_type.title()
        
        # Log available fields for debugging
        relevant_fields = {k: v for k, v in session_data.items() if any(word in k.lower() for word in ['transcode', 'stream', 'decision', 'play'])}
        logger.debug("Relevant stream fields: %s", relevant_fields)
        
        # Final fallback
        return "Direct Play"  # Default assumption for Plex
        
    except Exception as e:
        logger.error("Error determining stream type: %s", e)
        return "Unknown"

async def nowplaying_command(update, context: CallbackContext):
    try:
        async with AsyncClient() as client:
            lines = ["🎥 *Now Playing*"]
            
            # Tautulli data (Plex)
            try:
                taut_url = TAUTILLI_URL.rstrip('/') + f"/api/v2?apikey={TAUTILLI_API_KEY}&cmd=get_activity"
                logger.debug("Fetching Tautulli data from: %s", taut_url.replace(TAUTILLI_API_KEY, "***"))
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
                        
                        # Use improved stream type detection
                        stream_type = get_stream_type(s)
                        stream = escape_md(stream_type)
                        
                        state = escape_md(s.get("state", ""))
                        lines.append(f"\\- {user} – {title} – {stream} \\({state}\\)")

                    # WAN bandwidth - convert from kbps to Mbps
                    wan_kbps = taut_data.get("wan_bandwidth", 0)
                    if wan_kbps > 0:
                        wan_mbps = wan_kbps / 1000  # Convert kbps to Mbps
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
                # Filter for active sessions (ones that are actually playing something)
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
        logger.debug("Sending nowplaying message: %s", msg[:200] + "..." if len(msg) > 200 else msg)
        
        try:
            await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN_V2)
        except Exception as markdown_error:
            logger.error("❌ Markdown parsing error: %s", markdown_error)
            # Send as plain text if markdown fails
            plain_msg = msg.replace("\\", "").replace("*", "").replace("_", "")
            await update.message.reply_text(f"🎥 Now Playing\n\n{plain_msg}")
        
    except Exception as e:
        logger.error("❌ Error in nowplaying command: %s", e)
        await update.message.reply_text("❌ Could not fetch now playing data. Check logs for details.")

# --- Upcoming command ---
async def upcoming_command(update, context: CallbackContext):
    """Show upcoming TV episodes and movies for this week"""
    try:
        async with AsyncClient() as client:
            await update.message.reply_text("📅 Fetching upcoming releases\\.\\.\\.", parse_mode=ParseMode.MARKDOWN_V2)
            
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
                await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN_V2)
            except Exception as markdown_error:
                logger.error("❌ Markdown parsing error in upcoming: %s", markdown_error)
                # Send as plain text if markdown fails
                plain_msg = msg.replace("\\", "").replace("*", "").replace("_", "")
                await update.message.reply_text(f"📅 Upcoming Releases\n\n{plain_msg}")
            
    except Exception as e:
        logger.error("❌ Error in upcoming command: %s", e)
        await update.message.reply_text("❌ Could not fetch upcoming releases\\. Check logs for details\\.", parse_mode=ParseMode.MARKDOWN_V2)

# --- Scheduled tasks ---
async def scheduled_wake(bot: Bot):
    melbourne_time = datetime.now(MELBOURNE_TZ)
    logger.info("⏰ Auto-wake job triggered at %s (Melbourne time)", melbourne_time.strftime('%Y-%m-%d %H:%M:%S %Z'))
    
    # Log system status
    logger.info("🔍 Pre-wake check - MAC: %s, Broadcast: %s, Group ID: %s", 
                PLEX_MAC, PLEX_BROADCAST_IP, GROUP_CHAT_ID)
    
    try:
        # Send WOL packet
        logger.info("📤 Sending WOL packet...")
        send_magic_packet(PLEX_MAC, ip_address=PLEX_BROADCAST_IP)
        logger.info("✅ WOL packet sent successfully to %s via %s", PLEX_MAC, PLEX_BROADCAST_IP)
        
        # Send Telegram notification
        logger.info("📱 Sending Telegram notification to group %s...", GROUP_CHAT_ID)
        message_text = f"🔌 Plex server auto-start (scheduled at {melbourne_time.strftime('%H:%M')})"
        await bot.send_message(chat_id=GROUP_CHAT_ID, text=message_text)
        logger.info("✅ Telegram notification sent successfully")
        
    except Exception as e:
        logger.error("❌ Auto-wake failed: %s", e, exc_info=True)  # Include full traceback
        try:
            error_message = f"❌ Auto-wake failed at {melbourne_time.strftime('%H:%M')}: {str(e)}"
            await bot.send_message(chat_id=GROUP_CHAT_ID, text=error_message)
            logger.info("✅ Error notification sent to Telegram")
        except Exception as telegram_error:
            logger.error("❌ Failed to send error notification to Telegram: %s", telegram_error)

# --- Commands ---
async def on_command(update, context: CallbackContext):
    try:
        send_magic_packet(PLEX_MAC, ip_address=PLEX_BROADCAST_IP)
        logger.info("✅ Manual WOL packet sent to %s via %s", PLEX_MAC, PLEX_BROADCAST_IP)
        await update.message.reply_text("🔌 Sent Wake-on-LAN packet.")
    except Exception as e:
        logger.error("❌ Manual WOL failed: %s", e)
        await update.message.reply_text(f"❌ Wake-on-LAN failed: {str(e)}")

async def off_command(update, context: CallbackContext):
    user_id = update.effective_user.id
    if user_id not in OFF_USER_IDS:
        return await update.message.reply_text("❌ Not authorized.")
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(PLEX_SERVER_IP, username=PLEX_SSH_USER, password=PLEX_SSH_PASSWORD)
        stdin, stdout, stderr = ssh.exec_command('sudo -S shutdown -h now', get_pty=True)
        stdin.write(PLEX_SSH_PASSWORD + '\n')
        stdin.flush()
        ssh.close()
        logger.info("✅ Shutdown command sent to %s", PLEX_SERVER_IP)
        await update.message.reply_text("🔌 Plex server is shutting down.")
    except Exception as e:
        logger.error("❌ Shutdown failed: %s", e)
        await update.message.reply_text("❌ Shutdown failed.")

async def debug_command(update, context: CallbackContext):
    """Debug command to check bot status and scheduler"""
    try:
        current_time = datetime.now(MELBOURNE_TZ).strftime('%Y-%m-%d %H:%M:%S %Z')
        msg = f"🔍 *Bot Debug Info*\n"
        msg += f"\\- Current time: {escape_md(current_time)}\n"
        msg += f"\\- Plex MAC: {escape_md(PLEX_MAC)}\n"
        msg += f"\\- Broadcast IP: {escape_md(PLEX_BROADCAST_IP)}\n"
        msg += f"\\- Group Chat ID: {escape_md(str(GROUP_CHAT_ID))}\n"
        msg += f"\\- Tautulli URL: {escape_md(TAUTILLI_URL[:50] + '...' if len(TAUTILLI_URL) > 50 else TAUTILLI_URL)}\n"
        msg += f"\\- Jellyfin URL: {escape_md(JELLYFIN_URL[:50] + '...' if len(JELLYFIN_URL) > 50 else JELLYFIN_URL) if JELLYFIN_URL else 'Not configured'}\n"
        msg += f"\\- Sonarr URL: {escape_md(SONARR_URL[:50] + '...' if len(SONARR_URL) > 50 else SONARR_URL) if SONARR_URL else 'Not configured'}\n"
        msg += f"\\- Radarr URL: {escape_md(RADARR_URL[:50] + '...' if len(RADARR_URL) > 50 else RADARR_URL) if RADARR_URL else 'Not configured'}\n"
        
        # Add scheduler info
        if scheduler:
            msg += f"\n📅 *Scheduler Status*\n"
            msg += f"\\- Active jobs: {len(scheduler.get_jobs())}\n"
            for job in scheduler.get_jobs():
                if job.next_run_time:
                    next_run = job.next_run_time.astimezone(MELBOURNE_TZ).strftime('%Y-%m-%d %H:%M:%S %Z')
                    msg += f"\\- {escape_md(job.id)}: {escape_md(next_run)}\n"
                else:
                    msg += f"\\- {escape_md(job.id)}: Never\n"
        else:
            msg += f"\n📅 *Scheduler Status*\n\\- Scheduler not initialized"
            
        await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN_V2)
    except Exception as e:
        logger.error("❌ Debug command failed: %s", e)
        await update.message.reply_text(f"❌ Debug failed: {e}")

async def testjellyfin_command(update, context: CallbackContext):
    """Test Jellyfin API connectivity"""
    if not (JELLYFIN_URL and JELLYFIN_API_KEY):
        await update.message.reply_text("❌ Jellyfin not configured\\.", parse_mode=ParseMode.MARKDOWN_V2)
        return
    
    try:
        async with AsyncClient() as client:
            await update.message.reply_text("🔍 Testing Jellyfin API\\.\\.\\.", parse_mode=ParseMode.MARKDOWN_V2)
            
            # Test sessions endpoint
            base_url = JELLYFIN_URL.rstrip('/')
            sessions_url = f"{base_url}/Sessions?api_key={JELLYFIN_API_KEY}"
            
            resp = await client.get(sessions_url)
            
            if resp.status_code == 200:
                sessions = resp.json()
                msg = "✅ *Jellyfin API Test Success*\n\n"
                msg += f"*Sessions Endpoint:* ✅ \\({len(sessions)} sessions\\)\n"
                
                # Show active sessions if any
                active_sessions = [s for s in sessions if s.get("NowPlayingItem")]
                if active_sessions:
                    msg += f"*Active Sessions:* {len(active_sessions)}\n"
                    for session in active_sessions[:3]:  # Show first 3
                        user = session.get("UserName", "Unknown")
                        msg += f"\\- {escape_md(user)}\n"
                else:
                    msg += "*Active Sessions:* None"
                    
            else:
                msg = f"❌ *Jellyfin API Test Failed*\n\n"
                msg += f"Status Code: {resp.status_code}\n"
                msg += "Check URL and API key configuration\\."
                
        await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN_V2)
        
    except Exception as e:
        logger.error("❌ Jellyfin test failed: %s", e)
        await update.message.reply_text(f"❌ Test failed: {escape_md(str(e))}", parse_mode=ParseMode.MARKDOWN_V2)

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

async def fetch_tautulli_stats(client, time_range=7):
    """Fetch viewing statistics from Tautulli using basic API calls"""
    try:
        base_url = TAUTILLI_URL.rstrip('/')
        
        # Test basic API connectivity first
        logger.info("🔍 Testing Tautulli API connectivity...")
        test_url = f"{base_url}/api/v2?apikey={TAUTILLI_API_KEY}&cmd=get_activity"
        test_resp = await client.get(test_url)
        test_resp.raise_for_status()
        logger.info("✅ Tautulli API connection successful")
        
        # Get history data (this is the most reliable call)
        logger.info("📊 Fetching Tautulli history...")
        history_url = f"{base_url}/api/v2?apikey={TAUTILLI_API_KEY}&cmd=get_history&length=200"
        history_resp = await client.get(history_url)
        history_resp.raise_for_status()
        history_result = history_resp.json()
        
        if history_result.get("response", {}).get("result") != "success":
            logger.error("❌ Tautulli history API returned error: %s", history_result.get("response", {}).get("message", "Unknown"))
            return None, None
            
        history_data = history_result.get("response", {}).get("data", {}).get("data", [])
        logger.info("✅ Retrieved %d history items", len(history_data))
        
        # Try to get user stats (fallback if not available)
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
                else:
                    logger.warning("⚠️ User stats API not successful: %s", user_result.get("response", {}).get("message", "Unknown"))
            else:
                logger.warning("⚠️ User stats API returned status %d", user_resp.status_code)
                
        except Exception as user_error:
            logger.warning("⚠️ User stats API not available (older Tautulli?): %s", user_error)
            user_data = None
        
        return user_data, history_data
        
    except Exception as e:
        logger.error("❌ Failed to fetch Tautulli stats: %s", e)
        return None, None

def calculate_user_stats_from_history(history_data, days=7):
    """Calculate user stats from history data if API doesn't provide them"""
    from collections import defaultdict
    
    if not history_data:
        return []
    
    # Calculate cutoff date
    cutoff_date = datetime.now() - timedelta(days=days)
    
    # Aggregate by user
    user_stats = defaultdict(lambda: {"total_time": 0, "total_plays": 0})
    
    for item in history_data:
        try:
            # Parse the date (Tautulli uses Unix timestamp)
            item_date = datetime.fromtimestamp(int(item.get("date", 0)))
            
            if item_date < cutoff_date:
                continue
                
            user = item.get("user", "Unknown")
            duration = int(item.get("duration", 0) or 0)
            
            user_stats[user]["total_time"] += duration
            user_stats[user]["total_plays"] += 1
            
        except (ValueError, TypeError) as e:
            logger.debug("Error parsing history item for user stats: %s", e)
            continue
    
    # Convert to list format similar to API response
    result = []
    for user, stats in user_stats.items():
        result.append({
            "user": user,
            "total_time": stats["total_time"],
            "total_plays": stats["total_plays"]
        })
    
    return result

def analyze_most_watched_content(history_data, days=7):
    """Analyze history data to find most watched content in the past week"""
    from collections import defaultdict
    
    if not history_data:
        return []
    
    # Calculate cutoff date (7 days ago)
    cutoff_date = datetime.now() - timedelta(days=days)
    
    # Count plays for each title
    content_plays = defaultdict(lambda: {"plays": 0, "users": set(), "duration": 0})
    
    for item in history_data:
        try:
            # Parse the date (Tautulli uses Unix timestamp)
            item_date = datetime.fromtimestamp(int(item.get("date", 0)))
            
            if item_date < cutoff_date:
                continue
                
            # Get content identifier
            title = item.get("full_title") or item.get("title", "Unknown")
            user = item.get("user", "Unknown")
            duration = int(item.get("duration", 0) or 0)
            
            content_plays[title]["plays"] += 1
            content_plays[title]["users"].add(user)
            content_plays[title]["duration"] += duration
            
        except (ValueError, TypeError) as e:
            logger.debug("Error parsing history item: %s", e)
            continue
    
    # Sort by number of plays
    sorted_content = sorted(
        [(title, data) for title, data in content_plays.items()],
        key=lambda x: x[1]["plays"],
        reverse=True
    )
    
    return sorted_content[:10]  # Top 10

async def stats_command(update, context: CallbackContext):
    """Show weekly viewing statistics"""
    try:
        async with AsyncClient() as client:
            await update.message.reply_text("📊 Fetching weekly stats\\.\\.\\.", parse_mode=ParseMode.MARKDOWN_V2)
            
            user_stats, history_data = await fetch_tautulli_stats(client)
            
            if not history_data:
                await update.message.reply_text("❌ Could not fetch statistics\\. Check Tautulli connection\\.", parse_mode=ParseMode.MARKDOWN_V2)
                return
            
            # If user stats API failed, calculate from history
            if not user_stats and history_data:
                logger.info("📊 User stats API unavailable, calculating from history data...")
                user_stats = calculate_user_stats_from_history(history_data)
                logger.info("✅ Calculated stats for %d users from history", len(user_stats))
            
            # Calculate date range
            end_date = datetime.now(MELBOURNE_TZ)
            start_date = end_date - timedelta(days=7)
            date_range = f"{start_date.strftime('%d %b')} \\- {end_date.strftime('%d %b %Y')}"
            
            msg = f"📊 *Weekly Stats* \\({date_range}\\)\n\n"
            
            # Top Users section
            if user_stats:
                msg += "*🏆 Top Users \\(Watch Time\\):*\n"
                # Sort users by total time watched
                sorted_users = sorted(user_stats, key=lambda x: int(x.get("total_time", 0) or 0), reverse=True)
                
                for i, user in enumerate(sorted_users[:5], 1):
                    username = escape_md(user.get("user", "Unknown"))
                    total_time = int(user.get("total_time", 0) or 0)
                    plays = user.get("total_plays", 0)
                    duration_str = escape_md(format_duration(total_time))
                    
                    # Add emoji for top 3
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
            
            # Add some overall stats if available
            if user_stats and history_data:
                total_users = len([u for u in user_stats if int(u.get("total_time", 0) or 0) > 0])
                total_plays = sum(int(u.get("total_plays", 0) or 0) for u in user_stats)
                total_time = sum(int(u.get("total_time", 0) or 0) for u in user_stats)
                
                msg += f"\n*📈 Week Summary:*\n"
                msg += f"\\- Active users: {total_users}\n"
                msg += f"\\- Total plays: {total_plays}\n"
                msg += f"\\- Total watch time: {escape_md(format_duration(total_time))}"
            
            try:
                await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN_V2)
            except Exception as markdown_error:
                logger.error("❌ Markdown parsing error in stats: %s", markdown_error)
                # Send as plain text if markdown fails
                plain_msg = msg.replace("\\", "").replace("*", "").replace("_", "")
                await update.message.reply_text(f"📊 Weekly Stats\n\n{plain_msg}")
            
    except Exception as e:
        logger.error("❌ Error in stats command: %s", e)
        await update.message.reply_text("❌ Could not fetch statistics\\. Check logs for details\\.", parse_mode=ParseMode.MARKDOWN_V2)

async def logs_command(update, context: CallbackContext):
    """Show recent log entries from current session"""
    user_id = update.effective_user.id
    if user_id not in OFF_USER_IDS:  # Only authorized users
        return await update.message.reply_text("❌ Not authorized.")
    
    try:
        # Read the entire current session log file
        with open('bot.log', 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        # Get last 50 lines or entire file if smaller
        recent_lines = lines[-50:] if len(lines) > 50 else lines
        
        # Format for Telegram (escape markdown and limit length)
        log_text = ''.join(recent_lines)
        if len(log_text) > 4000:  # Telegram message limit
            log_text = "..." + log_text[-3900:]
        
        # Escape markdown characters
        log_text = escape_md(log_text)
        
        session_info = f"Current session \\({len(lines)} total lines\\)"
        
        await update.message.reply_text(
            f"📋 *Session Logs \\(last {len(recent_lines)} lines\\):*\n_{session_info}_\n\n```\n{log_text}\n```",
            parse_mode=ParseMode.MARKDOWN_V2
        )
        
    except FileNotFoundError:
        await update.message.reply_text("❌ Log file not found\\. Bot may have just started\\.", parse_mode=ParseMode.MARKDOWN_V2)
    except Exception as e:
        logger.error("❌ Error reading logs: %s", e)
        await update.message.reply_text(f"❌ Error reading logs: {escape_md(str(e))}", parse_mode=ParseMode.MARKDOWN_V2)

async def testwake_command(update, context: CallbackContext):
    """Test the scheduled wake function manually"""
    try:
        await update.message.reply_text("🧪 Testing scheduled wake function...")
        
        # Call the same function that the scheduler uses
        await scheduled_wake(context.bot)
        
        await update.message.reply_text("✅ Test completed! Check logs for details.")
        
    except Exception as e:
        logger.error("❌ Test wake command failed: %s", e)
        await update.message.reply_text(f"❌ Test failed: {str(e)}")

async def hot_command(update, context: CallbackContext):
    """Show what's hot this week (manual version of weekly trending)"""
    try:
        await update.message.reply_text("🔥 Fetching what's hot this week\\.\\.\\.", parse_mode=ParseMode.MARKDOWN_V2)
        logger.info("🔥 Manual hot command triggered by user %s", update.effective_user.username or update.effective_user.id)
        
        text = await format_message()
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN_V2)
        logger.info("✅ Manual hot message sent successfully")
        
    except Exception as e:
        logger.error("❌ Hot command failed: %s", e)
        await update.message.reply_text("❌ Could not fetch trending content\\. Check logs for details\\.", parse_mode=ParseMode.MARKDOWN_V2)

async def info_command(update, context: CallbackContext):
    """Show comprehensive bot and server information"""
    try:
        msg = "🤖 *Plex Bot \\- Complete Guide*\n\n"
        msg += "*🎬 Media Commands:*\n"
        msg += "\\- `/auth poop` \\- Allows you to request movies/TV shows\n"
        msg += "\\- `/movie <title>` or `/m <title>` \\- Search for a movie\n"
        msg += "\\- `/series <title>` or `/s <title>` or `/tv <title>` \\- Search for TV series\n"
        msg += "\\- `/nowplaying` or `/np` \\- Show current streams\n"
        msg += "\\- `/stats` \\- Weekly viewing statistics\n"
        msg += "\\- `/upcoming` or `/up` \\- Show upcoming releases\n"
        msg += "\\- `/hot` \\- Show what's trending this week\n\n"
        msg += "*🔌 Server & Access:*\n"
        msg += "\\- `/on` \\- Wake up Plex server\n"
        msg += "\\- `/off` \\- Shutdown server \\(authorized users\\)\n"
        msg += "\\- **Jellyfin:** https://stoveflix\\.duckdns\\.org\n"
        msg += "\\- **Plex App Setup Guide:** https://mediaclients\\.wiki/Plex\n\n"
        msg += "*📱 Quick Tips:*\n"
        msg += "\\- Use `/np` for quick stream checks\n"
        msg += "\\- Server auto\\-starts weekdays 4\\:30pm, weekends 10am\n"
        msg += "\\- Check `/stats` to see weekly viewing champions\n"
        msg += "\\- Request content after using `/auth poop`\n"
        msg += "\\- Use `/upcoming` to plan your viewing\n\n"
        msg += "*🆘 Need Help?*\n"
        msg += "\\- Server down? Try `/on` to wake it up\n"
        msg += "\\- Can't find content? Use `/movie` or `/series` to search\n"
        msg += "\\- Buffering issues? Check `/np` for server load\n"
        msg += "\\- Questions? Ask in this chat\\!\n\n"
        msg += "*🔧 Admin Commands:*\n"
        msg += "\\- `/debug` \\- Show bot status\n"
        msg += "\\- `/logs` \\- View session logs \\(authorized users\\)\n"
        msg += "\\- `/testwake` \\- Test wake function\n"
        msg += "\\- `/testjellyfin` \\- Test Jellyfin connection\n\n"
        msg += "*💡 Pro Tips:*\n"
        msg += "\\- Bookmark the Jellyfin/Plex links above\n"
        msg += "\\- Use specific search terms for better results\n"
        msg += "\\- Check what others are watching with `/np`\n"
        msg += "\\- Weekly stats reset every Sunday"
        
        try:
            await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN_V2)
        except Exception as markdown_error:
            logger.error("❌ Markdown parsing error in info: %s", markdown_error)
            # Send as plain text if markdown fails
            plain_msg = msg.replace("\\", "").replace("*", "").replace("_", "")
            await update.message.reply_text(f"🤖 Plex Bot - Complete Guide\n\n{plain_msg}")
        
    except Exception as e:
        logger.error("❌ Error in info command: %s", e)
        await update.message.reply_text("❌ Error showing info\\.", parse_mode=ParseMode.MARKDOWN_V2)

# Global scheduler reference for debugging
scheduler = None

# --- Main ---
if __name__ == "__main__":
    builder = ApplicationBuilder().token(BOT_TOKEN)

    async def on_startup(app):
        global scheduler
        scheduler = AsyncIOScheduler(timezone=MELBOURNE_TZ)
        
        # Add jobs - removed weekly_hot since it's now a manual command
        scheduler.add_job(
            scheduled_wake, 
            CronTrigger(day_of_week='mon,tue,wed,thu,fri', hour=16, minute=30), 
            args=[app.bot], 
            id='auto_on_weekday'
        )
        scheduler.add_job(
            scheduled_wake, 
            CronTrigger(day_of_week='sat,sun', hour=10, minute=0), 
            args=[app.bot], 
            id='auto_on_weekend'
        )
        
        scheduler.start()
        logger.info("📅 Scheduler started with %d jobs", len(scheduler.get_jobs()))
        
        # Log next run times for debugging
        for job in scheduler.get_jobs():
            if job.next_run_time:
                next_run = job.next_run_time.astimezone(MELBOURNE_TZ).strftime('%Y-%m-%d %H:%M:%S %Z')
                logger.info("⏰ Job '%s' next run: %s", job.id, next_run)
            else:
                logger.info("⏰ Job '%s' next run: Never", job.id)
        
        logger.info("🚀 Bot startup complete at %s", datetime.now(MELBOURNE_TZ).strftime('%Y-%m-%d %H:%M:%S %Z'))

    builder.post_init(on_startup)
    app = builder.build()
    app.add_handler(CommandHandler("on", on_command))
    app.add_handler(CommandHandler("off", off_command))
    app.add_handler(CommandHandler("nowplaying", nowplaying_command))
    app.add_handler(CommandHandler("np", nowplaying_command))  # Alias for nowplaying
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("upcoming", upcoming_command))
    app.add_handler(CommandHandler("up", upcoming_command))  # Alias for upcoming
    app.add_handler(CommandHandler("hot", hot_command))  # Manual trending command
    app.add_handler(CommandHandler("debug", debug_command))
    app.add_handler(CommandHandler("testjellyfin", testjellyfin_command))
    app.add_handler(CommandHandler("logs", logs_command))
    app.add_handler(CommandHandler("testwake", testwake_command))
    app.add_handler(CommandHandler("info", info_command))

    logger.info("🚀 Bot starting up...")
    app.run_polling()
