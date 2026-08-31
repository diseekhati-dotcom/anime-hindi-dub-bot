"""
Anime information service.

Sources:
- AnimeDubHindi schedule: anime metadata
- MyAnimeList poster: through Jikan API

Provides:
- Anime name
- Hindi dub status
- Platform, when explicitly available
- Dubbed by / dubbing studio, when explicitly available
- Season
- Episode
- Languages
- Schedule
- Release date
- MAL poster through Jikan

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

SCHEDULE_URL = (
    "https://www.animedubhindi.link/schedule.php"
)

JIKAN_URL = (
    "https://api.jikan.moe/v4/anime"
)


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
                    "Anime not found in AnimeDubHindi schedule: %s",
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
        """
        Find matching anime on the schedule page.

        The schedule currently uses heading elements for
        anime titles, so headings are preferred over every
        link on the page.
        """

        # -----------------------------------------------------------
        # First search actual heading elements.
        # -----------------------------------------------------------

        elements = soup.find_all(
            [
                "h1",
                "h2",
                "h3",
                "h4",
                "h5",
            ]
        )

        # -----------------------------------------------------------
        # If headings are unavailable, search links.
        # -----------------------------------------------------------

        if not elements:

            elements = soup.find_all("a")

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

            # -------------------------------------------------------
            # FIND NEARBY INFORMATION CONTAINER
            # -------------------------------------------------------

            container = element

            best_text = ""

            for _ in range(8):

                if container.parent is None:
                    break

                container = container.parent

                text = container.get_text(
                    " ",
                    strip=True
                )

                # Keep the smallest useful container.
                if 30 <= len(text) <= 2500:

                    best_text = text

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

            if best_text:

                text = best_text

            else:

                text = element.get_text(
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
            # PLATFORM / DUB BY
            # -------------------------------------------------------

            platform = self._extract_platform(
                text,
                element
            )

            dub_by = self._extract_dub_by(
                text,
                element
            )

            return {
                "name": clean_title,

                "hindi_dub": (
                    "Available"
                    if "Hindi" in languages
                    else "Not Mentioned"
                ),

                "platform": platform,

                "dub_by": dub_by,

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
        text: str,
        element=None
    ) -> Optional[str]:
        """
        Extract a streaming platform only when it is
        explicitly present in the source HTML/text.
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

        # Search visible text.
        for platform in platforms:

            if re.search(
                rf"\b{re.escape(platform)}\b",
                text,
                re.I
            ):
                return platform

        # Search attributes around the anime element.
        if element is not None:

            try:

                attributes_text = " ".join(
                    str(value)
                    for value in element.attrs.values()
                )

                for platform in platforms:

                    if re.search(
                        rf"\b{re.escape(platform)}\b",
                        attributes_text,
                        re.I
                    ):
                        return platform

            except Exception:
                pass

        return None

    # ===============================================================
    # DUB BY
    # ===============================================================

    @staticmethod
    def _extract_dub_by(
        text: str,
        element=None
    ) -> Optional[str]:
        """
        Extract dubbing studio/network only when
        explicitly mentioned by the source.
        """

        patterns = [

            r"Dubbed\s*by\s*[:\-]?\s*([^|•\n]+)",

            r"Dub\s*by\s*[:\-]?\s*([^|•\n]+)",

            r"Dubbing\s*by\s*[:\-]?\s*([^|•\n]+)",

            r"Dubbing\s*Studio\s*[:\-]?\s*([^|•\n]+)",

            r"Dubbing\s*Studio\s*Name\s*[:\-]?\s*([^|•\n]+)",

            r"Studio\s*[:\-]?\s*([^|•\n]+)",
        ]

        for pattern in patterns:

            match = re.search(
                pattern,
                text,
                re.I
            )

            if match:

                value = match.group(1).strip()

                value = re.sub(
                    r"\s+",
                    " ",
                    value
                )

                if value and len(value) <= 100:

                    return value

        # Check nearby element attributes too.
        if element is not None:

            try:

                attributes_text = " ".join(
                    str(value)
                    for value in element.attrs.values()
                )

                for pattern in patterns:

                    match = re.search(
                        pattern,
                        attributes_text,
                        re.I
                    )

                    if match:

                        value = match.group(1).strip()

                        if value and len(value) <= 100:
                            return value

            except Exception:
                pass

        return None

    # ===============================================================
    # MAL POSTER THROUGH JIKAN
    # ===============================================================

    def _get_poster(
        self,
        anime_name: str
    ) -> Optional[str]:
        """
        Get the MyAnimeList poster through Jikan.

        Only the remote image URL is returned.
        The bot does not permanently store the image.
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
            # EXACT TITLE MATCH
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
            # WORD-BASED MATCH
            # -------------------------------------------------------

            if selected is None:

                query_words = set(
                    query.split()
                )

                for anime in data:

                    for title in self._get_titles(
                        anime
                    ):

                        title_words = set(
                            self._normalize(title).split()
                        )

                        if query_words.issubset(
                            title_words
                        ):

                            selected = anime
                            break

                    if selected:
                        break

            # -------------------------------------------------------
            # FALLBACK TO FIRST RESULT
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
                or jpg.get("small_image_url")
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
                exc,
                exc_info=True
            )

            return None

    # ===============================================================
    # MAL TITLES
    # ===============================================================

    @staticmethod
    def _get_titles(
        anime: Dict
    ) -> list:
        """Return useful titles from Jikan/MAL."""

        titles = []

        for key in (
            "title",
            "title_english",
            "title_japanese",
        ):

            value = anime.get(key)

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

    # ===============================================================
    # NORMALIZE
    # ===============================================================

    @staticmethod
    def _normalize(
        text: str
    ) -> str:
        """Normalize an anime title."""

        if not text:
            return ""

        text = text.lower()

        text = text.replace(
            "-",
            " "
        )

        text = text.replace(
            "–",
            " "
        )

        text = text.replace(
            "—",
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
            r"\bS\s*([0-9]+)\b",
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

            # 01 Oct 2026
            (
                r"\b\d{1,2}\s+"
                r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|"
                r"Sep|Oct|Nov|Dec)"
                r"\s+\d{4}\b"
            ),

            # Oct 01, 2026
            (
                r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|"
                r"Sep|Oct|Nov|Dec)"
                r"\s+\d{1,2},\s+\d{4}\b"
            ),

            # 01/10/2026
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
    """
    Public function used by commands.py.

    Returns anime information dictionary or None.
    """

    return anime_scraper.search_anime(
        anime_name
    )
