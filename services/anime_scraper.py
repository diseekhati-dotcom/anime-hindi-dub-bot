"""
Anime information service.

Sources:
- AnimeDubHindi schedule: anime metadata
- MyAnimeList via Jikan API: anime poster

Provides:
- Anime name
- Hindi dub status
- Season
- Episode
- Languages
- Schedule
- Release date
- Source name
- MAL/Jikan poster

No anime episodes or copyrighted files are downloaded,
stored, watched, or distributed.
"""

import re
from typing import Dict, Optional, List

import requests
from bs4 import BeautifulSoup

from utils.logger import logger


# ===================================================================
# URLs
# ===================================================================

SCHEDULE_URL = (
    "https://www.animedubhindi.link/schedule.php"
)

JIKAN_SEARCH_URL = (
    "https://api.jikan.moe/v4/anime"
)


# ===================================================================
# ANIME SCRAPER
# ===================================================================

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
            "Searching anime: %s",
            anime_name
        )

        # -----------------------------------------------------------
        # AnimeDubHindi
        # -----------------------------------------------------------

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

        except requests.RequestException as exc:

            logger.error(
                "AnimeDubHindi request failed: %s",
                exc
            )

            return None

        except Exception as exc:

            logger.error(
                "AnimeDubHindi parser error: %s",
                exc,
                exc_info=True
            )

            return None

        if not result:

            logger.info(
                "Anime not found on AnimeDubHindi: %s",
                anime_name
            )

            return None

        # -----------------------------------------------------------
        # POSTER FROM MAL THROUGH JIKAN
        # -----------------------------------------------------------

        poster_url = self._get_poster(
            result["name"]
        )

        result["poster_url"] = poster_url

        return result

    # ===============================================================
    # FIND ANIME
    # ===============================================================

    def _find_anime(
        self,
        soup: BeautifulSoup,
        query: str
    ) -> Optional[Dict]:
        """Find anime information from schedule page."""

        # Search headings first.
        elements = soup.find_all(
            [
                "h1",
                "h2",
                "h3",
                "h4",
                "h5"
            ]
        )

        # If no headings exist, search links.
        if not elements:

            elements = soup.find_all(
                "a"
            )

        # -----------------------------------------------------------
        # SEARCH EACH TITLE
        # -----------------------------------------------------------

        for element in elements:

            title = element.get_text(
                " ",
                strip=True
            )

            if not title:
                continue

            # Ignore very large text blocks.
            if len(title) > 200:
                continue

            if not self._title_matches(
                title,
                query
            ):
                continue

            # -------------------------------------------------------
            # FIND SURROUNDING CARD
            # -------------------------------------------------------

            container = element

            for _ in range(8):

                if container.parent is None:
                    break

                container = container.parent

                text = container.get_text(
                    " ",
                    strip=True
                )

                # Stop when useful anime information is found.
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

            # Prevent accidentally using the entire webpage.
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

            # -------------------------------------------------------
            # RESULT
            # -------------------------------------------------------

            return {
                "name": clean_title,

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

                "original_broadcast": None,

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

                # Poster is filled by Jikan.
                "poster_url": None,
            }

        return None

    # ===============================================================
    # MAL / JIKAN POSTER
    # ===============================================================

    def _get_poster(
        self,
        anime_name: str
    ) -> Optional[str]:
        """
        Find anime poster using MyAnimeList data
        through the public Jikan API.

        The bot only uses the remote image URL.
        It does not download or permanently store
        the poster.
        """

        if not anime_name:
            return None

        try:

            logger.info(
                "Searching MAL/Jikan poster: %s",
                anime_name
            )

            response = self.session.get(
                JIKAN_SEARCH_URL,
                params={
                    "q": anime_name,
                    "limit": 10,
                    "sfw": "true",
                },
                timeout=20
            )

            response.raise_for_status()

            payload = response.json()

            data = payload.get(
                "data",
                []
            )

            if not data:

                logger.warning(
                    "No MAL/Jikan result for: %s",
                    anime_name
                )

                return None

            normalized_query = self._normalize(
                anime_name
            )

            selected = None

            # -------------------------------------------------------
            # FIRST: EXACT TITLE MATCH
            # -------------------------------------------------------

            for anime in data:

                titles = self._get_all_titles(
                    anime
                )

                for title in titles:

                    if (
                        self._normalize(title)
                        == normalized_query
                    ):
                        selected = anime
                        break

                if selected:
                    break

            # -------------------------------------------------------
            # SECOND: WORD MATCH
            # -------------------------------------------------------

            if selected is None:

                query_words = set(
                    normalized_query.split()
                )

                for anime in data:

                    titles = self._get_all_titles(
                        anime
                    )

                    for title in titles:

                        normalized_title = (
                            self._normalize(title)
                        )

                        title_words = set(
                            normalized_title.split()
                        )

                        if query_words.issubset(
                            title_words
                        ):
                            selected = anime
                            break

                    if selected:
                        break

            # -------------------------------------------------------
            # THIRD: FIRST RESULT
            # -------------------------------------------------------

            if selected is None:

                selected = data[0]

            # -------------------------------------------------------
            # GET MAL IMAGE
            # -------------------------------------------------------

            images = selected.get(
                "images",
                {}
            )

            jpg = images.get(
                "jpg",
                {}
            )

            poster_url = (
                jpg.get("large_image_url")
                or jpg.get("image_url")
            )

            if poster_url:

                logger.info(
                    "MAL/Jikan poster found: %s",
                    anime_name
                )

                return poster_url

            logger.warning(
                "MAL/Jikan result has no poster: %s",
                anime_name
            )

            return None

        except requests.RequestException as exc:

            logger.warning(
                "Jikan request failed for '%s': %s",
                anime_name,
                exc
            )

            return None

        except ValueError as exc:

            logger.warning(
                "Invalid Jikan JSON for '%s': %s",
                anime_name,
                exc
            )

            return None

        except Exception as exc:

            logger.warning(
                "Poster lookup error for '%s': %s",
                anime_name,
                exc,
                exc_info=True
            )

            return None

    # ===============================================================
    # GET ALL MAL TITLES
    # ===============================================================

    @staticmethod
    def _get_all_titles(
        anime: Dict
    ) -> List[str]:
        """Return all useful titles from Jikan/MAL."""

        titles = []

        # Main title
        title = anime.get("title")

        if title:
            titles.append(title)

        # English title
        title_english = anime.get(
            "title_english"
        )

        if title_english:
            titles.append(title_english)

        # Japanese title
        title_japanese = anime.get(
            "title_japanese"
        )

        if title_japanese:
            titles.append(title_japanese)

        # Alternative titles
        for item in anime.get(
            "titles",
            []
        ):

            if not isinstance(
                item,
                dict
            ):
                continue

            value = item.get(
                "title"
            )

            if value:
                titles.append(value)

        # Remove duplicates while keeping order.
        unique = []

        for value in titles:

            if value and value not in unique:
                unique.append(value)

        return unique

    # ===============================================================
    # NORMALIZE
    # ===============================================================

    @staticmethod
    def _normalize(
        text: str
    ) -> str:
        """Normalize anime title for searching."""

        if not text:
            return ""

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
        """Check whether title matches search query."""

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

        # Exact match
        if (
            title_normalized
            == query_normalized
        ):
            return True

        # Query contained in title
        if (
            query_normalized
            in title_normalized
        ):
            return True

        # All words exist
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
        """Remove common schedule title noise."""

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
        """Extract season information."""

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
        """Extract episode number/range."""

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
        """Extract listed audio languages."""

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

            patterns = [
                rf"\b{day}\b\s+"
                rf"([0-9]{{1,2}}:"
                rf"[0-9]{{2}}\s*[AP]M)",

                rf"\b{day}\b.*?"
                rf"([0-9]{{1,2}}:"
                rf"[0-9]{{2}}\s*[AP]M)",
            ]

            for pattern in patterns:

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
        """Extract common date
