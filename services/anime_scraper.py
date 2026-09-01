"""
Anime Metadata Scraper Service
Fetches and verifies Hindi-dubbed anime information directly from official sources.

Sources:
- Official OTT platforms: Crunchyroll, Netflix, Amazon Prime Video,
  JioHotstar, Amazon MX Player, ZEE5, SonyLIV
- Prime Video Channel / YouTube: Anime Times (@animetimesindia)
- Official YouTube channels: Muse India (@MuseIndiaChannel),
  Ani-One India (@AniOneIN)
- Neutral Metadata: Jikan/MyAnimeList
  (Poster, Studio, Canonical Title only)

Important:
- No anime episodes are downloaded or distributed.
- Only publicly available metadata is processed.
- Search engines are used ONLY for discovery.
- Availability is considered verified ONLY after direct official-source
  page validation.
"""

import html
import json
import re
import time
from concurrent.futures import (
    ThreadPoolExecutor,
    as_completed,
    TimeoutError as FutureTimeoutError,
)
from typing import Dict, List, Optional, Set
from urllib.parse import (
    parse_qs,
    quote,
    unquote,
    urljoin,
    urlparse,
)

import requests
from bs4 import BeautifulSoup

from utils.logger import logger


# =====================================================================
# CONFIGURATION
# =====================================================================

JIKAN_URL = "https://api.jikan.moe/v4/anime"

OVERALL_TIMEOUT_SECONDS = 8.0
DISCOVERY_TIMEOUT_SECONDS = 2.0
PAGE_TIMEOUT_SECONDS = 2.0
MAX_CANDIDATES_PER_SOURCE = 3

SUPPORTED_LANGUAGES = [
    "Hindi",
    "English",
    "Tamil",
    "Telugu",
    "Japanese",
]

LANGUAGE_TITLE_CLEAN_RE = re.compile(
    r"\b("
    r"hindi|english|tamil|telugu|japanese|malayalam|"
    r"bangla|bengali|kannada|chinese|korean|marathi|"
    r"multi\s+audio|dual\s+audio|multi\s+language"
    r")\b",
    re.I,
)


# =====================================================================
# OFFICIAL SOURCES
# =====================================================================

OFFICIAL_SOURCES = {
    "Crunchyroll": {
        "domains": [
            "crunchyroll.com",
        ],
        "search_site": "crunchyroll.com",
        "youtube_handles": [],
    },

    "Netflix": {
        "domains": [
            "netflix.com",
        ],
        "search_site": "netflix.com",
        "youtube_handles": [],
    },

    "Amazon Prime Video": {
        "domains": [
            "primevideo.com",
        ],
        "search_site": "primevideo.com",
        "youtube_handles": [],
    },

    "JioHotstar": {
        "domains": [
            "hotstar.com",
            "jiohotstar.com",
        ],
        "search_site": "hotstar.com",
        "youtube_handles": [],
    },

    "Amazon MX Player": {
        "domains": [
            "mxplayer.in",
        ],
        "search_site": "mxplayer.in",
        "youtube_handles": [],
    },

    "ZEE5": {
        "domains": [
            "zee5.com",
        ],
        "search_site": "zee5.com",
        "youtube_handles": [],
    },

    "SonyLIV": {
        "domains": [
            "sonyliv.com",
        ],
        "search_site": "sonyliv.com",
        "youtube_handles": [],
    },

    "Anime Times": {
        "domains": [
            "youtube.com",
            "animetimes.co.jp",
        ],
        "search_site": "youtube.com",
        "youtube_handles": [
            "animetimesindia",
        ],
    },

    "Muse India": {
        "domains": [
            "youtube.com",
            "museindia.in",
        ],
        "search_site": "youtube.com",
        "youtube_handles": [
            "MuseIndiaChannel",
        ],
    },

    "Ani-One India": {
        "domains": [
            "youtube.com",
            "ani-one.com",
        ],
        "search_site": "youtube.com",
        "youtube_handles": [
            "AniOneIN",
        ],
    },
}


# =====================================================================
# SCRAPER
# =====================================================================

