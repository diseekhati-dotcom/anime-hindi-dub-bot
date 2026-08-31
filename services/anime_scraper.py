"""
Anime information service.

Source:
- AnimeDubHindi schedule for anime metadata
- AnimeDubHindi anime pages for official dub information
- Jikan API (MyAnimeList data) for posters

The bot only returns anime metadata.
No anime episodes, watch links, or download links are handled.
"""

import re
from typing import Dict, Optional

import requests
from bs4 import BeautifulSoup

from utils.logger import logger


SCHEDULE_URL = "https://www.animedubhindi.link/schedule.php"
SITE_URL = "https://www.animedubhindi.link"
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

    # ===============================================================
    # MAIN SEARCH
    # ===============================================================

    def search_anime(
        self,
        anime_name: str
    ) -> Optional[Dict]:
        """Search anime and return complete metadata."""

        if not anime_name:
            return None

        anime_name = anime_name.strip()

        if not anime_name:
            return None

        query = self._normalize(anime_name)

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

            # -------------------------------------------------------
            # POSTER
            # -------------------------------------------------------

            result["poster_url"] = self._get_poster(
                result["name"]
            )

            # -------------------------------------------------------
            # OFFICIAL DUB INFORMATION
            # -------------------------------------------------------

            dub_info = self._find_dub_information(
                result["name"]
            )

            if dub_info:
                if dub_info.get("platform"):
                    result["platform"] = dub_info["platform"]

                if dub_info.get("dub_by"):
                    result["dub_by"] = dub_info["dub_by"]

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
    # FIND ANIME ON SCHEDULE
    # ===============================================================

    def _find_anime(
        self,
        soup: BeautifulSoup,
        query: str
    ) -> Optional[Dict]:
        """Find anime from AnimeDubHindi schedule."""

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

            if len(title) > 200:
                continue

            if not self._title_matches(
                title,
                query
            ):
                continue

            # -------------------------------------------------------
            # FIND NEARBY CARD
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
            }

        return None

    # ===============================================================
    # DUB INFORMATION
    # ===============================================================

    def _find_dub_information(
        self,
        anime_name: str
    ) -> Optional[Dict]:
        """
        Search AnimeDubHindi's indexed anime pages.

        Looks for information such as:
        Official Dub By: Crunchyroll
        Official Dub By: AnimeTimes
        Official Dub By: Muse India
        """

        try:

            query = self._normalize(
                anime_name
            )

            # Search AnimeDubHindi site using its
            # WordPress-style search endpoint.
            search_url = (
                f"{SITE_URL}/?s="
                + requests.utils.quote(
                    anime_name
                )
            )

            response = self.session.get(
                search_url,
                timeout=15
            )

            if response.status_code != 200:
                return None

            soup = BeautifulSoup(
                response.text,
                "html.parser"
            )

            # -------------------------------------------------------
            # FIND LINKS
            # -------------------------------------------------------

            links = soup.find_all(
                "a",
                href=True
            )

            candidates = []

            for link in links:

                text = link.get_text(
                    " ",
                    strip=True
                )

                href = link.get(
                    "href"
                )

                if not href:
                    continue

                if not text:
                    continue

                normalized = self._normalize(
                    text
                )

                if (
                    query in normalized
                    or normalized in query
                ):
                    candidates.append(
                        href
                    )

            # Remove duplicate URLs.
            candidates = list(
                dict.fromkeys(
                    candidates
                )
            )

            # -------------------------------------------------------
            # OPEN CANDIDATE PAGES
            # -------------------------------------------------------

            for url in candidates[:10]:

                try:

                    page = self.session.get(
                        url,
                        timeout=12
                    )

                    if page.status_code != 200:
                        continue

                    page_soup = BeautifulSoup(
                        page.text,
                        "html.parser"
                    )

                    page_text = page_soup.get_text(
                        " ",
                        strip=True
                    )

                    if not re.search(
                        r"Official\s+Dub\s+By",
                        page_text,
                        re.I
                    ):
                        continue

                    dub_by = self._extract_dub_by(
                        page_text
                    )

                    platform = self._extract_platform(
                        page_text
                    )

                    if dub_by or platform:

                        logger.info(
                            "Dub information found for %s: "
                            "platform=%s dub_by=%s",
                            anime_name,
                            platform,
                            dub_by
                        )

                        return {
                            "platform": platform,
                            "dub_by": dub_by,
                        }

                except Exception as exc:

                    logger.debug(
                        "Dub page check failed: %s",
                        exc
                    )

            return None

        except Exception as exc:

            logger.warning(
                "Dub information search failed for %s: %s",
                anime_name,
                exc
            )

            return None

    # ===============================================================
    # EXTRACT DUB BY
    # ===============================================================

    @staticmethod
    def _extract_dub_by(
        text: str
    ) -> Optional[str]:
        """Extract Official Dub By value."""

        patterns = [
            r"Official\s+Dub\s+By\s*:\s*"
            r"(.+?)(?=\s+Encoder\s*:|\s+Download|\s+Watch|$)",

            r"Official\s+Dub\s+By\s+"
            r"(.+?)(?=\s+Encoder\s*:|\s+Download|\s+Watch|$)",
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

                if value:
                    return value

        return None

    # ===============================================================
    # EXTRACT PLATFORM
    # ===============================================================

    @staticmethod
    def _extract_platform(
        text: str
    ) -> Optional[str]:
        """
        Extract platform when explicitly present.

        Examples:
        Platform: Crunchyroll
        Official Platform: Sony YAY
        """

        patterns = [
            r"(?:Official\s+)?Platform\s*:\s*"
            r"(.+?)(?=\s+Official\s+Dub\s+By|\s+Dub\s+By|"
            r"\s+Encoder\s*:|\s+Download|\s+Watch|$)",

            r"Official\s+Platform\s*:\s*"
            r"(.+?)(?=\s+Official\s+Dub\s+By|\s+Encoder\s*:|$)",
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
        Get MyAnimeList poster through Jikan.

        The bot only uses the remote image URL.
        """

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
                return None

            query = self._normalize(
                anime_name
            )

            selected = None

            # -------------------------------------------------------
            # EXACT MATCH
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

    # ===============================================================
    # MAL TITLES
    # ===============================================================

    @staticmethod
    def _get_titles(
        anime: Dict
    ) -> list:
        """Get all useful titles from Jikan/MAL."""

        titles = []

        for key in (
            "title",
            "title_english",
            "title_japanese"
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

    # ===============================================================
    # NORMALIZE
    # ===============================================================

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

    # ===============================================================
    # TITLE MATCH
    # ===============================================================

    @staticmethod
    def _title_matches(
        title: str,
        query: str
    ) -> bool:
        """Check anime title."""

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

        if title_normalized == query_normalized:
            return True

        if query_normalized in title_normalized:
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
                
