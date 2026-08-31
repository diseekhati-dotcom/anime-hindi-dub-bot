"""
Anime information service.

Live sources:
- AnimeDubHindi -> Hindi dub, season, episode, languages, schedule
- Jikan / MyAnimeList -> poster + anime identity + studio
- Official platform pages -> platform/audio verification when available

No anime episodes, watch links, or download links are handled.
"""

import re
from typing import Dict, Optional, List

import requests
from bs4 import BeautifulSoup

from utils.logger import logger


# ===================================================================
# URLs
# ===================================================================

SCHEDULE_URL = "https://www.animedubhindi.link/schedule.php"
JIKAN_URL = "https://api.jikan.moe/v4/anime"

# Official platforms that can be checked.
PLATFORM_DOMAINS = {
    "Crunchyroll": "crunchyroll.com",
    "Netflix": "netflix.com",
    "JioHotstar": "hotstar.com",
    "Amazon Prime Video": "primevideo.com",
    "Sony YAY": "sonyliv.com",
    "MX Player": "mxplayer.in",
}


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

    # ===============================================================
    # MAIN SEARCH
    # ===============================================================

    def search_anime(
        self,
        anime_name: str
    ) -> Optional[Dict]:
        """
        Search anime live and combine information from
        AnimeDubHindi and Jikan/MAL.
        """

        if not anime_name:
            return None

        anime_name = anime_name.strip()

        if not anime_name:
            return None

        logger.info(
            "Live anime search: %s",
            anime_name
        )

        try:
            # -------------------------------------------------------
            # AnimeDubHindi
            # -------------------------------------------------------

            response = self.session.get(
                SCHEDULE_URL,
                timeout=20
            )

            response.raise_for_status()

            soup = BeautifulSoup(
                response.text,
                "html.parser"
            )

            query = self._normalize(
                anime_name
            )

            result = self._find_anime(
                soup,
                query
            )

            if not result:
                logger.info(
                    "Anime not found on AnimeDubHindi: %s",
                    anime_name
                )
                return None

            # -------------------------------------------------------
            # MAL / JIKAN
            # -------------------------------------------------------

            mal_info = self._get_mal_info(
                result["name"]
            )

            if mal_info:
                result["poster_url"] = mal_info.get(
                    "poster_url"
                )

                result["studio"] = mal_info.get(
                    "studio"
                )

                result["mal_url"] = mal_info.get(
                    "mal_url"
                )

            else:
                result["poster_url"] = None
                result["studio"] = None
                result["mal_url"] = None

            # -------------------------------------------------------
            # PLATFORM / DUB INFORMATION
            # -------------------------------------------------------
            #
            # Only explicitly detectable information is returned.
            # The scraper never guesses a platform.
            #

            platform_data = self._extract_platform_info(
                result["name"]
            )

            result["platform"] = platform_data.get(
                "platform"
            )

            result["dub_by"] = platform_data.get(
                "dub_by"
            )

            return result

        except requests.RequestException as exc:
            logger.error(
                "Anime source request failed: %s",
                exc
            )
            return None

        except Exception as exc:
            logger.error(
                "Anime search error: %s",
                exc,
                exc_info=True
            )
            return None

    # ===============================================================
    # FIND ANIME ON ANIMEDUBHINDI
    # ===============================================================

    def _find_anime(
        self,
        soup: BeautifulSoup,
        query: str
    ) -> Optional[Dict]:
        """Find an anime from the live schedule page."""

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

        # -----------------------------------------------------------
        # Find matching title
        # -----------------------------------------------------------

        for element in elements:

            title = element.get_text(
                " ",
                strip=True
            )

            if not title:
                continue

            if len(title) > 200:
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

        # -----------------------------------------------------------
        # Find nearest useful container
        # -----------------------------------------------------------

        container = best_element

        for _ in range(8):

            if container.parent is None:
                break

            container = container.parent

            text = container.get_text(
                " ",
                strip=True
            )

            if len(text) > 3000:
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
            )

            if useful:
                break

        text = container.get_text(
            " ",
            strip=True
        )

        # Safety fallback.
        if len(text) > 3000:
            text = best_element.parent.get_text(
                " ",
                strip=True
            )

        languages = self._extract_languages(
            text
        )

        clean_title = self._clean_title(
            title
        )

        return {
            "name": clean_title,

            "hindi_dub": (
                "Available"
                if "Hindi" in languages
                else "Not Mentioned"
            ),

            "platform": None,

            "dub_by": None,

            "hindi_details": (
                "Hindi language listed on "
                "AnimeDubHindi schedule."
                if "Hindi" in languages
                else None
            ),

            "studio": None,

            "episodes": self._extract_episode(
                text
            ),

            "season": self._extract_season(
                text
            ),

            "languages": (
                " • ".join(languages)
                if languages
                else None
            ),

            "schedule": self._extract_schedule(
                text
            ),

            "release_date": self._extract_date(
                text
            ),

            "source": "AnimeDubHindi",

            "source_link": SCHEDULE_URL,

            "poster_url": None,

            "mal_url": None,
        }

    # ===============================================================
    # PLATFORM INFORMATION
    # ===============================================================

    def _extract_platform_info(
        self,
        anime_name: str
    ) -> Dict:
        """
        Check official platform search pages.

        This function only returns a platform when the official
        page can be reached and the anime title is visibly present.

        It does not guess.
        """

        found_platforms: List[str] = []

        # -----------------------------------------------------------
        # Official platform pages
        # -----------------------------------------------------------

        searches = [
            (
                "Crunchyroll",
                f"https://www.crunchyroll.com/search?q="
                f"{requests.utils.quote(anime_name)}",
            ),
            (
                "Netflix",
                f"https://www.netflix.com/search?q="
                f"{requests.utils.quote(anime_name)}",
            ),
            (
                "JioHotstar",
                f"https://www.hotstar.com/in/search?q="
                f"{requests.utils.quote(anime_name)}",
            ),
        ]

        for platform, url in searches:

            try:
                response = self.session.get(
                    url,
                    timeout=8,
                    allow_redirects=True
                )

                if response.status_code != 200:
                    continue

                page_text = BeautifulSoup(
                    response.text,
                    "html.parser"
                ).get_text(
                    " ",
                    strip=True
                )

                normalized_page = self._normalize(
                    page_text
                )

                normalized_name = self._normalize(
                    anime_name
                )

                if (
                    normalized_name
                    and normalized_name in normalized_page
                ):
                    found_platforms.append(
                        platform
                    )

            except Exception as exc:
                logger.debug(
                    "Platform check failed for %s: %s",
                    platform,
                    exc
                )

        # -----------------------------------------------------------
        # Do not claim Dub By from platform alone.
        # -----------------------------------------------------------

        platform_value = (
            " • ".join(
                dict.fromkeys(found_platforms)
            )
            if found_platforms
            else None
        )

        return {
            "platform": platform_value,
            "dub_by": None,
        }

    # ===============================================================
    # MAL / JIKAN
    # ===============================================================

    def _get_mal_info(
        self,
        anime_name: str
    ) -> Optional[Dict]:
        """Get poster, MAL URL and animation studio."""

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

            # Exact title match.
            for anime in data:

                for title in self._get_titles(
                    anime
                ):

                    if (
                        self._normalize(title)
                        == query
                    ):
                        selected = anime
                        break

                if selected:
                    break

            # Fallback.
            if selected is None:
                selected = data[0]

            # -------------------------------------------------------
            # Poster
            # -------------------------------------------------------

            images = selected.get(
                "images",
                {}
            )

            jpg = images.get(
                "jpg",
                {}
            )

            poster = (
                jpg.get("large_image_url")
                or jpg.get("image_url")
            )

            # -------------------------------------------------------
            # MAL URL
            # -------------------------------------------------------

            mal_url = selected.get(
                "url"
            )

            # -------------------------------------------------------
            # Studio
            # -------------------------------------------------------

            studio = None

            studios = selected.get(
                "studios",
                []
            )

            if studios:

                names = []

                for item in studios:

                    if isinstance(item, dict):

                        name = item.get(
                            "name"
                        )

                        if name:
                            names.append(name)

                if names:
                    studio = " • ".join(
                        dict.fromkeys(names)
                    )

            return {
                "poster_url": poster,
                "studio": studio,
                "mal_url": mal_url,
            }

        except requests.RequestException as exc:
            logger.warning(
                "Jikan request failed for %s: %s",
                anime_name,
                exc
            )
            return None

        except Exception as exc:
            logger.warning(
                "MAL information error for %s: %s",
                anime_name,
                exc
            )
            return None

    # ===============================================================
    # TITLES
    # ===============================================================

    @staticmethod
    def _get_titles(
        anime: Dict
    ) -> List[str]:
        """Return all useful anime titles."""

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
                titles.append(value)

        for item in anime.get(
            "titles",
            []
        ):

            if isinstance(item, dict):

                value = item.get(
                    "title"
                )

                if value:
                    titles.append(value)

        return titles

    # ===============================================================
    # NORMALIZE
    # ===============================================================

    @staticmethod
    def _normalize(
        text: str
    ) -> str:
        """Normalize anime title for matching."""

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

    # ===============================================================
    # TITLE MATCH
    # ===============================================================

    @staticmethod
    def _title_matches(
        title: str,
        query: str
    ) -> bool:
        """Check whether title matches query."""

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

    # ===============================================================
    # CLEAN TITLE
    # ===============================================================

    @staticmethod
    def _clean_title(
        title: str
    ) -> str:
        """Clean source text from anime title."""

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

    # ===============================================================
    # SEASON
    # ===============================================================

    @staticmethod
    def _extract_season(
        text: str
    ) -> Optional[str]:
        """Extract season number."""

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

    # ===============================================================
    # EPISODE
    # ===============================================================

    @staticmethod
    def _extract_episode(
        text: str
    ) -> Optional[str]:
        """Extract episode number."""

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

    # ===============================================================
    # LANGUAGES
    # ===============================================================

    @staticmethod
    def _extract_languages(
        text: str
    ) -> List[str]:
        """Extract available audio languages."""

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
                found.append(language)

        return found

    # ===============================================================
    # SCHEDULE
    # ===============================================================

    @staticmethod
    def _extract_schedule(
        text: str
    ) -> Optional[str]:
        """Extract schedule day and time."""

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

    # ===============================================================
    # DATE
    # ===============================================================

    @staticmethod
    def _extract_date(
        text: str
    ) -> Optional[str]:
        """Extract common date formats."""

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


# ===================================================================
# SINGLE INSTANCE
# ===================================================================

anime_scraper = AnimeScraper()


# ===================================================================
# PUBLIC FUNCTION
# ===================================================================

def get_anime_info(
    anime_name: str
) -> Optional[Dict]:
    """Public function used by commands.py."""

    return anime_scraper.search_anime(
        anime_name
                )
