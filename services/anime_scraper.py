"""
Anime information service.

Anime information:
- AnimeDubHindi schedule
- MAL poster through Jikan API

No anime episodes, watch links, or download links are handled.
"""

import re
from typing import Dict, Optional

import requests
from bs4 import BeautifulSoup

from utils.logger import logger


SCHEDULE_URL = "https://www.animedubhindi.link/schedule.php"
JIKAN_URL = "https://api.jikan.moe/v4/anime"


class AnimeScraper:
    """Anime information lookup service."""

    def __init__(self):
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

    # ---------------------------------------------------------------
    # MAIN SEARCH
    # ---------------------------------------------------------------

    def search_anime(
        self,
        anime_name: str
    ) -> Optional[Dict]:
        """Search AnimeDubHindi and get MAL poster."""

        if not anime_name:
            return None

        anime_name = anime_name.strip()

        if not anime_name:
            return None

        query = self._normalize(anime_name)

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

            # Get poster from MAL through Jikan.
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

    # ---------------------------------------------------------------
    # FIND ANIME
    # ---------------------------------------------------------------

    def _find_anime(
        self,
        soup: BeautifulSoup,
        query: str
    ) -> Optional[Dict]:
        """Find matching anime on the schedule page."""

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

            if len(title) > 200:
                continue

            if not self._title_matches(
                title,
                query
            ):
                continue

            # Find a nearby container containing anime details.
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
                    re.search(r"\bHindi\b", text, re.I)
                    or re.search(r"\bSeason\b", text, re.I)
                    or re.search(r"\bEpisode\b", text, re.I)
                    or re.search(r"\bEP\b", text, re.I)
                ):
                    break

            text = container.get_text(
                " ",
                strip=True
            )

            # Avoid taking the entire webpage.
            if len(text) > 3000:
                if element.parent:
                    text = element.parent.get_text(
                        " ",
                        strip=True
                    )

            languages = self._extract_languages(text)

            return {
                "name": self._clean_title(title),

                "hindi_dub": (
                    "Available"
                    if "Hindi" in languages
                    else "Not Mentioned"
                ),

                "platform": None,

                "hindi_details": (
                    "Hindi language listed on "
                    "AnimeDubHindi schedule."
                    if "Hindi" in languages
                    else None
                ),

                "episodes": self._extract_episode(text),

                "season": self._extract_season(text),

                "languages": (
                    " • ".join(languages)
                    if languages
                    else None
                ),

                "schedule": self._extract_schedule(text),

                "release_date": self._extract_date(text),

                "source": "AnimeDubHindi",

                "source_link": SCHEDULE_URL,

                "poster_url": None,
            }

        return None

    # ---------------------------------------------------------------
    # MAL POSTER THROUGH JIKAN
    # ---------------------------------------------------------------

    def _get_poster(
        self,
        anime_name: str
    ) -> Optional[str]:
        """Get MyAnimeList poster through Jikan API."""

        try:
            logger.info(
                "Searching MAL poster: %s",
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

            # First try exact title match.
            for anime in data:
                for title in self._get_titles(anime):
                    if self._normalize(title) == query:
                        selected = anime
                        break

                if selected:
                    break

            # If exact match fails, use first result.
            if selected is None:
                selected = data[0]

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
                    "MAL poster found: %s",
                    anime_name
                )

            return poster

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

    # ---------------------------------------------------------------
    # MAL TITLES
    # ---------------------------------------------------------------

    @staticmethod
    def _get_titles(
        anime: Dict
    ) -> list:
        """Get useful titles from Jikan/MAL result."""

        titles = []

        for key in (
            "title",
            "title_english",
            "title_japanese"
        ):
            value = anime.get(key)

            if value:
                titles.append(value)

        for item in anime.get("titles", []):
            if isinstance(item, dict):
                value = item.get("title")

                if value:
                    titles.append(value)

        return titles

    # ---------------------------------------------------------------
    # NORMALIZE
    # ---------------------------------------------------------------

    @staticmethod
    def _normalize(
        text: str
    ) -> str:
        """Normalize title."""

        text = text.lower()
        text = text.replace("-", " ")

        text = re.sub(
            r"[^a-z0-9 ]+",
            " ",
            text
        )

        return " ".join(
            text.split()
        )

    # ---------------------------------------------------------------
    # TITLE MATCH
    # ---------------------------------------------------------------

    @staticmethod
    def _title_matches(
        title: str,
        query: str
    ) -> bool:
        """Check title against search query."""

        title = AnimeScraper._normalize(title)
        query = AnimeScraper._normalize(query)

        if not query:
            return False

        if title == query:
            return True

        if query in title:
            return True

        query_words = set(query.split())
        title_words = set(title.split())

        return query_words.issubset(title_words)

    # ---------------------------------------------------------------
    # CLEAN TITLE
    # ---------------------------------------------------------------

    @staticmethod
    def _clean_title(
        title: str
    ) -> str:
        """Clean title."""

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

    # ---------------------------------------------------------------
    # SEASON
    # ---------------------------------------------------------------

    @staticmethod
    def _extract_season(
        text: str
    ) -> Optional[str]:
        """Extract season."""

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
                return f"Season {match.group(1)}"

        return None

    # ---------------------------------------------------------------
    # EPISODE
    # ---------------------------------------------------------------

    @staticmethod
    def _extract_episode(
        text: str
    ) -> Optional[str]:
        """Extract episode."""

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

    # ---------------------------------------------------------------
    # LANGUAGES
    # ---------------------------------------------------------------

    @staticmethod
    def _extract_languages(
        text: str
    ) -> list:
        """Extract languages."""

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

    # ---------------------------------------------------------------
    # SCHEDULE
    # ---------------------------------------------------------------

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

    # ---------------------------------------------------------------
    # DATE
    # ---------------------------------------------------------------

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
