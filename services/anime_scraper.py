"""
Anime metadata scraper.

Sources:
- AnimeDubHindi:
    Hindi Dub status
    Season
    Episode
    Languages
    Schedule
    Release Date
    Explicit Dub By / platform tags
    Old/completed and ongoing anime posts

- Official streaming / official YouTube pages:
    Platform
    Explicitly listed audio language
    Season information when publicly visible
    Dub By / official channel information when explicitly visible

- Jikan / MyAnimeList:
    Anime title
    Poster
    Animation studio
    Total episode count

Important:
- No anime episodes are downloaded.
- No watch/download links are returned.
- Only metadata is processed.
- Source displayed to users is only "DC".
"""

import html
import re
from typing import Dict, List, Optional
from urllib.parse import quote, unquote, urljoin

import requests
from bs4 import BeautifulSoup

from utils.logger import logger


# =====================================================================
# URLS
# =====================================================================

SITE_URL = "https://www.animedubhindi.link/"
SCHEDULE_URL = f"{SITE_URL}schedule.php"
JIKAN_URL = "https://api.jikan.moe/v4/anime"


# =====================================================================
# OFFICIAL SOURCES
# =====================================================================

OFFICIAL_SOURCES = {
    "Crunchyroll": [
        "crunchyroll.com",
    ],
    "Netflix": [
        "netflix.com",
    ],
    "JioHotstar": [
        "hotstar.com",
        "jiohotstar.com",
    ],
    "Amazon Prime Video": [
        "primevideo.com",
        "amazon.com",
    ],
    "Sony YAY": [
        "sonyliv.com",
    ],
    "MX Player": [
        "mxplayer.in",
    ],
    "Muse India": [
        "youtube.com",
        "museindia.in",
    ],
    "Anime Times": [
        "youtube.com",
        "animetimes.co.jp",
    ],
    "Ani-One": [
        "youtube.com",
        "ani-one.com",
    ],
    "YouTube": [
        "youtube.com",
    ],
}


# =====================================================================
# PLATFORM TAGS FOUND ON ANIME DUB HINDI
# =====================================================================

PLATFORM_TAGS = {
    "cr dub": "Crunchyroll",
    "crunchyroll dub": "Crunchyroll",
    "crunchyroll": "Crunchyroll",
    "cr": "Crunchyroll",

    "nf dub": "Netflix",
    "netflix dub": "Netflix",
    "netflix": "Netflix",
    "nf": "Netflix",

    "amzn dub": "Amazon Prime Video",
    "amazon prime video": "Amazon Prime Video",
    "prime video": "Amazon Prime Video",
    "amzn": "Amazon Prime Video",

    "hotstar": "JioHotstar",
    "jiohotstar": "JioHotstar",
    "jio hotstar": "JioHotstar",

    "sony yay": "Sony YAY",
    "sony liv": "Sony LIV",

    "mx player": "MX Player",

    "muse dub": "Muse India",
    "muse india": "Muse India",

    "anime times": "Anime Times",
    "anime time": "Anime Times",

    "ani-one": "Ani-One",
    "ani one": "Ani-One",
}


# =====================================================================
# LANGUAGE NAMES
# =====================================================================

LANGUAGES = [
    "Hindi",
    "English",
    "Tamil",
    "Telugu",
    "Japanese",
    "Korean",
    "Chinese",
    "Malayalam",
    "Kannada",
    "Marathi",
    "Bengali",
    "Bangla",
]


