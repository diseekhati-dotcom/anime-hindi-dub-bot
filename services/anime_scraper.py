"""
Anime information service.

Sources:
- AnimeDubHindi: Hindi-dub information and available anime data
- Jikan / MyAnimeList: anime identity, poster and studio

The bot does NOT download or distribute anime episodes.
"""

import re
from typing import Dict, Optional, List
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

from utils.logger import logger


SITE_URL = "https://www.animedubhindi.link/"
SCHEDULE_URL = "https://www.animedubhindi.link/schedule.php"
JIKAN_URL = "https://api.jikan.moe/v4/anime"

REQUEST_TIMEOUT = 8


class AnimeScraper:

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

    # ================================================================
    # MAIN SEARCH
    # ================================================================

    def search_anime(
        self,
        anime_name: str
    ) -> Optional[Dict]:

        anime_name = anime_name.strip()

        if not anime_name:
            return None

        logger.info(
            "Anime search: %s",
            anime_name
        )

        query = self._normalize(anime_name)

        # ------------------------------------------------------------
        # AnimeDubHindi
        # ------------------------------------------------------------

        result = self._search_page(
            SCHEDULE_URL,
            query
        )

        # ------------------------------------------------------------
        # Site search
        # ------------------------------------------------------------

        if not result:

            result = self._search_site(
                anime_name,
                query
            )

        # ------------------------------------------------------------
        # MAL/Jikan
        # ------------------------------------------------------------

        mal_info = self._get_mal_info(
            anime_name
        )

        # ------------------------------------------------------------
        # Nothing found
        # ------------------------------------------------------------

        if not result and not mal_info:
            return None

        # ------------------------------------------------------------
        # AnimeDubHindi result
        # ------------------------------------------------------------

        if result:

            if mal_info:

                result["poster_url"] = (
                    mal_info.get("poster_url")
                )

                result["studio"] = (
                    mal_info.get("studio")
                )

                result["mal_url"] = (
                    mal_info.get("mal_url")
                )

            return result

        # ------------------------------------------------------------
        # MAL-only result
        # ------------------------------------------------------------

        return {
            "name": (
                mal_info.get("name")
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

            "poster_url": mal_info.get(
                "poster_url"
            ),

            "mal_url": mal_info.get(
                "mal_url"
            ),

            "source": "DC",
        }

    # ================================================================
    # PAGE SEARCH
    # ================================================================

    def _search_page(
        self,
        url: str,
        query: str
    ) -> Optional[Dict]:

        try:

            response = self.session.get(
                url,
                timeout=REQUEST_TIMEOUT
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

            logger.warning(
                "Page search failed: %s",
                exc
            )

            return None

    # ================================================================
    # WEBSITE SEARCH
    # ================================================================

    def _search_site(
        self,
        anime_name: str,
        query: str
    ) -> Optional[Dict]:

        search_url = (
            SITE_URL
            + "?s="
            + quote(anime_name)
        )

        try:

            response = self.session.get(
                search_url,
                timeout=REQUEST_TIMEOUT
            )

            response.raise_for_status()

            soup = BeautifulSoup(
                response.text,
                "html.parser"
            )

            # First inspect search page itself.
            result = self._find_anime(
                soup,
                query
            )

            if result:
                return result

            # Do NOT crawl every link.
            # This prevents the huge 10-minute delay.
            #
            # Only inspect a small number of matching links.

            checked = 0

            for link in soup.find_all(
                "a",
                href=True
            ):

                title = link.get_text(
                    " ",
                    strip=True
                )

                if not title:
                    continue

                if len(title) > 250:
                    continue

                if not self._title_matches(
                    title,
                    query
                ):
                    continue

                href = link.get("href")

                if not href:
                    continue

                if not href.startswith(
                    SITE_URL
                ):
                    continue

                try:

                    article = self.session.get(
                        href,
                        timeout=REQUEST_TIMEOUT
                    )

                    if article.status_code != 200:
                        continue

                    article_soup = (
                        BeautifulSoup(
                            article.text,
                            "html.parser"
                        )
                    )

                    result = self._find_anime(
                        article_soup,
                        query
                    )

                    if result:
                        return result

                except Exception:
                    pass

                checked += 1

                if checked >= 2:
                    break

        except Exception as exc:

            logger.warning(
                "Site search failed: %s",
                exc
            )

        return None

    # ================================================================
    # FIND ANIME
    # ================================================================

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

        best = None

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

                best = element
                break

        if best is None:
            return None

        title = self._clean_title(
            best.get_text(
                " ",
                strip=True
            )
        )

        # ------------------------------------------------------------
        # Small container only
        # ------------------------------------------------------------

        container = best

        for _ in range(6):

            if container.parent is None:
                break

            parent = container.parent

            text = parent.get_text(
                " ",
                strip=True
            )

            if len(text) <= 2500:
                container = parent
            else:
                break

        text = container.get_text(
            " ",
            strip=True
        )

        languages = (
            self._extract_languages(text)
        )

        return {
            "name": title,

            "hindi_dub": (
                "Available"
                if "Hindi" in languages
                else "Not Mentioned"
            ),

            "platform": self._extract_platform(
                text
            ),

            "dub_by": self._extract_dub_by(
                text
            ),

            "studio": None,

            "hindi_details": (
                "Hindi dub information found."
                if "Hindi" in languages
                else None
            ),

            "season": self._extract_season(
                text
            ),

            "episodes": self._extract_episode(
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

            "poster_url": None,

            "mal_url": None,

            "source": "DC",
        }

    # ================================================================
    # PLATFORM
    # ================================================================

    @staticmethod
    def _extract_platform(
        text: str
    ) -> Optional[str]:

        platforms = [
            "Amazon Prime Video",
            "Prime Video",
            "Crunchyroll",
            "Netflix",
            "JioHotstar",
            "Jio Hotstar",
            "Sony YAY",
            "Sony Yay",
            "MX Player",
            "YouTube",
            "Animax",
            "Disney+",
            "Disney Plus",
        ]

        found = []

        for platform in platforms:

            if re.search(
                rf"\b{re.escape(platform)}\b",
                text,
                re.I
            ):

                found.append(platform)

        return (
            " • ".join(
                dict.fromkeys(found)
            )
            if found
            else None
        )

    # ================================================================
    # DUB BY
    # ================================================================

    @staticmethod
    def _extract_dub_by(
        text: str
    ) -> Optional[str]:

        patterns = [
            r"Dubbed\s+By\s*[:\-]?\s*([^|•\n]+)",
            r"Dub\s+By\s*[:\-]?\s*([^|•\n]+)",
            r"Dubbing\s+By\s*[:\-]?\s*([^|•\n]+)",
            r"Dubbing\s+Studio\s*[:\-]?\s*([^|•\n]+)",
            r"Dub\s+Studio\s*[:\-]?\s*([^|•\n]+)",
        ]

        for pattern in patterns:

            match = re.search(
                pattern,
                text,
                re.I
            )

            if not match:
                continue

            value = re.sub(
                r"\s+",
                " ",
                match.group(1)
            ).strip()

            if 0 < len(value) <= 120:
                return value

        return None

    # ================================================================
    # MAL / JIKAN
    # ================================================================

    def _get_mal_info(
        self,
        anime_name: str
    ) -> Optional[Dict]:

        try:

            response = self.session.get(
                JIKAN_URL,
                params={
                    "q": anime_name,
                    "limit": 5,
                    "sfw": "true",
                },
                timeout=REQUEST_TIMEOUT
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

            # Exact match first.
            for anime in data:

                titles = self._get_titles(
                    anime
                )

                if any(
                    self._normalize(title)
                    == query
                    for title in titles
                ):
                    selected = anime
                    break

            # Partial match.
            if selected is None:

                for anime in data:

                    titles = self._get_titles(
                        anime
                    )

                    for title in titles:

                        normalized = (
                            self._normalize(title)
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

            # Poster.
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

            # Studio.
            studio_names = []

            for item in selected.get(
                "studios",
                []
            ):

                if isinstance(
                    item,
                    dict
                ):

                    name = item.get(
                        "name"
                    )

                    if name:
                        studio_names.append(
                            name
                        )

            studio = (
                " • ".join(
                    dict.fromkeys(
                        studio_names
                    )
                )
                if studio_names
                else None
            )

            return {
                "name": (
                    selected.get("title")
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
                "Jikan failed for %s: %s",
                anime_name,
                exc
            )

            return None

    # ================================================================
    # TITLES
    # ================================================================

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

            value = anime.get(key)

            if value:
                titles.append(value)

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
                    titles.append(value)

        return titles

    # ================================================================
    # NORMALIZE
    # ================================================================

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

    # ================================================================
    # TITLE MATCH
    # ================================================================

    @staticmethod
    def _title_matches(
        title: str,
        query: str
    ) -> bool:

        title_n = AnimeScraper._normalize(
            title
        )

        query_n = AnimeScraper._normalize(
            query
        )

        if not query_n:
            return False

        if title_n == query_n:
            return True

        if query_n in title_n:
            return True

        return set(
            query_n.split()
        ).issubset(
            set(title_n.split())
        )

    # ================================================================
    # CLEAN TITLE
    # ================================================================

    @staticmethod
    def _clean_title(
        title: str
    ) -> str:

        # Remove common source/download suffixes.
        patterns = [
            r"\s*[-|–]\s*AnimeDubHindi.*$",
            r"\s+Hindi\s+Dub.*$",
            r"\s+Download.*$",
            r"\s+\{.*?\}$",
        ]

        for pattern in patterns:

            title = re.sub(
                pattern,
                "",
                title,
                flags=re.I
            )

        return re.sub(
            r"\s+",
            " ",
            title
        ).strip()

    # ================================================================
    # SEASON
    # ================================================================

    @staticmethod
    def _extract_season(
        text: str
    ) -> Optional[str]:

        matches = re.findall(
            r"\bSeason\s*([0-9]+)\b",
            text,
            re.I
        )

        if not matches:
            matches = re.findall(
                r"\bS([0-9]+)\b",
                text,
                re.I
            )

        if not matches:
            return None

        numbers = sorted(
            set(matches),
            key=int
        )

        return ", ".join(numbers)

    # ================================================================
    # EPISODE
    # ================================================================

    @staticmethod
    def _extract_episode(
        text: str
    ) -> Optional[str]:

        patterns = [
            r"\bEpisode\s*([0-9]+(?:-[0-9]+)?)",
            r"\bEP\s*([0-9]+(?:-[0-9]+)?)",
            r"\bEp\.\s*([0-9]+(?:-[0-9]+)?)",
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

    # ================================================================
    # LANGUAGES
    # ================================================================

    @staticmethod
    def _extract_languages(
        text: str
    ) -> List[str]:

        languages = [
            "Hindi",
            "English",
            "Tamil",
            "Telugu",
            "Japanese",
            "Malayalam",
            "Kannada",
            "Bengali",
            "Chinese",
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

    # ================================================================
    # SCHEDULE
    # ================================================================

    @staticmethod
    def _extract_schedule(
        text: str
    ) -> Optional[str]:

        days = (
            "Monday",
            "Tuesday",
            "Wednesday",
            "Thursday",
            "Friday",
            "Saturday",
            "Sunday",
            "Daily",
        )

        pattern = (
            r"\b("
            + "|".join(days)
            + r")\b.*?"
            r"([0-9]{1,2}:"
            r"[0-9]{2}\s*[AP]M)"
        )

        match = re.search(
            pattern,
            text,
            re.I
        )

        if match:

            return (
                f"{match.group(1)} "
                f"{match.group(2)}"
            )

        return None

    # ================================================================
    # DATE
    # ================================================================

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
