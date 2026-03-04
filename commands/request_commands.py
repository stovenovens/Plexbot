"""
Request system commands
Handles movie and TV series requests via TMDB search with Sonarr/Radarr integration
Similar to Searcharr but simplified for group chat use without authentication
"""

import re
import logging
from datetime import datetime
from telegram.ext import CallbackContext
from telegram.constants import ParseMode
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from httpx import AsyncClient
from rapidfuzz import fuzz
from rapidfuzz.distance import Levenshtein as _Lev
from spellchecker import SpellChecker

_spell = SpellChecker()

from config import (
    TMDB_BEARER_TOKEN, SONARR_URL, SONARR_API_KEY, RADARR_URL, RADARR_API_KEY,
    MELBOURNE_TZ, GROUP_CHAT_ID, BOT_TOPIC_ID, SILENT_NOTIFICATIONS,
    TAUTILLI_URL, TAUTILLI_API_KEY
)
from utils.helpers import send_command_response, escape_md

logger = logging.getLogger(__name__)

# Network keyword → typical origin countries for result re-ranking.
# Sorted longest-first so "bbc one" is matched before "bbc".
NETWORK_QUALIFIERS = {
    "bbc one":       ["GB"],
    "bbc two":       ["GB"],
    "bbc three":     ["GB"],
    "bbc four":      ["GB"],
    "bbc america":   ["GB", "US"],
    "bbc":           ["GB"],
    "itv1":          ["GB"],
    "itv2":          ["GB"],
    "itv":           ["GB"],
    "channel 4":     ["GB"],
    "channel4":      ["GB"],
    "channel 5":     ["GB"],
    "channel5":      ["GB"],
    "sky atlantic":  ["GB"],
    "sky":           ["GB"],
    "prime video":   [],
    "apple tv+":     [],
    "apple tv":      [],
    "disney+":       [],
    "disney":        [],
    "paramount+":    ["US"],
    "paramount":     ["US"],
    "hbo max":       ["US"],
    "hbo":           ["US"],
    "netflix":       [],
    "amazon":        [],
    "hulu":          ["US"],
    "peacock":       ["US"],
    "showtime":      ["US"],
    "fx":            ["US"],
    "amc":           ["US"],
    "abc":           ["US"],
    "nbc":           ["US"],
    "cbs":           ["US"],
    "fox":           ["US"],
    "pbs":           ["US"],
    "max":           ["US"],
    "abc australia": ["AU"],
    "network ten":   ["AU"],
    "stan":          ["AU"],
}

# Country/origin keyword → ISO 3166-1 alpha-2 code
COUNTRY_QUALIFIERS = {
    "british":    "GB",
    "uk":         "GB",
    "australian": "AU",
    "aussie":     "AU",
    "canadian":   "CA",
    "irish":      "IE",
    "korean":     "KR",
    "k-drama":    "KR",
    "kdrama":     "KR",
    "japanese":   "JP",
    "anime":      "JP",
    "french":     "FR",
    "german":     "DE",
    "spanish":    "ES",
    "swedish":    "SE",
    "norwegian":  "NO",
    "danish":     "DK",
    "dutch":      "NL",
    "italian":    "IT",
}

# Articles to try stripping in fallback searches
_ARTICLES = re.compile(r"^(the|a|an)\s+", re.IGNORECASE)


def spell_correct_query(query: str) -> str | None:
    """
    Attempt to spell-correct a query word by word.
    Only accepts corrections within Levenshtein edit distance 1 (single-char fix).
    This catches missing/extra letters ("stanger"→"stranger", "interstellr"→"interstellar")
    while rejecting severely garbled words that would produce wrong results.
    Returns the corrected string if anything changed, else None.
    """
    words = query.split()
    corrected = []
    changed = False
    for word in words:
        if len(word) <= 3 or word.isdigit():
            corrected.append(word)
            continue
        suggestion = _spell.correction(word.lower())
        if suggestion and suggestion != word.lower():
            # Only accept if it's a single-character fix
            if _Lev.distance(word.lower(), suggestion) == 1:
                corrected.append(suggestion)
                changed = True
            else:
                corrected.append(word)
        else:
            corrected.append(word)
    return " ".join(corrected) if changed else None


