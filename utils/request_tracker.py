"""
Request tracking system for monitoring content requests and their status
Tracks movies/TV shows added to Radarr/Sonarr and notifies users when available
"""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from httpx import AsyncClient
from telegram import Bot

from config import (
    RADARR_URL, RADARR_API_KEY, SONARR_URL, SONARR_API_KEY,
    GROUP_CHAT_ID, BOT_TOPIC_ID, SILENT_NOTIFICATIONS
)

logger = logging.getLogger(__name__)

# Storage file for tracking requests
REQUESTS_DB_FILE = Path(__file__).parent.parent / "data" / "requests.json"


class RequestTracker:
    """Manages tracking of content requests and their download status"""

    def __init__(self):
        self.requests = self._load_requests()

    def _ensure_data_dir(self):
        """Ensure data directory exists"""
        REQUESTS_DB_FILE.parent.mkdir(parents=True, exist_ok=True)

    def _load_requests(self) -> Dict:
        """Load requests from JSON file"""
        try:
            if REQUESTS_DB_FILE.exists():
                with open(REQUESTS_DB_FILE, 'r') as f:
                    data = json.load(f)
                    logger.info("📂 Loaded %d tracked requests", len(data.get('requests', [])))
                    return data
            else:
                logger.info("📂 No existing requests database found, starting fresh")
                return {"requests": []}
        except Exception as e:
            logger.error("❌ Failed to load requests database: %s", e)
            return {"requests": []}

    def _save_requests(self):
        """Save requests to JSON file"""
        try:
            self._ensure_data_dir()
            with open(REQUESTS_DB_FILE, 'w') as f:
                json.dump(self.requests, f, indent=2)
            logger.debug("💾 Saved requests database")
        except Exception as e:
            logger.error("❌ Failed to save requests database: %s", e)

    def add_request(self, media_type: str, title: str, year: int, user_id: int,
                    username: str, tmdb_id: int = None, tvdb_id: int = None,
                    radarr_id: int = None, sonarr_id: int = None,
                    release_date: str = None):
        """
        Add a new request to track

        Args:
            media_type: "movie" or "tv"
            title: Movie/show title
            year: Release year
            user_id: Telegram user ID who requested
            username: Telegram username
            tmdb_id: TMDB ID
            tvdb_id: TVDB ID (for TV shows)
            radarr_id: Radarr movie ID (if known)
            sonarr_id: Sonarr series ID (if known)
            release_date: Release date string (YYYY-MM-DD format)
        """
        request_data = {
            "id": f"{media_type}_{tmdb_id or tvdb_id}_{user_id}_{int(datetime.now().timestamp())}",
            "media_type": media_type,
            "title": title,
            "year": year,
            "user_id": user_id,
            "username": username,
            "tmdb_id": tmdb_id,
            "tvdb_id": tvdb_id,
            "radarr_id": radarr_id,
            "sonarr_id": sonarr_id,
            "release_date": release_date,
            "status": "pending",  # pending, downloading, available, failed, unreleased
            "requested_at": datetime.now().isoformat(),
            "notified": False,
            "subscribers": [{"user_id": user_id, "username": username}]  # Track all users interested
        }

        self.requests["requests"].append(request_data)
        self._save_requests()

        logger.info("📝 Added request: %s (%d) by user %s", title, year, username)
        return request_data["id"]

    def find_existing_request(self, media_type: str, tmdb_id: int) -> Optional[Dict]:
        """
        Find an existing request for the same content (any user)

        Returns:
            The existing request dict if found, None otherwise
        """
        for request in self.requests["requests"]:
            if (request["media_type"] == media_type and
                request.get("tmdb_id") == tmdb_id and
                not request.get("notified", False)):
                return request
        return None

    def add_subscriber(self, request_id: str, user_id: int, username: str) -> bool:
        """
        Add a subscriber to an existing request

        Returns:
            True if subscriber was added, False if already subscribed
        """
        for request in self.requests["requests"]:
            if request["id"] == request_id:
                # Initialize subscribers list if not present (for old requests)
                if "subscribers" not in request:
                    request["subscribers"] = [{
                        "user_id": request["user_id"],
                        "username": request.get("username", "Unknown")
                    }]

                # Check if user is already subscribed
                for sub in request["subscribers"]:
                    if sub["user_id"] == user_id:
                        return False

                # Add new subscriber
                request["subscribers"].append({
                    "user_id": user_id,
                    "username": username
                })
                self._save_requests()
                logger.info("👥 Added subscriber %s to request %s", username, request_id)
                return True
        return False

    def is_release_date_future(self, release_date: str) -> bool:
        """Check if release date is in the future"""
        if not release_date:
            return False
        try:
            release = datetime.strptime(release_date, "%Y-%m-%d").date()
            return release > datetime.now().date()
        except (ValueError, TypeError):
            return False

    def get_release_date_display(self, release_date: str) -> str:
        """Format release date for display"""
        if not release_date:
            return "Unknown"
        try:
            release = datetime.strptime(release_date, "%Y-%m-%d")
            return release.strftime("%B %d, %Y")
        except (ValueError, TypeError):
            return release_date

    def get_user_requests(self, user_id: int) -> List[Dict]:
        """Get all requests for a specific user"""
        return [r for r in self.requests["requests"] if r["user_id"] == user_id]

    def get_pending_requests(self) -> List[Dict]:
        """Get all requests that haven't been notified yet"""
        return [r for r in self.requests["requests"] if not r.get("notified", False)]

    def update_request_status(self, request_id: str, status: str, notified: bool = None):
        """Update status of a request"""
        for request in self.requests["requests"]:
            if request["id"] == request_id:
                request["status"] = status
                request["updated_at"] = datetime.now().isoformat()
                if notified is not None:
                    request["notified"] = notified
                self._save_requests()
                logger.info("🔄 Updated request %s: status=%s, notified=%s",
                          request_id, status, notified)
                return True
        return False

    def remove_request(self, request_id: str) -> bool:
        """Remove a specific request by ID"""
        original_count = len(self.requests["requests"])
        self.requests["requests"] = [
            r for r in self.requests["requests"]
            if r.get("id") != request_id
        ]
        removed = original_count - len(self.requests["requests"])
        if removed > 0:
            self._save_requests()
            return True
        return False

    def remove_old_requests(self, days: int = 30):
        """Remove requests older than specified days that have been notified"""
        from datetime import timedelta
        cutoff = datetime.now() - timedelta(days=days)

        original_count = len(self.requests["requests"])
        self.requests["requests"] = [
            r for r in self.requests["requests"]
            if not (r.get("notified", False) and
                   datetime.fromisoformat(r["requested_at"]) < cutoff)
        ]

        removed = original_count - len(self.requests["requests"])
        if removed > 0:
            self._save_requests()
            logger.info("🧹 Removed %d old requests (older than %d days)", removed, days)

    async def check_radarr_movie_status(self, radarr_id: int) -> tuple[str, bool]:
        """
        Check if a movie is downloaded in Radarr

        Returns:
            (status, has_file) tuple
            status: "downloading", "available", "pending", "failed"
            has_file: True if movie file exists
        """
        if not (RADARR_URL and RADARR_API_KEY):
            return "unknown", False

        try:
            base_url = RADARR_URL.rstrip('/')
            headers = {"X-Api-Key": RADARR_API_KEY}

            async with AsyncClient(timeout=10.0) as client:
                # Try v3 first, then v2, then v1
                for api_version in ["v3", "v2", "v1"]:
                    url = f"{base_url}/api/{api_version}/movie/{radarr_id}"
                    try:
                        resp = await client.get(url, headers=headers)
                        if resp.status_code == 200:
                            movie = resp.json()
                            has_file = movie.get("hasFile", False)

                            # Check download status
                            if has_file:
                                return "available", True

                            # Check if downloading
                            downloaded = movie.get("downloaded", False)
                            monitored = movie.get("monitored", False)

                            if downloaded:
                                return "available", True
                            elif monitored:
                                # Check queue to see if actively downloading
                                queue_url = f"{base_url}/api/{api_version}/queue"
                                queue_resp = await client.get(queue_url, headers=headers)
                                if queue_resp.status_code == 200:
                                    queue = queue_resp.json()
                                    records = queue.get("records", [])
                                    for record in records:
                                        if record.get("movieId") == radarr_id:
                                            return "downloading", False

                                return "pending", False
                            else:
                                return "failed", False
                        elif resp.status_code == 404:
                            continue
                    except Exception as e:
                        logger.debug("Radarr API %s check failed: %s", api_version, e)
                        continue

                return "unknown", False

        except Exception as e:
            logger.error("❌ Failed to check Radarr movie status: %s", e)
            return "unknown", False

    async def check_sonarr_series_status(self, sonarr_id: int) -> tuple[str, bool]:
        """
        Check if a TV series has any downloaded episodes in Sonarr

        Returns:
            (status, has_episodes) tuple
            status: "downloading", "available", "pending", "failed"
            has_episodes: True if at least one episode is downloaded
        """
        if not (SONARR_URL and SONARR_API_KEY):
            return "unknown", False

        try:
            base_url = SONARR_URL.rstrip('/')
            headers = {"X-Api-Key": SONARR_API_KEY}

            async with AsyncClient(timeout=10.0) as client:
                # Try v3 first, then v2, then v1
                for api_version in ["v3", "v2", "v1"]:
                    url = f"{base_url}/api/{api_version}/series/{sonarr_id}"
                    try:
                        resp = await client.get(url, headers=headers)
                        if resp.status_code == 200:
                            series = resp.json()

                            # Check if series has any episodes with files
                            statistics = series.get("statistics", {})
                            episode_file_count = statistics.get("episodeFileCount", 0)
                            has_episodes = episode_file_count > 0

                            if has_episodes:
                                return "available", True

                            # Check if monitored
                            monitored = series.get("monitored", False)
                            if monitored:
                                # Check queue for active downloads
                                queue_url = f"{base_url}/api/{api_version}/queue"
                                queue_resp = await client.get(queue_url, headers=headers)
                                if queue_resp.status_code == 200:
                                    queue = queue_resp.json()
                                    records = queue.get("records", [])
                                    for record in records:
                                        if record.get("seriesId") == sonarr_id:
                                            return "downloading", False

                                return "pending", False
                            else:
                                return "failed", False
                        elif resp.status_code == 404:
                            continue
                    except Exception as e:
                        logger.debug("Sonarr API %s check failed: %s", api_version, e)
                        continue

                return "unknown", False

        except Exception as e:
            logger.error("❌ Failed to check Sonarr series status: %s", e)
            return "unknown", False

    async def check_all_pending_requests(self, bot: Bot):
        """
        Check status of all pending requests and send notifications for completed ones

        This should be called periodically by a scheduler
        """
        pending = self.get_pending_requests()

        if not pending:
            logger.debug("📭 No pending requests to check")
            return

        # Filter out unreleased content - no point checking for them
        pending_to_check = []
        skipped_unreleased = 0
        for request in pending:
            release_date = request.get("release_date")
            if release_date and self.is_release_date_future(release_date):
                # Update status to unreleased if not already
                if request.get("status") != "unreleased":
                    self.update_request_status(request["id"], "unreleased")
                skipped_unreleased += 1
            else:
                # If it was unreleased but now the date has passed, set back to pending
                if request.get("status") == "unreleased":
                    self.update_request_status(request["id"], "pending")
                    logger.info("📅 Request %s is now released, starting to check for availability", request.get("title"))
                pending_to_check.append(request)

        if skipped_unreleased > 0:
            logger.debug("⏭️ Skipped %d unreleased requests", skipped_unreleased)

        if not pending_to_check:
            logger.debug("📭 No released pending requests to check")
            return

        # Quick connectivity check before attempting full check
        # This avoids spamming APIs when the server is offline
        try:
            if RADARR_URL or SONARR_URL:
                test_url = (RADARR_URL or SONARR_URL).rstrip('/')
                async with AsyncClient(timeout=5.0) as client:
                    try:
                        # Quick ping to see if services are reachable
                        await client.get(f"{test_url}/ping", timeout=5.0)
                    except Exception:
                        logger.debug("⏸️ Radarr/Sonarr unreachable, skipping request check (server may be offline)")
                        return
        except Exception:
            pass  # If we can't test connectivity, proceed anyway

        logger.info("🔍 Checking %d pending requests", len(pending_to_check))
        notifications_sent = 0

        for request in pending_to_check:
            try:
                request_id = request["id"]
                media_type = request["media_type"]
                title = request["title"]
                user_id = request["user_id"]
                username = request.get("username", "Unknown")

                # Check status based on media type
                if media_type == "movie":
                    radarr_id = request.get("radarr_id")
                    if not radarr_id:
                        continue

                    status, has_file = await self.check_radarr_movie_status(radarr_id)

                    # If status is unknown, the movie was removed from Radarr - remove the request
                    if status == "unknown":
                        self.remove_request(request_id)
                        logger.info("🗑️ Auto-removed request '%s' - no longer in Radarr", title)
                        continue

                    # Update status
                    self.update_request_status(request_id, status)

                    # Send notification if available
                    if has_file and status == "available":
                        # Notify all subscribers
                        subscribers = request.get("subscribers", [{"user_id": user_id, "username": username}])
                        for subscriber in subscribers:
                            await self.send_availability_notification(
                                bot, subscriber["user_id"], subscriber["username"], title, media_type
                            )
                        self.update_request_status(request_id, status, notified=True)
                        notifications_sent += 1

                elif media_type == "tv":
                    sonarr_id = request.get("sonarr_id")
                    if not sonarr_id:
                        continue

                    status, has_episodes = await self.check_sonarr_series_status(sonarr_id)

                    # If status is unknown, the series was removed from Sonarr - remove the request
                    if status == "unknown":
                        self.remove_request(request_id)
                        logger.info("🗑️ Auto-removed request '%s' - no longer in Sonarr", title)
                        continue

                    # Update status
                    self.update_request_status(request_id, status)

                    # Send notification if available
                    if has_episodes and status == "available":
                        # Notify all subscribers
                        subscribers = request.get("subscribers", [{"user_id": user_id, "username": username}])
                        for subscriber in subscribers:
                            await self.send_availability_notification(
                                bot, subscriber["user_id"], subscriber["username"], title, media_type
                            )
                        self.update_request_status(request_id, status, notified=True)
                        notifications_sent += 1

            except Exception as e:
                logger.error("❌ Error checking request %s: %s", request.get("id"), e)
                continue

        if notifications_sent > 0:
            logger.info("📬 Sent %d availability notifications", notifications_sent)

    async def send_availability_notification(self, bot: Bot, user_id: int,
                                            username: str, title: str, media_type: str):
        """Send notification to user that their requested content is available"""
        try:
            from utils.helpers import escape_md

            media_emoji = "🎬" if media_type == "movie" else "📺"
            media_name = "movie" if media_type == "movie" else "series"

            message = (
                f"✅ *Request Available\\!*\n\n"
                f"{media_emoji} Your requested {media_name} *{escape_md(title)}* "
                f"is now available on Plex\\!\n\n"
                f"Happy watching\\! 🍿"
            )

            # Send to bot topic and mention user
            from telegram.constants import ParseMode

            await bot.send_message(
                chat_id=GROUP_CHAT_ID,
                text=f"@{username} {message}" if username != "Unknown" else message,
                message_thread_id=BOT_TOPIC_ID,
                parse_mode=ParseMode.MARKDOWN_V2,
                disable_notification=SILENT_NOTIFICATIONS
            )

            logger.info("📬 Sent availability notification for '%s' to user %s", title, username)

        except Exception as e:
            logger.error("❌ Failed to send availability notification: %s", e)

    async def check_radarr_indexer_results(self, radarr_id: int) -> Tuple[int, bool]:
        """
        Trigger a search in Radarr and check if any releases are found

        Returns:
            (result_count, search_triggered) tuple
        """
        if not (RADARR_URL and RADARR_API_KEY):
            return 0, False

        try:
            base_url = RADARR_URL.rstrip('/')
            headers = {"X-Api-Key": RADARR_API_KEY, "Content-Type": "application/json"}

            async with AsyncClient(timeout=30.0) as client:
                for api_version in ["v3", "v2", "v1"]:
                    try:
                        # Trigger a movie search command
                        command_url = f"{base_url}/api/{api_version}/command"
                        command_data = {"name": "MoviesSearch", "movieIds": [radarr_id]}

                        resp = await client.post(command_url, headers=headers, json=command_data)
                        if resp.status_code in [200, 201]:
                            logger.info("🔍 Triggered Radarr search for movie ID %d", radarr_id)

                            # Wait a moment for search to process
                            import asyncio
                            await asyncio.sleep(3)

                            # Check releases endpoint for results
                            release_url = f"{base_url}/api/{api_version}/release?movieId={radarr_id}"
                            release_resp = await client.get(release_url, headers=headers)

                            if release_resp.status_code == 200:
                                releases = release_resp.json()
                                result_count = len(releases)
                                logger.info("🔍 Found %d releases for movie ID %d", result_count, radarr_id)
                                return result_count, True

                            return 0, True
                        elif resp.status_code == 404:
                            continue
                    except Exception as e:
                        logger.debug("Radarr search API %s failed: %s", api_version, e)
                        continue

                return 0, False

        except Exception as e:
            logger.error("❌ Failed to check Radarr indexer results: %s", e)
            return 0, False

    async def check_sonarr_indexer_results(self, sonarr_id: int) -> Tuple[int, bool]:
        """
        Trigger a search in Sonarr and check if any releases are found

        Returns:
            (result_count, search_triggered) tuple
        """
        if not (SONARR_URL and SONARR_API_KEY):
            return 0, False

        try:
            base_url = SONARR_URL.rstrip('/')
            headers = {"X-Api-Key": SONARR_API_KEY, "Content-Type": "application/json"}

            async with AsyncClient(timeout=30.0) as client:
                for api_version in ["v3", "v2", "v1"]:
                    try:
                        # Trigger a series search command
                        command_url = f"{base_url}/api/{api_version}/command"
                        command_data = {"name": "SeriesSearch", "seriesId": sonarr_id}

                        resp = await client.post(command_url, headers=headers, json=command_data)
                        if resp.status_code in [200, 201]:
                            logger.info("🔍 Triggered Sonarr search for series ID %d", sonarr_id)

                            # Wait a moment for search to process
                            import asyncio
                            await asyncio.sleep(3)

                            # Check releases endpoint for results
                            release_url = f"{base_url}/api/{api_version}/release?seriesId={sonarr_id}"
                            release_resp = await client.get(release_url, headers=headers)

                            if release_resp.status_code == 200:
                                releases = release_resp.json()
                                result_count = len(releases)
                                logger.info("🔍 Found %d releases for series ID %d", result_count, sonarr_id)
                                return result_count, True

                            return 0, True
                        elif resp.status_code == 404:
                            continue
                    except Exception as e:
                        logger.debug("Sonarr search API %s failed: %s", api_version, e)
                        continue

                return 0, False

        except Exception as e:
            logger.error("❌ Failed to check Sonarr indexer results: %s", e)
            return 0, False


# Global tracker instance
request_tracker = RequestTracker()
