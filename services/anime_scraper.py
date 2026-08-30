"""
Anime information service.

Reads anime information from the public AnimeDubHindi schedule page.

Provides:
- Anime name
- Hindi dub status
- Season
- Episode
- Languages
- Schedule
- Jikan anime poster

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

SCHEDULE_URL = (
    "https://www.animedubhindi.link/schedule.php"
)

JIKAN_SEARCH_URL = (
    "https://api.jikan.moe/v4/anime"
)


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

    # ----------------------------------------------------------------
    # MAIN SEARCH
    # ----------------------------------------------------------------

    def search_anime(
        self,
        anime_name: str
    ) -> Optional[Dict]:
        """
        Search anime from AnimeDubHindi schedule
        and get poster from Jikan.
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
            query
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

            # --------------------------------------------------------
            # GET POSTER
            # --------------------------------------------------------

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
                "Anime parser error: %s",
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
        """Find anime from schedule page."""

        # Search headings first.
        headings = soup.find_all(
            [
                "h1",
                "h2",
                "h3",
                "h4",
                "h5"
            ]
        )

        # If headings don't contain the anime,
        # also search links.
        if not headings:

            headings = soup.find_all(
                "a"
            )

        # ------------------------------------------------------------
        # SEARCH TITLES
        # ------------------------------------------------------------

        for element in headings:

            title = element.get_text(
                " ",
                strip=True
            )

            if not title:
                continue

            # Avoid huge pieces of page text.
            if len(title) > 200:
                continue

            if not self._title_matches(
                title,
                query
            ):
                continue

            # --------------------------------------------------------
            # FIND INFORMATION CONTAINER
            # --------------------------------------------------------

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

            # Prevent entire webpage from becoming result.
            if len(text) > 3000:

                if element.parent:

                    text = element.parent.get_text(
                        " ",
                        strip=True
                    )

            # --------------------------------------------------------
            # EXTRACT DATA
            # --------------------------------------------------------

            languages = (
                self._extract_languages(
                    text
                )
            )

            season = (
                self._extract_season(
                    text
                )
            )

            episode = (
                self._extract_episode(
                    text
                )
            )

            schedule = (
                self._extract_schedule(
                    text
                )
            )

            release_date = (
                self._extract_date(
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

                # Kept internally.
                # commands.py only displays source name.
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

        Only the remote image URL is used.
        The bot does not download or store the poster.
        """

        try:

            logger.info(
                "Searching Jikan poster: %s",
                anime_name
            )

            response = self.session.get(
                JIKAN_SEARCH_URL,
                params={
                    "q": anime_name,
                    "limit": 5,
                    "sfw": "true",
                },
                timeout=15
            )

            response.raise_for_status()

            data = response.json().get(
                "data",
                []
            )

            if not data:

                logger.warning(
                    "Jikan returned no result for: %s",
                    anime_name
                )

                return None

            # --------------------------------------------------------
            # FIND BEST TITLE MATCH
            # --------------------------------------------------------

            normalized_query = (
                self._normalize(
                    anime_name
                )
            )

            selected = data[0]

            for anime in data:

                titles = []

                if anime.get("title"):
                    titles.append(
                        anime.get("title")
                    )

                if anime.get("title_english"):
                    titles.append(
                        anime.get("title_english")
                    )

                if anime.get("title_japanese"):
                    titles.append(
                        anime.get("title_japanese")
                    )

                for title in titles:

                    if not title:
                        continue

                    normalized_title = (
                        self._normalize(
                            title
                        )
                    )

                    if (
                        normalized_title
                        == normalized_query
                    ):
                        selected = anime
                        break

                else:
                    continue

                break

            # --------------------------------------------------------
            # GET IMAGE
            # --------------------------------------------------------

            images = selected.get(
                "images",
                {}
            )

            jpg = images.get(
                "jpg",
                {}
            )

            poster_url = (
                jpg.get(
                    "large_image_url"
                )
                or jpg.get(
                    "image_url"
                )
            )

            if poster_url:

                logger.info(
                    "Poster found for: %s",
                    anime_name
                )

                return poster_url

            logger.warning(
                "Jikan result has no poster: %s",
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

    # ----------------------------------------------------------------
    # NORMALIZE
    # ----------------------------------------------------------------

    @staticmethod
    def _normalize(
        text: str
    ) -> str:
        """Normalize title for matching."""

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
    # TITLE MATCH
    # ----------------------------------------------------------------

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

        # Exact match
        if (
            title_normalized
            == query_normalized
        ):
            return True

        # Query exists inside title
        if (
            query_normalized
            in title_normalized
        ):
            return True

        # All query words exist
        query_words = set(
            query_normalized.split()
        )

        title_words = set(
            title_normalized.split()
        )

        return query_words.issubset(
            title_words
        )

    # ----------------------------------------------------------------
    # CLEAN TITLE
    # ----------------------------------------------------------------

    @staticmethod
    def _clean_title(
        title: str
    ) -> str:
        """Remove unnecessary title text."""

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

    # ----------------------------------------------------------------
    # SEASON
    # ----------------------------------------------------------------

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

    # ----------------------------------------------------------------
    # LANGUAGES
    # ----------------------------------------------------------------

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

                found.append(
                    language
                )

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
            r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|"
            r"Sep|Oct|Nov|Dec)"
            r"\s+\d{4}\b",

            r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|"
            r"Sep|Oct|Nov|Dec)"
            r"\s+\d{1,2},\s+\d{4}\b",

            r"\b\d{1,2}"
            r"[/-]\d{1,2}"
            r"[/-]\d{2,4}\b",
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


# -------------------------------------------------------------------
# PUBLIC FUNCTION
# -------------------------------------------------------------------

def get_anime_info(
    anime_name: str
) -> Optional[Dict]:
    """Public helper used by Telegram bot."""

    return anime_scraper.search_anime(
        anime_name
    )
