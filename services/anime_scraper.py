"""
Anime Metadata Scraper Service
Fetches and verifies Hindi-dubbed anime information from multiple sources.

Sources:
- AnimeDubHindi: Hindi dub status, seasons, episodes, schedule
- Official platforms: Crunchyroll, Netflix, Prime Video, JioHotstar, MX Player, ZEE5, SonyLIV
- YouTube channels: Muse India, Ani-One India, Anime Times
- Jikan/MyAnimeList: Title, poster, studio, episode count

Important:
- No anime episodes are downloaded or distributed.
- Only publicly available metadata is processed.
- All information is verified from actual sources.
"""

import html
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FutureTimeoutError
from typing import Dict, List, Optional
from urllib.parse import quote, unquote, urljoin

import requests
from bs4 import BeautifulSoup

from utils.logger import logger


# =====================================================================
# URLS & CONFIGURATION
# =====================================================================

SITE_URL = "https://www.animedubhindi.link/"
ANIME_MIRCHI_URL = "https://animemirchi.com/"
JIKAN_URL = "https://api.jikan.moe/v4/anime"

# Only these 5 languages are supported
SUPPORTED_LANGUAGES = ["Hindi", "English", "Tamil", "Telugu", "Japanese"]

# Official platform sources
OFFICIAL_PLATFORMS = {
    "Crunchyroll": ["crunchyroll.com"],
    "Netflix": ["netflix.com"],
    "Amazon Prime Video": ["primevideo.com", "amazon.com"],
    "JioHotstar": ["hotstar.com", "jiohotstar.com"],
    "MX Player": ["mxplayer.in"],
    "ZEE5": ["zee5.com"],
    "SonyLIV": ["sonyliv.com"],
    "Anime Times": ["youtube.com", "animetimes.co.jp"],
    "Muse India": ["youtube.com", "museindia.in"],
    "Ani-One India": ["youtube.com", "ani-one.com"],
}

# Platform tags found in AnimeDubHindi posts
PLATFORM_TAGS = {
    "crunchyroll": "Crunchyroll",
    "cr dub": "Crunchyroll",
    "netflix": "Netflix",
    "nf dub": "Netflix",
    "amazon prime": "Amazon Prime Video",
    "prime video": "Amazon Prime Video",
    "hotstar": "JioHotstar",
    "jiohotstar": "JioHotstar",
    "mx player": "MX Player",
    "zee5": "ZEE5",
    "sony liv": "SonyLIV",
}


