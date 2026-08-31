"""
Anime information service.

Sources:
- AnimeDubHindi schedule: anime metadata
- MyAnimeList poster: through Jikan API

No anime episodes, watch links, or download links
are downloaded, stored, or distributed.
"""

import re
from typing import Dict, Optional

import requests
from bs4 import BeautifulSoup

from utils.logger import logger


# ===================================================================
# URLs
# ===================================================================

SCHEDULE_URL = "https://www.animedubhindi.link/schedule.php"
JIKAN_URL = "https://api.jikan.moe/v4/anime"


# ===================================================================
# SCRAPER
# ===================================================================

class AnimeScraper:
    """Anime information lookup service."""

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
        Search AnimeDubHindi schedule and attach
        a MyAnimeList poster through Jikan.
        """

        if not anime_name:
            return None

        anime_name = anime_name.strip()

        if not anime_name:
            return None

        query = self._normalize(anime_name)

        logger.info(
            "Searching AnimeDubHindi: %s",
            anime_name
        )

        try:
            response = self.session.get(
                SCHEDULE_URL,
                timeout=20
            )

            response.raise_for_status()

            soup = BeautifulSoup(
                response.text,
                "html.parser"
            )

            result = self._find_anime(
                soup,
                query
            )

            if not result:
                logger.info(
                    "Anime not found: %s",
                    anime_name
                )
                return None

            # -------------------------------------------------------
            # MAL POSTER THROUGH JIKAN
            # -------------------------------------------------------

            poster_url = self._get_poster(
                result["name"]
            )

            result["poster_url"] = poster_url

            return result

        except requests.RequestException as exc:
            logger.error(
                "AnimeDubHindi request failed: %s",
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
    # FIND ANIME
    # ===============================================================

    def _find_anime(
        self,
        soup: BeautifulSoup,
        query: str
    ) -> Optional[Dict]:
        """Find anime information from the schedule page."""

        elements = soup.find_all(
            [
                "h1",
                "h2",
                "h3",
                "h4",
                "h5",
                "a"
            ]
        )

        for element in elements:

            title = element.get_text(
                " ",
                strip=True
            )

            if not title:
                continue

            # Ignore extremely large pieces of page text.
            if len(title) > 200:
                continue

            if not self._title_matches(
                title,
                query
            ):
                continue

            # -------------------------------------------------------
            # FIND NEARBY INFORMATION CONTAINER
            # -------------------------------------------------------

            container = element

            for _ in range(7):

                if container.parent is None:
                    break

                container = container.parent

                text = container.get_text(
                    " ",
                    strip=True
                )

                if (
                    re.search(
                        r"\bHindi\b",
                        text,
                        re.I
                    )
                    or re.search(
                        r"\bSeason\b",
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
                ):
                    break

            text = container.get_text(
                " ",
                strip=True
            )

            # Prevent the complete webpage from being parsed.
            if len(text) > 3000:

                if element.parent:
                    text = element.parent.get_text(
                        " ",
                        strip=True
                    )

            # -------------------------------------------------------
            # EXTRACT INFORMATION
            # -------------------------------------------------------

            languages = self._extract_languages(
                text
            )

            season = self._extract_season(
                text
            )

            episode = self._extract_episode(
                text
            )

            schedule = self._extract_schedule(
                text
            )

            release_date = self._extract_date(
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

                # These are populated when the source
                # provides platform/dubbing information.
                "platform": self._extract_platform(
                    text
                ),

                "dub_by": self._extract_dub_by(
                    text
                ),

                "hindi_details": (
                    "Hindi language listed on "
                    "AnimeDubHindi schedule."
                    if "Hindi" in languages
                    else None
                ),

                "episodes": episode,

                "season": season,

                "languages": (
                    " • ".join(languages)
                    if languages
                    else None
                ),

                "schedule": schedule,

                "release_date": release_date,

                "source": "AnimeDubHindi",

                "source_link": SCHEDULE_URL,

                "poster_url": None,
            }

        return None

    # ===============================================================
    # PLATFORM
    # ===============================================================

    @staticmethod
    def _extract_platform(
        text: str
    ) -> Optional[str]:
        """
        Extract a streaming platform when explicitly
        mentioned in the schedule text.
        """

        platforms = [
            "Crunchyroll",
            "Sony YAY",
            "Sony Yay",
            "MX Player",
            "JioHotstar",
            "Jio Hotstar",
            "Netflix",
            "Amazon Prime Video",
            "Prime Video",
            "Disney+",
            "Disney Plus",
            "YouTube",
            "Animax",
        ]

        for platform in platforms:

            if re.search(
                rf"\b{re.escape(platform)}\b",
                text,
                re.I
            ):
                return platform

        return None

    # ===============================================================
    # DUB BY
    # ===============================================================

    @staticmethod
    def _extract_dub_by(
        text: str
    ) -> Optional[str]:
        """
        Extract dubbing studio/network if explicitly
        mentioned in the schedule text.
        """

        patterns = [
            r"Dubbed\s*by\s*[:\-]?\s*([^|•,\n]+)",
            r"Dub\s*by\s*[:\-]?\s*([^|•,\n]+)",
            r"Dubbing\s*by\s*[:\-]?\s*([^|•,\n]+)",
            r"Dubbing\s*Studio\s*[:\-]?\s*([^|•,\n]+)",
        ]

        for pattern in patterns:

            match = re.search(
                pattern,
                text,
                re.I
            )

            if match:

                value = match.group(1).strip()

                if value:
                    return value

        return None

    # ===============================================================
    # MAL POSTER THROUGH JIKAN
    # ===============================================================

    def _get_poster(
        self,
        anime_name: str
    ) -> Optional[str]:
        """
        Get the MyAnimeList poster URL through Jikan.

        The bot only receives the remote URL.
        It does not permanently store the image.
        """

        try:

            logger.info(
                "Searching MAL poster through Jikan: %s",
                anime_name
            )

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

                logger.warning(
                    "No MAL result for: %s",
                    anime_name
                )

                return None

            query = self._normalize(
                anime_name
            )

            selected = None

            # -------------------------------------------------------
            # EXACT MATCH FIRST
            # -------------------------------------------------------

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

            # -------------------------------------------------------
            # FALLBACK
            # -------------------------------------------------------

            if selected is None:
                selected = data[0]

            # -------------------------------------------------------
            # IMAGE
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

            if poster:

                logger.info(
                    "MAL poster found for: %s",
                    anime_name
                )

                return poster

            logger.warning(
                "MAL result has no poster: %s",
                anime_name
            )

            return None

        except requests.RequestException as exc:

            logger.warning(
                "Jikan request failed for %s: %s",
                anime_name,
                exc
            )

            return None

        except Exception as exc:

            logger.warning(
                "Poster error for %s: %s",
                anime_name,
                exc
            )

            return None

    # ===============================================================
    # MAL TITLES
    # ===============================================================

    @staticmethod
    def _get_titles(
        anime: Dict
    ) -> list:
        """Return useful MAL/Jikan titles."""

        titles = []

        for key in (
            "title",
            "title_english",
            "title_japanese"
        ):

            value = anime.get(key)

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
        """Normalize an anime title."""

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
        """Check whether a title matches the search query."""

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

        # Exact match.
        if (
            title_normalized
            == query_normalized
        ):
            return True

        # Query contained in title.
        if (
            query_normalized
            in title_normalized
        ):
            return True

        # Every query word exists in title.
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
        """Remove unnecessary source text from title."""

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
    ) -> list:
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
