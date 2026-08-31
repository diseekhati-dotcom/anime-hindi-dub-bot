"""
Anime information service.

Searches:
- AnimeDubHindi schedule/archive/search pages
- Jikan / MyAnimeList metadata

Returns:
- Anime name
- Hindi dub status
- Platform (only when explicitly found)
- Dub By (only when explicitly found)
- Studio
- Season
- Episode
- Languages
- Schedule
- Release date
- Poster

Important:
- No anime episodes are downloaded.
- No watch/download links are returned.
- Source URLs are not displayed by the bot.
"""

import re
from typing import Dict, Optional, List
from urllib.parse import quote, urljoin

import requests
from bs4 import BeautifulSoup

from utils.logger import logger


# =====================================================================
# URLS
# =====================================================================

SITE_URL = "https://www.animedubhindi.link/"
SCHEDULE_URL = "https://www.animedubhindi.link/schedule.php"
JIKAN_URL = "https://api.jikan.moe/v4/anime"


class AnimeScraper:
    """Live anime information lookup service."""

    def __init__(self) -> None:

        self.session = requests.Session()

        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/120.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        })

    # =================================================================
    # MAIN SEARCH
    # =================================================================

    def search_anime(
        self,
        anime_name: str
    ) -> Optional[Dict]:

        if not anime_name:
            return None

        anime_name = anime_name.strip()

        if not anime_name:
            return None

        logger.info(
            "Live anime search: %s",
            anime_name
        )

        query = self._normalize(
            anime_name
        )

        # -------------------------------------------------------------
        # 1. AnimeDubHindi schedule
        # -------------------------------------------------------------

        result = self._search_page(
            SCHEDULE_URL,
            query
        )

        # -------------------------------------------------------------
        # 2. AnimeDubHindi website search
        # -------------------------------------------------------------

        if not result:

            result = self._search_site(
                anime_name,
                query
            )

        # -------------------------------------------------------------
        # 3. Jikan / MAL
        # -------------------------------------------------------------

        mal_info = self._get_mal_info(
            anime_name
        )

        # -------------------------------------------------------------
        # Anime not found anywhere
        # -------------------------------------------------------------

        if not result and not mal_info:

            logger.info(
                "Anime not found anywhere: %s",
                anime_name
            )

            return None

        # -------------------------------------------------------------
        # If AnimeDubHindi found it
        # -------------------------------------------------------------

        if result:

            if mal_info:

                result["poster_url"] = (
                    mal_info.get(
                        "poster_url"
                    )
                )

                result["studio"] = (
                    mal_info.get(
                        "studio"
                    )
                )

                result["mal_url"] = (
                    mal_info.get(
                        "mal_url"
                    )
                )

            else:

                result["poster_url"] = None
                result["studio"] = None
                result["mal_url"] = None

            return result

        # -------------------------------------------------------------
        # If only Jikan found it
        #
        # This still lets users search ANY anime.
        # Hindi information is NOT guessed.
        # -------------------------------------------------------------

        return {
            "name": (
                mal_info.get(
                    "name"
                )
                or anime_name
            ),

            "hindi_dub": "Not Verified",

            "platform": None,

            "dub_by": None,

            "studio": mal_info.get(
                "studio"
            ),

            "hindi_details": None,

            "episodes": None,

            "season": None,

            "languages": None,

            "schedule": None,

            "release_date": None,

            "source": "MyAnimeList / Jikan",

            "source_link": None,

            "poster_url": mal_info.get(
                "poster_url"
            ),

            "mal_url": mal_info.get(
                "mal_url"
            ),
        }

    # =================================================================
    # GENERIC PAGE SEARCH
    # =================================================================

    def _search_page(
        self,
        url: str,
        query: str
    ) -> Optional[Dict]:

        try:

            response = self.session.get(
                url,
                timeout=20,
                allow_redirects=True
            )

            response.raise_for_status()

            soup = BeautifulSoup(
                response.text,
                "html.parser"
            )

            return self._find_anime(
                soup,
                query
            )

        except Exception as exc:

            logger.debug(
                "Page search failed %s: %s",
                url,
                exc
            )

            return None

    # =================================================================
    # ANIMEDUBHINDI SITE SEARCH
    # =================================================================

    def _search_site(
        self,
        anime_name: str,
        query: str
    ) -> Optional[Dict]:

        # Common WordPress-style search.
        search_url = (
            SITE_URL
            + "?s="
            + quote(anime_name)
        )

        try:

            response = self.session.get(
                search_url,
                timeout=20,
                allow_redirects=True
            )

            if response.status_code != 200:
                return None

            soup = BeautifulSoup(
                response.text,
                "html.parser"
            )

            # ---------------------------------------------------------
            # First: inspect search page itself
            # ---------------------------------------------------------

            result = self._find_anime(
                soup,
                query
            )

            if result:
                return result

            # ---------------------------------------------------------
            # Second: inspect matching article links
            # ---------------------------------------------------------

            links = soup.find_all(
                "a",
                href=True
            )

            visited = set()

            for link in links:

                title = link.get_text(
                    " ",
                    strip=True
                )

                href = link.get(
                    "href"
                )

                if not title or not href:
                    continue

                if len(title) > 250:
                    continue

                if not self._title_matches(
                    title,
                    query
                ):
                    continue

                full_url = urljoin(
                    SITE_URL,
                    href
                )

                if full_url in visited:
                    continue

                visited.add(
                    full_url
                )

                # Don't leave the AnimeDubHindi site.
                if not full_url.startswith(
                    SITE_URL
                ):
                    continue

                try:

                    article_response = (
                        self.session.get(
                            full_url,
                            timeout=15
                        )
                    )

                    if (
                        article_response.status_code
                        != 200
                    ):
                        continue

                    article_soup = (
                        BeautifulSoup(
                            article_response.text,
                            "html.parser"
                        )
                    )

                    result = self._find_anime(
                        article_soup,
                        query
                    )

                    if result:

                        # Keep source as name only.
                        result["source"] = (
                            "AnimeDubHindi"
                        )

                        result["source_link"] = None

                        return result

                except Exception:
                    continue

        except Exception as exc:

            logger.debug(
                "AnimeDubHindi search failed: %s",
                exc
            )

        return None

    # =================================================================
    # FIND ANIME IN PAGE
    # =================================================================

    def _find_anime(
        self,
        soup: BeautifulSoup,
        query: str
    ) -> Optional[Dict]:

        elements = soup.find_all(
            [
                "h1",
                "h2",
                "h3",
                "h4",
                "h5",
                "a",
                "strong",
                "b",
            ]
        )

        best_element = None

        # -------------------------------------------------------------
        # Find title
        # -------------------------------------------------------------

        for element in elements:

            title = element.get_text(
                " ",
                strip=True
            )

            if not title:
                continue

            if len(title) > 250:
                continue

            if self._title_matches(
                title,
                query
            ):

                best_element = element
                break

        if best_element is None:
            return None

        title = best_element.get_text(
            " ",
            strip=True
        )

        # -------------------------------------------------------------
        # Find useful information container
        # -------------------------------------------------------------

        container = best_element

        for _ in range(10):

            if container.parent is None:
                break

            container = container.parent

            text = container.get_text(
                " ",
                strip=True
            )

            if len(text) > 5000:
                continue

            useful = (
                re.search(
                    r"\bHindi\b",
                    text,
                    re.I
                )
                or re.search(
                    r"\bEpisode\b",
                    text,
                    re.I
                )
                or re.search(
                    r"\bEP\b",
                    text,
                    re.I
                )
                or re.search(
                    r"\bSeason\b",
                    text,
                    re.I
                )
                or re.search(
                    r"\bDubbed\b",
                    text,
                    re.I
                )
                or re.search(
                    r"\bPlatform\b",
                    text,
                    re.I
                )
            )

            if useful:
                break

        text = container.get_text(
            " ",
            strip=True
        )

        if len(text) > 5000:

            parent = best_element.parent

            if parent:

                text = parent.get_text(
                    " ",
                    strip=True
                )

        languages = (
            self._extract_languages(
                text
            )
        )

        clean_title = (
            self._clean_title(
                title
            )
        )

        return {
            "name": clean_title,

            "hindi_dub": (
                "Available"
                if "Hindi" in languages
                else "Not Mentioned"
            ),

            "platform": (
                self._extract_platform(
                    text
                )
            ),

            "dub_by": (
                self._extract_dub_by(
                    text
                )
            ),

            "studio": None,

            "hindi_details": (
                "Hindi language listed on "
                "AnimeDubHindi."
                if "Hindi" in languages
                else None
            ),

            "episodes": (
                self._extract_episode(
                    text
                )
            ),

            "season": (
                self._extract_season(
                    text
                )
            ),

            "languages": (
                " • ".join(languages)
                if languages
                else None
            ),

            "schedule": (
                self._extract_schedule(
                    text
                )
            ),

            "release_date": (
                self._extract_date(
                    text
                )
            ),

            "source": (
                "AnimeDubHindi"
            ),

            # Never display source URL.
            "source_link": None,

            "poster_url": None,

            "mal_url": None,
        }

    # =================================================================
    # PLATFORM
    # =================================================================

    @staticmethod
    def _extract_platform(
        text: str
    ) -> Optional[str]:

        platforms = [
            "Crunchyroll",
            "Netflix",
            "JioHotstar",
            "Jio Hotstar",
            "Amazon Prime Video",
            "Prime Video",
            "Sony YAY",
            "Sony Yay",
            "MX Player",
            "YouTube",
            "Disney+",
            "Disney Plus",
            "Animax",
        ]

        found = []

        for platform in platforms:

            if re.search(
                rf"\b{re.escape(platform)}\b",
                text,
                re.I
            ):

                found.append(
                    platform
                )

        if not found:
            return None

        return " • ".join(
            dict.fromkeys(
                found
            )
        )

    # =================================================================
    # DUB BY
    # =================================================================

    @staticmethod
    def _extract_dub_by(
        text: str
    ) -> Optional[str]:

        patterns = [

            r"Dubbed\s*by\s*[:\-]?\s*"
            r"([^|•\n]+)",

            r"Dub\s*by\s*[:\-]?\s*"
            r"([^|•\n]+)",

            r"Dubbing\s*by\s*[:\-]?\s*"
            r"([^|•\n]+)",

            r"Dubbing\s*Studio\s*[:\-]?\s*"
            r"([^|•\n]+)",

            r"Dub\s*Studio\s*[:\-]?\s*"
            r"([^|•\n]+)",
        ]

        for pattern in patterns:

            match = re.search(
                pattern,
                text,
                re.I
            )

            if match:

                value = (
                    match.group(1)
                    .strip()
                )

                value = re.sub(
                    r"\s+",
                    " ",
                    value
                )

                # Prevent accidentally returning huge text.
                if len(value) > 150:
                    value = value[:150].strip()

                if value:
                    return value

        return None

    # =================================================================
    # MAL / JIKAN
    # =================================================================

    def _get_mal_info(
        self,
        anime_name: str
    ) -> Optional[Dict]:

        try:

            response = self.session.get(
                JIKAN_URL,
                params={
                    "q": anime_name,
                    "limit": 10,
                    "sfw": "true",
                },
                timeout=20
            )

            response.raise_for_status()

            data = response.json().get(
                "data",
                []
            )

            if not data:
                return None

            query = self._normalize(
                anime_name
            )

            selected = None

            # ---------------------------------------------------------
            # Exact title
            # ---------------------------------------------------------

            for anime in data:

                for title in (
                    self._get_titles(
                        anime
                    )
                ):

                    if (
                        self._normalize(
                            title
                        )
                        == query
                    ):

                        selected = anime
                        break

                if selected:
                    break

            # ---------------------------------------------------------
            # Partial title
            # ---------------------------------------------------------

            if selected is None:

                for anime in data:

                    for title in (
                        self._get_titles(
                            anime
                        )
                    ):

                        normalized = (
                            self._normalize(
                                title
                            )
                        )

                        if (
                            query in normalized
                            or normalized in query
                        ):

                            selected = anime
                            break

                    if selected:
                        break

            if selected is None:
                selected = data[0]

            # ---------------------------------------------------------
            # Poster
            # ---------------------------------------------------------

            images = selected.get(
                "images",
                {}
            )

            jpg = images.get(
                "jpg",
                {}
            )

            poster = (
                jpg.get(
                    "large_image_url"
                )
                or jpg.get(
                    "image_url"
                )
            )

            # ---------------------------------------------------------
            # Studio
            # ---------------------------------------------------------

            studios = selected.get(
                "studios",
                []
            )

            studio_names = []

            for item in studios:

                if not isinstance(
                    item,
                    dict
                ):
                    continue

                studio_name = item.get(
                    "name"
                )

                if studio_name:
                    studio_names.append(
                        studio_name
                    )

            studio = None

            if studio_names:

                studio = " • ".join(
                    dict.fromkeys(
                        studio_names
                    )
                )

            return {
                "name": (
                    selected.get(
                        "title"
                    )
                    or anime_name
                ),

                "poster_url": poster,

                "studio": studio,

                "mal_url": selected.get(
                    "url"
                ),
            }

        except Exception as exc:

            logger.warning(
                "Jikan error for %s: %s",
                anime_name,
                exc
            )

            return None

    # =================================================================
    # TITLES
    # =================================================================

    @staticmethod
    def _get_titles(
        anime: Dict
    ) -> List[str]:

        titles = []

        for key in (
            "title",
            "title_english",
            "title_japanese",
        ):

            value = anime.get(
                key
            )

            if value:
                titles.append(
                    value
                )

        for item in anime.get(
            "titles",
            []
        ):

            if isinstance(
                item,
                dict
            ):

                value = item.get(
                    "title"
                )

                if value:
                    titles.append(
                        value
                    )

        return titles

    # =================================================================
    # NORMALIZE
    # =================================================================

    @staticmethod
    def _normalize(
        text: str
    ) -> str:

        text = text.lower()

        text = text.replace(
            "-",
            " "
        )

        text = re.sub(
            r"[^a-z0-9 ]+",
            " ",
            text
        )

        return " ".join(
            text.split()
        )

    # =================================================================
    # TITLE MATCH
    # =================================================================

    @staticmethod
    def _title_matches(
        title: str,
        query: str
    ) -> bool:

        title_normalized = (
            AnimeScraper._normalize(
                title
            )
        )

        query_normalized = (
            AnimeScraper._normalize(
                query
            )
        )

        if not query_normalized:
            return False

        if (
            title_normalized
            == query_normalized
        ):
            return True

        if (
            query_normalized
            in title_normalized
        ):
            return True

        query_words = set(
            query_normalized.split()
        )

        title_words = set(
            title_normalized.split()
        )

        return query_words.issubset(
            title_words
        )

    # =================================================================
    # CLEAN TITLE
    # =================================================================

    @staticmethod
    def _clean_title(
        title: str
    ) -> str:

        title = re.sub(
            r"\s+[-|–]\s+AnimeDubHindi.*$",
            "",
            title,
            flags=re.I
        )

        title = re.sub(
            r"\s+Hindi\s+Dub.*$",
            "",
            title,
            flags=re.I
        )

        return title.strip()

    # =================================================================
    # SEASON
    # =================================================================

    @staticmethod
    def _extract_season(
        text: str
    ) -> Optional[str]:

        patterns = [
            r"\bSeason\s*([0-9]+)\b",
            r"\bS([0-9]+)\b",
        ]

        for pattern in patterns:

            match = re.search(
                pattern,
                text,
                re.I
            )

            if match:

                return (
                    f"Season "
                    f"{match.group(1)}"
                )

        return None

    # =================================================================
    # EPISODE
    # =================================================================

    @staticmethod
    def _extract_episode(
        text: str
    ) -> Optional[str]:

        patterns = [
            r"\bEP\s*([0-9]+(?:-[0-9]+)?)\b",
            r"\bEpisode\s*([0-9]+(?:-[0-9]+)?)\b",
            r"\bEp\.\s*([0-9]+(?:-[0-9]+)?)\b",
        ]

        for pattern in patterns:

            match = re.search(
                pattern,
                text,
                re.I
            )

            if match:
                return match.group(1)

        return None

    # =================================================================
    # LANGUAGES
    # =================================================================

    @staticmethod
    def _extract_languages(
        text: str
    ) -> List[str]:

        possible_languages = [
            "Hindi",
            "Tamil",
            "Telugu",
            "English",
            "Japanese",
        ]

        found = []

        for language in possible_languages:

            if re.search(
                rf"\b{re.escape(language)}\b",
                text,
                re.I
            ):

                found.append(
                    language
                )

        return found

    # =================================================================
    # SCHEDULE
    # =================================================================

    @staticmethod
    def _extract_schedule(
        text: str
    ) -> Optional[str]:

        days = [
            "Monday",
            "Tuesday",
            "Wednesday",
            "Thursday",
            "Friday",
            "Saturday",
            "Sunday",
            "Daily",
        ]

        for day in days:

            pattern = (
                rf"\b{day}\b.*?"
                rf"([0-9]{{1,2}}:"
                rf"[0-9]{{2}}\s*[AP]M)"
            )

            match = re.search(
                pattern,
                text,
                re.I
            )

            if match:

                return (
                    f"{day} "
                    f"{match.group(1)}"
                )

        return None

    # =================================================================
    # DATE
    # =================================================================

    @staticmethod
    def _extract_date(
        text: str
    ) -> Optional[str]:

        patterns = [

            (
                r"\b\d{1,2}\s+"
                r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|"
                r"Sep|Oct|Nov|Dec)"
                r"\s+\d{4}\b"
            ),

            (
                r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|"
                r"Sep|Oct|Nov|Dec)"
                r"\s+\d{1,2},\s+\d{4}\b"
            ),

            r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b",
        ]

        for pattern in patterns:

            match = re.search(
                pattern,
                text,
                re.I
            )

            if match:
                return match.group(0)

        return None


# =====================================================================
# SINGLE INSTANCE
# =====================================================================

anime_scraper = AnimeScraper()


# =====================================================================
# PUBLIC FUNCTION
# =====================================================================

def get_anime_info(
    anime_name: str
) -> Optional[Dict]:

    return anime_scraper.search_anime(
        anime_name
    )

  
