"""
Anime information service.

Live metadata sources:
- AnimeDubHindi schedule/category/post pages
    -> Hindi Dub
    -> Season
    -> Episode
    -> Languages
    -> Schedule
    -> Release Date
    -> Official Dub By
    -> Platform indicators when explicitly listed
- Jikan / MyAnimeList
    -> Poster
    -> Studio
    -> Anime identity

The bot does NOT download, store, or distribute anime episodes/files.
Only public metadata is read.
"""

import re
from typing import Dict, Optional, List
from urllib.parse import quote, urljoin

import requests
from bs4 import BeautifulSoup

from utils.logger import logger


# ===================================================================
# URLS
# ===================================================================

BASE_URL = "https://www.animedubhindi.link/"
SCHEDULE_URL = "https://www.animedubhindi.link/schedule.php"
JIKAN_URL = "https://api.jikan.moe/v4/anime"

# Public category pages used only for finding metadata.
SEARCH_PAGES = [
    BASE_URL,
    f"{BASE_URL}page/2/",
    f"{BASE_URL}category/series/",
    f"{BASE_URL}category/english/",
    f"{BASE_URL}category/language/hindi/",
    f"{BASE_URL}category/language/hindi/page/2/",
    f"{BASE_URL}category/language/hindi/page/3/",
]


# ===================================================================
# PLATFORM NAMES
# ===================================================================

PLATFORM_NAMES = [
    "Crunchyroll",
    "Netflix",
    "JioHotstar",
    "Jio Hotstar",
    "Amazon Prime Video",
    "Prime Video",
    "Amazon Prime",
    "Sony YAY",
    "Sony Yay",
    "Sony LIV",
    "MX Player",
    "YouTube",
    "Muse Asia",
    "Muse India",
    "Ani-One Asia",
    "Ani-One India",
    "Disney+",
    "Disney Plus",
    "Animax",
]


# ===================================================================
# PLATFORM ABBREVIATIONS FOUND ON SOURCE PAGES
# ===================================================================

PLATFORM_ABBREVIATIONS = {
    "NF": "Netflix",
    "AMZN": "Amazon Prime Video",
    "AMAZON": "Amazon Prime Video",
    "CR": "Crunchyroll",
}


