"""
Recently Added notification system
Monitors Plex via Tautulli for new content and notifies the group
Skips content that was added via user requests (they already get notified)
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set
from httpx import AsyncClient
from telegram import Bot
from telegram.constants import ParseMode

from config import (
    TAUTILLI_URL, TAUTILLI_API_KEY,
    GROUP_CHAT_ID, BOT_TOPIC_ID, SILENT_NOTIFICATIONS
)
from utils.helpers import escape_md

logger = logging.getLogger(__name__)

# Storage file for tracking notified items
NOTIFIED_DB_FILE = Path(__file__).parent.parent / "data" / "notified_items.json"


class RecentlyAddedNotifier:
    """Monitors Plex for new content and sends notifications"""

    def __init__(self):
        self.notified_items = self._load_notified_items()

    def _ensure_data_dir(self):
        """Ensure data directory exists"""
        NOTIFIED_DB_FILE.parent.mkdir(parents=True, exist_ok=True)

    def _load_notified_items(self) -> Dict:
        """Load notified items from JSON file"""
        try:
            if NOTIFIED_DB_FILE.exists():
                with open(NOTIFIED_DB_FILE, 'r') as f:
                    data = json.load(f)
                    logger.info("📂 Loaded %d notified items", len(data.get('items', [])))
                    return data
            else:
                logger.info("📂 No existing notified items database found, starting fresh")
                return {"items": [], "last_check": None}
        except Exception as e:
            logger.error("❌ Failed to load notified items database: %s", e)
            return {"items": [], "last_check": None}

    def _save_notified_items(self):
        """Save notified items to JSON file"""
        try:
            self._ensure_data_dir()
            with open(NOTIFIED_DB_FILE, 'w') as f:
                json.dump(self.notified_items, f, indent=2)
            logger.debug("💾 Saved notified items database")
        except Exception as e:
            logger.error("❌ Failed to save notified items database: %s", e)

    def _get_notified_keys(self) -> Set[str]:
        """Get set of already notified item keys"""
        return {item.get("key") for item in self.notified_items.get("items", [])}

    def _add_notified_item(self, key: str, title: str, media_type: str):
        """Mark an item as notified"""
        self.notified_items["items"].append({
            "key": key,
            "title": title,
            "media_type": media_type,
            "notified_at": datetime.now().isoformat()
        })
        # Keep only last 500 items to prevent file growing too large
        if len(self.notified_items["items"]) > 500:
            self.notified_items["items"] = self.notified_items["items"][-500:]
        self._save_notified_items()

    def _is_user_request(self, title: str, year: Optional[int], media_type: str) -> bool:
        """
        Check if this content was added via user request.
        If so, they already got notified - skip the general notification.
        """
        from utils.request_tracker import request_tracker

        title_lower = title.lower().strip()

        for request in request_tracker.requests.get("requests", []):
            req_title = request.get("title", "").lower().strip()
            req_type = request.get("media_type", "")
            req_year = request.get("year")

            # Match type
            type_match = (
                (media_type == "movie" and req_type == "movie") or
                (media_type == "show" and req_type == "tv")
            )

            if not type_match:
                continue

            # Match title
            title_match = (
                req_title == title_lower or
                title_lower in req_title or
                req_title in title_lower
            )

            if title_match:
                # If we have years, check they match (allow 1 year difference)
                if year and req_year:
                    if abs(int(year) - int(req_year)) <= 1:
                        logger.debug("Skipping notification for '%s' - matches user request", title)
                        return True
                else:
                    logger.debug("Skipping notification for '%s' - matches user request", title)
                    return True

        return False

    async def fetch_recently_added(self, count: int = 20) -> List[Dict]:
        """
        Fetch recently added items from Tautulli

        Returns:
            List of recently added items
        """
        if not (TAUTILLI_URL and TAUTILLI_API_KEY):
            logger.warning("Tautulli not configured, cannot fetch recently added")
            return []

        try:
            base_url = TAUTILLI_URL.rstrip('/')

            async with AsyncClient(timeout=15.0) as client:
                url = f"{base_url}/api/v2"
                params = {
                    "apikey": TAUTILLI_API_KEY,
                    "cmd": "get_recently_added",
                    "count": count
                }

                resp = await client.get(url, params=params)

                if resp.status_code != 200:
                    logger.error("Tautulli recently added returned %d", resp.status_code)
                    return []

                result = resp.json()

                if result.get("response", {}).get("result") != "success":
                    logger.error("Tautulli recently added not successful")
                    return []

                data = result.get("response", {}).get("data", {})

                # Handle different response formats
                recently_added = []
                if isinstance(data, dict):
                    recently_added = data.get("recently_added", [])
                elif isinstance(data, list):
                    recently_added = data

                return recently_added

        except Exception as e:
            logger.error("❌ Failed to fetch recently added: %s", e)
            return []

    async def check_and_notify(self, bot: Bot):
        """
        Check for new content and send notifications.
        This should be called periodically by a scheduler.
        """
        recently_added = await self.fetch_recently_added(count=20)

        if not recently_added:
            logger.debug("📭 No recently added items to check")
            return

        notified_keys = self._get_notified_keys()
        new_items = []

        for item in recently_added:
            # Skip if item is not a dictionary (could be string in some responses)
            if not isinstance(item, dict):
                logger.debug("Skipping non-dict recently added item: %s", type(item))
                continue

            # Create unique key for this item
            rating_key = item.get("rating_key", "")
            media_type = item.get("media_type", "")

            # Skip seasons and episodes - we only notify for shows (series) and movies
            if media_type in ["season", "episode"]:
                # For episodes, we could optionally notify, but skip for now
                continue

            key = f"{media_type}_{rating_key}"

            # Skip if already notified
            if key in notified_keys:
                continue

            # Get item details
            title = item.get("title", "Unknown")
            year = item.get("year")

            # Skip if this was a user request (they already got notified)
            if self._is_user_request(title, year, media_type):
                # Mark as notified so we don't check again
                self._add_notified_item(key, title, media_type)
                continue

            new_items.append({
                "key": key,
                "title": title,
                "year": year,
                "media_type": media_type,
                "thumb": item.get("thumb"),
                "added_at": item.get("added_at")
            })

        # Send notifications for new items
        for item in new_items:
            await self._send_notification(bot, item)
            self._add_notified_item(item["key"], item["title"], item["media_type"])

        # Update last check time
        self.notified_items["last_check"] = datetime.now().isoformat()
        self._save_notified_items()

        if new_items:
            logger.info("📺 Sent %d new content notifications", len(new_items))

    async def _send_notification(self, bot: Bot, item: Dict):
        """Send notification for a newly added item"""
        try:
            title = item.get("title", "Unknown")
            year = item.get("year")
            media_type = item.get("media_type", "")

            # Format message
            if media_type == "movie":
                emoji = "🎬"
                type_name = "movie"
            else:
                emoji = "📺"
                type_name = "series"

            year_str = f" \\({year}\\)" if year else ""

            message = (
                f"{emoji} *New {type_name} added to Plex\\!*\n\n"
                f"*{escape_md(title)}{year_str}*\n\n"
                f"🍿 Now available to watch\\!"
            )

            await bot.send_message(
                chat_id=GROUP_CHAT_ID,
                text=message,
                message_thread_id=BOT_TOPIC_ID,
                parse_mode=ParseMode.MARKDOWN_V2,
                disable_notification=SILENT_NOTIFICATIONS
            )

            logger.info("📢 Sent notification for new %s: %s", media_type, title)

        except Exception as e:
            logger.error("❌ Failed to send new content notification: %s", e)

    def cleanup_old_items(self, days: int = 30):
        """Remove notified items older than specified days"""
        from datetime import timedelta
        cutoff = datetime.now() - timedelta(days=days)

        original_count = len(self.notified_items.get("items", []))
        self.notified_items["items"] = [
            item for item in self.notified_items.get("items", [])
            if datetime.fromisoformat(item.get("notified_at", datetime.now().isoformat())) > cutoff
        ]

        removed = original_count - len(self.notified_items["items"])
        if removed > 0:
            self._save_notified_items()
            logger.info("🧹 Cleaned up %d old notified items", removed)


# Global instance
recently_added_notifier = RecentlyAddedNotifier()