def parse_query_qualifiers(query: str) -> dict:
    """
    Strip network/country/year hints from a search query.

    Returns:
        clean_query         – what to send to TMDB (qualifiers removed)
        preferred_countries – ISO codes inferred from network/country hints
        year                – 4-digit year if found, else None
    """
    clean = query.lower().strip()
    preferred_countries: set[str] = set()
    year = None

    # Extract year first so it doesn't interfere with other patterns
    m = re.search(r"\b(19|20)\d{2}\b", clean)
    if m:
        year = int(m.group())
        clean = (clean[:m.start()] + clean[m.end():]).strip()

    # Network qualifiers – longest match first
    for keyword in sorted(NETWORK_QUALIFIERS, key=len, reverse=True):
        if re.search(r"\b" + re.escape(keyword) + r"\b", clean):
            preferred_countries.update(NETWORK_QUALIFIERS[keyword])
            clean = re.sub(r"\b" + re.escape(keyword) + r"\b", "", clean).strip()
            break  # one network qualifier per query

    # Country qualifiers – longest match first
    for keyword, code in sorted(COUNTRY_QUALIFIERS.items(), key=lambda x: len(x[0]), reverse=True):
        if re.search(r"\b" + re.escape(keyword) + r"\b", clean):
            preferred_countries.add(code)
            clean = re.sub(r"\b" + re.escape(keyword) + r"\b", "", clean).strip()
            break

    clean = " ".join(clean.split())
    return {
        "clean_query": clean if clean else query,
        "preferred_countries": list(preferred_countries),
        "year": year,
    }