class AnimeScraper:
    """Live anime information lookup service."""

    # =================================================================
    # INIT
    # =================================================================

    def __init__(self) -> None:

        self.session = requests.Session()

        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Linux; Android 14) "
                    "AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/131.0 "
                    "Mobile Safari/537.36"
                ),
                "Accept-Language": (
                    "en-IN,en;q=0.9"
                ),
            }
        )

    # =================================================================
    # MAIN SEARCH
    # =================================================================

    def search_anime(
        self,
        anime_name: str,
    ) -> Optional[Dict]:

        anime_name = (
            anime_name or ""
        ).strip()

        if not anime_name:
            return None

        query = self._normalize(
            anime_name
        )

        logger.info(
            "Anime search started: %s",
            anime_name
        )

        # -------------------------------------------------------------
        # AnimeDubHindi
        # -------------------------------------------------------------

        result = self._find_animedubhindi(
            anime_name,
            query
        )

        # -------------------------------------------------------------
        # MAL / Jikan
        # -------------------------------------------------------------

        mal = self._get_mal_info(
            anime_name
        )

        # -------------------------------------------------------------
        # If neither source knows the anime
        # -------------------------------------------------------------

        if not result and not mal:

            logger.info(
                "Anime not found: %s",
                anime_name
            )

            return None

        # -------------------------------------------------------------
        # Build fallback result from MAL
        # -------------------------------------------------------------

        if not result:

            result = {
                "name": (
                    mal.get("name")
                    if mal
                    else anime_name
                ),

                "hindi_dub": "Not Verified",

                "platform": None,

                "platform_entries": [],

                "dub_by": None,

                "studio": (
                    mal.get("studio")
                    if mal
                    else None
                ),

                "hindi_details": None,

                "season": None,

                "episodes": (
                    mal.get("episodes")
                    if mal
                    else None
                ),

                "languages": None,

                "schedule": None,

                "release_date": None,

                "poster_url": (
                    mal.get("poster_url")
                    if mal
                    else None
                ),

                "mal_url": (
                    mal.get("mal_url")
                    if mal
                    else None
                ),

                "source": "DC",

                "source_link": None,
            }

        # -------------------------------------------------------------
        # Merge MAL
        # -------------------------------------------------------------

        if mal:

            # Prefer the real MAL title.
            if (
                not result.get("name")
                or self._is_generic_title(
                    result.get("name")
                )
            ):
                result["name"] = (
                    mal.get("name")
                    or anime_name
                )

            result["poster_url"] = (
                mal.get("poster_url")
                or result.get("poster_url")
            )

            result["studio"] = (
                mal.get("studio")
                or result.get("studio")
            )

            result["mal_url"] = (
                mal.get("mal_url")
            )

            if not result.get("episodes"):
                result["episodes"] = (
                    mal.get("episodes")
                )

        # -------------------------------------------------------------
        # Check official OTT / YouTube sources
        # -------------------------------------------------------------

        official = self._check_official_sources(
            result.get(
                "name",
                anime_name
            )
        )

        result["platform_entries"] = (
            self._dedupe_platform_entries(
                result.get(
                    "platform_entries",
                    []
                )
                + official.get(
                    "platform_entries",
                    []
                )
            )
        )

        result["platform"] = (
            self._platform_summary(
                result["platform_entries"]
            )
        )

        # Explicit Dub By only.
        if official.get("dub_by"):
            result["dub_by"] = (
                official["dub_by"]
            )

        # -------------------------------------------------------------
        # Final source name
        # -------------------------------------------------------------

        result["source"] = "DC"
        result["source_link"] = None

        return result

    # =================================================================
    # ANIMEDUBHINDI SEARCH
    # =================================================================

    def _find_animedubhindi(
        self,
        anime_name: str,
        query: str,
    ) -> Optional[Dict]:

        # -------------------------------------------------------------
        # Current schedule
        # -------------------------------------------------------------

        schedule_result = self._search_schedule(
            query
        )

        if schedule_result:
            return schedule_result

        # -------------------------------------------------------------
        # Site search
        # -------------------------------------------------------------

        search_result = self._search_site_search(
            anime_name,
            query
        )

        if search_result:
            return search_result

        # -------------------------------------------------------------
        # Search engine fallback restricted to the site.
        # This helps with old/completed posts.
        # -------------------------------------------------------------

        engine_result = self._search_engine_for_site(
            anime_name,
            query
        )

        if engine_result:
            return engine_result

        return None

    # =================================================================
    # SCHEDULE
    # =================================================================

    def _search_schedule(
        self,
        query: str,
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

            return self._parse_matching_page(
                soup,
                query,
                SCHEDULE_URL
            )

        except Exception as exc:

            logger.warning(
                "Schedule search failed: %s",
                exc
            )

            return None

    # =================================================================
    # WORDPRESS SITE SEARCH
    # =================================================================

    def _search_site_search(
        self,
        anime_name: str,
        query: str,
    ) -> Optional[Dict]:

        search_url = (
            SITE_URL
            + "?s="
            + quote(anime_name)
        )

        try:

            response = self.session.get(
                search_url,
                timeout=20,
                allow_redirects=True
            )

            if response.status_code != 200:
                return None

            soup = BeautifulSoup(
                response.text,
                "html.parser"
            )

            # ---------------------------------------------------------
            # DO NOT treat page title like:
            # "Search Results for: Naruto"
            # as the anime itself.
            # ---------------------------------------------------------

            candidates = []

            for link in soup.find_all(
                "a",
                href=True
            ):

                title = link.get_text(
                    " ",
                    strip=True
                )

                href = link.get(
                    "href"
                )

                if not title or not href:
                    continue

                if len(title) > 300:
                    continue

                if self._is_generic_title(
                    title
                ):
                    continue

                if not self._title_matches(
                    title,
                    query
                ):
                    continue

                full_url = urljoin(
                    SITE_URL,
                    href
                )

                if not full_url.startswith(
                    SITE_URL
                ):
                    continue

                candidates.append(
                    (
                        title,
                        full_url
                    )
                )

            # ---------------------------------------------------------
            # Try article pages.
            # ---------------------------------------------------------

            seen = set()

            for fallback_title, article_url in (
                candidates
            ):

                if article_url in seen:
                    continue

                seen.add(
                    article_url
                )

                result = self._parse_detail_page(
                    article_url,
                    fallback_title,
                    query
                )

                if result:
                    return result

        except Exception as exc:

            logger.warning(
                "AnimeDubHindi search failed: %s",
                exc
            )

        return None

    # =================================================================
    # SEARCH ENGINE FALLBACK
    # =================================================================

    def _search_engine_for_site(
        self,
        anime_name: str,
        query: str,
    ) -> Optional[Dict]:

        search_url = (
            "https://html.duckduckgo.com/html/?q="
            + quote(
                f"site:animedubhindi.link "
                f'"{anime_name}"'
            )
        )

        try:

            response = self.session.get(
                search_url,
                timeout=15
            )

            response.raise_for_status()

            soup = BeautifulSoup(
                response.text,
                "html.parser"
            )

            for result in soup.select(
                ".result"
            ):

                anchor = result.select_one(
                    ".result__a"
                )

                if not anchor:
                    continue

                href = anchor.get(
                    "href"
                )

                if not href:
                    continue

                href = unquote(
                    href
                )

                if not href.startswith(
                    "http"
                ):
                    continue

                if "animedubhindi.link" not in (
                    href.lower()
                ):
                    continue

                title = anchor.get_text(
                    " ",
                    strip=True
                )

                if not self._title_matches(
                    title,
                    query
                ):
                    # Look at result snippet too.
                    snippet_tag = (
                        result.select_one(
                            ".result__snippet"
                        )
                    )

                    snippet = (
                        snippet_tag.get_text(
                            " ",
                            strip=True
                        )
                        if snippet_tag
                        else ""
                    )

                    if not self._title_matches(
                        snippet,
                        query
                    ):
                        continue

                parsed = self._parse_detail_page(
                    href,
                    title,
                    query
                )

                if parsed:
                    return parsed

        except Exception as exc:

            logger.debug(
                "Search engine fallback failed: %s",
                exc
            )

        return None

    # =================================================================
    # PARSE MATCHING PAGE
    # =================================================================

    def _parse_matching_page(
        self,
        soup: BeautifulSoup,
        query: str,
        page_url: str,
    ) -> Optional[Dict]:

        elements = soup.find_all(
            [
                "h1",
                "h2",
                "h3",
                "h4",
                "h5",
                "a",
            ]
        )

        best = None
        best_score = -1

        for element in elements:

            title = element.get_text(
                " ",
                strip=True
            )

            if not title:
                continue

            if len(title) > 300:
                continue

            if self._is_generic_title(
                title
            ):
                continue

            if not self._title_matches(
                title,
                query
            ):
                continue

            container = element
            text = title

            for _ in range(8):

                if container.parent is None:
                    break

                container = container.parent

                candidate = (
                    container.get_text(
                        " ",
                        strip=True
                    )
                )

                if (
                    20
                    <= len(candidate)
                    <= 5000
                ):
                    text = candidate

                if re.search(
                    r"\bHindi\b",
                    candidate,
                    re.I
                ):
                    break

            score = 0

            if re.search(
                r"\bHindi\b",
                text,
                re.I
            ):
                score += 50

            if self._extract_season(
                text
            ):
                score += 20

            if self._extract_episode(
                text
            ):
                score += 20

            if self._extract_schedule(
                text
            ):
                score += 10

            if (
                self._extract_platform_tag(
                    text
                )
            ):
                score += 15

            if score > best_score:

                best_score = score

                best = (
                    element,
                    title,
                    text
                )

        if not best:
            return None

        element, title, text = best

        href = element.get(
            "href"
        )

        detail_url = None

        if href:

            full = urljoin(
                SITE_URL,
                href
            )

            if full.startswith(
                SITE_URL
            ):
                detail_url = full

        return self._build_result(
            title,
            text,
            detail_url
        )

    # =================================================================
    # PARSE DETAIL PAGE
    # =================================================================

    def _parse_detail_page(
        self,
        url: str,
        fallback_title: str,
        query: str,
    ) -> Optional[Dict]:

        try:

            response = self.session.get(
                url,
                timeout=20
            )

            if response.status_code != 200:
                return None

            soup = BeautifulSoup(
                response.text,
                "html.parser"
            )

            for tag in soup.find_all(
                [
                    "script",
                    "style",
                    "noscript",
                ]
            ):
                tag.decompose()

            title = self._pick_title(
                soup,
                fallback_title
            )

            page_text = soup.get_text(
                " ",
                strip=True
            )

            # Search page titles and generic headings are never
            # accepted as anime names.
            if self._is_generic_title(
                title
            ):
                title = fallback_title

            if (
                not self._title_matches(
                    title,
                    query
                )
                and not self._title_matches(
                    page_text[:12000],
                    query
                )
            ):
                return None

            result = self._build_result(
                title,
                page_text,
                url
            )

            # Use source page's OG image only as temporary fallback.
            if not result.get(
                "poster_url"
            ):
                result["poster_url"] = (
                    self._extract_og_image(
                        soup
                    )
                )

            return result

        except Exception as exc:

            logger.debug(
                "Detail page parsing failed: %s",
                exc
            )

            return None

    # =================================================================
    # BUILD RESULT
    # =================================================================

    def _build_result(
        self,
        title: str,
        text: str,
        detail_url: Optional[str],
    ) -> Dict:

        languages = (
            self._extract_languages(
                text
            )
        )

        return {
            "name": self._clean_title(
                title
            ),

            "hindi_dub": (
                "Available"
                if "Hindi" in languages
                else "Not Mentioned"
            ),

            "platform": (
                self._extract_platform_tag(
                    text
                )
            ),

            "platform_entries": (
                self._entries_from_source(
                    text,
                    languages
                )
            ),

            "dub_by": (
                self._extract_dub_by(
                    text
                )
            ),

            "studio": None,

            "hindi_details": None,

            "season": (
                self._extract_season(
                    text
                )
            ),

            "episodes": (
                self._extract_episode(
                    text
                )
            ),

            "languages": (
                self._languages_string(
                    languages
                )
            ),

            "schedule": (
                self._extract_schedule(
                    text
                )
            ),

            "release_date": (
                self._extract_date(
                    text
                )
            ),

            "poster_url": None,

            "mal_url": None,

            "source": "DC",

            "source_link": None,

            "_detail_url": detail_url,
        }
    # =================================================================
    # SOURCE PLATFORM TAG
    # =================================================================

    @staticmethod
    def _extract_platform_tag(
        text: str,
    ) -> Optional[str]:

        low = (
            text or ""
        ).lower()

        found = []

        for alias, platform in sorted(
            PLATFORM_TAGS.items(),
            key=lambda item: len(
                item[0]
            ),
            reverse=True
        ):

            if re.search(
                rf"\b{re.escape(alias)}\b",
                low,
                re.I
            ):

                found.append(
                    platform
                )

        if not found:
            return None

        return " • ".join(
            dict.fromkeys(
                found
            )
        )

    # =================================================================
    # SOURCE ENTRIES
    # =================================================================

    def _entries_from_source(
        self,
        text: str,
        languages: List[str],
    ) -> List[Dict]:

        platform = (
            self._extract_platform_tag(
                text
            )
        )

        if not platform:
            return []

        seasons = (
            self._season_numbers(
                text
            )
        )

        if not seasons:
            seasons = ["all"]

        platforms = [
            item.strip()
            for item in platform.split(
                " • "
            )
        ]

        return [
            {
                "platform": name,
                "seasons": seasons,
                "languages": (
                    self._ordered_languages(
                        languages
                    )
                ),
                "verified": True,
                "source": "AnimeDubHindi",
            }
            for name in platforms
        ]

    # =================================================================
    # OFFICIAL PLATFORM CHECK
    # =================================================================

    def _check_official_sources(
        self,
        anime_name: str,
    ) -> Dict:

        entries = []
        dub_by_names = []

        for platform, domains in (
            OFFICIAL_SOURCES.items()
        ):

            for domain in domains:

                results = self._search_engine(
                    anime_name,
                    domain
                )

                for item in results[:5]:

                    combined = (
                        f"{item.get('title', '')} "
                        f"{item.get('snippet', '')}"
                    )

                    page = self._fetch_page(
                        item["url"]
                    )

                    if page:

                        page_text, _soup = page

                        combined += (
                            " "
                            + page_text[:30000]
                        )

                    # Must contain the anime title.
                    if not self._query_present(
                        anime_name,
                        combined
                    ):
                        continue

                    languages = (
                        self._extract_languages(
                            combined
                        )
                    )

                    # A platform is useful only when an audio language
                    # is actually exposed.
                    if not languages:
                        continue

                    seasons = (
                        self._season_numbers(
                            combined
                        )
                    )

                    if not seasons:

                        # If the page is clearly a series page,
                        # treat it as all seasons rather than inventing
                        # a season number.
                        seasons = ["all"]

                    # YouTube channels are presented as YouTube,
                    # while the channel itself can be shown through
                    # the Dub By field.
                    display_platform = (
                        "YouTube"
                        if platform in {
                            "Muse India",
                            "Anime Times",
                            "Ani-One",
                        }
                        else platform
                    )

                    entries.append(
                        {
                            "platform": (
                                display_platform
                            ),
                            "channel": (
                                platform
                                if display_platform
                                == "YouTube"
                                else None
                            ),
                            "seasons": seasons,
                            "languages": (
                                self._ordered_languages(
                                    languages
                                )
                            ),
                            "verified": True,
                            "source": platform,
                        }
                    )

                    # Only accept an explicit Dub By statement.
                    explicit = (
                        self._extract_dub_by(
                            combined
                        )
                    )

                    if explicit:
                        dub_by_names.append(
                            explicit
                        )

                    break
                    
        # -------------------------------------------------------------
        # Deduplicate Dub By names.
        # -------------------------------------------------------------

        unique_dub_by = []

        for value in dub_by_names:

            if value not in unique_dub_by:
                unique_dub_by.append(
                    value
                )

        return {
            "platform_entries": (
                self._dedupe_platform_entries(
                    entries
                )
            ),
            "dub_by": (
                " • ".join(
                    unique_dub_by
                )
                if unique_dub_by
                else None
            ),
        }

    # =================================================================
    # WEB SEARCH
    # =================================================================

    def _search_engine(
        self,
        anime_name: str,
        domain: str,
    ) -> List[Dict]:

        query = (
            f"site:{domain} "
            f'"{anime_name}" '
            f'"Hindi" anime'
        )

        url = (
            "https://html.duckduckgo.com/html/?q="
            + quote(query)
        )

        try:

            response = self.session.get(
                url,
                timeout=15
            )

            response.raise_for_status()

            soup = BeautifulSoup(
                response.text,
                "html.parser"
            )

            results = []

            for result in soup.select(
                ".result"
            )[:10]:

                anchor = result.select_one(
                    ".result__a"
                )

                if not anchor:
                    continue

                href = anchor.get(
                    "href"
                )

                if not href:
                    continue

                href = unquote(
                    href
                )

                if domain.lower() not in (
                    href.lower()
                ):
                    continue

                snippet_tag = (
                    result.select_one(
                        ".result__snippet"
                    )
                )

                results.append(
                    {
                        "url": href,
                        "title": anchor.get_text(
                            " ",
                            strip=True
                        ),
                        "snippet": (
                            snippet_tag.get_text(
                                " ",
                                strip=True
                            )
                            if snippet_tag
                            else ""
                        ),
                    }
                )

            return results

        except Exception as exc:

            logger.debug(
                "Official source search failed %s: %s",
                domain,
                exc
            )

            return []
    # =================================================================
    # FETCH PAGE
    # =================================================================

    def _fetch_page(
        self,
        url: str,
    ) -> Optional[tuple]:

        try:

            response = self.session.get(
                url,
                timeout=15,
                allow_redirects=True
            )

            if response.status_code != 200:
                return None

            soup = BeautifulSoup(
                response.text,
                "html.parser"
            )

            for tag in soup.find_all(
                [
                    "script",
                    "style",
                    "noscript",
                ]
            ):
                tag.decompose()

            return (
                soup.get_text(
                    " ",
                    strip=True
                ),
                soup,
            )

        except Exception:
            return None

    # =================================================================
    # JIKAN / MAL
    # =================================================================

    def _get_mal_info(
        self,
        anime_name: str,
    ) -> Optional[Dict]:

        try:

            response = self.session.get(
                JIKAN_URL,
                params={
                    "q": anime_name,
                    "limit": 10,
                    "sfw": "true",
                },
                timeout=20,
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

            # ---------------------------------------------------------
            # Exact title
            # ---------------------------------------------------------

            for anime in data:

                for title in (
                    self._get_titles(
                        anime
                    )
                ):

                    if (
                        self._normalize(
                            title
                        )
                        == query
                    ):

                        selected = anime
                        break

                if selected:
                    break

            # ---------------------------------------------------------
            # Word/partial title
            # ---------------------------------------------------------

            if selected is None:

                for anime in data:

                    for title in (
                        self._get_titles(
                            anime
                        )
                    ):

                        if self._title_matches(
                            title,
                            query
                        ):

                            selected = anime
                            break

                    if selected:
                        break

            if selected is None:
                selected = data[0]

            jpg = (
                selected.get(
                    "images",
                    {}
                ).get(
                    "jpg",
                    {}
                )
            )

            poster = (
                jpg.get(
                    "large_image_url"
                )
                or jpg.get(
                    "image_url"
                )
                or jpg.get(
                    "small_image_url"
                )
            )

            studios = []

            for item in selected.get(
                "studios",
                []
            ):

                if not isinstance(
                    item,
                    dict
                ):
                    continue

                name = item.get(
                    "name"
                )

                if name:
                    studios.append(
                        name
                    )

            studio = (
                " • ".join(
                    dict.fromkeys(
                        studios
                    )
                )
                if studios
                else None
            )

            return {
                "name": (
                    selected.get(
                        "title"
                    )
                    or anime_name
                ),

                "poster_url": poster,

                "studio": studio,

                "mal_url": (
                    selected.get(
                        "url"
                    )
                ),

                "episodes": (
                    str(
                        selected.get(
                            "episodes"
                        )
                    )
                    if selected.get(
                        "episodes"
                    ) is not None
                    else None
                ),
            }

        except Exception as exc:

            logger.warning(
                "Jikan lookup failed for %s: %s",
                anime_name,
                exc
            )

            return None
    # =================================================================
    # TITLE HELPERS
    # =================================================================

    @staticmethod
    def _get_titles(
        anime: Dict,
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

        return list(
            dict.fromkeys(
                titles
            )
        )

    @staticmethod
    def _pick_title(
        soup: BeautifulSoup,
        fallback: str,
    ) -> str:

        h1 = soup.find(
            "h1"
        )

        if h1:

            value = h1.get_text(
                " ",
                strip=True
            )

            if value:
                return value

        og_title = soup.find(
            "meta",
            attrs={
                "property": "og:title"
            }
        )

        if og_title:

            value = og_title.get(
                "content"
            )

            if value:
                return value

        title_tag = soup.find(
            "title"
        )

        if title_tag:

            value = title_tag.get_text(
                " ",
                strip=True
            )

            if value:
                return value

        return fallback

    @staticmethod
    def _extract_og_image(
        soup: BeautifulSoup,
    ) -> Optional[str]:

        tag = soup.find(
            "meta",
            attrs={
                "property": "og:image"
            }
        )

        if tag:

            value = tag.get(
                "content"
            )

            if value:
                return value.strip()

        return None

    # =================================================================
    # NORMALIZATION / MATCHING
    # =================================================================

    @staticmethod
    def _normalize(
        text: str,
    ) -> str:

        text = (
            text or ""
        ).lower()

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

    @staticmethod
    def _title_matches(
        title: str,
        query: str,
    ) -> bool:

        a = AnimeScraper._normalize(
            title
        )

        b = AnimeScraper._normalize(
            query
        )

        if not b:
            return False

        if a == b:
            return True

        if b in a:
            return True

        return set(
            b.split()
        ).issubset(
            set(
                a.split()
            )
        )

    @staticmethod
    def _query_present(
        anime_name: str,
        text: str,
    ) -> bool:

        query = AnimeScraper._normalize(
            anime_name
        )

        normalized = AnimeScraper._normalize(
            text
        )

        return (
            query in normalized
            or set(
                query.split()
            ).issubset(
                set(
                    normalized.split()
                )
            )
        )

    @staticmethod
    def _is_generic_title(
        title: Optional[str],
    ) -> bool:

        if not title:
            return True

        value = title.strip().lower()

        return (
            value.startswith(
                "search results for:"
            )
            or value.startswith(
                "results for:"
            )
            or value in {
                "search",
                "anime",
                "anime schedule",
                "search results",
            }
        )

    @staticmethod
    def _clean_title(
        title: str,
    ) -> str:

        title = re.sub(
            r"^search\s+results?\s+for:\s*",
            "",
            title or "",
            flags=re.I
        )

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
        
    # =================================================================
    # DUB BY
    # =================================================================

    @staticmethod
    def _extract_dub_by(
        text: str,
    ) -> Optional[str]:

        patterns = [
            (
                r"official\s+dub(?:bed)?\s+by"
                r"\s*[:\-]?\s*"
                r"(.{1,120}?)"
                r"(?=\s+(?:encoder|quality|"
                r"subtitle|audio|genres|total|"
                r"episode|$))"
            ),
            (
                r"dub(?:bed)?\s+by"
                r"\s*[:\-]?\s*"
                r"(.{1,120}?)"
                r"(?=\s+(?:encoder|quality|"
                r"subtitle|audio|genres|total|"
                r"episode|$))"
            ),
            (
                r"dubbing\s+(?:studio|by)"
                r"\s*[:\-]?\s*"
                r"(.{1,120}?)"
                r"(?=\s+(?:encoder|quality|"
                r"subtitle|audio|genres|total|"
                r"episode|$))"
            ),
        ]

        for pattern in patterns:

            match = re.search(
                pattern,
                text or "",
                re.I
            )

            if match:

                value = re.sub(
                    r"\s+",
                    " ",
                    match.group(1)
                ).strip(
                    " :-|•,"
                )

                if (
                    value
                    and len(value) <= 120
                ):
                    return value

        return None

    # =================================================================
    # SEASON
    # =================================================================

    @staticmethod
    def _season_numbers(
        text: str
    ) -> List[str]:

        values = set()

        for value in re.findall(
            r"\bSeason\s*([0-9]{1,3})\b",
            text or "",
            re.I
        ):

            values.add(
                int(value)
            )

        for value in re.findall(
            r"\bS\s*([0-9]{1,3})\b",
            text or "",
            re.I
        ):

            values.add(
                int(value)
            )

        return [
            str(value)
            for value in sorted(
                values
            )
        ]

    @staticmethod
    def _extract_season(
        text: str
    ) -> Optional[str]:

        seasons = (
            AnimeScraper._season_numbers(
                text
            )
        )

        if not seasons:
            return None

        if len(seasons) > 5:
            return (
                f"{len(seasons)} Seasons"
            )

        return (
            "Season "
            + ", ".join(
                seasons
            )
        )

    # =================================================================
    # EPISODE
    # =================================================================

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
                text or "",
                re.I
            )

            if match:
                return match.group(1)

        return None

    # =================================================================
    # LANGUAGES
    # =================================================================

    @staticmethod
    def _extract_languages(
        text: str
    ) -> List[str]:

        found = []

        for language in LANGUAGES:

            if re.search(
                rf"\b{re.escape(language)}\b",
                text or "",
                re.I
            ):

                found.append(
                    language
                )

        return list(
            dict.fromkeys(
                found
            )
        )

    @staticmethod
    def _ordered_languages(
        languages: List[str]
    ) -> List[str]:

        order = [
            "Hindi",
            "English",
            "Tamil",
            "Telugu",
            "Japanese",
            "Korean",
            "Chinese",
            "Malayalam",
            "Kannada",
            "Marathi",
            "Bengali",
            "Bangla",
        ]

        return [
            language
            for language in order
            if language in languages
        ]

    @staticmethod
    def _languages_string(
        languages: List[str]
    ) -> Optional[str]:

        ordered = (
            AnimeScraper._ordered_languages(
                languages
            )
        )

        return (
            " • ".join(
                ordered
            )
            if ordered
            else None
    )

    # =================================================================
    # SCHEDULE
    # =================================================================

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

            match = re.search(
                rf"\b{day}\b.*?"
                rf"([0-9]{{1,2}}:"
                rf"[0-9]{{2}}\s*[AP]M)",
                text or "",
                re.I
            )

            if match:

                return (
                    f"{day} "
                    f"{match.group(1)}"
                )

        return None

    # =================================================================
    # DATE
    # =================================================================

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
                text or "",
                re.I
            )

            if match:
                return match.group(0)

        return None

    # =================================================================
    # PLATFORM SUMMARY
    # =================================================================

    @staticmethod
    def _dedupe_platform_entries(
        entries: List[Dict]
    ) -> List[Dict]:

        output = []
        seen = set()

        for entry in entries:

            key = (
                entry.get(
                    "platform"
                ),
                entry.get(
                    "channel"
                ),
                tuple(
                    entry.get(
                        "seasons",
                        []
                    )
                ),
                tuple(
                    entry.get(
                        "languages",
                        []
                    )
                ),
            )

            if key in seen:
                continue

            seen.add(key)

            output.append(
                entry
            )

        return output

    @staticmethod
    def _platform_summary(
        entries: List[Dict]
    ) -> Optional[str]:

        if not entries:
            return None

        grouped = {}

        for entry in entries:

            platform = entry.get(
                "platform"
            )

            if not platform:
                continue

            label = platform

            if entry.get(
                "channel"
            ):
                label = (
                    f"{platform} "
                    f"({entry['channel']})"
                )

            if label not in grouped:

                grouped[label] = {
                    "seasons": set(),
                    "languages": set(),
                }

            for season in entry.get(
                "seasons",
                []
            ):
                grouped[label]["seasons"].add(
                    str(season)
                )

            for language in entry.get(
                "languages",
                []
            ):
                grouped[label]["languages"].add(
                    str(language)
                )

        lines = []

        def sort_key(item):

            label, data = item

            return (
                0
                if "Hindi"
                in data["languages"]
                else 1,
                label.lower(),
            )

        for label, data in sorted(
            grouped.items(),
            key=sort_key
        ):

            seasons = sorted(
                {
                    int(value)
                    for value
                    in data["seasons"]
                    if value.isdigit()
                }
            )

            if len(seasons) > 5:

                season_text = (
                    f"{len(seasons)} Seasons"
                )

            elif seasons:

                season_text = (
                    "Season "
                    + ", ".join(
                        str(value)
                        for value in seasons
                    )
                )

            else:

                season_text = (
                    "All Seasons"
                )

            languages = (
                AnimeScraper._ordered_languages(
                    list(
                        data["languages"]
                    )
                )
            )

            language_text = (
                " • ".join(
                    languages
                )
                if languages
                else "Verified"
            )

            lines.append(
                f"• {label} — "
                f"{season_text} — "
                f"{language_text}"
            )

        return (
            "\n".join(lines)
            if lines
            else None
            )

# =====================================================================
# SINGLE INSTANCE
# =====================================================================

anime_scraper = AnimeScraper()


# =====================================================================
# PUBLIC FUNCTION
# =====================================================================

def get_anime_info(
    anime_name: str,
) -> Optional[Dict]:
    """Public function used by commands.py."""

    return anime_scraper.search_anime(
        anime_name
    )
