"""
Anime information service.

Anime information:
- Anime name
- Hindi dub status
- Season
- Episode
- Languages
- Schedule
- Source

Poster:
- MyAnimeList (MAL) via Jikan API

No anime episodes, watch links, or copyrighted files
are downloaded, stored, or distributed.
"""

import re
import time
from typing import Dict, Optional

import requests
from bs4 import BeautifulSoup

from utils.logger import logger


# -------------------------------------------------------------------
# URLs
# -------------------------------------------------------------------

SCHEDULE_URL = (
    "https://www.animedubhindi.link/schedule.php"
)

JIKAN_SEARCH_URL = (
    "https://api.jikan.moe/v4/anime"
)


class AnimeScraper:
    """Anime information + MAL poster lookup service."""

    def __init__(self):

        self.session = requests.Session()

        self.session.headers.update({
            "User-Agent": (
                "AnimeHindiDubBot/1.0 "
                "(Telegram anime information bot)"
            ),
            "Accept": "application/json,text/html;q=0.9",
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
        Search AnimeDubHindi schedule.

        Poster is fetched separately from
        MyAnimeList through Jikan.
        """

        if not anime_name:
            return None

        anime_name = anime_name.strip()

        if not anime_name:
            return None

        query = self._normalize(
            anime_name
        )

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
                    "Anime not found on schedule: %s",
                    anime_name
                )

                return None

            # -------------------------------------------------------
            # POSTER FROM MAL / JIKAN
            # -------------------------------------------------------

            poster_url = self._get_mal_poster(
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
                "Anime scraper error: %s",
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
        """Find anime entry from AnimeDubHindi schedule."""

        # Search headings
        elements = soup.find_all(
            [
                "h1",
                "h2",
                "h3",
                "h4",
                "h5"
            ]
        )

        # If no headings, search links
        if not elements:

            elements = soup.find_all(
                "a"
            )

        for element in elements:

            title = element.get_text(
                " ",
                strip=True
            )

            if not title:
                continue

            # Ignore huge text blocks
            if len(title) > 200:
                continue

            if not self._title_matches(
                title,
                query
            ):
                continue

            # -------------------------------------------------------
            # FIND INFORMATION CONTAINER
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

                if len(text) > 40:

                    if (
                        re.search(
                            r"\bHindi\b",
                            text,
                            re.I
                        )
                        or re.search(
                            r"\bEP\b",
                            text,
                            re.I
                        )
                        or re.search(
                            r"\bEpisode\b",
                            text,
                            re.I
                        )
                        or re.search(
                            r"\bSeason\b",
                            text,
                            re.I
                        )
                    ):
                        break

            text = container.get_text(
                " ",
                strip=True
            )

            # Prevent reading entire webpage
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

                # Poster is filled below
                "poster_url": None,
            }

        return None

    # ===============================================================
    # MAL POSTER
    # ===============================================================

    def _get_mal_poster(
        self,
        anime_name: str
    ) -> Optional[str]:
        """
        Get anime poster from MyAnimeList
        through the Jikan API.

        Jikan provides MAL anime information
        including official MAL image URLs.

        The bot only sends the remote image URL.
        It does not save the poster.
        """

        if not anime_name:
            return None

        logger.info(
            "Searching MAL poster through Jikan: %s",
            anime_name
        )

        try:

            # -------------------------------------------------------
            # FIRST SEARCH
            # -------------------------------------------------------

            response = self.session.get(
                JIKAN_SEARCH_URL,
                params={
                    "q": anime_name,
                    "limit": 10,
                    "sfw": "true",
                },
                timeout=20
            )

            # -------------------------------------------------------
            # JIKAN RATE LIMIT
            # -------------------------------------------------------

            if response.status_code == 429:

                logger.warning(
                    "Jikan rate limit reached for: %s",
                    anime_name
                )

                # Wait briefly and try once more
                time.sleep(2)

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

            # -------------------------------------------------------
            # FIND BEST MATCH
            # -------------------------------------------------------

            selected = self._select_best_mal_result(
                data,
                anime_name
            )

            if not selected:

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

            # Prefer large MAL image
            poster_url = (
                jpg.get("large_image_url")
                or jpg.get("image_url")
            )

            if poster_url:

                logger.info(
                    "MAL poster found: %s -> %s",
                    anime_name,
                    poster_url
                )

                return poster_url

            # -------------------------------------------------------
            # WEBP FALLBACK
            # -------------------------------------------------------

            webp = images.get(
                "webp",
                {}
            )

            poster_url = (
                webp.get("large_image_url")
                or webp.get("image_url")
            )

            if poster_url:

                logger.info(
                    "MAL WebP poster found: %s",
                    anime_name
                )

                return poster_url

            logger.warning(
                "MAL result has no poster: %s",
                anime_name
            )

            return None

        except requests.RequestException as exc:

            logger.warning(
                "Jikan/MAL poster request failed "
                "for %s: %s",
                anime_name,
                exc
            )

            return None

        except ValueError as exc:

            logger.warning(
                "Invalid Jikan JSON for %s: %s",
                anime_name,
                exc
            )

            return None

        except Exception as exc:

            logger.warning(
                "MAL poster error for %s: %s",
                anime_name,
                exc
            )

            return None

    # ===============================================================
    # BEST MAL RESULT
    # ===============================================================

    def _select_best_mal_result(
        self,
        results: list,
        anime_name: str
    ) -> Optional[Dict]:
        """Select the closest MAL anime result."""

        query = self._normalize(
            anime_name
        )

        if not query:
            return None

        best_result = None
        best_score = -1

        for anime in results:

            titles = []

            # Main title
            if anime.get("title"):
                titles.append(
                    anime.get("title")
                )

            # English title
            if anime.get("title_english"):
                titles.append(
                    anime.get("title_english")
                )

            # Japanese title
            if anime.get("title_japanese"):
                titles.append(
                    anime.get("title_japanese")
                )

            # Synonyms
            for synonym in anime.get(
                "title_synonyms",
                []
            ):

                if synonym:
                    titles.append(
                        synonym
                    )

            for title in titles:

                if not title:
                    continue

                normalized_title = (
                    self._normalize(
                        title
                    )
                )

                score = 0

                # Exact match
                if normalized_title == query:

                    score = 100

                # Query contained in title
                elif query in normalized_title:

                    score = 80

                # Title contained in query
                elif normalized_title in query:

                    score = 70

                else:

                    query_words = set(
                        query.split()
                    )

                    title_words = set(
                        normalized_title.split()
                    )

                    common_words = (
                        query_words
                        & title_words
                    )

                    if common_words:

                        score = int(
                            (
                                len(common_words)
                                / len(query_words)
                            )
                            * 60
                        )

                if score > best_score:

                    best_score = score
                    best_result = anime

        return best_result

    # ===============================================================
    # NORMALIZE
    # ===============================================================

    @staticmethod
    def _normalize(
        text: str
    ) -> str:
        """Normalize anime title."""

        if not text:
            return ""

        text = text.lower()

        # Replace common separators
        text = text.replace(
            "-",
            " "
        )

        text = text.replace(
            "_",
            " "
        )

        text = text.replace(
            ":",
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

        # Exact
        if (
            title_normalized
            == query_normalized
        ):
            return True

        # Query inside title
        if (
            query_normalized
            in title_normalized
        ):
            return True

        # Every query word exists
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

    # ===============================================================
    # SEASON
    # ===============================================================

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
        """Extract episode."""

        patterns = [
            r"\bEP\s*([0-9]+(?:-[0-9]+)?)\b",

            r"\bEpisode\s*"
            r"([0-9]+(?:-[0-9]+)?)\b",

            r"\bEp\.\s*"
            r"([0-9]+(?:-[0-9]+)?)\b",
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
        """Extract audio languages."""

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

    # ===============================================================
    # SCHEDULE
    # ===============================================================

    @staticmethod
    def _extract_schedule(
        text: str
    ) -> Optional[str]:
        """Extract schedule day/time."""

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

  