class AnimeScraper:
    """Multi-source anime metadata scraper."""

    def __init__(self):
        self.session = requests.Session()

        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Linux; Android 14) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/131.0 Mobile Safari/537.36"
            ),
            "Accept-Language": "en-IN,en;q=0.9",
            "Accept": (
                "text/html,application/xhtml+xml,"
                "application/xml;q=0.9,*/*;q=0.8"
            ),
        })

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
            logger.warning(
                "Empty anime name provided"
            )
            return None

        query = self._normalize(
            anime_name
        )

        is_movie_query = bool(
            re.search(
                r"\b(movie|film|theatrical)\b",
                anime_name,
                re.I,
            )
        )

        logger.info(
            "Anime search started across "
            "10 official sources: %s",
            anime_name,
        )

        official_results: Dict[str, Dict] = {}
        mal_info: Optional[Dict] = None

        executor = ThreadPoolExecutor(
            max_workers=11,
            thread_name_prefix="anime-source",
        )

        futures = {}

        try:
            # ---------------------------------------------------------
            # Jikan
            # ---------------------------------------------------------

            mal_future = executor.submit(
                self._get_mal_info,
                anime_name,
                is_movie_query,
            )

            futures[mal_future] = "mal"

            # ---------------------------------------------------------
            # Official sources
            # ---------------------------------------------------------

            for (
                platform_name,
                platform_cfg,
            ) in OFFICIAL_SOURCES.items():

                future = executor.submit(
                    self._verify_single_official_platform,
                    platform_name,
                    platform_cfg,
                    anime_name,
                    query,
                    is_movie_query,
                )

                futures[future] = (
                    f"platform:{platform_name}"
                )

            # ---------------------------------------------------------
            # HARD COLLECTION DEADLINE
            # ---------------------------------------------------------

            deadline = (
                time.monotonic()
                + OVERALL_TIMEOUT_SECONDS
            )

            try:
                for future in as_completed(
                    futures,
                    timeout=OVERALL_TIMEOUT_SECONDS,
                ):

                    if time.monotonic() >= deadline:
                        break

                    task_key = futures[future]

                    try:
                        result = future.result(
                            timeout=max(
                                0.01,
                                deadline
                                - time.monotonic(),
                            )
                        )

                        if not result:
                            continue

                        if task_key == "mal":
                            mal_info = result

                        elif task_key.startswith(
                            "platform:"
                        ):
                            platform_name = (
                                task_key.split(
                                    ":",
                                    1,
                                )[1]
                            )

                            if result.get(
                                "verified"
                            ):
                                official_results[
                                    platform_name
                                ] = result

                    except Exception as exc:
                        logger.debug(
                            "%s failed: %s",
                            task_key,
                            exc,
                        )

            except FutureTimeoutError:
                logger.warning(
                    "Official-source search reached "
                    "%ss deadline.",
                    OVERALL_TIMEOUT_SECONDS,
                )

        finally:
            executor.shutdown(
                wait=False,
                cancel_futures=True,
            )

        # -------------------------------------------------------------
        # Merge ONLY verified official results
        # -------------------------------------------------------------

        final_result = self._merge_results(
            official_results,
            mal_info,
            anime_name,
            is_movie_query,
        )

        if final_result:
            logger.info(
                "Verified anime: %s",
                final_result.get("name"),
            )
        else:
            logger.info(
                "Anime not verified: %s",
                anime_name,
            )

        return final_result

    # =================================================================
    # OFFICIAL SOURCE VERIFICATION
    # =================================================================

    def _verify_single_official_platform(
        self,
        platform_name: str,
        platform_cfg: Dict,
        anime_name: str,
        query: str,
        is_movie_query: bool,
    ) -> Optional[Dict]:

        started = time.monotonic()

        try:
            # ---------------------------------------------------------
            # STEP 1: DISCOVERY
            # ---------------------------------------------------------

            candidate_urls = (
                self._discover_candidate_urls(
                    platform_name,
                    platform_cfg,
                    anime_name,
                )
            )

            if not candidate_urls:
                return None

            # ---------------------------------------------------------
            # STEP 2: DIRECT OFFICIAL VERIFICATION
            # ---------------------------------------------------------

            for candidate_url in candidate_urls[
                :MAX_CANDIDATES_PER_SOURCE
            ]:

                if (
                    time.monotonic() - started
                    >= OVERALL_TIMEOUT_SECONDS
                ):
                    break

                # -----------------------------------------------------
                # HOSTNAME CHECK BEFORE REQUEST
                # -----------------------------------------------------

                if not self._is_allowed_domain(
                    candidate_url,
                    platform_cfg["domains"],
                ):
                    continue

                # -----------------------------------------------------
                # YOUTUBE SPECIAL VERIFICATION
                # -----------------------------------------------------

                if platform_cfg.get(
                    "youtube_handles"
                ):
                    result = (
                        self._verify_youtube_candidate(
                            platform_name,
                            platform_cfg,
                            candidate_url,
                            anime_name,
                            query,
                            is_movie_query,
                        )
                    )

                else:
                    result = (
                        self._verify_standard_candidate(
                            platform_name,
                            platform_cfg,
                            candidate_url,
                            anime_name,
                            query,
                            is_movie_query,
                        )
                    )

                if result:
                    return result

        except Exception as exc:
            logger.debug(
                "%s verification failed: %s",
                platform_name,
                exc,
            )

        return None
        
    # =================================================================
    # DISCOVERY
    # =================================================================

    def _discover_candidate_urls(
        self,
        platform_name: str,
        platform_cfg: Dict,
        anime_name: str,
    ) -> List[str]:

        search_site = platform_cfg.get(
            "search_site",
            "",
        )

        # -------------------------------------------------------------
        # YouTube:
        # Search specifically for the official channel handle.
        # -------------------------------------------------------------

        if platform_cfg.get(
            "youtube_handles"
        ):

            handles = platform_cfg[
                "youtube_handles"
            ]

            handle_queries = []

            for handle in handles:
                handle_queries.append(
                    f'"{anime_name}" '
                    f'site:youtube.com '
                    f'"@{handle}"'
                )

            search_query = " OR ".join(
                handle_queries
            )

        else:
            search_query = (
                f"site:{search_site} "
                f'"{anime_name}"'
            )

        search_url = (
            "https://html.duckduckgo.com/html/"
            "?q="
            + quote(search_query)
        )

        try:
            response = self.session.get(
                search_url,
                timeout=DISCOVERY_TIMEOUT_SECONDS,
                allow_redirects=True,
            )

            if response.status_code != 200:
                return []

        except requests.RequestException:
            return []

        soup = BeautifulSoup(
            response.text,
            "html.parser",
        )

        candidates: List[str] = []

        # -------------------------------------------------------------
        # DDG result parser
        # -------------------------------------------------------------

        result_nodes = soup.select(
            "div.result"
        )

        for result in result_nodes:

            links = result.select(
                "a.result__a"
            )

            if not links:
                links = result.find_all(
                    "a",
                    href=True,
                )

            for link in links:

                href = link.get(
                    "href",
                    "",
                ).strip()

                clean_url = (
                    self._unwrap_search_url(
                        href
                    )
                )

                if not clean_url:
                    continue

                if not clean_url.startswith(
                    ("http://", "https://")
                ):
                    continue

                # -----------------------------------------------------
                # SECURITY:
                # Search result itself must already belong to the
                # official source.
                # -----------------------------------------------------

                if not self._is_allowed_domain(
                    clean_url,
                    platform_cfg["domains"],
                ):
                    continue

                # -----------------------------------------------------
                # Reject obvious generic pages before fetching.
                # -----------------------------------------------------

                if self._is_obviously_generic_url(
                    clean_url,
                    platform_cfg,
                ):
                    continue

                if clean_url not in candidates:
                    candidates.append(
                        clean_url
                    )

                break

        return candidates

    # =================================================================
    # SEARCH URL UNWRAPPER
    # =================================================================

    @staticmethod
    def _unwrap_search_url(
        href: str,
    ) -> Optional[str]:

        if not href:
            return None

        href = html.unescape(
            unquote(href)
        )

        # -------------------------------------------------------------
        # DuckDuckGo "uddg" redirect parameter
        # -------------------------------------------------------------

        try:
            parsed = urlparse(
                href
            )

            params = parse_qs(
                parsed.query
            )

            if "uddg" in params:

                target = params[
                    "uddg"
                ][0]

                target = unquote(
                    html.unescape(
                        target
                    )
                )

                if target.startswith(
                    ("http://", "https://")
                ):
                    return target

        except Exception:
            pass

        return href

    # =================================================================
    # STANDARD OFFICIAL PAGE
    # =================================================================

    def _verify_standard_candidate(
        self,
        platform_name: str,
        platform_cfg: Dict,
        candidate_url: str,
        anime_name: str,
        query: str,
        is_movie_query: bool,
    ) -> Optional[Dict]:

        try:

            # ---------------------------------------------------------
            # DIRECT FETCH
            # ---------------------------------------------------------

            page_resp = self.session.get(
                candidate_url,
                timeout=PAGE_TIMEOUT_SECONDS,
                allow_redirects=True,
            )

            if page_resp.status_code != 200:
                return None

            final_url = page_resp.url

            # ---------------------------------------------------------
            # REDIRECT VALIDATION
            # ---------------------------------------------------------

            if not self._is_allowed_domain(
                final_url,
                platform_cfg["domains"],
            ):
                return None

            # ---------------------------------------------------------
            # PARSE OFFICIAL PAGE
            # ---------------------------------------------------------

            page_soup = BeautifulSoup(
                page_resp.text,
                "html.parser",
            )

            # ---------------------------------------------------------
            # GENERIC PAGE REJECTION
            # ---------------------------------------------------------

            if self._is_generic_landing_page(
                final_url,
                page_soup,
            ):
                return None

            # ---------------------------------------------------------
            # CANONICAL URL VALIDATION
            # ---------------------------------------------------------

            canonical_url = (
                self._extract_canonical_url(
                    page_soup,
                    final_url,
                )
            )

            if canonical_url:

                if not self._is_allowed_domain(
                    canonical_url,
                    platform_cfg["domains"],
                ):
                    return None

            # ---------------------------------------------------------
            # OFFICIAL PAGE TITLE
            # ---------------------------------------------------------

            page_title = (
                self._extract_official_page_title(
                    page_soup
                )
            )

            page_text = page_soup.get_text(
                " ",
                strip=True,
            )

            if not page_title:
                return None

            if len(page_text) < 80:
                return None

            # ---------------------------------------------------------
            # ANIME IDENTITY VERIFICATION
            # ---------------------------------------------------------

            identity_ok = (
                self._title_matches(
                    page_title,
                    query,
                )
                or self._title_matches(
                    page_text[:2000],
                    query,
                )
            )

            if not identity_ok:
                return None

            # ---------------------------------------------------------
            # MOVIE / SERIES INTENT
            # ---------------------------------------------------------

            is_page_movie = (
                self._is_movie_result(
                    page_title
                )
                or self._is_movie_result(
                    page_text[:1500]
                )
            )

            if is_movie_query != is_page_movie:
                return None

            # ---------------------------------------------------------
            # VERIFIED LANGUAGE EXTRACTION
            # ---------------------------------------------------------

            verified_languages = (
                self._extract_verified_languages(
                    page_text,
                    page_soup,
                )
            )

            # ---------------------------------------------------------
            # SEASONS
            # ---------------------------------------------------------

            seasons = (
                self._extract_seasons(
                    page_text,
                    page_soup,
                )
            )

            # ---------------------------------------------------------
            # EPISODES
            # ---------------------------------------------------------

            episodes = (
                self._extract_episodes(
                    page_text,
                    page_soup,
                )
            )

            # ---------------------------------------------------------
            # STATUS
            # ---------------------------------------------------------

            status = (
                self._extract_status(
                    page_text,
                    page_soup,
                )
            )

            # ---------------------------------------------------------
            # VERIFIED RESULT
            # ---------------------------------------------------------

            return {
                "verified": True,
                "platform": platform_name,
                "url": final_url,
                "languages": verified_languages,
                "seasons": seasons,
                "episodes": episodes,
                "status": status,
                "title": self._clean_title(
                    page_title
                ),
            }

        except (
            requests.RequestException,
            ValueError,
            Exception,
        ) as exc:

            logger.debug(
                "Direct verification failed "
                "for %s: %s",
                candidate_url,
                exc,
            )

            return None

    # =================================================================
    # YOUTUBE VERIFICATION
    # =================================================================

    def _verify_youtube_candidate(
        self,
        platform_name: str,
        platform_cfg: Dict,
        candidate_url: str,
        anime_name: str,
        query: str,
        is_movie_query: bool,
    ) -> Optional[Dict]:

        try:

            parsed = urlparse(
                candidate_url
            )

            hostname = (
                parsed.hostname or ""
            ).lower()

            # ---------------------------------------------------------
            # ONLY REAL YOUTUBE HOSTS
            # ---------------------------------------------------------

            if hostname not in {
                "youtube.com",
                "www.youtube.com",
                "m.youtube.com",
            }:
                return None

            path = (
                parsed.path or ""
            ).lower()

            # ---------------------------------------------------------
            # CHANNEL HOME IS NOT AN ANIME RESULT
            # ---------------------------------------------------------

            if path.startswith("/@"):
                return None

            # ---------------------------------------------------------
            # ACTUAL VIDEO / PLAYLIST REQUIRED
            # ---------------------------------------------------------

            query_params = parse_qs(
                parsed.query
            )

            is_video = (
                path == "/watch"
                and bool(
                    query_params.get(
                        "v"
                    )
                )
            )

            is_playlist = bool(
                query_params.get(
                    "list"
                )
            )

            if not is_video and not is_playlist:
                return None

            # ---------------------------------------------------------
            # OFFICIAL CHANNEL OWNER CHECK
            # ---------------------------------------------------------

            if not self._verify_youtube_owner_oembed(
                candidate_url,
                platform_cfg,
            ):
                return None

            # ---------------------------------------------------------
            # DIRECT FETCH
            # ---------------------------------------------------------

            response = self.session.get(
                candidate_url,
                timeout=PAGE_TIMEOUT_SECONDS,
                allow_redirects=True,
            )

            if response.status_code != 200:
                return None

            final_url = response.url

            if not self._is_allowed_domain(
                final_url,
                ["youtube.com"],
            ):
                return None

            soup = BeautifulSoup(
                response.text,
                "html.parser",
            )

            # ---------------------------------------------------------
            # GENERIC PAGE CHECK
            # ---------------------------------------------------------

            if self._is_generic_landing_page(
                final_url,
                soup,
            ):
                return None

            # ---------------------------------------------------------
            # TITLE + TEXT
            # ---------------------------------------------------------

            page_title = (
                self._extract_official_page_title(
                    soup
                )
            )

            page_text = soup.get_text(
                " ",
                strip=True,
            )

            if not page_title:
                return None

            if len(page_text) < 50:
                return None

            # ---------------------------------------------------------
            # ANIME IDENTITY
            # ---------------------------------------------------------

            if not (
                self._title_matches(
                    page_title,
                    query,
                )
                or self._title_matches(
                    page_text[:2000],
                    query,
                )
            ):
                return None

            # ---------------------------------------------------------
            # MOVIE / SERIES
            # ---------------------------------------------------------

            is_page_movie = (
                self._is_movie_result(
                    page_title
                )
                or self._is_movie_result(
                    page_text[:1500]
                )
            )

            if is_movie_query != is_page_movie:
                return None

            # ---------------------------------------------------------
            # LANGUAGE
            # ---------------------------------------------------------

            languages = (
                self._extract_verified_languages(
                    page_text,
                    soup,
                )
            )

            # ---------------------------------------------------------
            # SEASONS
            # ---------------------------------------------------------

            seasons = (
                self._extract_seasons(
                    page_text,
                    soup,
                )
            )

            # ---------------------------------------------------------
            # EPISODES
            # ---------------------------------------------------------

            episodes = (
                self._extract_episodes(
                    page_text,
                    soup,
                )
            )

            # ---------------------------------------------------------
            # STATUS
            # ---------------------------------------------------------

            status = (
                self._extract_status(
                    page_text,
                    soup,
                )
            )

            return {
                "verified": True,
                "platform": platform_name,
                "url": final_url,
                "languages": languages,
                "seasons": seasons,
                "episodes": episodes,
                "status": status,
                "title": self._clean_title(
                    page_title
                ),
            }

        except Exception as exc:

            logger.debug(
                "YouTube verification failed "
                "for %s: %s",
                candidate_url,
                exc,
            )

        return None

    # =================================================================
    # YOUTUBE OWNER VERIFICATION
    # =================================================================

    def _verify_youtube_owner_oembed(
        self,
        video_url: str,
        platform_cfg: Dict,
    ) -> bool:

        handles = [
            h.lower().lstrip("@")
            for h in platform_cfg.get(
                "youtube_handles",
                [],
            )
        ]

        if not handles:
            return False

        try:

            oembed_url = (
                "https://www.youtube.com/oembed"
                "?url="
                + quote(
                    video_url,
                    safe="",
                )
                + "&format=json"
            )

            response = self.session.get(
                oembed_url,
                timeout=PAGE_TIMEOUT_SECONDS,
                allow_redirects=True,
            )

            if response.status_code != 200:
                return False

            data = response.json()

            author_url = str(
                data.get(
                    "author_url",
                    "",
                )
            ).lower()

            author_name = str(
                data.get(
                    "author_name",
                    "",
                )
            ).lower()

            # ---------------------------------------------------------
            # STRONG CHECK:
            # Official handle must appear in author URL.
            # ---------------------------------------------------------

            for handle in handles:

                if (
                    f"/@{handle}"
                    in author_url
                ):
                    return True

            # ---------------------------------------------------------
            # FALLBACK:
            # Exact-ish normalized author name comparison.
            # ---------------------------------------------------------

            normalized_author = re.sub(
                r"[^a-z0-9]+",
                "",
                author_name,
            )

            for handle in handles:

                normalized_handle = re.sub(
                    r"[^a-z0-9]+",
                    "",
                    handle,
                )

                if (
                    normalized_author
                    == normalized_handle
                ):
                    return True

        except Exception as exc:

            logger.debug(
                "YouTube oEmbed verification "
                "failed: %s",
                exc,
            )

        return False

            # =================================================================
    # SECURITY & DOMAIN VERIFICATION
    # =================================================================

    @staticmethod
    def _is_allowed_domain(
        url: str,
        allowed_domains: List[str],
    ) -> bool:

        try:
            parsed = urlparse(
                url
            )

            hostname = (
                parsed.hostname or ""
            ).lower().rstrip(".")

            if not hostname:
                return False

            for domain in allowed_domains:

                domain = (
                    domain.lower()
                    .strip()
                    .rstrip(".")
                )

                # Exact domain OR legitimate subdomain.
                if (
                    hostname == domain
                    or hostname.endswith(
                        "." + domain
                    )
                ):
                    return True

            return False

        except Exception:
            return False

    # =================================================================
    # OBVIOUS GENERIC URL DETECTION
    # =================================================================

    @staticmethod
    def _is_obviously_generic_url(
        url: str,
        platform_cfg: Dict,
    ) -> bool:

        try:
            parsed = urlparse(
                url
            )

            path = (
                parsed.path or ""
            ).strip("/").lower()

            # ---------------------------------------------------------
            # Root/homepage
            # ---------------------------------------------------------

            if not path:
                return True

            # ---------------------------------------------------------
            # Generic routes
            # ---------------------------------------------------------

            generic_paths = {
                "login",
                "signin",
                "sign-in",
                "register",
                "signup",
                "browse",
                "search",
                "home",
                "catalog",
                "error",
                "404",
            }

            if path in generic_paths:
                return True

            # ---------------------------------------------------------
            # Search / browse / catalog routes
            # ---------------------------------------------------------

            if path.startswith(
                (
                    "search",
                    "browse",
                    "catalog",
                )
            ):
                return True

            # ---------------------------------------------------------
            # YouTube channel homepage
            # ---------------------------------------------------------

            hostname = (
                parsed.hostname or ""
            ).lower()

            if "youtube.com" in hostname:

                if path.startswith("@"):
                    return True

        except Exception:
            return True

        return False

    # =================================================================
    # CANONICAL URL EXTRACTION
    # =================================================================

    @staticmethod
    def _extract_canonical_url(
        soup: BeautifulSoup,
        base_url: str,
    ) -> Optional[str]:

        # -------------------------------------------------------------
        # Standard canonical tag
        # -------------------------------------------------------------

        canonical_tag = soup.find(
            "link",
            attrs={
                "rel": re.compile(
                    r"canonical",
                    re.I,
                )
            },
        )

        if canonical_tag:

            href = canonical_tag.get(
                "href"
            )

            if href:

                return urljoin(
                    base_url,
                    href.strip(),
                )

        # -------------------------------------------------------------
        # OpenGraph URL fallback
        # -------------------------------------------------------------

        og_url = soup.find(
            "meta",
            attrs={
                "property": "og:url"
            },
        )

        if og_url:

            content = og_url.get(
                "content"
            )

            if content:

                return urljoin(
                    base_url,
                    content.strip(),
                )

        return None

    # =================================================================
    # GENERIC LANDING PAGE DETECTION
    # =================================================================

    @staticmethod
    def _is_generic_landing_page(
        url: str,
        soup: BeautifulSoup,
    ) -> bool:

        parsed = urlparse(
            url
        )

        path = (
            parsed.path or ""
        ).strip("/").lower()

        # -------------------------------------------------------------
        # Root URL
        # -------------------------------------------------------------

        if not path:
            return True

        # -------------------------------------------------------------
        # Authentication / generic routes
        # -------------------------------------------------------------

        generic_paths = {
            "login",
            "signin",
            "sign-in",
            "register",
            "signup",
            "browse",
            "search",
            "home",
            "catalog",
            "error",
            "404",
        }

        if path in generic_paths:
            return True

        # -------------------------------------------------------------
        # Search / browse / catalog
        # -------------------------------------------------------------

        if path.startswith(
            (
                "search",
                "browse",
                "catalog",
            )
        ):
            return True

        # -------------------------------------------------------------
        # YouTube channel root
        # -------------------------------------------------------------

        hostname = (
            parsed.hostname or ""
        ).lower()

        if "youtube.com" in hostname:

            if path.startswith("@"):

                # A channel page is not an anime result.
                return True

        # -------------------------------------------------------------
        # Generic HTML title detection
        # -------------------------------------------------------------

        title_text = ""

        if soup.title:

            title_text = (
                soup.title.get_text(
                    " ",
                    strip=True,
                ).lower()
            )

        generic_titles = [
            "log in",
            "sign in",
            "404 not found",
            "page not found",
            "home page",
            "welcome to",
            "search results",
            "browse anime",
            "watch popular movies",
        ]

        for generic_title in generic_titles:

            if generic_title in title_text:
                return True

        return False

    # =================================================================
    # JIKAN / MYANIMELIST
    # =================================================================

    def _get_mal_info(
        self,
        anime_name: str,
        is_movie_query: bool,
    ) -> Optional[Dict]:

        """
        Fetch ONLY neutral metadata from Jikan/MyAnimeList.

        Jikan is never trusted for:
        - Hindi dub
        - Audio language
        - OTT availability
        - Platform
        - Dub provider
        - Official episode verification
        """

        try:

            response = self.session.get(
                JIKAN_URL,
                params={
                    "q": anime_name,
                    "limit": 5,
                    "sfw": "true",
                },
                timeout=PAGE_TIMEOUT_SECONDS,
            )

            response.raise_for_status()

            payload = response.json()

            data = payload.get(
                "data",
                [],
            )

            if not data:
                return None

            selected_anime = None

            # ---------------------------------------------------------
            # Select matching movie/series type.
            # ---------------------------------------------------------

            for anime in data:

                anime_type = (
                    anime.get(
                        "type"
                    )
                    or ""
                ).lower()

                is_type_movie = (
                    anime_type
                    in {
                        "movie",
                        "feature film",
                    }
                )

                if (
                    is_movie_query
                    and is_type_movie
                ):
                    selected_anime = anime
                    break

                if (
                    not is_movie_query
                    and not is_type_movie
                ):
                    selected_anime = anime
                    break

            # ---------------------------------------------------------
            # If no correctly typed result exists,
            # DO NOT blindly use data[0].
            # ---------------------------------------------------------

            if not selected_anime:
                return None

            # ---------------------------------------------------------
            # Poster
            # ---------------------------------------------------------

            jpg = (
                selected_anime
                .get(
                    "images",
                    {},
                )
                .get(
                    "jpg",
                    {},
                )
            )

            poster = (
                jpg.get(
                    "large_image_url"
                )
                or jpg.get(
                    "image_url"
                )
            )

            # ---------------------------------------------------------
            # Studio
            # ---------------------------------------------------------

            studios = []

            for studio in selected_anime.get(
                "studios",
                [],
            ):

                if (
                    isinstance(
                        studio,
                        dict,
                    )
                    and studio.get(
                        "name"
                    )
                ):
                    studios.append(
                        studio["name"]
                    )

            # ---------------------------------------------------------
            # Neutral metadata only
            # ---------------------------------------------------------

            return {
                "name": (
                    selected_anime.get(
                        "title"
                    )
                    or anime_name
                ),

                "poster_url": poster,

                "studio": (
                    " • ".join(studios)
                    if studios
                    else None
                ),

                "mal_url": (
                    selected_anime.get(
                        "url"
                    )
                ),
            }

        except Exception as exc:

            logger.debug(
                "MAL neutral lookup failed: %s",
                exc,
            )

        return None

    # =================================================================
    # RESULT MERGING
    # =================================================================

    def _merge_results(
        self,
        official_results: Dict[str, Dict],
        mal_info: Optional[Dict],
        anime_name: str,
        is_movie_query: bool,
    ) -> Optional[Dict]:

        # -------------------------------------------------------------
        # Absolutely require at least one official verification.
        # -------------------------------------------------------------

        if not official_results:
            return None

        verified_platforms = list(
            official_results.keys()
        )

        verified_languages: Set[str] = set()

        verified_seasons: List[int] = []

        platform_episodes: Dict[
            str,
            str,
        ] = {}

        dub_by: List[str] = []

        verified_statuses: List[str] = []

        # -------------------------------------------------------------
        # Merge each verified official source.
        # -------------------------------------------------------------

        for (
            platform_name,
            platform_data,
        ) in official_results.items():

            languages = (
                platform_data.get(
                    "languages",
                    [],
                )
                or []
            )

            # ---------------------------------------------------------
            # Languages can ONLY come from official verification.
            # ---------------------------------------------------------

            for language in languages:

                if language in SUPPORTED_LANGUAGES:

                    verified_languages.add(
                        language
                    )

            # ---------------------------------------------------------
            # Seasons
            # ---------------------------------------------------------

            seasons = platform_data.get(
                "seasons"
            )

            if seasons:

                verified_seasons.extend(
                    self._parse_season_numbers(
                        seasons
                    )
                )

            # ---------------------------------------------------------
            # Episodes
            # ---------------------------------------------------------

            episodes = platform_data.get(
                "episodes"
            )

            if episodes:

                platform_episodes[
                    platform_name
                ] = episodes

            # ---------------------------------------------------------
            # Status
            # ---------------------------------------------------------

            status = platform_data.get(
                "status"
            )

            if status:

                verified_statuses.append(
                    status
                )

            # ---------------------------------------------------------
            # Dub provider:
            # Only report a platform when Hindi was explicitly
            # verified there.
            # ---------------------------------------------------------

            if (
                "Hindi" in languages
                and platform_name
                not in dub_by
            ):

                dub_by.append(
                    platform_name
                )

        # -------------------------------------------------------------
        # Title:
        # Jikan canonical title preferred.
        # Otherwise use user's search title.
        # -------------------------------------------------------------

        raw_title = (
            mal_info.get("name")
            if mal_info
            else None
        ) or anime_name

        clean_name = (
            self._clean_title(
                raw_title
            )
        )

        # -------------------------------------------------------------
        # Language formatting
        # -------------------------------------------------------------

        formatted_languages = (
            self._format_languages(
                list(
                    verified_languages
                )
            )
        )

        # -------------------------------------------------------------
        # Hindi dub status
        # -------------------------------------------------------------

        hindi_dub = (
            "Available"
            if "Hindi"
            in verified_languages
            else "Not Verified"
        )

        # -------------------------------------------------------------
        # Seasons
        # -------------------------------------------------------------

        formatted_seasons = (
            self._format_season_numbers(
                verified_seasons
            )
            if not is_movie_query
            else None
        )

        # -------------------------------------------------------------
        # Episodes
        # -------------------------------------------------------------

        formatted_episodes = None

        if not is_movie_query:

            if len(
                platform_episodes
            ) > 1:

                lines = []

                for (
                    platform,
                    episodes,
                ) in platform_episodes.items():

                    lines.append(
                        f"• {platform}: "
                        f"{episodes}"
                    )

                formatted_episodes = (
                    "\n"
                    + "\n".join(
                        lines
                    )
                )

            elif len(
                platform_episodes
            ) == 1:

                formatted_episodes = (
                    next(
                        iter(
                            platform_episodes.values()
                        )
                    )
                )

        # -------------------------------------------------------------
        # Status
        # -------------------------------------------------------------

        status = (
            self._merge_statuses(
                verified_statuses
            )
            if verified_statuses
            else "Not Verified"
        )

        # -------------------------------------------------------------
        # FINAL RESULT
        # -------------------------------------------------------------

        return {
            "name": clean_name,

            "hindi_dub": hindi_dub,

            "platform": " • ".join(
                verified_platforms
            ),

            "dub_by": (
                " • ".join(
                    dub_by
                )
                if dub_by
                else None
            ),

            "seasons": formatted_seasons,

            "episodes": formatted_episodes,

            "status": status,

            "languages": formatted_languages,

            # ---------------------------------------------------------
            # Neutral metadata from Jikan only.
            # ---------------------------------------------------------

            "poster_url": (
                mal_info.get(
                    "poster_url"
                )
                if mal_info
                else None
            ),

            "studio": (
                mal_info.get(
                    "studio"
                )
                if mal_info
                else None
            ),

            "source": "DC",

            "source_link": (
                mal_info.get(
                    "mal_url"
                )
                if mal_info
                else None
            ),
        }

    # =================================================================
    # STATUS MERGING
    # =================================================================

    @staticmethod
    def _merge_statuses(
        statuses: List[str],
    ) -> str:

        normalized = {
            status
            for status in statuses
            if status
            in {
                "Ongoing",
                "Completed",
            }
        }

        # -------------------------------------------------------------
        # Ongoing wins if sources disagree.
        # -------------------------------------------------------------

        if "Ongoing" in normalized:
            return "Ongoing"

        if "Completed" in normalized:
            return "Completed"

        return "Not Verified"

    # =================================================================
    # LANGUAGE EXTRACTION
    # =================================================================

    @staticmethod
    def _extract_verified_languages(
        text: str,
        soup: Optional[BeautifulSoup] = None,
    ) -> List[str]:

        """
        Extract languages ONLY when the official page provides
        evidence that the language is an audio/dub/voice track.

        Subtitle-only mentions are ignored.
        """

        if not text and not soup:
            return []

        # -------------------------------------------------------------
        # Build searchable corpus
        # -------------------------------------------------------------

        corpus_parts: List[str] = []

        if text:
            corpus_parts.append(text)

        if soup:

            # Meta tags
            for meta in soup.find_all("meta"):

                corpus_parts.append(
                    " ".join(
                        [
                            str(
                                meta.get(
                                    "name",
                                    "",
                                )
                            ),
                            str(
                                meta.get(
                                    "property",
                                    "",
                                )
                            ),
                            str(
                                meta.get(
                                    "itemprop",
                                    "",
                                )
                            ),
                            str(
                                meta.get(
                                    "content",
                                    "",
                                )
                            ),
                        ]
                    )
                )

            # JSON-LD
            for script in soup.find_all(
                "script",
                attrs={
                    "type": "application/ld+json"
                },
            ):

                try:

                    corpus_parts.append(
                        script.get_text(
                            " ",
                            strip=True,
                        )
                    )

                except Exception:
                    pass

            # Useful data attributes
            for tag in soup.find_all(
                attrs=True
            ):

                for attr_name, attr_value in (
                    tag.attrs.items()
                ):

                    if (
                        attr_name.startswith(
                            "data-"
                        )
                    ):

                        if isinstance(
                            attr_value,
                            list,
                        ):
                            attr_value = " ".join(
                                map(
                                    str,
                                    attr_value,
                                )
                            )

                        corpus_parts.append(
                            str(
                                attr_value
                            )
                        )

        full_corpus = " ".join(
            corpus_parts
        )

        if not full_corpus:
            return []

        # -------------------------------------------------------------
        # Normalize HTML entities and whitespace
        # -------------------------------------------------------------

        full_corpus = html.unescape(
            full_corpus
        )

        full_corpus = re.sub(
            r"\s+",
            " ",
            full_corpus,
        )

        found: List[str] = []

        # -------------------------------------------------------------
        # Language-specific detection
        # -------------------------------------------------------------

        for language in SUPPORTED_LANGUAGES:

            lang = re.escape(
                language
            )

            patterns = [

                # "Audio: Hindi"
                rf"\b(?:audio|audio\s+language|audio\s+track)"
                rf"\s*[:\-]?\s*"
                rf"[^.;|]{{0,80}}\b{lang}\b",

                # "Hindi Audio"
                rf"\b{lang}\b"
                rf"\s+(?:audio|audio\s+track)\b",

                # "Hindi Dub"
                rf"\b{lang}\b"
                rf"\s+(?:dub|dubbed|dubbing)\b",

                # "Dub: Hindi"
                rf"\b(?:dub|dubbed|dubbing|voice)"
                rf"\s*[:\-]?\s*"
                rf"[^.;|]{{0,80}}\b{lang}\b",

                # "Available in Hindi audio"
                rf"\b(?:available|watch|stream)"
                rf"\s+(?:in|with)"
                rf"\s+"
                rf"[^.;|]{{0,60}}\b{lang}\b"
                rf"(?:\s+(?:audio|dub|dubbed))?",

                # "Hindi version"
                rf"\b{lang}\b"
                rf"\s+(?:version|track)\b",

                # "Hindi voice"
                rf"\b{lang}\b"
                rf"\s+voice\b",

                # "Sub & Dub: Hindi"
                rf"\bsub\s*(?:&|and|/)\s*dub\b"
                rf"\s*[:\-]?\s*"
                rf"[^.;|]{{0,100}}\b{lang}\b",
            ]

            language_verified = False

            for pattern in patterns:

                for match in re.finditer(
                    pattern,
                    full_corpus,
                    re.I,
                ):

                    snippet = (
                        match.group(0)
                        .lower()
                    )

                    # -------------------------------------------------
                    # Reject subtitle-only evidence.
                    # -------------------------------------------------

                    subtitle_only = (
                        (
                            "subtitle"
                            in snippet
                            or "subtitles"
                            in snippet
                            or "subbed"
                            in snippet
                        )
                        and
                        not any(
                            token in snippet
                            for token in (
                                "audio",
                                "dub",
                                "dubbed",
                                "dubbing",
                                "voice",
                            )
                        )
                    )

                    if subtitle_only:
                        continue

                    language_verified = True
                    break

                if language_verified:
                    break

            if language_verified:
                found.append(
                    language
                )

        return found

    # =================================================================
    # LANGUAGE FORMATTER
    # =================================================================

    @staticmethod
    def _format_languages(
        languages: List[str],
    ) -> Optional[str]:

        if not languages:
            return None

        language_set = {
            language
            for language in languages
            if language in SUPPORTED_LANGUAGES
        }

        ordered = [
            language
            for language in SUPPORTED_LANGUAGES
            if language in language_set
        ]

        return (
            " • ".join(ordered)
            if ordered
            else None
        )

    # =================================================================
    # SEASON PARSING
    # =================================================================

    @staticmethod
    def _parse_season_numbers(
        text: str,
    ) -> List[int]:

        if not text:
            return []

        seasons: Set[int] = set()

        # -------------------------------------------------------------
        # Explicit "Season 1"
        # -------------------------------------------------------------

        for match in re.finditer(
            r"\bSeason\s*[-:]?\s*(\d{1,2})\b",
            text,
            re.I,
        ):

            try:

                number = int(
                    match.group(1)
                )

                if 1 <= number <= 30:
                    seasons.add(
                        number
                    )

            except (
                ValueError,
                IndexError,
            ):
                continue

        # -------------------------------------------------------------
        # Explicit "S1"
        # -------------------------------------------------------------

        for match in re.finditer(
            r"(?<![A-Za-z0-9])S\s*"
            r"(\d{1,2})"
            r"(?![A-Za-z0-9])",
            text,
            re.I,
        ):

            try:

                number = int(
                    match.group(1)
                )

                if 1 <= number <= 30:
                    seasons.add(
                        number
                    )

            except (
                ValueError,
                IndexError,
            ):
                continue

        return sorted(
            seasons
        )

    # =================================================================
    # SEASON FORMATTER
    # =================================================================

    @staticmethod
    def _format_season_numbers(
        season_nums: List[int],
    ) -> Optional[str]:

        if not season_nums:
            return None

        unique_sorted = sorted(
            {
                number
                for number in season_nums
                if 1 <= number <= 30
            }
        )

        if not unique_sorted:
            return None

        return ", ".join(
            f"Season {number}"
            for number in unique_sorted
        )

    # =================================================================
    # SEASON EXTRACTION
    # =================================================================

    @staticmethod
    def _extract_seasons(
        text: str,
        soup: Optional[BeautifulSoup] = None,
    ) -> Optional[str]:

        if not text:
            return None

        numbers = (
            AnimeScraper._parse_season_numbers(
                text
            )
        )

        return (
            AnimeScraper._format_season_numbers(
                numbers
            )
        )

    # =================================================================
    # EPISODE EXTRACTION
    # =================================================================

    @staticmethod
    def _extract_episodes(
        text: str,
        soup: Optional[BeautifulSoup] = None,
    ) -> Optional[str]:

        if not text:
            return None

        # -------------------------------------------------------------
        # Normalize whitespace
        # -------------------------------------------------------------

        clean_text = re.sub(
            r"\s+",
            " ",
            text,
        )

        # -------------------------------------------------------------
        # 12/12
        # -------------------------------------------------------------

        match = re.search(
            r"\b(\d{1,4})\s*/\s*(\d{1,4})\b",
            clean_text,
            re.I,
        )

        if match:

            current = int(
                match.group(1)
            )

            total = int(
                match.group(2)
            )

            if (
                1 <= current <= 9999
                and 1 <= total <= 9999
                and current <= total
            ):

                return (
                    f"{current}/{total}"
                )

        # -------------------------------------------------------------
        # "12 episodes"
        # -------------------------------------------------------------

        match = re.search(
            r"\b(\d{1,4})\s+episodes?\b",
            clean_text,
            re.I,
        )

        if match:

            number = int(
                match.group(1)
            )

            if 1 <= number <= 9999:
                return (
                    f"{number} episodes"
                )

        # -------------------------------------------------------------
        # "Episodes: 12"
        # -------------------------------------------------------------

        match = re.search(
            r"\bepisodes?\s*[:\-]?\s*"
            r"(\d{1,4})\b",
            clean_text,
            re.I,
        )

        if match:

            number = int(
                match.group(1)
            )

            if 1 <= number <= 9999:
                return (
                    f"{number} episodes"
                )

        # -------------------------------------------------------------
        # "12 released"
        # -------------------------------------------------------------

        match = re.search(
            r"\b(\d{1,4})\s+"
            r"(?:episodes?\s+)?released\b",
            clean_text,
            re.I,
        )

        if match:

            number = int(
                match.group(1)
            )

            if 1 <= number <= 9999:
                return (
                    f"{number} released"
                )

        # -------------------------------------------------------------
        # "Episode 12"
        #
        # This is NOT treated as total episode count unless the page
        # explicitly describes it as released/current/available.
        # -------------------------------------------------------------

        match = re.search(
            r"\bepisode\s+"
            r"(\d{1,4})"
            r"\s+"
            r"(?:released|available|out)\b",
            clean_text,
            re.I,
        )

        if match:

            number = int(
                match.group(1)
            )

            if 1 <= number <= 9999:
                return (
                    f"{number} released"
                )

        return None

    # =================================================================
    # STATUS EXTRACTION
    # =================================================================

    @staticmethod
    def _extract_status(
        text: str,
        soup: Optional[BeautifulSoup] = None,
    ) -> Optional[str]:

        if not text:
            return None

        clean_text = re.sub(
            r"\s+",
            " ",
            text,
        ).lower()

        # -------------------------------------------------------------
        # Explicit ongoing indicators
        # -------------------------------------------------------------

        ongoing_patterns = [
            r"\bongoing\b",
            r"\bcurrently airing\b",
            r"\bcurrently streaming\b",
            r"\bairing now\b",
            r"\bnew episode every\b",
        ]

        for pattern in ongoing_patterns:

            if re.search(
                pattern,
                clean_text,
                re.I,
            ):
                return "Ongoing"

        # -------------------------------------------------------------
        # Explicit completion indicators
        # -------------------------------------------------------------

        completed_patterns = [
            r"\bcompleted\b",
            r"\bcomplete series\b",
            r"\bseries complete\b",
            r"\bfinished\b",
            r"\bended\b",
            r"\bfinal episode\b",
            r"\bseries finale\b",
        ]

        for pattern in completed_patterns:

            if re.search(
                pattern,
                clean_text,
                re.I,
            ):
                return "Completed"

        return None

    # =================================================================
    # TITLE NORMALIZATION
    # =================================================================

    @staticmethod
    def _normalize(
        text: str,
    ) -> str:

        text = (
            text or ""
        ).lower()

        # -------------------------------------------------------------
        # HTML entities / common Unicode variants
        # -------------------------------------------------------------

        text = html.unescape(
            text
        )

        text = text.replace(
            "×",
            "x",
        )

        text = text.replace(
            "✕",
            "x",
        )

        text = text.replace(
            "–",
            " ",
        )

        text = text.replace(
            "—",
            " ",
        )

        # -------------------------------------------------------------
        # Common title variation
        # -------------------------------------------------------------

        text = re.sub(
            r"\bspy\s*x\s*family\b",
            "spy family",
            text,
            flags=re.I,
        )

        # -------------------------------------------------------------
        # Remove harmless article differences.
        # -------------------------------------------------------------

        text = re.sub(
            r"\bthe\b",
            " ",
            text,
            flags=re.I,
        )

        # -------------------------------------------------------------
        # Remove punctuation.
        # -------------------------------------------------------------

        text = re.sub(
            r"[^a-z0-9]+",
            " ",
            text,
        )

        return " ".join(
            text.split()
        )

    # =================================================================
    # TITLE MATCHING
    # =================================================================

    @staticmethod
    def _title_matches(
        title: str,
        query: str,
    ) -> bool:

        if not title or not query:
            return False

        normalized_title = (
            AnimeScraper._normalize(
                title
            )
        )

        normalized_query = (
            AnimeScraper._normalize(
                query
            )
        )

        if (
            not normalized_title
            or not normalized_query
        ):
            return False

        # -------------------------------------------------------------
        # Exact match
        # -------------------------------------------------------------

        if (
            normalized_title
            == normalized_query
        ):
            return True

        # -------------------------------------------------------------
        # Query contained inside title.
        # -------------------------------------------------------------

        if (
            normalized_query
            in normalized_title
        ):
            return True

        title_words = set(
            normalized_title.split()
        )

        query_words = set(
            normalized_query.split()
        )

        if not title_words or not query_words:
            return False

        # -------------------------------------------------------------
        # Very short titles need stricter matching.
        # Prevents false positives for names such as:
        # "One", "Blue", "Fire", etc.
        # -------------------------------------------------------------

        if len(query_words) <= 2:

            return query_words.issubset(
                title_words
            )

        # -------------------------------------------------------------
        # Longer titles:
        # At least 75% of query tokens must match.
        # -------------------------------------------------------------

        overlap = (
            query_words
            .intersection(
                title_words
            )
        )

        ratio = (
            len(overlap)
            / len(query_words)
        )

        return ratio >= 0.75

    # =================================================================
    # MOVIE DETECTION
    # =================================================================

    @staticmethod
    def _is_movie_result(
        title: str,
    ) -> bool:

        if not title:
            return False

        return bool(
            re.search(
                r"\b("
                r"movie|film|"
                r"theatrical\s+release|"
                r"feature\s+film"
                r")\b",
                title,
                re.I,
            )
        )

    # =================================================================
    # TITLE CLEANING
    # =================================================================

    @staticmethod
    def _clean_title(
        title: str,
    ) -> str:

        if not title:
            return ""

        title = html.unescape(
            str(title)
        )

        # -------------------------------------------------------------
        # Remove common search-result prefixes.
        # -------------------------------------------------------------

        title = re.sub(
            r"^\s*search\s+results?"
            r"\s*(?:for)?\s*[:\-]\s*",
            "",
            title,
            flags=re.I,
        )

        # -------------------------------------------------------------
        # Remove source suffixes.
        # -------------------------------------------------------------

        title = re.sub(
            r"\s+[-|–—]\s+"
            r"(?:Crunchyroll|Netflix|"
            r"Prime\s+Video|"
            r"JioHotstar|Hotstar|"
            r"MX\s+Player|"
            r"ZEE5|SonyLIV|YouTube)"
            r".*$",
            "",
            title,
            flags=re.I,
        )

        # -------------------------------------------------------------
        # Remove language labels only when they are standalone
        # metadata markers.
        # -------------------------------------------------------------

        title = re.sub(
            r"\b("
            r"Hindi|English|Tamil|Telugu|Japanese|"
            r"Malayalam|Bangla|Bengali|Kannada|"
            r"Chinese|Korean|Marathi"
            r")\b",
            "",
            title,
            flags=re.I,
        )

        title = re.sub(
            r"\b("
            r"multi\s+audio|"
            r"dual\s+audio|"
            r"multi\s+language"
            r")\b",
            "",
            title,
            flags=re.I,
        )

        # -------------------------------------------------------------
        # Remove common video metadata.
        # -------------------------------------------------------------

        title = re.sub(
            r"\b("
            r"official\s+trailer|"
            r"official\s+video|"
            r"trailer|"
            r"episode\s+\d+|"
            r"ep\.?\s*\d+"
            r")\b",
            "",
            title,
            flags=re.I,
        )

        # -------------------------------------------------------------
        # Remove empty bracket groups.
        # -------------------------------------------------------------

        title = re.sub(
            r"\(\s*\)",
            "",
            title,
        )

        title = re.sub(
            r"\[\s*\]",
            "",
            title,
        )

        title = re.sub(
            r"\{\s*\}",
            "",
            title,
        )

        # -------------------------------------------------------------
        # Clean separators without destroying normal title text.
        # -------------------------------------------------------------

        title = re.sub(
            r"\s*[\|–—]+\s*",
            " ",
            title,
        )

        title = re.sub(
            r"\s{2,}",
            " ",
            title,
        )

        return title.strip(
            " -|:,."
        )

    # =================================================================
    # OFFICIAL PAGE TITLE EXTRACTION
    # =================================================================

    @staticmethod
    def _extract_official_page_title(
        soup: BeautifulSoup,
    ) -> str:

        if not soup:
            return ""

        # -------------------------------------------------------------
        # OpenGraph title is generally closer to the actual content
        # title than <title>, especially on streaming sites.
        # -------------------------------------------------------------

        og_title = soup.find(
            "meta",
            attrs={
                "property": "og:title"
            },
        )

        if og_title:

            content = og_title.get(
                "content"
            )

            if content:

                content = (
                    content.strip()
                )

                if content:
                    return content

        # -------------------------------------------------------------
        # H1 fallback
        # -------------------------------------------------------------

        h1 = soup.find(
            "h1"
        )

        if h1:

            text = h1.get_text(
                " ",
                strip=True,
            )

            if text:
                return text

        # -------------------------------------------------------------
        # HTML title fallback
        # -------------------------------------------------------------

        title_tag = soup.find(
            "title"
        )

        if title_tag:

            text = title_tag.get_text(
                " ",
                strip=True,
            )

            if text:
                return text

        return ""

    # =================================================================
    # STRUCTURED DATA HELPERS
    # =================================================================

    @staticmethod
    def _extract_json_ld(
        soup: Optional[BeautifulSoup],
    ) -> List[Dict]:

        if not soup:
            return []

        results: List[Dict] = []

        scripts = soup.find_all(
            "script",
            attrs={
                "type": re.compile(
                    r"application/ld\+json",
                    re.I,
                )
            },
        )

        for script in scripts:

            raw = script.get_text(
                " ",
                strip=True,
            )

            if not raw:
                continue

            try:

                data = json.loads(
                    raw
                )

            except (
                json.JSONDecodeError,
                TypeError,
                ValueError,
            ):
                continue

            # ---------------------------------------------------------
            # JSON-LD can be a dictionary.
            # ---------------------------------------------------------

            if isinstance(
                data,
                dict,
            ):

                results.append(
                    data
                )

                # -----------------------------------------------------
                # Some documents use @graph.
                # -----------------------------------------------------

                graph = data.get(
                    "@graph"
                )

                if isinstance(
                    graph,
                    list,
                ):

                    for item in graph:

                        if isinstance(
                            item,
                            dict,
                        ):
                            results.append(
                                item
                            )

            # ---------------------------------------------------------
            # Or directly an array.
            # ---------------------------------------------------------

            elif isinstance(
                data,
                list,
            ):

                for item in data:

                    if isinstance(
                        item,
                        dict,
                    ):
                        results.append(
                            item
                        )

        return results

    # =================================================================
    # JSON-LD TEXT EXTRACTION
    # =================================================================

    @staticmethod
    def _json_ld_text(
        soup: Optional[BeautifulSoup],
    ) -> str:

        objects = (
            AnimeScraper._extract_json_ld(
                soup
            )
        )

        if not objects:
            return ""

        parts: List[str] = []

        for obj in objects:

            try:

                parts.append(
                    json.dumps(
                        obj,
                        ensure_ascii=False,
                    )
                )

            except (
                TypeError,
                ValueError,
            ):
                continue

        return " ".join(
            parts
        )

    # =================================================================
    # SEARCH CORPUS BUILDER
    # =================================================================

    @staticmethod
    def _build_search_corpus(
        text: str,
        soup: Optional[BeautifulSoup],
    ) -> str:

        parts: List[str] = []

        if text:
            parts.append(
                text
            )

        if soup:

            # ---------------------------------------------------------
            # Metadata
            # ---------------------------------------------------------

            for meta in soup.find_all(
                "meta"
            ):

                values = []

                for attribute in (
                    "name",
                    "property",
                    "itemprop",
                    "content",
                ):

                    value = meta.get(
                        attribute
                    )

                    if value:
                        values.append(
                            str(value)
                        )

                if values:
                    parts.append(
                        " ".join(
                            values
                        )
                    )

            # ---------------------------------------------------------
            # JSON-LD
            # ---------------------------------------------------------

            json_text = (
                AnimeScraper._json_ld_text(
                    soup
                )
            )

            if json_text:
                parts.append(
                    json_text
                )

        corpus = " ".join(
            parts
        )

        corpus = html.unescape(
            corpus
        )

        corpus = re.sub(
            r"\s+",
            " ",
            corpus,
        )

        return corpus.strip()

    # =================================================================
    # URL HELPERS
    # =================================================================

    @staticmethod
    def _same_url(
        first_url: str,
        second_url: str,
    ) -> bool:

        try:

            first = urlparse(
                first_url
            )

            second = urlparse(
                second_url
            )

            return (
                first.scheme.lower()
                == second.scheme.lower()
                and (
                    first.hostname or ""
                ).lower()
                == (
                    second.hostname or ""
                ).lower()
                and (
                    first.path.rstrip("/")
                    == second.path.rstrip("/")
                )
            )

        except Exception:
            return False

    # =================================================================
    # SOURCE URL EXTRACTION
    # =================================================================

    @staticmethod
    def _extract_source_urls(
        soup: Optional[BeautifulSoup],
        base_url: str,
    ) -> List[str]:

        if not soup:
            return []

        urls: List[str] = []

        # -------------------------------------------------------------
        # Canonical
        # -------------------------------------------------------------

        canonical = (
            AnimeScraper._extract_canonical_url(
                soup,
                base_url,
            )
        )

        if canonical:
            urls.append(
                canonical
            )

        # -------------------------------------------------------------
        # OpenGraph
        # -------------------------------------------------------------

        og_url = soup.find(
            "meta",
            attrs={
                "property": "og:url"
            },
        )

        if og_url:

            content = og_url.get(
                "content"
            )

            if content:

                urls.append(
                    urljoin(
                        base_url,
                        content,
                    )
                )

        # -------------------------------------------------------------
        # Deduplicate
        # -------------------------------------------------------------

        unique_urls = []

        for url in urls:

            if url and url not in unique_urls:
                unique_urls.append(
                    url
                )

        return unique_urls

    # =================================================================
    # TEXT / DOM UTILITIES
    # =================================================================

    @staticmethod
    def _get_tag_text(
        soup: Optional[BeautifulSoup],
        tag_name: str,
    ) -> str:

        if not soup:
            return ""

        tag = soup.find(
            tag_name
        )

        if not tag:
            return ""

        return tag.get_text(
            " ",
            strip=True,
        )

    # =================================================================
    # META CONTENT EXTRACTION
    # =================================================================

    @staticmethod
    def _extract_meta_content(
        soup: Optional[BeautifulSoup],
    ) -> List[str]:

        if not soup:
            return []

        values: List[str] = []

        for meta in soup.find_all(
            "meta"
        ):

            for attribute in (
                "content",
                "name",
                "property",
                "itemprop",
            ):

                value = meta.get(
                    attribute
                )

                if value:
                    values.append(
                        str(value)
                    )

        return values

    # =================================================================
    # JSON / SCRIPT TEXT EXTRACTION
    # =================================================================

    @staticmethod
    def _extract_script_text(
        soup: Optional[BeautifulSoup],
    ) -> List[str]:

        if not soup:
            return []

        values: List[str] = []

        for script in soup.find_all(
            "script"
        ):

            try:

                text = script.get_text(
                    " ",
                    strip=True,
                )

            except Exception:
                continue

            if text:
                values.append(
                    text
                )

        return values

    # =================================================================
    # PAGE TEXT NORMALIZATION
    # =================================================================

    @staticmethod
    def _clean_page_text(
        text: str,
    ) -> str:

        if not text:
            return ""

        text = html.unescape(
            text
        )

        # Remove zero-width characters.
        text = re.sub(
            r"[\u200b-\u200d\ufeff]",
            "",
            text,
        )

        # Normalize whitespace.
        text = re.sub(
            r"\s+",
            " ",
            text,
        )

        return text.strip()

    # =================================================================
    # LANGUAGE EVIDENCE HELPERS
    # =================================================================

    @staticmethod
    def _has_audio_language_evidence(
        corpus: str,
        language: str,
    ) -> bool:

        if not corpus or not language:
            return False

        lang = re.escape(
            language
        )

        # -------------------------------------------------------------
        # Strong audio/dub relationships.
        # -------------------------------------------------------------

        strong_patterns = [

            rf"\b(?:audio|audio\s+track|"
            rf"audio\s+language)\b"
            rf"[^.;|]{{0,80}}\b{lang}\b",

            rf"\b{lang}\b"
            rf"[^.;|]{{0,40}}"
            rf"\b(?:audio|audio\s+track)\b",

            rf"\b(?:dub|dubbed|dubbing|"
            rf"voice|voice\s+track)\b"
            rf"[^.;|]{{0,80}}\b{lang}\b",

            rf"\b{lang}\b"
            rf"[^.;|]{{0,40}}"
            rf"\b(?:dub|dubbed|dubbing|voice)\b",
        ]

        for pattern in strong_patterns:

            if re.search(
                pattern,
                corpus,
                re.I,
            ):
                return True

        # -------------------------------------------------------------
        # Explicit language-selection UI wording.
        # -------------------------------------------------------------

        ui_patterns = [

            rf"\bselect\s+audio\b"
            rf"[^.;|]{{0,100}}\b{lang}\b",

            rf"\baudio\s+languages?\b"
            rf"[^.;|]{{0,100}}\b{lang}\b",

            rf"\blanguages?\b"
            rf"[^.;|]{{0,80}}"
            rf"\b{lang}\b"
            rf"[^.;|]{{0,50}}"
            rf"\baudio\b",

            rf"\b{lang}\b"
            rf"[^.;|]{{0,80}}"
            rf"\b(?:version|track)\b",
        ]

        for pattern in ui_patterns:

            if re.search(
                pattern,
                corpus,
                re.I,
            ):
                return True

        return False

    # =================================================================
    # TITLE EVIDENCE
    # =================================================================

    @staticmethod
    def _extract_title_candidates(
        soup: Optional[BeautifulSoup],
    ) -> List[str]:

        if not soup:
            return []

        candidates: List[str] = []

        # -------------------------------------------------------------
        # OG title
        # -------------------------------------------------------------

        og_title = soup.find(
            "meta",
            attrs={
                "property": "og:title"
            },
        )

        if og_title:

            value = og_title.get(
                "content"
            )

            if value:
                candidates.append(
                    value.strip()
                )

        # -------------------------------------------------------------
        # H1
        # -------------------------------------------------------------

        for h1 in soup.find_all(
            "h1"
        ):

            value = h1.get_text(
                " ",
                strip=True,
            )

            if value:
                candidates.append(
                    value
                )

        # -------------------------------------------------------------
        # Title
        # -------------------------------------------------------------

        if soup.title:

            value = soup.title.get_text(
                " ",
                strip=True,
            )

            if value:
                candidates.append(
                    value
                )

        # -------------------------------------------------------------
        # Deduplicate
        # -------------------------------------------------------------

        unique = []

        for candidate in candidates:

            if candidate not in unique:
                unique.append(
                    candidate
                )

        return unique

    # =================================================================
    # URL PATH ANALYSIS
    # =================================================================

    @staticmethod
    def _url_path_tokens(
        url: str,
    ) -> Set[str]:

        if not url:
            return set()

        try:

            parsed = urlparse(
                url
            )

            path = unquote(
                parsed.path or ""
            ).lower()

            tokens = re.findall(
                r"[a-z0-9]+",
                path,
            )

            return set(
                tokens
            )

        except Exception:
            return set()

    # =================================================================
    # YOUTUBE URL VALIDATION
    # =================================================================

    @staticmethod
    def _is_youtube_video_url(
        url: str,
    ) -> bool:

        try:

            parsed = urlparse(
                url
            )

            hostname = (
                parsed.hostname or ""
            ).lower()

            if hostname not in {
                "youtube.com",
                "www.youtube.com",
                "m.youtube.com",
            }:
                return False

            if (
                parsed.path.lower()
                != "/watch"
            ):
                return False

            params = parse_qs(
                parsed.query
            )

            video_ids = params.get(
                "v",
                [],
            )

            return bool(
                video_ids
                and video_ids[0].strip()
            )

        except Exception:
            return False

    # =================================================================
    # YOUTUBE PLAYLIST URL VALIDATION
    # =================================================================

    @staticmethod
    def _is_youtube_playlist_url(
        url: str,
    ) -> bool:

        try:

            parsed = urlparse(
                url
            )

            hostname = (
                parsed.hostname or ""
            ).lower()

            if hostname not in {
                "youtube.com",
                "www.youtube.com",
                "m.youtube.com",
            }:
                return False

            params = parse_qs(
                parsed.query
            )

            playlist_ids = params.get(
                "list",
                [],
            )

            return bool(
                playlist_ids
                and playlist_ids[0].strip()
            )

        except Exception:
            return False

    # =================================================================
    # URL QUALITY CHECK
    # =================================================================

    @staticmethod
    def _has_specific_content_path(
        url: str,
    ) -> bool:

        if not url:
            return False

        try:

            parsed = urlparse(
                url
            )

            path = (
                parsed.path or ""
            ).strip("/").lower()

            if not path:
                return False

            generic_segments = {
                "home",
                "search",
                "browse",
                "catalog",
                "login",
                "signin",
                "register",
                "signup",
                "error",
                "404",
            }

            segments = [
                segment
                for segment in path.split("/")
                if segment
            ]

            if not segments:
                return False

            if all(
                segment in generic_segments
                for segment in segments
            ):
                return False

            return True

        except Exception:
            return False

    # =================================================================
    # OFFICIAL SOURCE DOMAIN SANITIZATION
    # =================================================================

    @staticmethod
    def _sanitize_official_url(
        url: str,
        allowed_domains: List[str],
    ) -> Optional[str]:

        if not url:
            return None

        url = html.unescape(
            unquote(
                url.strip()
            )
        )

        if not url.startswith(
            ("http://", "https://")
        ):
            return None

        # -------------------------------------------------------------
        # Only HTTPS should be accepted for final official URLs.
        # -------------------------------------------------------------

        parsed = urlparse(
            url
        )

        if parsed.scheme.lower() != "https":
            return None

        if not AnimeScraper._is_allowed_domain(
            url,
            allowed_domains,
        ):
            return None

        return url

    # =================================================================
    # SAFE URL JOIN
    # =================================================================

    @staticmethod
    def _safe_urljoin(
        base_url: str,
        target_url: str,
        allowed_domains: List[str],
    ) -> Optional[str]:

        if not base_url or not target_url:
            return None

        try:

            joined = urljoin(
                base_url,
                target_url,
            )

            return AnimeScraper._sanitize_official_url(
                joined,
                allowed_domains,
            )

        except Exception:
            return None

    # =================================================================
    # RESPONSE VALIDATION
    # =================================================================

    @staticmethod
    def _is_html_response(
        response: requests.Response,
    ) -> bool:

        try:

            content_type = (
                response.headers.get(
                    "Content-Type",
                    "",
                )
                .lower()
            )

            return (
                "text/html"
                in content_type
                or "application/xhtml+xml"
                in content_type
                or not content_type
            )

        except Exception:
            return False

    # =================================================================
    # PAGE RESPONSE SAFETY CHECK
    # =================================================================

    @staticmethod
    def _validate_page_response(
        response: requests.Response,
        allowed_domains: List[str],
    ) -> bool:

        if not response:
            return False

        if response.status_code != 200:
            return False

        if not AnimeScraper._is_html_response(
            response
        ):
            return False

        final_url = (
            response.url
            or ""
        )

        if not AnimeScraper._is_allowed_domain(
            final_url,
            allowed_domains,
        ):
            return False

        return True

    # =================================================================
    # PAGE CONTENT QUALITY
    # =================================================================

    @staticmethod
    def _has_meaningful_page_content(
        soup: Optional[BeautifulSoup],
        minimum_length: int = 80,
    ) -> bool:

        if not soup:
            return False

        text = soup.get_text(
            " ",
            strip=True,
        )

        text = re.sub(
            r"\s+",
            " ",
            text,
        ).strip()

        return len(
            text
        ) >= minimum_length

    # =================================================================
    # ERROR PAGE DETECTION
    # =================================================================

    @staticmethod
    def _looks_like_error_page(
        soup: Optional[BeautifulSoup],
    ) -> bool:

        if not soup:
            return True

        title = ""

        if soup.title:
            title = soup.title.get_text(
                " ",
                strip=True,
            ).lower()

        text = soup.get_text(
            " ",
            strip=True,
        ).lower()

        error_patterns = [
            "404 not found",
            "page not found",
            "something went wrong",
            "content unavailable",
            "video unavailable",
            "this page isn't available",
            "this content is not available",
        ]

        for pattern in error_patterns:

            if (
                pattern in title
                or pattern in text[:3000]
            ):
                return True

        return False

            # =================================================================
    # CANONICAL URL EXTRACTION
    # =================================================================

    @staticmethod
    def _extract_canonical_url(
        soup: Optional[BeautifulSoup],
        base_url: Optional[str] = None,
    ) -> Optional[str]:

        if not soup:
            return None

        # -------------------------------------------------------------
        # Prefer <link rel="canonical">
        # -------------------------------------------------------------

        canonical_tag = soup.find(
            "link",
            attrs={
                "rel": re.compile(
                    r"canonical",
                    re.I,
                )
            },
        )

        if canonical_tag:

            href = canonical_tag.get(
                "href"
            )

            if href:

                href = href.strip()

                if base_url:
                    href = urljoin(
                        base_url,
                        href,
                    )

                return href

        # -------------------------------------------------------------
        # Fallback to og:url
        # -------------------------------------------------------------

        og_url = soup.find(
            "meta",
            attrs={
                "property": "og:url"
            },
        )

        if og_url:

            content = og_url.get(
                "content"
            )

            if content:

                content = content.strip()

                if base_url:
                    content = urljoin(
                        base_url,
                        content,
                    )

                return content

        return None

    # =================================================================
    # GENERIC LANDING PAGE DETECTION
    # =================================================================

    @staticmethod
    def _is_generic_landing_page(
        url: str,
        soup: BeautifulSoup,
    ) -> bool:

        if not url:
            return True

        try:

            parsed = urlparse(
                url
            )

            path = (
                parsed.path or ""
            ).strip(
                "/"
            ).lower()

            query = (
                parsed.query or ""
            ).lower()

            hostname = (
                parsed.hostname or ""
            ).lower()

        except Exception:
            return True

        # -------------------------------------------------------------
        # Root page
        # -------------------------------------------------------------

        if not path:
            return True

        # -------------------------------------------------------------
        # Generic routes
        # -------------------------------------------------------------

        generic_paths = {
            "login",
            "signin",
            "sign-in",
            "register",
            "signup",
            "sign-up",
            "browse",
            "search",
            "home",
            "catalog",
            "error",
            "404",
        }

        path_parts = [
            part
            for part in path.split("/")
            if part
        ]

        if (
            len(path_parts) == 1
            and path_parts[0]
            in generic_paths
        ):
            return True

        # -------------------------------------------------------------
        # YouTube channel root.
        #
        # A channel itself is not enough evidence that a particular
        # anime exists on that channel.
        # -------------------------------------------------------------

        if (
            "youtube.com"
            in hostname
        ):

            if (
                path.startswith("@")
                and "/watch"
                not in path
                and "list="
                not in query
            ):
                return True

            if path in {
                "channel",
                "c",
                "user",
            }:
                return True

        # -------------------------------------------------------------
        # Generic page title detection
        # -------------------------------------------------------------

        title = ""

        if soup and soup.title:

            title = soup.title.get_text(
                " ",
                strip=True,
            ).lower()

        generic_title_patterns = [
            "log in",
            "login",
            "sign in",
            "signin",
            "create account",
            "register",
            "404",
            "not found",
            "page not found",
            "search results",
            "search result",
            "browse",
            "home page",
            "welcome",
            "something went wrong",
        ]

        for pattern in generic_title_patterns:

            if pattern in title:
                return True

        return False

    # =================================================================
    # YOUTUBE OFFICIAL CHANNEL VERIFICATION
    # =================================================================

    @staticmethod
    def _verify_youtube_official_channel(
        url: str,
        soup: BeautifulSoup,
        platform_cfg: Dict,
    ) -> bool:

        handles = (
            platform_cfg.get(
                "youtube_handles",
                [],
            )
        )

        if not handles:
            return True

        if not url:
            return False

        url_lower = (
            unquote(
                url
            )
            .lower()
        )

        # -------------------------------------------------------------
        # 1. Exact handle in final URL
        # -------------------------------------------------------------

        for handle in handles:

            expected = (
                "/@"
                + handle.lower()
            )

            if expected in url_lower:
                return True

        # -------------------------------------------------------------
        # 2. Inspect canonical URL
        # -------------------------------------------------------------

        canonical = (
            AnimeScraper._extract_canonical_url(
                soup,
                url,
            )
            if soup
            else None
        )

        if canonical:

            canonical_lower = (
                canonical.lower()
            )

            for handle in handles:

                if (
                    "/@"
                    + handle.lower()
                ) in canonical_lower:

                    return True

        # -------------------------------------------------------------
        # 3. Inspect metadata
        # -------------------------------------------------------------

        metadata_parts: List[str] = []

        if soup:

            for meta in soup.find_all(
                "meta"
            ):

                for attr in (
                    "content",
                    "name",
                    "property",
                    "itemprop",
                ):

                    value = meta.get(
                        attr
                    )

                    if value:
                        metadata_parts.append(
                            str(value)
                        )

            for link in soup.find_all(
                "link"
            ):

                for attr in (
                    "href",
                    "itemprop",
                ):

                    value = link.get(
                        attr
                    )

                    if value:
                        metadata_parts.append(
                            str(value)
                        )

        metadata = " ".join(
            metadata_parts
        ).lower()

        for handle in handles:

            h = handle.lower()

            if (
                f"youtube.com/@{h}"
                in metadata
                or f"@{h}"
                in metadata
            ):
                return True

        # -------------------------------------------------------------
        # 4. JSON-LD verification
        # -------------------------------------------------------------

        if soup:

            for obj in (
                AnimeScraper._extract_json_ld(
                    soup
                )
            ):

                try:

                    raw = json.dumps(
                        obj,
                        ensure_ascii=False,
                    ).lower()

                except (
                    TypeError,
                    ValueError,
                ):
                    continue

                for handle in handles:

                    h = handle.lower()

                    if (
                        f"youtube.com/@{h}"
                        in raw
                        or f"@{h}"
                        in raw
                    ):
                        return True

        # -------------------------------------------------------------
        # Do NOT accept an arbitrary YouTube page merely because the
        # word "YouTube" appears in it.
        # -------------------------------------------------------------

        return False

    # =================================================================
    # FINAL PLATFORM RESULT VALIDATION
    # =================================================================

    @staticmethod
    def _validate_verified_platform_result(
        result: Optional[Dict],
    ) -> bool:

        if not result:
            return False

        if result.get(
            "verified"
        ) is not True:
            return False

        platform = result.get(
            "platform"
        )

        url = result.get(
            "url"
        )

        title = result.get(
            "title"
        )

        if not platform:
            return False

        if not url:
            return False

        if not title:
            return False

        return True

    # =================================================================
    # FINAL RESULT SANITIZATION
    # =================================================================

    @staticmethod
    def _sanitize_final_result(
        result: Optional[Dict],
    ) -> Optional[Dict]:

        if not result:
            return None

        clean_result = dict(
            result
        )

        # -------------------------------------------------------------
        # Normalize languages
        # -------------------------------------------------------------

        languages = clean_result.get(
            "languages"
        )

        if languages:

            language_list = [
                language.strip()
                for language in
                str(languages).split("•")
                if language.strip()
                in SUPPORTED_LANGUAGES
            ]

            clean_result[
                "languages"
            ] = (
                " • ".join(
                    language_list
                )
                if language_list
                else None
            )

        # -------------------------------------------------------------
        # Hindi status must always be based on verified language data.
        # -------------------------------------------------------------

        language_text = (
            clean_result.get(
                "languages"
            )
            or ""
        )

        clean_result[
            "hindi_dub"
        ] = (
            "Available"
            if "Hindi"
            in language_text
            else "Not Verified"
        )

        # -------------------------------------------------------------
        # Never claim a platform when none was verified.
        # -------------------------------------------------------------

        if not clean_result.get(
            "platform"
        ):
            return None

        return clean_result

    # =================================================================
    # SAFE PUBLIC SEARCH WRAPPER
    # =================================================================

    def safe_search_anime(
        self,
        anime_name: str,
    ) -> Optional[Dict]:

        try:

            result = self.search_anime(
                anime_name
            )

            return (
                self._sanitize_final_result(
                    result
                )
            )

        except Exception as exc:

            logger.exception(
                "Anime search failed: %s",
                exc,
            )

            return None


# =====================================================================
# SINGLETON
# =====================================================================

anime_scraper = AnimeScraper()


# =====================================================================
# PUBLIC API
# =====================================================================

def get_anime_info(
    anime_name: str,
) -> Optional[Dict]:

    """
    Public API for verified anime metadata.

    Only information verified from official sources is returned.
    Jikan/MAL is used only for neutral metadata such as poster,
    studio, canonical title, and MAL URL.
    """

    anime_name = (
        anime_name or ""
    ).strip()

    if not anime_name:
        return None

    return anime_scraper.safe_search_anime(
        anime_name
)