def rank_results(results: list, original_query: str, preferred_countries: list, year: int | None) -> list:
    """
    Score and re-rank TMDB results using:
      - rapidfuzz title similarity (handles typos & word-order differences)
      - origin_country match bonus
      - release year proximity bonus

    TMDB's own ranking is preserved for equal scores (stable sort).
    """
    query_lower = original_query.lower()

    def score(show):
        title = (show.get("name") or show.get("title") or "").lower()
        original_title = (show.get("original_name") or show.get("original_title") or "").lower()

        # Best of regular title vs original title
        similarity = max(
            fuzz.token_sort_ratio(query_lower, title),
            fuzz.token_sort_ratio(query_lower, original_title),
        )

        country_bonus = 0
        if preferred_countries:
            origin = show.get("origin_country", [])
            if any(c in origin for c in preferred_countries):
                country_bonus = 20

        year_bonus = 0
        if year is not None:
            air_date = show.get("first_air_date") or show.get("release_date") or ""
            if len(air_date) >= 4:
                try:
                    diff = abs(int(air_date[:4]) - year)
                    if diff == 0:
                        year_bonus = 10
                    elif diff <= 2:
                        year_bonus = 4
                except ValueError:
                    pass

        return similarity + country_bonus + year_bonus

    return sorted(results, key=score, reverse=True)


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

    async def smart_search_tv(self, raw_query: str) -> tuple[list, str | None, str]:
        """
        Search for TV series with qualifier stripping, fallback chain, and re-ranking.

        Returns (results, error, effective_query_used)
        effective_query_used is shown to the user so they know what was actually searched.
        """
        parsed = parse_query_qualifiers(raw_query)
        clean = parsed["clean_query"]
        preferred_countries = parsed["preferred_countries"]
        year = parsed["year"]

        # Build the fallback chain (deduplicated, preserving order)
        candidates: list[str] = []
        spell_corrected = spell_correct_query(clean)
        for q in [clean, raw_query, _ARTICLES.sub("", clean).strip(), spell_corrected]:
            if not q:
                continue
            q = q.strip()
            if q and q not in candidates:
                candidates.append(q)

        results = []
        used_query = clean
        last_error = None

        for attempt in candidates:
            results, last_error = await self.search_tmdb_tv(attempt)
            if last_error:
                return [], last_error, attempt
            if results:
                used_query = attempt
                logger.info("📺 TV search succeeded with query '%s' (raw: '%s')", attempt, raw_query)
                break
            logger.info("📺 TV search returned no results for '%s', trying next fallback", attempt)

        if not results:
            return [], None, raw_query

        ranked = rank_results(results, clean, preferred_countries, year)
        return ranked, None, used_query

    async def smart_search_movie(self, raw_query: str) -> tuple[list, str | None, str]:
        """
        Search for movies with qualifier stripping, fallback chain, and re-ranking.

        Returns (results, error, effective_query_used)
        """
        parsed = parse_query_qualifiers(raw_query)
        clean = parsed["clean_query"]
        preferred_countries = parsed["preferred_countries"]
        year = parsed["year"]

        candidates: list[str] = []
        spell_corrected = spell_correct_query(clean)
        for q in [clean, raw_query, _ARTICLES.sub("", clean).strip(), spell_corrected]:
            if not q:
                continue
            q = q.strip()
            if q and q not in candidates:
                candidates.append(q)

        results = []
        used_query = clean
        last_error = None

        for attempt in candidates:
            results, last_error = await self.search_tmdb_movie(attempt)
            if last_error:
                return [], last_error, attempt
            if results:
                used_query = attempt
                logger.info("🎬 Movie search succeeded with query '%s' (raw: '%s')", attempt, raw_query)
                break
            logger.info("🎬 Movie search returned no results for '%s', trying next fallback", attempt)

        if not results:
            return [], None, raw_query

        ranked = rank_results(results, clean, preferred_countries, year)
        return ranked, None, used_query

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

                return None, "Server is offline. Please use /on to wake it up, then try again."

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

                return None, "Server is offline. Please use /on to wake it up, then try again."

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

                return None, "Server is offline. Please use /on to wake it up, then try again."

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

                return None, "Server is offline. Please use /on to wake it up, then try again."

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

    async def get_tvdb_id_from_tmdb(self, tmdb_id: int):
        """Get TVDB ID for a TV show from TMDB external_ids endpoint"""
        if not TMDB_BEARER_TOKEN:
            return None

        try:
            headers = {"Authorization": f"Bearer {TMDB_BEARER_TOKEN}", "accept": "application/json"}
            async with AsyncClient() as client:
                resp = await client.get(
                    f"https://api.themoviedb.org/3/tv/{tmdb_id}/external_ids",
                    headers=headers
                )
                if resp.status_code == 200:
                    data = resp.json()
                    tvdb_id = data.get("tvdb_id")
                    if tvdb_id:
                        logger.debug("Got TVDB ID %s for TMDB ID %s", tvdb_id, tmdb_id)
                        return tvdb_id
                return None
        except Exception as e:
            logger.debug("Failed to get TVDB ID from TMDB: %s", e)
            return None

    async def check_exists_in_plex(self, title: str, year: int = None, media_type: str = "movie"):
        """
        Check if content already exists in Plex library via Tautulli API

        Args:
            title: The title to search for
            year: Optional release year for more accurate matching
            media_type: "movie" or "show"

        Returns:
            (exists: bool, match_info: dict or None)
        """
        if not (TAUTILLI_URL and TAUTILLI_API_KEY):
            return False, None

        try:
            base_url = TAUTILLI_URL.rstrip('/')

            async with AsyncClient(timeout=10.0) as client:
                # Use Tautulli's search API to find content in library
                search_url = f"{base_url}/api/v2"
                params = {
                    "apikey": TAUTILLI_API_KEY,
                    "cmd": "search",
                    "query": title,
                    "limit": 20
                }

                resp = await client.get(search_url, params=params)

                if resp.status_code != 200:
                    logger.info("🔍 Plex check: Tautulli search returned %d", resp.status_code)
                    return False, None

                result = resp.json()

                if result.get("response", {}).get("result") != "success":
                    logger.info("🔍 Plex check: Tautulli search not successful")
                    return False, None

                # Get search results - handle various response structures
                data = result.get("response", {}).get("data", {})

                logger.info("🔍 Plex check: Searching for '%s' (%s) - response data type: %s, keys: %s",
                           title, media_type, type(data).__name__,
                           list(data.keys()) if isinstance(data, dict) else "N/A")

                # Handle Tautulli search response format
                # results_list is a dict keyed by media type: {"movie": [...], "show": [...], "episode": [...]}
                search_results = []
                if isinstance(data, dict):
                    results_list = data.get("results_list", {})

                    if isinstance(results_list, dict):
                        # Tautulli format: {"movie": [...], "show": [...], "episode": [...], ...}
                        # Flatten all media type lists into one list, tagging each item with its type
                        for result_type, items in results_list.items():
                            if isinstance(items, list):
                                for item in items:
                                    if isinstance(item, dict):
                                        # Ensure media_type is set from the key if not present
                                        if "media_type" not in item:
                                            item["media_type"] = result_type
                                        search_results.append(item)
                    elif isinstance(results_list, list):
                        # Fallback: results_list is a flat list
                        search_results = [r for r in results_list if isinstance(r, dict)]

                elif isinstance(data, list):
                    search_results = [r for r in data if isinstance(r, dict)]

                logger.info("🔍 Plex check: Found %d search results for '%s'", len(search_results), title)

                if not search_results:
                    return False, None

                # Normalize the search title for comparison
                search_title_lower = title.lower().strip()

                for item in search_results:
                    # Skip if item is not a dictionary (could be string in some responses)
                    if not isinstance(item, dict):
                        logger.info("🔍 Plex check: Skipping non-dict result: %s", type(item))
                        continue

                    item_title = item.get("title", "").lower().strip()
                    item_year = item.get("year")
                    item_media_type = item.get("media_type", "").lower()

                    logger.info("🔍 Plex check: Comparing - search='%s' (%s) vs result='%s' (%s, type=%s)",
                               title.lower().strip(), media_type, item_title, item_year, item_media_type)

                    # Map Tautulli media types to our types
                    # Tautulli uses: movie, show, season, episode, artist, album, track
                    # Only match at the correct level - never let an episode/season result
                    # satisfy a show-level check, otherwise short titles like "Reunion"
                    # match episode titles like "Season 3 Reunion Special"
                    type_match = False
                    if media_type == "movie" and item_media_type == "movie":
                        type_match = True
                    elif media_type == "show" and item_media_type == "show":
                        type_match = True

                    if not type_match:
                        continue

                    # Check title match using fuzzy similarity rather than substring containment.
                    # Substring checks are too loose - "reunion" matches "season 3 reunion special".
                    # Strip leading articles before comparing so "The Reunion" == "Reunion".
                    norm_search = _ARTICLES.sub("", search_title_lower).strip()
                    norm_item   = _ARTICLES.sub("", item_title).strip()
                    similarity = fuzz.token_sort_ratio(norm_search, norm_item)
                    title_match = similarity >= 85

                    if title_match:
                        # If we have a year, verify it matches (allow 1 year difference)
                        if year and item_year:
                            try:
                                if abs(int(item_year) - int(year)) <= 1:
                                    logger.info("✅ Found '%s' (%s) in Plex library", item.get("title"), item_year)
                                    return True, item
                            except (ValueError, TypeError):
                                pass
                        elif not year:
                            # No year provided, title match is enough
                            logger.info("✅ Found '%s' in Plex library", item.get("title"))
                            return True, item
                        else:
                            # Year provided but item has no year - still accept if title matches well
                            if item_title == search_title_lower:
                                logger.info("✅ Found '%s' in Plex library (exact title match)", item.get("title"))
                                return True, item

                logger.info("🔍 Plex check: No match found for '%s' in %d results", title, len(search_results))
                return False, None

        except Exception as e:
            logger.error("❌ Plex library check failed: %s", e)
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
    
    def create_movie_keyboard(self, movie: dict, index: int, total: int, search_id: str,
                               already_in_radarr: bool = False, already_on_plex: bool = False):
        """Create inline keyboard for movie result

        Args:
            movie: Movie data dict
            index: Current result index
            total: Total results
            search_id: Search session ID
            already_in_radarr: True if movie exists in Radarr
            already_on_plex: True if movie exists in Plex library
        """
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

        # Add/Already Added button - Plex check takes priority
        action_row = []
        if already_on_plex:
            action_row.append(InlineKeyboardButton("✅ Already on Plex!", callback_data="already_on_plex"))
        elif already_in_radarr:
            action_row.append(InlineKeyboardButton("✅ Already in Radarr!", callback_data="already_added"))
        else:
            if RADARR_URL and RADARR_API_KEY:
                action_row.append(InlineKeyboardButton("➕ Add Movie", callback_data=f"add_movie_{search_id}_{index}"))
            else:
                action_row.append(InlineKeyboardButton("❌ Radarr Not Configured", callback_data="not_configured"))

        action_row.append(InlineKeyboardButton("❌ Cancel", callback_data=f"cancel_search_{search_id}"))
        keyboard.append(action_row)

        return InlineKeyboardMarkup(keyboard)
    
    def create_tv_keyboard(self, show: dict, index: int, total: int, search_id: str,
                            already_in_sonarr: bool = False, already_on_plex: bool = False):
        """Create inline keyboard for TV show result

        Args:
            show: TV show data dict
            index: Current result index
            total: Total results
            search_id: Search session ID
            already_in_sonarr: True if show exists in Sonarr
            already_on_plex: True if show exists in Plex library
        """
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

        # Add/Already Added button - Plex check takes priority
        action_row = []
        if already_on_plex:
            action_row.append(InlineKeyboardButton("✅ Already on Plex!", callback_data="already_on_plex"))
        elif already_in_sonarr:
            action_row.append(InlineKeyboardButton("✅ Already in Sonarr!", callback_data="already_added"))
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
        if BOT_TOPIC_ID and update.message and update.message.message_thread_id != BOT_TOPIC_ID:
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

        results, error, used_query = await request_manager.smart_search_movie(query)

        if error:
            await send_command_response(update, context, f"❌ Search failed: {escape_md(error)}", parse_mode=ParseMode.MARKDOWN_V2)
            return

        if not results:
            await send_command_response(update, context, f"❌ No movies found for: *{escape_md(query)}*", parse_mode=ParseMode.MARKDOWN_V2)
            return

        if used_query.lower() != query.lower():
            logger.info("🎬 Movie search used fallback query '%s' for raw '%s'", used_query, query)

        # Store search results
        search_id = f"movie_{user.id}_{int(datetime.now().timestamp())}"
        request_manager.active_searches[search_id] = {
            "type": "movie",
            "query": query,
            "results": results,
            "user_id": user.id,
            "current_index": 0
        }

        # Check if first result already exists
        first_movie = results[0]
        tmdb_id = first_movie.get("id")
        title = first_movie.get("title", "")
        year = None
        if first_movie.get("release_date"):
            try:
                year = int(first_movie["release_date"][:4])
            except (ValueError, IndexError):
                pass

        # Check Plex first (most authoritative - content is actually available)
        already_on_plex = False
        on_plex, _ = await request_manager.check_exists_in_plex(title, year, "movie")
        already_on_plex = on_plex

        # Then check Radarr (content is being managed/downloaded)
        already_in_radarr = False
        if tmdb_id and not already_on_plex:
            exists, _ = await request_manager.check_movie_exists_in_radarr(tmdb_id)
            already_in_radarr = exists

        # Format and send first result
        msg = request_manager.format_movie_result(first_movie, 0, len(results))
        keyboard = request_manager.create_movie_keyboard(
            first_movie, 0, len(results), search_id,
            already_in_radarr=already_in_radarr, already_on_plex=already_on_plex
        )
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

        results, error, used_query = await request_manager.smart_search_tv(query)

        if error:
            await send_command_response(update, context, f"❌ Search failed: {escape_md(error)}", parse_mode=ParseMode.MARKDOWN_V2)
            return

        if not results:
            await send_command_response(update, context, f"❌ No TV series found for: *{escape_md(query)}*", parse_mode=ParseMode.MARKDOWN_V2)
            return

        if used_query.lower() != query.lower():
            logger.info("📺 TV search used fallback query '%s' for raw '%s'", used_query, query)

        # Store search results
        search_id = f"tv_{user.id}_{int(datetime.now().timestamp())}"
        request_manager.active_searches[search_id] = {
            "type": "tv",
            "query": query,
            "results": results,
            "user_id": user.id,
            "current_index": 0
        }

        # Check if first result already exists
        first_show = results[0]
        name = first_show.get("name", "")
        year = None
        if first_show.get("first_air_date"):
            try:
                year = int(first_show["first_air_date"][:4])
            except (ValueError, IndexError):
                pass

        # Check Plex first (most authoritative - content is actually available)
        already_on_plex = False
        on_plex, _ = await request_manager.check_exists_in_plex(name, year, "show")
        already_on_plex = on_plex

        # Check Sonarr if not already on Plex (requires TVDB ID lookup from TMDB)
        already_in_sonarr = False
        if not already_on_plex:
            tmdb_id = first_show.get("id")
            if tmdb_id:
                tvdb_id = await request_manager.get_tvdb_id_from_tmdb(tmdb_id)
                if tvdb_id:
                    exists, _ = await request_manager.check_series_exists_in_sonarr(tvdb_id)
                    already_in_sonarr = exists

        # Format and send first result
        msg = request_manager.format_tv_result(first_show, 0, len(results))
        keyboard = request_manager.create_tv_keyboard(
            first_show, 0, len(results), search_id,
            already_in_sonarr=already_in_sonarr, already_on_plex=already_on_plex
        )
        poster_url = request_manager.get_poster_url(first_show.get("poster_path"))

        await send_command_response_with_markup(update, context, msg, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=keyboard, photo_url=poster_url)

    except Exception as e:
        logger.error("❌ TV series search command failed: %s", e)
        await send_command_response(update, context, f"❌ Search failed: {escape_md(str(e))}", parse_mode=ParseMode.MARKDOWN_V2)

# Alias commands
tv_command = series_command  # /tv is an alias for /series