class AnimeScraper:
    """Live anime metadata lookup service."""

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
        Search live AnimeDubHindi metadata and attach
        Jikan/MAL information.
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

        query = self._normalize(anime_name)

        try:

            # -------------------------------------------------------
            # 1. SEARCH SCHEDULE
            # -------------------------------------------------------

            result = self._search_schedule(
                query
            )

            # -------------------------------------------------------
            # 2. IF NOT FOUND, SEARCH SITE PAGES
            # -------------------------------------------------------

            if not result:

                result = self._search_site_pages(
                    query
                )

            if not result:

                logger.info(
                    "Anime not found: %s",
                    anime_name
                )

                return None

            # -------------------------------------------------------
            # 3. GET DETAILED SOURCE POST
            # -------------------------------------------------------

            detail_url = result.get(
                "detail_url"
            )

            if detail_url:

                detail_data = (
                    self._get_detail_information(
                        detail_url,
                        result["name"]
                    )
                )

                if detail_data:

                    result.update(
                        detail_data
                    )

            # -------------------------------------------------------
            # 4. JIKAN / MAL
            # -------------------------------------------------------

            mal_info = self._get_mal_info(
                result["name"]
            )

            if mal_info:

                result["poster_url"] = (
                    mal_info.get(
                        "poster_url"
                    )
                )

                result["studio"] = (
                    mal_info.get(
                        "studio"
                    )
                )

                result["mal_url"] = (
                    mal_info.get(
                        "mal_url"
                    )
                )

            else:

                result["poster_url"] = None
                result["studio"] = None
                result["mal_url"] = None

            # -------------------------------------------------------
            # 5. PLATFORM FALLBACK
            # -------------------------------------------------------

            if not result.get("platform"):

                result["platform"] = (
                    self._detect_platform(
                        result.get(
                            "raw_text",
                            ""
                        )
                    )
                )

            # -------------------------------------------------------
            # 6. CLEAN INTERNAL DATA
            # -------------------------------------------------------

            result.pop(
                "raw_text",
                None
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
    # SCHEDULE SEARCH
    # ===============================================================

    def _search_schedule(
        self,
        query: str
    ) -> Optional[Dict]:

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

                container = element

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

                    if (
                        "Hindi" in text
                        or "Episode" in text
                        or "Season" in text
                        or "EP" in text
                    ):
                        break

                text = container.get_text(
                    " ",
                    strip=True
                )

                clean_title = self._clean_title(
                    title
                )

                return {
                    "name": clean_title,

                    "hindi_dub": (
                        "Available"
                        if re.search(
                            r"\bHindi\b",
                            text,
                            re.I
                        )
                        else "Not Mentioned"
                    ),

                    "platform": None,

                    "dub_by": None,

                    "hindi_details": (
                        "Hindi language listed "
                        "on AnimeDubHindi schedule."
                        if re.search(
                            r"\bHindi\b",
                            text,
                            re.I
                        )
                        else None
                    ),

                    "studio": None,

                    "season": self._extract_season(
                        text
                    ),

                    "episodes": self._extract_episode(
                        text
                    ),

                    "languages": self._languages_string(
                        self._extract_languages(
                            text
                        )
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

                    "detail_url": (
                        element.get("href")
                        if element.name == "a"
                        else None
                    ),

                    "raw_text": text,
                }

        except Exception as exc:

            logger.warning(
                "Schedule search failed: %s",
                exc
            )

        return None

    # ===============================================================
    # SITE PAGE SEARCH
    # ===============================================================

    def _search_site_pages(
        self,
        query: str
    ) -> Optional[Dict]:

        for page_url in SEARCH_PAGES:

            try:

                response = self.session.get(
                    page_url,
                    timeout=15
                )

                if response.status_code != 200:
                    continue

                soup = BeautifulSoup(
                    response.text,
                    "html.parser"
                )

                # WordPress-style article links.
                links = soup.find_all(
                    "a",
                    href=True
                )

                for link in links:

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

                    href = link.get(
                        "href"
                    )

                    if not href:
                        continue

                    detail_url = urljoin(
                        BASE_URL,
                        href
                    )

                    clean_title = (
                        self._clean_title_from_post_title(
                            title
                        )
                    )

                    return {
                        "name": clean_title,
                        "hindi_dub": "Available",
                        "platform": None,
                        "dub_by": None,
                        "hindi_details": (
                            "Hindi language listed "
                            "on AnimeDubHindi."
                        ),
                        "studio": None,
                        "season": None,
                        "episodes": None,
                        "languages": None,
                        "schedule": None,
                        "release_date": None,
                        "source": "AnimeDubHindi",
                        "source_link": SCHEDULE_URL,
                        "poster_url": None,
                        "mal_url": None,
                        "detail_url": detail_url,
                        "raw_text": title,
                    }

            except Exception as exc:

                logger.debug(
                    "Site page search failed %s: %s",
                    page_url,
                    exc
                )

        return None

    # ===============================================================
    # DETAIL PAGE
    # ===============================================================

    def _get_detail_information(
        self,
        detail_url: str,
        anime_name: str
    ) -> Optional[Dict]:
        """
        Read metadata from the anime article page.

        Only text metadata is extracted.
        No episode/file links are used.
        """

        try:

            response = self.session.get(
                detail_url,
                timeout=20
            )

            response.raise_for_status()

            soup = BeautifulSoup(
                response.text,
                "html.parser"
            )

            # Remove scripts/styles.
            for tag in soup.find_all(
                ["script", "style", "noscript"]
            ):
                tag.decompose()

            text = soup.get_text(
                " ",
                strip=True
            )

            # -------------------------------------------------------
            # Official Dub By
            # -------------------------------------------------------

            dub_by = self._extract_dub_by(
                text
            )

            # -------------------------------------------------------
            # Platform
            # -------------------------------------------------------

            platform = self._extract_platform(
                text
            )

            # -------------------------------------------------------
            # Sometimes platform is encoded in title.
            # -------------------------------------------------------

            if not platform:

                platform = self._detect_platform(
                    soup.title.get_text(
                        " ",
                        strip=True
                    )
                    if soup.title
                    else ""
                )

            # -------------------------------------------------------
            # Languages
            # -------------------------------------------------------

            languages = self._extract_languages(
                text
            )

            # -------------------------------------------------------
            # Season / Episode
            # -------------------------------------------------------

            season = self._extract_season(
                text
            )

            episode = self._extract_episode(
                text
            )

            # -------------------------------------------------------
            # Date
            # -------------------------------------------------------

            release_date = self._extract_date(
                text
            )

            return {
                "platform": platform,

                "dub_by": dub_by,

                "hindi_details": (
                    f"Official Dub By: {dub_by}"
                    if dub_by
                    else (
                        "Hindi language listed "
                        "on AnimeDubHindi."
                    )
                ),

                "season": (
                    season
                    if season
                    else None
                ),

                "episodes": (
                    episode
                    if episode
                    else None
                ),

                "languages": (
                    self._languages_string(
                        languages
                    )
                    if languages
                    else None
                ),

                "release_date": (
                    release_date
                    if release_date
                    else None
                ),

                "raw_text": text,
            }

        except Exception as exc:

            logger.warning(
                "Detail page failed for %s: %s",
                anime_name,
                exc
            )

            return None

    # ===============================================================
    # DUB BY
    # ===============================================================

    @staticmethod
    def _extract_dub_by(
        text: str
    ) -> Optional[str]:
        """
        Extract explicitly written Official Dub By / Dub By.
        """

        patterns = [
            r"Official\s+Dub\s+By\s*[:\-]?\s*"
            r"(.{1,100}?)(?=\s+(?:Encoder|Quality|"
            r"Subtitle|Audio|Genres|Total|IMDb|$))",

            r"Dubbed\s+By\s*[:\-]?\s*"
            r"(.{1,100}?)(?=\s+(?:Encoder|Quality|"
            r"Subtitle|Audio|Genres|Total|IMDb|$))",

            r"Dub\s+By\s*[:\-]?\s*"
            r"(.{1,100}?)(?=\s+(?:Encoder|Quality|"
            r"Subtitle|Audio|Genres|Total|IMDb|$))",

            r"Official\s+Dubbing\s+By\s*[:\-]?\s*"
            r"(.{1,100}?)(?=\s+(?:Encoder|Quality|"
            r"Subtitle|Audio|Genres|Total|IMDb|$))",
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

                value = value.strip(
                    " :-|•,"
                )

                if value and len(value) < 100:

                    return value

        return None

    # ===============================================================
    # PLATFORM FALLBACK
    # ===============================================================

    @staticmethod
    def _detect_platform(
        text: str
    ) -> Optional[str]:

        if not text:
            return None

        found = []

        for platform in PLATFORM_NAMES:

            if re.search(
                re.escape(platform),
                text,
                re.I
            ):

                found.append(
                    platform
                )

        for abbreviation, platform in (
            PLATFORM_ABBREVIATIONS.items()
        ):

            if re.search(
                rf"\b{re.escape(abbreviation)}\b",
                text,
                re.I
            ):

                found.append(
                    platform
                )

        if not found:
            return None

        return " • ".join(
            dict.fromkeys(found)
        )

    # ===============================================================
    # MAL / JIKAN
    # ===============================================================

    def _get_mal_info(
        self,
        anime_name: str
    ) -> Optional[Dict]:

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

            # Exact match first.
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

            # Word match fallback.
            if selected is None:

                for anime in data:

                    titles = self._get_titles(
                        anime
                    )

                    for title in titles:

                        if self._title_matches(
                            title,
                            query
                        ):

                            selected = anime
                            break

                    if selected:
                        break

            # Final fallback.
            if selected is None:
                selected = data[0]

            # -------------------------------------------------------
            # POSTER
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
                jpg.get(
                    "large_image_url"
                )
                or jpg.get(
                    "image_url"
                )
            )

            # -------------------------------------------------------
            # MAL URL
            # -------------------------------------------------------

            mal_url = selected.get(
                "url"
            )

            # -------------------------------------------------------
            # STUDIO
            # -------------------------------------------------------

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

    @staticmethod
    def _clean_title_from_post_title(
        title: str
    ) -> str:

        # Remove common metadata after anime name.
        patterns = [
            r"\s+Season\s+\d+.*$",
            r"\s+S\d+.*$",
            r"\s+Hindi.*$",
        ]

        cleaned = title

        for pattern in patterns:

            cleaned = re.sub(
                pattern,
                "",
                cleaned,
                flags=re.I
            )

        return cleaned.strip()

    # ===============================================================
    # SEASON
    # ===============================================================

    @staticmethod
    def _extract_season(
        text: str
    ) -> Optional[str]:

        patterns = [
            r"\bSeason\s*([0-9]+)\b",
            r"\bS([0-9]+)\b",
            r"\bSeason\s*([0-9]+)\s*Part",
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

        # Handle S1 P4 style.
        match = re.search(
            r"\bS([0-9]+)\s+P([0-9]+)\b",
            text,
            re.I
        )

        if match:

            return (
                f"Season {match.group(1)} "
                f"Part {match.group(2)}"
            )

        return None

    # ===============================================================
    # EPISODE
    # ===============================================================

    @staticmethod
    def _extract_episode(
        text: str
    ) -> Optional[str]:

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

        possible_languages = [
            "Hindi",
            "Tamil",
            "Telugu",
            "Bangla",
            "Bengali",
            "English",
            "Japanese",
            "Chinese",
            "Korean",
            "Malayalam",
            "Kannada",
            "Marathi",
        ]

        found = []

        for language in possible_languages:

            if re.search(
                rf"\b{re.escape(language)}\b",
                text,
                re.I
            ):

                # Normalize Bengali naming.
                if (
                    language == "Bengali"
                    and "Bangla" in found
                ):
                    continue

                found.append(
                    language
                )

        return found

    @staticmethod
    def _languages_string(
        languages: List[str]
    ) -> Optional[str]:

        if not languages:
            return None

        return " • ".join(
            dict.fromkeys(
                languages
            )
        )

    # ===============================================================
    # SCHEDULE
    # ===============================================================

    @staticmethod
    def _extract_schedule(
        text: str
    ) -> Optional[str]:

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
