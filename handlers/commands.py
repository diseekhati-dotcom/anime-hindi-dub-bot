"""
Anime information service.

Uses AnimeDubHindi schedule for anime metadata
and Jikan for anime poster information.

No anime episodes or copyrighted files are downloaded,
stored, or distributed.
"""

import re
from typing import Dict, Optional

import requests
from bs4 import BeautifulSoup

from utils.logger import logger


# -------------------------------------------------------------------
# URLs
# -------------------------------------------------------------------

SCHEDULE_URL = "https://www.animedubhindi.link/schedule.php"
JIKAN_URL = "https://api.jikan.moe/v4/anime"


class AnimeScraper:
    """Anime information lookup service."""

    def __init__(self):
        self.session = requests.Session()

        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        })

    # ----------------------------------------------------------------
    # MAIN SEARCH
    # ----------------------------------------------------------------

    def search_anime(
        self,
        anime_name: str
    ) -> Optional[Dict]:
        """Search AnimeDubHindi schedule."""

        if not anime_name or not anime_name.strip():
            return None

        query = self._normalize(anime_name)

        logger.info(
            "Anime search: %s",
            query
        )

        try:
            response = self.session.get(
                SCHEDULE_URL,
                timeout=15
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

            # --------------------------------------------------------
            # POSTER
            # --------------------------------------------------------

            result["poster_url"] = self._get_poster(
                result["name"]
            )

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

    # ----------------------------------------------------------------
    # FIND ANIME
    # ----------------------------------------------------------------

    def _find_anime(
        self,
        soup: BeautifulSoup,
        query: str
    ) -> Optional[Dict]:
        """Find matching anime from schedule page."""

        # Look through common title elements.
        elements = soup.find_all(
            ["h1", "h2", "h3", "h4", "h5", "a"]
        )

        for element in elements:

            title = element.get_text(
                " ",
                strip=True
            )

            if not title:
                continue

            # Ignore very long page text.
            if len(title) > 150:
                continue

            if not self._title_matches(
                title,
                query
            ):
                continue

            # Find useful surrounding container.
            container = element

            for _ in range(6):

                if container.parent is None:
                    break

                container = container.parent

                text = container.get_text(
                    " ",
                    strip=True
                )

                if (
                    len(text) > len(title)
                    and (
                        "Hindi" in text
                        or "English" in text
                        or "Japanese" in text
                        or "Season" in text
                        or "EP" in text
                    )
                ):
                    break

            text = container.get_text(
                " ",
                strip=True
            )

            # Don't use an entire page as a result.
            if len(text) > 2500:
                text = element.parent.get_text(
                    " ",
                    strip=True
                )

            languages = self._extract_languages(
                text
            )

            return {
                "name": self._clean_title(title),

                "hindi_dub": (
                    "Available"
                    if "Hindi" in languages
                    else "Status Unknown"
                ),

                "platform": None,

                "hindi_details": (
                    "Hindi language listed on "
                    "AnimeDubHindi schedule."
                    if "Hindi" in languages
                    else None
                ),

                "original_broadcast": None,

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

                # Kept internally but NOT displayed
                # by commands.py.
                "source_link": SCHEDULE_URL,
            }

        return None

    # ----------------------------------------------------------------
    # POSTER
    # ----------------------------------------------------------------

    def _get_poster(
        self,
        anime_name: str
    ) -> Optional[str]:
        """
        Get anime poster from Jikan.

        Only the image URL is used.
        The bot does not download or store the poster.
        """

        try:

            response = self.session.get(
                JIKAN_URL,
                params={
                    "q": anime_name,
                    "limit": 1,
                },
                timeout=10
            )

            response.raise_for_status()

            data = response.json().get(
                "data",
                []
            )

            if not data:
                logger.warning(
                    "No poster result for: %s",
                    anime_name
                )
                return None

            anime = data[0]

            images = anime.get(
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
                    "Poster found for: %s",
                    anime_name
                )

            return poster

        except Exception as exc:

            logger.warning(
                "Poster fetch failed for %s: %s",
                anime_name,
                exc
            )

            return None

    # ----------------------------------------------------------------
    # NORMALIZATION
    # ----------------------------------------------------------------

    @staticmethod
    def _normalize(
        text: str
    ) -> str:
        """Normalize anime title."""

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

    # ----------------------------------------------------------------
    # TITLE MATCHING
    # ----------------------------------------------------------------

    @staticmethod
    def _title_matches(
        title: str,
        query: str
    ) -> bool:
        """Check if title matches search query."""

        normalized_title = (
            AnimeScraper._normalize(title)
        )

        normalized_query = (
            AnimeScraper._normalize(query)
        )

        if not normalized_query:
            return False

        # Exact match
        if normalized_title == normalized_query:
            return True

        # Query contained in title
        if normalized_query in normalized_title:
            return True

        # Every query word exists in title
        query_words = set(
            normalized_query.split()
        )

        title_words = set(
            normalized_title.split()
        )

        return query_words.issubset(
            title_words
        )

    # ----------------------------------------------------------------
    # TITLE CLEANING
    # ----------------------------------------------------------------

    @staticmethod
    def _clean_title(
        title: str
    ) -> str:
        """Clean common title noise."""

        title = re.sub(
            r"\s+[-|–]\s+AnimeDubHindi.*$",
            "",
            title,
            flags=re.I
        )

        return title.strip()

    # ----------------------------------------------------------------
    # SEASON
    # ----------------------------------------------------------------

    @staticmethod
    def _extract_season(
        text: str
    ) -> Optional[str]:
        """Extract season number."""

        match = re.search(
            r"\bSeason\s*([0-9]+)\b",
            text,
            re.I
        )

        if match:
            return (
                f"Season {match.group(1)}"
            )

        match = re.search(
            r"\bS([0-9]+)\b",
            text,
            re.I
        )

        if match:
            return (
                f"Season {match.group(1)}"
            )

        return None

    # ----------------------------------------------------------------
    # EPISODE
    # ----------------------------------------------------------------

    @staticmethod
    def _extract_episode(
        text: str
    ) -> Optional[str]:
        """Extract episode number."""

        patterns = [
            r"\bEP\s*([0-9]+(?:-[0-9]+)?)\b",
            r"\bEpisode\s*([0-9]+(?:-[0-9]+)?)\b",
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

    # ----------------------------------------------------------------
    # LANGUAGES
    # ----------------------------------------------------------------

    @staticmethod
    def _extract_languages(
        text: str
    ) -> list:
        """Extract listed audio languages."""

        languages = [
            "Hindi",
            "Tamil",
            "Telugu",
            "English",
            "Japanese",
        ]

        found = []

        for language in languages:

            if re.search(
                rf"\b{re.escape(language)}\b",
                text,
                re.I
            ):
                found.append(language)

        return found

    # ----------------------------------------------------------------
    # SCHEDULE
    # ----------------------------------------------------------------

    @staticmethod
    def _extract_schedule(
        text: str
    ) -> Optional[str]:
        """Extract day and time."""

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

            match = re.search(
                rf"\b{day}\b\s+"
                rf"([0-9]{{1,2}}:[0-9]{{2}}\s*[AP]M)",
                text,
                re.I
            )

            if match:

                return (
                    f"{day} "
                    f"{match.group(1)}"
                )

        return None

    # ----------------------------------------------------------------
    # DATE
    # ----------------------------------------------------------------

    @staticmethod
    def _extract_date(
        text: str
    ) -> Optional[str]:
        """Extract common date formats."""

        patterns = [
            r"\b\d{1,2}\s+"
            r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
            r"\s+\d{4}\b",

            r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
            r"\s+\d{1,2},\s+\d{4}\b",

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


# -------------------------------------------------------------------
# SINGLE INSTANCE
# -------------------------------------------------------------------

anime_scraper = AnimeScraper()


def get_anime_info(
    anime_name: str
) -> Optional[Dict]:
    """Public helper used by Telegram bot."""

    return anime_scraper.search_anime(
        anime_name
    )