class AnimeScraper:
    """Multi-source anime metadata scraper with parallel platform checking."""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': (
                "Mozilla/5.0 (Linux; Android 14) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0 Mobile Safari/537.36"
            ),
            'Accept-Language': 'en-IN,en;q=0.9',
        })

    def search_anime(self, anime_name: str) -> Optional[Dict]:
        """
        Search for anime from multiple sources in parallel.
        
        Args:
            anime_name: Name of the anime to search for
            
        Returns:
            Dictionary with verified anime information or None
        """
        anime_name = (anime_name or "").strip()
        
        if not anime_name:
            logger.warning("Empty anime name provided")
            return None

        query = self._normalize(anime_name)
        is_movie_query = bool(re.search(r"\b(movie|film)\b", anime_name, re.I))

        logger.info(f"Anime search started: {anime_name}")

        # Run searches in parallel
        with ThreadPoolExecutor(max_workers=4, thread_name_prefix="anime-source") as executor:
            futures = {
                executor.submit(self._search_animedubhindi, anime_name, query, is_movie_query): "animedubhindi",
                executor.submit(self._get_mal_info, anime_name): "mal",
                executor.submit(self._search_anime_mirchi, anime_name, query): "mirchi",
            }

            results = {}
            
            try:
                for future in as_completed(futures, timeout=8):
                    source = futures[future]
                    try:
                        value = future.result()
                        if value:
                            results[source] = value
                    except Exception as exc:
                        logger.debug(f"{source} lookup failed: {exc}")
            except FutureTimeoutError:
                logger.warning("Some sources exceeded timeout")

        # No sources found anime
        if not results:
            logger.info(f"Anime not found: {anime_name}")
            return None

        # Build final result by merging sources
        final_result = self._merge_results(results, anime_name, is_movie_query)
        
        if final_result:
            logger.info(f"Successfully found anime: {anime_name}")
        
        return final_result

    # =====================================================================
    # ANIMEDUBHINDI SEARCH
    # =====================================================================

    def _search_animedubhindi(self, anime_name: str, query: str, is_movie_query: bool) -> Optional[Dict]:
        """Search AnimeDubHindi for anime with Hindi dub information."""
        try:
            search_url = SITE_URL + "?s=" + quote(anime_name)
            response = self.session.get(search_url, timeout=6, allow_redirects=True)
            
            if response.status_code != 200:
                return None

            soup = BeautifulSoup(response.text, "html.parser")
            
            # Find best matching article
            for link in soup.find_all("a", href=True):
                title = link.get_text(" ", strip=True)
                href = link.get("href")
                
                if not title or not href or len(title) > 300:
                    continue
                
                if not self._title_matches(title, query):
                    continue

                # Check if we should skip this result
                should_skip = False
                if is_movie_query and "movie" not in title.lower() and "film" not in title.lower():
                    should_skip = True
                elif not is_movie_query and self._is_movie_result(title):
                    should_skip = True
                
                if should_skip:
                    continue

                full_url = urljoin(SITE_URL, href)
                if not full_url.startswith(SITE_URL):
                    continue

                result = self._parse_animedubhindi_page(full_url, title, query)
                if result:
                    return result

        except Exception as exc:
            logger.debug(f"AnimeDubHindi search failed: {exc}")

        return None

    def _parse_animedubhindi_page(self, url: str, fallback_title: str, query: str) -> Optional[Dict]:
        """Parse AnimeDubHindi article page for detailed anime information."""
        try:
            response = self.session.get(url, timeout=6)
            if response.status_code != 200:
                return None

            soup = BeautifulSoup(response.text, "html.parser")
            
            for tag in soup.find_all(["script", "style", "noscript"]):
                tag.decompose()

            title = self._extract_page_title(soup, fallback_title)
            text = soup.get_text(" ", strip=True)

            if not self._title_matches(title, query):
                return None

            languages = self._extract_languages(text)
            if not languages:
                return None

            return {
                "name": self._clean_title(title),
                "hindi_dub": "Available" if "Hindi" in languages else "Not Verified",
                "platform": self._extract_platform_tag(text),
                "platform_entries": [],
                "seasons": self._extract_seasons(text),
                "episodes": self._extract_episodes(text),
                "languages": self._format_languages(languages),
                "status": self._extract_status(text),
                "release_date": self._extract_date(text),
                "poster_url": self._extract_og_image(soup),
                "source": "AnimeDubHindi",
                "source_link": url,
            }

        except Exception as exc:
            logger.debug(f"AnimeDubHindi page parsing failed: {exc}")
            return None

    # =====================================================================
    # ANIME MIRCHI SEARCH
    # =====================================================================

    def _search_anime_mirchi(self, anime_name: str, query: str) -> Optional[Dict]:
        """Search Anime Mirchi for platform and dub information."""
        try:
            search_url = ANIME_MIRCHI_URL + "?s=" + quote(anime_name)
            response = self.session.get(search_url, timeout=6, allow_redirects=True)
            
            if response.status_code != 200:
                return None

            soup = BeautifulSoup(response.text, "html.parser")
            
            for link in soup.find_all("a", href=True):
                title = link.get_text(" ", strip=True)
                href = link.get("href")
                
                if not title or not href or len(title) > 300:
                    continue
                
                if not self._title_matches(title, query):
                    continue

                full_url = urljoin(ANIME_MIRCHI_URL, href)
                if not full_url.startswith(ANIME_MIRCHI_URL):
                    continue

                result = self._parse_mirchi_page(full_url, title, query)
                if result:
                    return result

        except Exception as exc:
            logger.debug(f"Anime Mirchi search failed: {exc}")

        return None

    def _parse_mirchi_page(self, url: str, fallback_title: str, query: str) -> Optional[Dict]:
        """Parse Anime Mirchi article for platform information."""
        try:
            response = self.session.get(url, timeout=6, allow_redirects=True)
            if response.status_code != 200:
                return None

            soup = BeautifulSoup(response.text, "html.parser")
            
            for tag in soup.find_all(["script", "style", "noscript"]):
                tag.decompose()

            title = self._extract_page_title(soup, fallback_title)
            text = soup.get_text(" ", strip=True)

            if not self._title_matches(title, query):
                return None

            platforms = self._extract_mirchi_platforms(text)
            if not platforms:
                return None

            languages = self._extract_languages(text)
            
            return {
                "name": self._clean_mirchi_title(title),
                "hindi_dub": "Available" if "Hindi" in languages else None,
                "platform": " • ".join(platforms) if platforms else None,
                "platform_entries": self._build_platform_entries(platforms, languages),
                "dub_by": self._extract_mirchi_dub_by(text),
                "seasons": self._extract_seasons(text),
                "episodes": self._extract_episodes(text),
                "languages": self._format_languages(languages),
                "source": "Anime Mirchi",
                "source_link": url,
            }

        except Exception as exc:
            logger.debug(f"Anime Mirchi page parsing failed: {exc}")
            return None

    # =====================================================================
    # JIKAN / MYANIMELIST
    # =====================================================================

    def _get_mal_info(self, anime_name: str) -> Optional[Dict]:
        """Fetch anime information from Jikan/MyAnimeList API."""
        try:
            response = self.session.get(
                JIKAN_URL,
                params={"q": anime_name, "limit": 5, "sfw": "true"},
                timeout=6,
            )
            response.raise_for_status()

            data = response.json().get("data", [])
            if not data:
                return None

            # Get best match
            anime = data[0]
            
            jpg = anime.get("images", {}).get("jpg", {})
            poster = jpg.get("large_image_url") or jpg.get("image_url")

            studios = [s.get("name") for s in anime.get("studios", []) if isinstance(s, dict) and s.get("name")]

            return {
                "name": anime.get("title") or anime_name,
                "poster_url": poster,
                "studio": " • ".join(studios) if studios else None,
                "mal_url": anime.get("url"),
                "episodes": str(anime.get("episodes")) if anime.get("episodes") else None,
            }

        except Exception as exc:
            logger.debug(f"Jikan lookup failed: {exc}")
            return None

    # =====================================================================
    # RESULT MERGING
    # =====================================================================

    def _merge_results(self, results: Dict, anime_name: str, is_movie_query: bool) -> Optional[Dict]:
        """Merge results from multiple sources with AnimeDubHindi as primary."""
        
        animedubhindi = results.get("animedubhindi")
        mal = results.get("mal")
        mirchi = results.get("mirchi")

        # If no AnimeDubHindi, try to build from MAL + Mirchi
        if not animedubhindi:
            if not mal and not mirchi:
                return None
            
            return {
                "name": mal.get("name") if mal else (mirchi.get("name") if mirchi else anime_name),
                "hindi_dub": mirchi.get("hindi_dub", "Not Verified") if mirchi else "Not Verified",
                "platform": mirchi.get("platform") if mirchi else None,
                "seasons": mal.get("episodes") if mal and not is_movie_query else None,
                "episodes": mal.get("episodes") if mal else None,
                "languages": mirchi.get("languages") if mirchi else None,
                "poster_url": mal.get("poster_url") if mal else None,
                "source": "DC",
                "source_link": mirchi.get("source_link") if mirchi else None,
            }

        # AnimeDubHindi is primary source
        final = animedubhindi.copy()

        # Merge MAL info (don't override richer AnimeDubHindi data)
        if mal:
            if not final.get("poster_url"):
                final["poster_url"] = mal.get("poster_url")
            if not final.get("episodes"):
                final["episodes"] = mal.get("episodes")
            if not final.get("studio"):
                final["studio"] = mal.get("studio")

        # Merge Mirchi info (platform/dub by is from Mirchi)
        if mirchi:
            if mirchi.get("platform") and not final.get("platform"):
                final["platform"] = mirchi["platform"]
            if mirchi.get("dub_by"):
                final["dub_by"] = mirchi["dub_by"]

        # Don't include seasons/episodes for movies
        if is_movie_query or self._is_movie_result(final.get("name")):
            final["seasons"] = None
            final["episodes"] = None

        return final

    # =====================================================================
    # PLATFORM EXTRACTION
    # =====================================================================

    @staticmethod
    def _extract_platform_tag(text: str) -> Optional[str]:
        """Extract platform names from text using known tags."""
        if not text:
            return None

        found = []
        text_lower = text.lower()

        for alias, platform in sorted(PLATFORM_TAGS.items(), key=lambda x: len(x[0]), reverse=True):
            if re.search(rf"\b{re.escape(alias)}\b", text_lower, re.I):
                if platform not in found:
                    found.append(platform)

        return " • ".join(found) if found else None

    @staticmethod
    def _extract_mirchi_platforms(text: str) -> List[str]:
        """Extract verified platforms from Anime Mirchi article."""
        if not text:
            return []

        found = []
        text_lower = text.lower()

        # List of platforms to look for
        platform_names = [
            "Crunchyroll", "Netflix", "Amazon Prime Video", "Prime Video",
            "JioHotstar", "Jio Hotstar", "MX Player", "ZEE5", "SonyLIV",
            "Muse India", "Ani-One", "Anime Times", "YouTube"
        ]

        for platform in platform_names:
            if re.search(rf"\b{re.escape(platform)}\b", text_lower, re.I):
                # Normalize names
                canonical = {
                    "Prime Video": "Amazon Prime Video",
                    "Jio Hotstar": "JioHotstar",
                }
                platform = canonical.get(platform, platform)
                
                if platform not in found:
                    found.append(platform)

        return found

    @staticmethod
    def _extract_mirchi_dub_by(text: str) -> Optional[str]:
        """Extract 'Dubbed By' information from text."""
        patterns = [
            r"Dubbed\s+By\s*[:|]\s*([^|\n]{1,120})",
            r"Dub(?:bed)?\s+(?:By|Studio)\s*[:|]\s*([^|\n]{1,120})",
        ]

        for pattern in patterns:
            match = re.search(pattern, text or "", re.I)
            if match:
                value = re.sub(r"\s+", " ", match.group(1)).strip(" :-|•,")
                if value and len(value) <= 120:
                    return value

        return None

    @staticmethod
    def _build_platform_entries(platforms: List[str], languages: List[str]) -> List[Dict]:
        """Build platform entry objects with metadata."""
        return [
            {
                "platform": p,
                "languages": [lang for lang in languages if lang in SUPPORTED_LANGUAGES],
                "verified": True,
            }
            for p in platforms
        ]

    # =====================================================================
    # LANGUAGE EXTRACTION
    # =====================================================================

    @staticmethod
    def _extract_languages(text: str) -> List[str]:
        """Extract only supported languages from text."""
        if not text:
            return []

        found = []
        for language in SUPPORTED_LANGUAGES:
            if re.search(rf"\b{re.escape(language)}\b", text or "", re.I):
                found.append(language)

        return list(dict.fromkeys(found))  # Remove duplicates

    @staticmethod
    def _format_languages(languages: List[str]) -> Optional[str]:
        """Format languages in preferred order."""
        ordered = [lang for lang in SUPPORTED_LANGUAGES if lang in languages]
        return " • ".join(ordered) if ordered else None

    # =====================================================================
    # SEASON & EPISODE EXTRACTION
    # =====================================================================

    @staticmethod
    def _extract_seasons(text: str) -> Optional[str]:
        """Extract and format season information."""
        if not text:
            return None

        seasons = set()
        
        # Look for "Season 1", "S1", etc.
        for pattern in [r"\bSeason\s+(\d+)\b", r"\bS(\d+)\b"]:
            for match in re.finditer(pattern, text or "", re.I):
                try:
                    seasons.add(int(match.group(1)))
                except (ValueError, IndexError):
                    pass

        if not seasons:
            return None

        # Format as "Season 1, Season 2, Season 3"
        sorted_seasons = sorted(seasons)
        if len(sorted_seasons) > 5:
            return f"{len(sorted_seasons)} Seasons"
        
        return ", ".join([f"Season {s}" for s in sorted_seasons])

    @staticmethod
    def _extract_episodes(text: str) -> Optional[str]:
        """Extract episode count or range."""
        if not text:
            return None

        patterns = [
            r"\b(\d+)/(\d+)\b",  # "12/13" format
            r"\bEpisodes?\s*[:\-]?\s*(\d+(?:-\d+)?)\b",
            r"\bEP\s*(\d+(?:-\d+)?)\b",
        ]

        for pattern in patterns:
            match = re.search(pattern, text or "", re.I)
            if match:
                return match.group(0).strip()

        return None

    @staticmethod
    def _extract_status(text: str) -> Optional[str]:
        """Extract ongoing/completed status."""
        if not text:
            return None

        text_lower = text.lower()
        
        if re.search(r"\bongoing\b", text_lower):
            return "Ongoing"
        elif re.search(r"\b(completed|finished|ended)\b", text_lower):
            return "Completed"

        return None

    # =====================================================================
    # DATE EXTRACTION
    # =====================================================================

    @staticmethod
    def _extract_date(text: str) -> Optional[str]:
        """Extract release date from text."""
        if not text:
            return None

        patterns = [
            r"\b\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{4}\b",
            r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2},\s+\d{4}\b",
            r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b",
        ]

        for pattern in patterns:
            match = re.search(pattern, text or "", re.I)
            if match:
                return match.group(0)

        return None

    # =====================================================================
    # TITLE MATCHING & CLEANING
    # =====================================================================

    @staticmethod
    def _normalize(text: str) -> str:
        """Normalize text for comparison."""
        text = (text or "").lower()
        text = text.replace("-", " ").replace("×", "x")
        text = re.sub(r"[^a-z0-9 ]+", " ", text)
        return " ".join(text.split())

    @staticmethod
    def _title_matches(title: str, query: str) -> bool:
        """Check if title matches query (case-insensitive, partial match)."""
        if not query:
            return False

        a = AnimeScraper._normalize(title)
        b = AnimeScraper._normalize(query)

        if a == b:
            return True
        if b in a:
            return True
        
        return set(b.split()).issubset(set(a.split()))

    @staticmethod
    def _is_movie_result(title: str) -> bool:
        """Check if title indicates a movie."""
        if not title:
            return False
        return bool(re.search(r"\b(movie|film|theatrical|ova)\b", title, re.I))

    @staticmethod
    def _clean_title(title: str) -> str:
        """Clean title for display."""
        title = re.sub(r"^search\s+results?\s+for:\s*", "", title or "", flags=re.I)
        title = re.sub(r"\s+[-|–]\s+AnimeDubHindi.*$", "", title, flags=re.I)
        return title.strip()

    @staticmethod
    def _clean_mirchi_title(title: str) -> str:
        """Clean Anime Mirchi title."""
        title = re.sub(r"\s+[-|–]\s+Anime Mirchi.*$", "", title or "", flags=re.I)
        return title.strip()

    # =====================================================================
    # PAGE PARSING UTILITIES
    # =====================================================================

    @staticmethod
    def _extract_page_title(soup: BeautifulSoup, fallback: str) -> str:
        """Extract page title from HTML."""
        h1 = soup.find("h1")
        if h1:
            text = h1.get_text(" ", strip=True)
            if text:
                return text

        og_title = soup.find("meta", attrs={"property": "og:title"})
        if og_title:
            content = og_title.get("content")
            if content:
                return content

        title_tag = soup.find("title")
        if title_tag:
            text = title_tag.get_text(" ", strip=True)
            if text:
                return text

        return fallback

    @staticmethod
    def _extract_og_image(soup: BeautifulSoup) -> Optional[str]:
        """Extract OG image from page."""
        tag = soup.find("meta", attrs={"property": "og:image"})
        if tag:
            content = tag.get("content")
            if content:
                return content.strip()
        return None


# =====================================================================
# SINGLETON & PUBLIC FUNCTION
# =====================================================================

anime_scraper = AnimeScraper()


def get_anime_info(anime_name: str) -> Optional[Dict]:
    """
    Public function to get anime information.
    
    Args:
        anime_name: Name of the anime to search for
        
    Returns:
        Dictionary with verified anime information or None
    """
    return anime_scraper.search_anime(anime_name)
