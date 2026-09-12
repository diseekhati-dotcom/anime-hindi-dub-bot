# ============================================================
# anime_scraper.py
# PART 1/7
# ============================================================

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time

from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from urllib.parse import quote_plus, urljoin, urlparse

import aiohttp
from bs4 import BeautifulSoup


# ------------------------------------------------------------
# Optional fuzzy matching
# ------------------------------------------------------------

try:
    from rapidfuzz import fuzz
except ImportError:
    fuzz = None


# ------------------------------------------------------------
# Logging
# ------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

logger = logging.getLogger("AnimeScraper")


# ------------------------------------------------------------
# Constants
# ------------------------------------------------------------

BASE_URL = "https://www.rareanimes.mov"
SEARCH_URL = BASE_URL + "/?s={query}"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/140.0.0.0 Safari/537.36"
)

REQUEST_TIMEOUT = 12

CACHE_DIR = Path("anime_cache")
CACHE_DIR.mkdir(exist_ok=True)

ONGOING_CACHE_TTL = 5 * 60
COMPLETED_CACHE_TTL = 24 * 60 * 60


# ------------------------------------------------------------
# HTTP headers
# ------------------------------------------------------------

HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": (
        "text/html,application/xhtml+xml,"
        "application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
}


# ------------------------------------------------------------
# Episode model
# ------------------------------------------------------------

@dataclass
class Episode:
    number: int
    title: str = ""
    languages: list[str] = field(default_factory=list)
    release_date: Optional[str] = None


# ------------------------------------------------------------
# Search candidate
# ------------------------------------------------------------

@dataclass
class SearchCandidate:
    title: str
    url: str
    score: float = 0.0


# ------------------------------------------------------------
# Anime model
# ------------------------------------------------------------

@dataclass
class AnimeInfo:

    title: str = ""

    canonical_title: str = ""

    aliases: list[str] = field(default_factory=list)

    poster_url: Optional[str] = None

    source_url: Optional[str] = None

    source: str = "DC"

    hindi_available: bool = False

    platform: list[str] = field(default_factory=list)

    season: Optional[int] = None

    total_episodes: Optional[int] = None

    available_episodes: dict[str, int] = field(
        default_factory=dict
    )

    languages: list[str] = field(default_factory=list)

    status: str = "unknown"

    last_episode: Optional[int] = None

    last_release: Optional[str] = None

    next_episode: Optional[int] = None

    expected_release: Optional[str] = None

    schedule: Optional[str] = None

    studio: Optional[str] = None

    dub_by: Optional[str] = None

    release_year: Optional[int] = None

    runtime: Optional[str] = None

    genres: list[str] = field(default_factory=list)

    synopsis: Optional[str] = None

    episodes: list[Episode] = field(default_factory=list)

    # --------------------------------------------------------
    # Franchise / multi-series support
    # --------------------------------------------------------

    franchise: Optional[str] = None

    series_type: str = "series"

    related_series: list[str] = field(
        default_factory=list
    )

    movies: list[str] = field(
        default_factory=list
    )

    scraped_at: float = field(
        default_factory=time.time
    )


# ------------------------------------------------------------
# Franchise result model
# ------------------------------------------------------------

@dataclass
class FranchiseInfo:

    name: str = ""

    series: list[AnimeInfo] = field(
        default_factory=list
    )

    movies: list[AnimeInfo] = field(
        default_factory=list
    )


# ------------------------------------------------------------
# Exceptions
# ------------------------------------------------------------

class AnimeNotFound(Exception):
    pass


class ScraperError(Exception):
    pass


# ============================================================
# PART 2/7
# HTTP / CACHE / TEXT UTILITIES
# ============================================================


# ------------------------------------------------------------
# HTTP session
# ------------------------------------------------------------

async def create_session() -> aiohttp.ClientSession:

    timeout = aiohttp.ClientTimeout(
        total=REQUEST_TIMEOUT
    )

    connector = aiohttp.TCPConnector(
        limit=10,
        limit_per_host=5,
        ssl=False,
    )

    return aiohttp.ClientSession(
        headers=HEADERS,
        timeout=timeout,
        connector=connector
    )


# ------------------------------------------------------------
# Fetch URL
# ------------------------------------------------------------

async def fetch(
    session: aiohttp.ClientSession,
    url: str,
) -> str:

    logger.info(
        "Fetching: %s",
        url
    )

    try:

        async with session.get(
            url,
            allow_redirects=True
        ) as response:

            if response.status != 200:

                raise ScraperError(
                    f"HTTP {response.status}: {url}"
                )

            return await response.text(
                errors="ignore"
            )

    except asyncio.TimeoutError:

        raise ScraperError(
            f"Timeout: {url}"
        )

    except aiohttp.ClientError as exc:

        raise ScraperError(
            f"Request failed: {url} -> {exc}"
        )


# ------------------------------------------------------------
# Normalize text
# ------------------------------------------------------------

def clean_text(
    value: str | None
) -> str:

    if not value:
        return ""

    value = value.replace(
        "\xa0",
        " "
    )

    value = value.replace(
        "\r",
        " "
    )

    value = value.replace(
        "\n",
        " "
    )

    value = re.sub(
        r"\s+",
        " ",
        value
    )

    return value.strip()


# ------------------------------------------------------------
# Normalize title for matching
# ------------------------------------------------------------

def normalize_title(
    title: str
) -> str:

    title = title.lower()

    replacements = [
        "–",
        "—",
        "-",
        "_",
        ":",
        ",",
        ".",
        "'",
        '"',
        "!",
        "?",
        "(",
        ")",
        "[",
        "]",
        "{",
        "}",
        "+",
        "/",
    ]

    for char in replacements:

        title = title.replace(
            char,
            " "
        )

    noise = [
        "season",
        "hindi",
        "dubbed",
        "dub",
        "episodes",
        "episode",
        "download",
        "hd",
        "watch",
        "online",
        "full",
        "complete",
    ]

    words = title.split()

    words = [
        word
        for word in words
        if word not in noise
    ]

    return " ".join(
        words
    ).strip()


def title_match_score(
    query: str,
    title: str
) -> float:

    q = normalize_title(query)
    t = normalize_title(title)

    if not q or not t:
        return 0.0

    if q == t:
        return 100.0

    if q in t:
        return 90.0

    if t in q:
        return 80.0

    q_words = set(q.split())
    t_words = set(t.split())

    if not q_words or not t_words:
        return 0.0

    overlap = len(q_words & t_words)

    return (
        overlap / len(q_words)
    ) * 70.0


# ------------------------------------------------------------
# Slug normalize
# ------------------------------------------------------------

def normalize_slug(
    value: str
) -> str:

    value = value.lower()

    value = re.sub(
        r"[^a-z0-9]+",
        "-",
        value
    )

    return value.strip("-")


# ------------------------------------------------------------
# Integer extractor
# ------------------------------------------------------------

def extract_int(
    value: str | None
) -> Optional[int]:

    if not value:
        return None

    match = re.search(
        r"\b(\d{1,4})\b",
        value
    )

    if not match:
        return None

    try:

        return int(
            match.group(1)
        )

    except ValueError:

        return None


# ------------------------------------------------------------
# Multiple integer extractor
# ------------------------------------------------------------

def extract_ints(
    value: str | None
) -> list[int]:

    if not value:
        return []

    return [
        int(x)
        for x in re.findall(
            r"\b\d{1,4}\b",
            value
        )
    ]


# ------------------------------------------------------------
# Unique preserving order
# ------------------------------------------------------------

def unique(
    items: list[str]
) -> list[str]:

    result = []

    seen = set()

    for item in items:

        item = clean_text(
            item
        )

        if not item:
            continue

        key = item.lower()

        if key in seen:
            continue

        seen.add(key)

        result.append(
            item
        )

    return result


# ------------------------------------------------------------
# Cache filename
# ------------------------------------------------------------

def cache_file(
    url: str
) -> Path:

    key = normalize_slug(
        url
    )

    if not key:
        key = "home"

    return CACHE_DIR / (
        f"{key[:180]}.json"
    )


# ------------------------------------------------------------
# Cache read
# ------------------------------------------------------------

def read_cache(
    url: str
) -> Optional[dict]:

    path = cache_file(
        url
    )

    if not path.exists():
        return None

    try:

        data = json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )

        timestamp = data.get(
            "timestamp",
            0
        )

        if (
            time.time() - timestamp
            > data.get(
                "ttl",
                ONGOING_CACHE_TTL
            )
        ):

            return None

        return data

    except Exception:

        return None


# ------------------------------------------------------------
# Cache write
# ------------------------------------------------------------

def write_cache(
    url: str,
    html: str,
    ttl: int,
) -> None:

    path = cache_file(
        url
    )

    payload = {
        "timestamp": time.time(),
        "ttl": ttl,
        "html": html,
    }

    try:

        path.write_text(
            json.dumps(
                payload,
                ensure_ascii=False
            ),
            encoding="utf-8"
        )

    except Exception as exc:

        logger.warning(
            "Cache write failed: %s",
            exc
        )


# ------------------------------------------------------------
# Cached fetch
# ------------------------------------------------------------

async def fetch_cached(
    session: aiohttp.ClientSession,
    url: str,
    ttl: int = ONGOING_CACHE_TTL,
) -> str:

    cached = read_cache(
        url
    )

    if cached:

        logger.info(
            "CACHE HIT: %s",
            url
        )

        return cached["html"]

    html = await fetch(
        session,
        url
    )

    write_cache(
        url,
        html,
        ttl
    )

    return html


# ============================================================
# PART 3/7 — SEARCH + TITLE RESOLVER
# ============================================================


def parse_search_results(
    html: str,
    query: str,
) -> list[SearchCandidate]:

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    candidates = []

    selectors = [
        "article a",
        ".post a",
        ".item a",
        ".anime a",
        "h2 a",
        "h3 a",
    ]

    seen = set()

    for selector in selectors:

        for tag in soup.select(
            selector
        ):

            href = tag.get(
                "href"
            )

            title = clean_text(
                tag.get_text(
                    " ",
                    strip=True
                )
            )

            if not href or not title:
                continue

            href = urljoin(
                BASE_URL,
                href
            )

            if href in seen:
                continue

            seen.add(
                href
            )

            score = title_match_score(
                query,
                title
            )

            candidates.append(
                SearchCandidate(
                    title=title,
                    url=href,
                    score=score,
                )
            )

    return candidates


# ------------------------------------------------------------
# Search anime
# ------------------------------------------------------------

async def search_anime(
    session: aiohttp.ClientSession,
    query: str,
) -> list[SearchCandidate]:

    query = clean_text(
        query
    )

    if not query:
        return []

    encoded = quote_plus(
        query
    )

    original_url = SEARCH_URL.format(
        query=encoded
    )

    candidates = []

    original_html = await fetch_cached(
        session,
        original_url,
        ttl=ONGOING_CACHE_TTL
    )

    original_candidates = parse_search_results(
        original_html,
        query
    )

    candidates.extend(
        original_candidates
    )

    # Remove duplicate URLs

    unique = {}

    for candidate in candidates:

        unique[candidate.url] = candidate

    candidates = list(
        unique.values()
    )

    candidates.sort(
        key=lambda x: x.score,
        reverse=True
    )

    logger.info(
        "Search results for %r: %d",
        query,
        len(candidates)
    )

    return candidates


# ------------------------------------------------------------
# Find best anime page
# ------------------------------------------------------------

async def find_anime_page(
    session: aiohttp.ClientSession,
    query: str,
) -> Optional[SearchCandidate]:

    candidates = await search_anime(
        session,
        query
    )

    if not candidates:

        logger.warning(
            "No search results found for %r",
            query
        )

        return None

    # Prefer strong exact / near-exact matches.

    for candidate in candidates:

        score = candidate.score

        if score >= 90:

            logger.info(
                "Strong match: %s (%s)",
                candidate.title,
                candidate.url
            )

            return candidate

    # Otherwise use best result.

    best = candidates[0]

    logger.info(
        "Best match: %s (score %.1f)",
        best.title,
        best.score
    )

    return best


# ============================================================
# FRANCHISE SEARCH HELPERS
# ============================================================


async def scrape_franchise_series(
    scraper: "AnimeScraper",
    franchise_key: str,
) -> list["AnimeInfo"]:

    """
    Search every known separately-named series belonging to a
    franchise.

    IMPORTANT:
    We intentionally scrape each title separately instead of
    treating them as seasons of one AnimeInfo object.

    Example:
        Dragon Ball
        Dragon Ball Z
        Dragon Ball GT
        Dragon Ball Super
        Dragon Ball DAIMA

    Each remains a separate series in the final output.
    """

    titles = FRANCHISE_SERIES.get(
        franchise_key,
        []
    )

    results: list[AnimeInfo] = []

    for title in titles:

        try:

            info = await scraper.scrape_single(
                title
            )

            if not info:
                continue

            # Only show entries where Hindi is actually available.

            if not info.hindi_available:

                logger.info(
                    "Skipping non-Hindi franchise series: %s",
                    title
                )

                continue

            results.append(
                info
            )

        except Exception as exc:

            logger.warning(
                "Franchise series failed: %s -> %s",
                title,
                exc
            )

    return results


async def scrape_franchise_movies(
    scraper: "AnimeScraper",
    franchise_key: str,
) -> list[str]:

    """
    Search known franchise movie titles and keep only movies
    for which the source page indicates Hindi availability.
    """

    titles = FRANCHISE_MOVIES.get(
        franchise_key,
        []
    )

    movies: list[str] = []

    for title in titles:

        try:

            info = await scraper.scrape_single(
                title
            )

            if not info:
                continue

            if not info.hindi_available:
                continue

            # Prefer the actual page title if available.

            movie_title = (
                info.title.strip()
                if info.title
                else title
            )

            if movie_title not in movies:

                movies.append(
                    movie_title
                )

        except Exception as exc:

            logger.warning(
                "Franchise movie failed: %s -> %s",
                title,
                exc
            )

    return movies


# ------------------------------------------------------------
# Build franchise wrapper
# ------------------------------------------------------------

def build_franchise_info(
    query: str,
    franchise_key: str,
    series: list[AnimeInfo],
    movies: list[str],
) -> AnimeInfo:

    franchise_name = query.strip()

    total_episodes = 0
    hindi_total = 0

    for anime in series:

        total_episodes += (
            anime.total_episodes or 0
        )

        if anime.available_episodes:

            hindi_total += (
                anime.available_episodes.get(
                    "Hindi",
                    0
                )
            )

    if series:

        base = series[0]

        base.title = franchise_name
        base.franchise_key = franchise_key
        base.franchise_series = series
        base.franchise_movies = movies

        base.total_episodes = total_episodes

        base.available_episodes = {
            "Hindi": hindi_total
        }

        return base

    return AnimeInfo(
        title=franchise_name,
        franchise_key=franchise_key,
        franchise_series=[],
        franchise_movies=movies,
        hindi_available=bool(movies),
        total_episodes=total_episodes,
        available_episodes={
            "Hindi": hindi_total
        },
    )

# ============================================================
# PART 2/7
# HTTP / CACHE / TEXT UTILITIES
# ============================================================


# ------------------------------------------------------------
# HTTP session
# ------------------------------------------------------------

async def create_session() -> aiohttp.ClientSession:

    timeout = aiohttp.ClientTimeout(
        total=REQUEST_TIMEOUT
    )

    connector = aiohttp.TCPConnector(
        limit=10,
        limit_per_host=5,
        ssl=False,
    )

    return aiohttp.ClientSession(
        headers=HEADERS,
        timeout=timeout,
        connector=connector
    )


# ------------------------------------------------------------
# Fetch URL
# ------------------------------------------------------------

async def fetch(
    session: aiohttp.ClientSession,
    url: str,
) -> str:

    logger.info(
        "Fetching: %s",
        url
    )

    try:

        async with session.get(
            url,
            allow_redirects=True
        ) as response:

            if response.status != 200:

                raise ScraperError(
                    f"HTTP {response.status}: {url}"
                )

            return await response.text(
                errors="ignore"
            )

    except asyncio.TimeoutError:

        raise ScraperError(
            f"Timeout: {url}"
        )

    except aiohttp.ClientError as exc:

        raise ScraperError(
            f"Request failed: {url} -> {exc}"
        )


# ------------------------------------------------------------
# Normalize text
# ------------------------------------------------------------

def clean_text(
    value: str | None
) -> str:

    if not value:
        return ""

    value = value.replace(
        "\xa0",
        " "
    )

    value = value.replace(
        "\r",
        " "
    )

    value = value.replace(
        "\n",
        " "
    )

    value = re.sub(
        r"\s+",
        " ",
        value
    )

    return value.strip()


# ------------------------------------------------------------
# Normalize title for matching
# ------------------------------------------------------------

def normalize_title(
    title: str
) -> str:

    title = title.lower()

    replacements = [
        "–",
        "—",
        "-",
        "_",
        ":",
        ",",
        ".",
        "'",
        '"',
        "!",
        "?",
        "(",
        ")",
        "[",
        "]",
        "{",
        "}",
        "+",
        "/",
    ]

    for char in replacements:

        title = title.replace(
            char,
            " "
        )

    # Common site noise

    noise = [
        "season",
        "hindi",
        "dubbed",
        "dub",
        "episodes",
        "episode",
        "download",
        "hd",
        "watch",
        "online",
        "full",
        "complete",
    ]

    words = title.split()

    words = [
        word
        for word in words
        if word not in noise
    ]

    return " ".join(
        words
    ).strip()


# ------------------------------------------------------------
# Title match score
# ------------------------------------------------------------

def title_match_score(
    query: str,
    title: str
) -> float:

    q = normalize_title(
        query
    )

    t = normalize_title(
        title
    )

    if not q or not t:
        return 0.0

    if q == t:
        return 100.0

    if q in t:
        return 90.0

    if t in q:
        return 80.0

    q_words = set(
        q.split()
    )

    t_words = set(
        t.split()
    )

    if not q_words or not t_words:
        return 0.0

    overlap = len(
        q_words & t_words
    )

    return (
        overlap / len(q_words)
    ) * 70.0


# ------------------------------------------------------------
# Slug normalize
# ------------------------------------------------------------

def normalize_slug(
    value: str
) -> str:

    value = value.lower()

    value = re.sub(
        r"[^a-z0-9]+",
        "-",
        value
    )

    return value.strip("-")


# ------------------------------------------------------------
# Integer extractor
# ------------------------------------------------------------

def extract_int(
    value: str | None
) -> Optional[int]:

    if not value:
        return None

    match = re.search(
        r"\b(\d{1,4})\b",
        value
    )

    if not match:
        return None

    try:

        return int(
            match.group(1)
        )

    except ValueError:

        return None


# ------------------------------------------------------------
# Multiple integer extractor
# ------------------------------------------------------------

def extract_ints(
    value: str | None
) -> list[int]:

    if not value:
        return []

    return [
        int(x)
        for x in re.findall(
            r"\b\d{1,4}\b",
            value
        )
    ]


# ------------------------------------------------------------
# Unique preserving order
# ------------------------------------------------------------

def unique(
    items: list[str]
) -> list[str]:

    result = []

    seen = set()

    for item in items:

        item = clean_text(
            item
        )

        if not item:
            continue

        key = item.lower()

        if key in seen:
            continue

        seen.add(
            key
        )

        result.append(
            item
        )

    return result


# ------------------------------------------------------------
# Cache filename
# ------------------------------------------------------------

def cache_file(
    url: str
) -> Path:

    key = normalize_slug(
        url
    )

    if not key:
        key = "home"

    return CACHE_DIR / (
        f"{key[:180]}.json"
    )


# ------------------------------------------------------------
# Cache read
# ------------------------------------------------------------

def read_cache(
    url: str
) -> Optional[dict]:

    path = cache_file(
        url
    )

    if not path.exists():
        return None

    try:

        data = json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )

        timestamp = data.get(
            "timestamp",
            0
        )

        if (
            time.time() - timestamp
            > data.get(
                "ttl",
                ONGOING_CACHE_TTL
            )
        ):

            return None

        return data

    except Exception:

        return None


# ------------------------------------------------------------
# Cache write
# ------------------------------------------------------------

def write_cache(
    url: str,
    html: str,
    ttl: int,
) -> None:

    path = cache_file(
        url
    )

    payload = {
        "timestamp": time.time(),
        "ttl": ttl,
        "html": html,
    }

    try:

        path.write_text(
            json.dumps(
                payload,
                ensure_ascii=False
            ),
            encoding="utf-8"
        )

    except Exception as exc:

        logger.warning(
            "Cache write failed: %s",
            exc
        )


# ------------------------------------------------------------
# Cached fetch
# ------------------------------------------------------------

async def fetch_cached(
    session: aiohttp.ClientSession,
    url: str,
    ttl: int = ONGOING_CACHE_TTL,
) -> str:

    cached = read_cache(
        url
    )

    if cached:

        logger.info(
            "CACHE HIT: %s",
            url
        )

        return cached["html"]

    html = await fetch(
        session,
        url
    )

    write_cache(
        url,
        html,
        ttl
    )

    return html

# ============================================================
# PART 3/7
# SEARCH + TITLE RESOLVER + FRANCHISE SUPPORT
# ============================================================


# ------------------------------------------------------------
# Parse search results
# ------------------------------------------------------------

def parse_search_results(
    html: str,
    query: str,
) -> list[SearchCandidate]:

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    candidates = []

    selectors = [
        "article a",
        ".post a",
        ".item a",
        ".anime a",
        "h2 a",
        "h3 a",
    ]

    seen = set()

    for selector in selectors:

        for tag in soup.select(
            selector
        ):

            href = tag.get(
                "href"
            )

            title = clean_text(
                tag.get_text(
                    " ",
                    strip=True
                )
            )

            if not href or not title:
                continue

            href = urljoin(
                BASE_URL,
                href
            )

            if href in seen:
                continue

            seen.add(
                href
            )

            score = title_match_score(
                query,
                title
            )

            candidates.append(
                SearchCandidate(
                    title=title,
                    url=href,
                    score=score,
                )
            )

    return candidates


# ------------------------------------------------------------
# Search anime
# ------------------------------------------------------------

async def search_anime(
    session: aiohttp.ClientSession,
    query: str,
) -> list[SearchCandidate]:

    query = clean_text(
        query
    )

    if not query:
        return []

    encoded = quote_plus(
        query
    )

    original_url = SEARCH_URL.format(
        query=encoded
    )

    candidates = []

    original_html = await fetch_cached(
        session,
        original_url,
        ttl=ONGOING_CACHE_TTL
    )

    original_candidates = parse_search_results(
        original_html,
        query
    )

    candidates.extend(
        original_candidates
    )

    # --------------------------------------------------------
    # Remove duplicate URLs
    # --------------------------------------------------------

    unique_candidates = {}

    for candidate in candidates:

        unique_candidates[
            candidate.url
        ] = candidate

    candidates = list(
        unique_candidates.values()
    )

    candidates.sort(
        key=lambda x: x.score,
        reverse=True
    )

    logger.info(
        "Search results for %r: %d",
        query,
        len(candidates)
    )

    return candidates


# ------------------------------------------------------------
# Find best anime page
# ------------------------------------------------------------

async def find_anime_page(
    session: aiohttp.ClientSession,
    query: str,
) -> Optional[SearchCandidate]:

    candidates = await search_anime(
        session,
        query
    )

    if not candidates:

        logger.warning(
            "No search results found for %r",
            query
        )

        return None

    # --------------------------------------------------------
    # Prefer strong exact / near-exact matches.
    # --------------------------------------------------------

    for candidate in candidates:

        score = candidate.score

        if score >= 90:

            logger.info(
                "Strong match: %s (%s)",
                candidate.title,
                candidate.url
            )

            return candidate

    # --------------------------------------------------------
    # Otherwise use best result.
    # --------------------------------------------------------

    best = candidates[0]

    logger.info(
        "Best match: %s (score %.1f)",
        best.title,
        best.score
    )

    return best


# ============================================================
# FRANCHISE SEARCH HELPERS
# ============================================================


async def scrape_franchise_series(
    scraper: "AnimeScraper",
    franchise_key: str,
) -> list["AnimeInfo"]:

    """
    Search every known separately-named series belonging to a
    franchise.

    IMPORTANT:
    Each separately named series remains a separate entry.

    Example:

        Dragon Ball
        Dragon Ball Z
        Dragon Ball GT
        Dragon Ball Super
        Dragon Ball DAIMA

    They are NOT treated as seasons of one AnimeInfo.
    """

    titles = FRANCHISE_SERIES.get(
        franchise_key,
        []
    )

    results: list[AnimeInfo] = []

    for title in titles:

        try:

            info = await scraper.scrape_single(
                title
            )

            if not info:
                continue

            # ------------------------------------------------
            # Only show entries where Hindi is available.
            # ------------------------------------------------

            if not info.hindi_available:

                logger.info(
                    "Skipping non-Hindi franchise series: %s",
                    title
                )

                continue

            results.append(
                info
            )

        except Exception as exc:

            logger.warning(
                "Franchise series failed: %s -> %s",
                title,
                exc
            )

    return results


# ------------------------------------------------------------
# Franchise movies
# ------------------------------------------------------------

async def scrape_franchise_movies(
    scraper: "AnimeScraper",
    franchise_key: str,
) -> list[str]:

    """
    Search known franchise movie titles and keep only movies
    for which the source page indicates Hindi availability.
    """

    titles = FRANCHISE_MOVIES.get(
        franchise_key,
        []
    )

    movies: list[str] = []

    for title in titles:

        try:

            info = await scraper.scrape_single(
                title
            )

            if not info:
                continue

            if not info.hindi_available:
                continue

            # ------------------------------------------------
            # Prefer actual page title if available.
            # ------------------------------------------------

            movie_title = (
                info.title.strip()
                if info.title
                else title
            )

            if movie_title not in movies:

                movies.append(
                    movie_title
                )

        except Exception as exc:

            logger.warning(
                "Franchise movie failed: %s -> %s",
                title,
                exc
            )

    return movies


# ------------------------------------------------------------
# Build franchise wrapper
# ------------------------------------------------------------

def build_franchise_info(
    query: str,
    franchise_key: str,
    series: list["AnimeInfo"],
    movies: list[str],
) -> "AnimeInfo":

    """
    Keep the original scraper API compatible by returning one
    AnimeInfo object.

    The object contains separate series and movie information.
    """

    franchise_name = query.strip()

    total_episodes = 0

    available_episodes = 0

    for anime in series:

        total_episodes += (
            anime.total_episodes or 0
        )

        available_episodes += (
            anime.available_episodes or 0
        )

    # --------------------------------------------------------
    # Use first Hindi series as base object.
    # --------------------------------------------------------

    if series:

        base = series[0]

        base.title = franchise_name

        base.franchise_key = franchise_key

        base.franchise_series = series

        base.franchise_movies = movies

        base.total_episodes = total_episodes

        base.available_episodes = available_episodes

        return base

    # --------------------------------------------------------
    # If no Hindi series was found, still return valid object.
    # --------------------------------------------------------

    return AnimeInfo(
        title=franchise_name,
        franchise_key=franchise_key,
        franchise_series=[],
        franchise_movies=movies,
        hindi_available=bool(movies),
        total_episodes=total_episodes,
        available_episodes=available_episodes,
    )


# ============================================================
# FRANCHISE DEFINITIONS
# ============================================================

FRANCHISE_SERIES = {

    "dragon ball": [
        "Dragon Ball",
        "Dragon Ball Z",
        "Dragon Ball GT",
        "Dragon Ball Super",
        "Dragon Ball DAIMA",
    ],

    "naruto": [
        "Naruto",
        "Naruto Shippuden",
    ],

    "one piece": [
        "One Piece",
    ],

    "bleach": [
        "Bleach",
        "Bleach Thousand-Year Blood War",
    ],

    "pokemon": [
        "Pokémon",
        "Pokémon Indigo League",
        "Pokémon Advanced",
        "Pokémon Diamond and Pearl",
        "Pokémon Black and White",
        "Pokémon XY",
        "Pokémon Sun and Moon",
        "Pokémon Journeys",
        "Pokémon Horizons",
    ],

    "digimon": [
        "Digimon Adventure",
        "Digimon Adventure 02",
        "Digimon Tamers",
        "Digimon Frontier",
        "Digimon Data Squad",
        "Digimon Fusion",
        "Digimon Adventure tri.",
        "Digimon Ghost Game",
    ],

    "yu gi oh": [
        "Yu-Gi-Oh!",
        "Yu-Gi-Oh! GX",
        "Yu-Gi-Oh! 5D's",
        "Yu-Gi-Oh! ZEXAL",
        "Yu-Gi-Oh! ARC-V",
        "Yu-Gi-Oh! VRAINS",
    ],
}


FRANCHISE_MOVIES = {

    "dragon ball": [
        "Dragon Ball Z: Dead Zone",
        "Dragon Ball Z: The World's Strongest",
        "Dragon Ball Z: The Tree of Might",
        "Dragon Ball Z: Lord Slug",
        "Dragon Ball Z: Cooler's Revenge",
        "Dragon Ball Z: Return of Cooler",
        "Dragon Ball Z: Super Android 13",
        "Dragon Ball Z: Broly",
        "Dragon Ball Z: Bojack Unbound",
        "Dragon Ball Z: Broly Second Coming",
        "Dragon Ball Z: Bio-Broly",
        "Dragon Ball Z: Fusion Reborn",
        "Dragon Ball Z: Wrath of the Dragon",
        "Dragon Ball Super: Broly",
        "Dragon Ball Super: Super Hero",
    ],

    "naruto": [
        "Naruto the Movie: Ninja Clash in the Land of Snow",
        "Naruto the Movie: Legend of the Stone of Gelel",
        "Naruto the Movie: Guardians of the Crescent Moon Kingdom",
        "Naruto Shippuden the Movie",
        "Naruto Shippuden the Movie: Bonds",
        "Naruto Shippuden the Movie: The Will of Fire",
        "Naruto Shippuden the Movie: The Lost Tower",
        "Naruto Shippuden the Movie: Blood Prison",
        "Road to Ninja: Naruto the Movie",
        "The Last: Naruto the Movie",
        "Boruto: Naruto the Movie",
    ],

    "bleach": [
        "Bleach the Movie: Memories of Nobody",
        "Bleach the Movie: The DiamondDust Rebellion",
        "Bleach the Movie: Fade to Black",
        "Bleach the Movie: Hell Verse",
    ],
}

# ============================================================
# PART 4/7
# ANIME SCRAPER CLASS
# ============================================================


class AnimeScraper:

    def __init__(
        self,
        session: Optional[aiohttp.ClientSession] = None,
    ):

        self.session = session

        self._own_session = (
            session is None
        )


    async def __aenter__(self):

        if self.session is None:

            self.session = aiohttp.ClientSession(
                headers=DEFAULT_HEADERS,
                timeout=REQUEST_TIMEOUT,
            )

        return self


    async def __aexit__(
        self,
        exc_type,
        exc,
        tb,
    ):

        if (
            self._own_session
            and self.session
        ):

            await self.session.close()


    async def ensure_session(self):

        if self.session is None:

            self.session = aiohttp.ClientSession(
                headers=DEFAULT_HEADERS,
                timeout=REQUEST_TIMEOUT,
            )


    # --------------------------------------------------------
    # Scrape one anime
    # --------------------------------------------------------

    async def scrape_single(
        self,
        query: str,
    ) -> Optional[AnimeInfo]:

        await self.ensure_session()

        logger.info(
            "Scraping anime: %s",
            query
        )

        candidate = await find_anime_page(
            self.session,
            query
        )

        if not candidate:

            return None

        try:

            html = await fetch_cached(
                self.session,
                candidate.url,
                ttl=ONGOING_CACHE_TTL
            )

        except Exception as exc:

            logger.error(
                "Failed to fetch anime page: %s",
                exc
            )

            return None

        try:

            anime = parse_anime_page(
                html,
                candidate.url,
                candidate.title,
            )

        except Exception as exc:

            logger.exception(
                "Anime page parsing failed: %s",
                exc
            )

            return None

        if anime is None:

            return None

        return anime


    # --------------------------------------------------------
    # Scrape franchise
    # --------------------------------------------------------

    async def scrape_franchise(
        self,
        query: str,
        franchise_key: str,
    ) -> Optional[AnimeInfo]:

        await self.ensure_session()

        logger.info(
            "Scraping franchise: %s",
            franchise_key
        )

        series = await scrape_franchise_series(
            self,
            franchise_key
        )

        movies = await scrape_franchise_movies(
            self,
            franchise_key
        )

        if not series and not movies:

            logger.warning(
                "No Hindi franchise data found: %s",
                franchise_key
            )

            return None

        return build_franchise_info(
            query=query,
            franchise_key=franchise_key,
            series=series,
            movies=movies,
        )


    # --------------------------------------------------------
    # Main search method
    # --------------------------------------------------------

    async def search(
        self,
        query: str,
    ) -> Optional[AnimeInfo]:

        query = clean_text(
            query
        )

        if not query:

            return None

        normalized = normalize_title(
            query
        )

        # ----------------------------------------------------
        # Check whether this is a known franchise.
        # ----------------------------------------------------

        franchise_key = None

        for key in FRANCHISE_SERIES:

            normalized_key = normalize_title(
                key
            )

            if (
                normalized == normalized_key
                or normalized_key in normalized
                or normalized in normalized_key
            ):

                franchise_key = key
                break

        # ----------------------------------------------------
        # Franchise search
        # ----------------------------------------------------

        if franchise_key:

            logger.info(
                "Known franchise detected: %s",
                franchise_key
            )

            try:

                franchise = await self.scrape_franchise(
                    query,
                    franchise_key
                )

                if franchise:

                    return franchise

            except Exception as exc:

                logger.exception(
                    "Franchise scrape failed: %s",
                    exc
                )

        # ----------------------------------------------------
        # Normal single-anime search
        # ----------------------------------------------------

        return await self.scrape_single(
            query
        )


# ============================================================
# PAGE PARSING
# ============================================================


def parse_anime_page(
    html: str,
    url: str,
    fallback_title: str = "",
) -> Optional[AnimeInfo]:

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    # --------------------------------------------------------
    # Title
    # --------------------------------------------------------

    title = ""

    title_selectors = [
        "h1",
        ".entry-title",
        ".anime-title",
        ".post-title",
        "meta[property='og:title']",
    ]

    for selector in title_selectors:

        node = soup.select_one(
            selector
        )

        if not node:
            continue

        if node.name == "meta":

            value = node.get(
                "content",
                ""
            )

        else:

            value = node.get_text(
                " ",
                strip=True
            )

        value = clean_text(
            value
        )

        if value:

            title = value
            break

    if not title:

        title = fallback_title


    # --------------------------------------------------------
    # Poster
    # --------------------------------------------------------

    poster_url = None

    poster_selectors = [
        "meta[property='og:image']",
        ".poster img",
        ".anime-poster img",
        ".post-thumbnail img",
        ".thumbnail img",
        "img",
    ]

    for selector in poster_selectors:

        node = soup.select_one(
            selector
        )

        if not node:
            continue

        if node.name == "meta":

            image = node.get(
                "content",
                ""
            )

        else:

            image = (
                node.get("src")
                or node.get("data-src")
                or node.get("data-lazy-src")
                or ""
            )

        if not image:

            continue

        poster_url = urljoin(
            url,
            image
        )

        break


    # --------------------------------------------------------
    # Page text
    # --------------------------------------------------------

    text = soup.get_text(
        "\n",
        strip=True
    )

    text = clean_text(
        text
    )


    # --------------------------------------------------------
    # Total episodes
    # --------------------------------------------------------

    total_episodes = extract_total_episodes(
        text
    )


    # --------------------------------------------------------
    # Hindi availability
    # --------------------------------------------------------

    hindi_available = detect_hindi(
        text
    )


    # --------------------------------------------------------
    # Season information
    # --------------------------------------------------------

    seasons = extract_seasons(
        text
    )


    # --------------------------------------------------------
    # Episode information
    # --------------------------------------------------------

    episodes = extract_episode_data(
        soup
    )


    # --------------------------------------------------------
    # Hindi episode count
    # --------------------------------------------------------

    hindi_count = 0

    for episode in episodes:

        if "Hindi" in episode.languages:

            hindi_count += 1


    available_episodes = {

        "Hindi": hindi_count

    }


    # --------------------------------------------------------
    # Movies
    # --------------------------------------------------------

    movies = extract_movies(
        soup,
        text
    )


    # --------------------------------------------------------
    # Build AnimeInfo
    # --------------------------------------------------------

    try:

        anime = AnimeInfo(
            title=title,
            url=url,
            poster_url=poster_url,
            total_episodes=total_episodes,
            available_episodes=available_episodes,
            hindi_available=hindi_available,
            seasons=seasons,
            episodes=episodes,
            movies=movies,
        )

    except TypeError:

        # ----------------------------------------------------
        # Compatibility fallback for older AnimeInfo model.
        # ----------------------------------------------------

        anime = AnimeInfo(
            title=title,
            url=url,
            poster_url=poster_url,
            total_episodes=total_episodes,
            available_episodes=available_episodes,
            hindi_available=hindi_available,
        )

        anime.seasons = seasons
        anime.episodes = episodes
        anime.movies = movies


    return anime


# ============================================================
# TOTAL EPISODE EXTRACTION
# ============================================================


def extract_total_episodes(
    text: str,
) -> int:

    patterns = [

        r"total\s*episodes?\s*[:\-]?\s*(\d+)",

        r"episodes?\s*[:\-]?\s*(\d+)",

        r"episode\s*count\s*[:\-]?\s*(\d+)",

        r"(\d+)\s*episodes?",

    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            text,
            re.IGNORECASE
        )

        if not match:
            continue

        try:

            value = int(
                match.group(1)
            )

            if value > 0:

                return value

        except (
            TypeError,
            ValueError,
        ):

            continue

    return 0


# ============================================================
# HINDI DETECTION
# ============================================================


def detect_hindi(
    text: str,
) -> bool:

    if not text:

        return False

    hindi_patterns = [

        r"\bhindi\b",

        r"\bhindi dubbed\b",

        r"\bhindi dub\b",

        r"\bdubbed in hindi\b",

        r"\blanguage\s*[:\-]?\s*hindi\b",

    ]

    for pattern in hindi_patterns:

        if re.search(
            pattern,
            text,
            re.IGNORECASE
        ):

            return True

    return False


# ============================================================
# SEASON EXTRACTION
# ============================================================


def extract_seasons(
    text: str,
) -> list[str]:

    seasons = []

    patterns = [

        r"\bseason\s+\d+\b",

        r"\bs\d+\b",

        r"\bpart\s+\d+\b",

    ]

    for pattern in patterns:

        matches = re.findall(
            pattern,
            text,
            re.IGNORECASE
        )

        for value in matches:

            value = clean_text(
                value
            )

            if value and value not in seasons:

                seasons.append(
                    value
                )

    return seasons


# ============================================================
# EPISODE DATA EXTRACTION
# ============================================================


def extract_episode_data(
    soup: BeautifulSoup,
) -> list[EpisodeInfo]:

    episodes = []

    # --------------------------------------------------------
    # Look for episode links/items.
    # --------------------------------------------------------

    selectors = [

        ".episode",

        ".episodes a",

        ".episode-list a",

        ".ep-list a",

        ".episodelist a",

        "a[href*='episode']",

    ]

    seen = set()

    for selector in selectors:

        for node in soup.select(
            selector
        ):

            href = node.get(
                "href"
            )

            title = clean_text(
                node.get_text(
                    " ",
                    strip=True
                )
            )

            if not title and not href:

                continue

            key = (
                href,
                title,
            )

            if key in seen:

                continue

            seen.add(
                key
            )

            number = extract_episode_number(
                title
            )

            if number <= 0:

                number = (
                    len(episodes)
                    + 1
                )

            languages = detect_episode_languages(
                title
            )

            episodes.append(
                EpisodeInfo(
                    number=number,
                    title=title,
                    url=href,
                    languages=languages,
                )
            )

    episodes.sort(
        key=lambda episode:
        episode.number
    )

    return episodes


# ============================================================
# EPISODE NUMBER
# ============================================================


def extract_episode_number(
    text: str,
) -> int:

    patterns = [

        r"\bepisode\s*(\d+)\b",

        r"\bep\.?\s*(\d+)\b",

        r"\bep\s*[-:]?\s*(\d+)\b",

        r"\bE(\d+)\b",

    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            text,
            re.IGNORECASE
        )

        if match:

            try:

                return int(
                    match.group(1)
                )

            except (
                TypeError,
                ValueError,
            ):

                pass

    return 0


# ============================================================
# EPISODE LANGUAGE DETECTION
# ============================================================


def detect_episode_languages(
    text: str,
) -> list[str]:

    languages = []

    if re.search(
        r"\bhindi\b",
        text,
        re.IGNORECASE
    ):

        languages.append(
            "Hindi"
        )

    if re.search(
        r"\benglish\b",
        text,
        re.IGNORECASE
    ):

        languages.append(
            "English"
        )

    if re.search(
        r"\bjapanese\b",
        text,
        re.IGNORECASE
    ):

        languages.append(
            "Japanese"
        )

    return languages


# ============================================================
# MOVIE EXTRACTION
# ============================================================


def extract_movies(
    soup: BeautifulSoup,
    text: str,
) -> list[str]:

    movies = []

    selectors = [

        ".movie a",

        ".movies a",

        ".movie-list a",

        "a[href*='movie']",

    ]

    seen = set()

    for selector in selectors:

        for node in soup.select(
            selector
        ):

            title = clean_text(
                node.get_text(
                    " ",
                    strip=True
                )
            )

            if not title:

                continue

            if title.lower() in seen:

                continue

            seen.add(
                title.lower()
            )

            movies.append(
                title
            )

    return movies

# ============================================================
# PART 5/7
# FORMATTERS
# ============================================================


def format_episode(
    episode: EpisodeInfo,
) -> str:

    number = episode.number

    title = (
        episode.title.strip()
        if episode.title
        else ""
    )

    if title:

        return (
            f"Episode {number} — "
            f"{title}"
        )

    return (
        f"Episode {number}"
    )


# ============================================================
# SINGLE ANIME FORMATTER
# ============================================================


def format_single_anime_info(
    anime: AnimeInfo,
) -> str:

    lines = []

    title = (
        anime.title.strip()
        if anime.title
        else "Unknown Anime"
    )

    lines.append(
        f"🎌 {title}"
    )

    # --------------------------------------------------------
    # URL
    # --------------------------------------------------------

    if getattr(
        anime,
        "url",
        None
    ):

        lines.append(
            f"🔗 {anime.url}"
        )


    # --------------------------------------------------------
    # Seasons
    # --------------------------------------------------------

    seasons = getattr(
        anime,
        "seasons",
        None
    )

    if seasons:

        lines.append("")

        lines.append(
            "📂 Seasons:"
        )

        for season in seasons:

            lines.append(
                f"   • {season}"
            )


    # --------------------------------------------------------
    # Total episodes
    # --------------------------------------------------------

    total = getattr(
        anime,
        "total_episodes",
        0
    )

    if total:

        lines.append("")

        lines.append(
            f"🎞 Total Episodes: {total}"
        )


    # --------------------------------------------------------
    # Hindi episode count
    #
    # IMPORTANT:
    # Individual episode names/numbers are NOT displayed.
    # --------------------------------------------------------

    hindi_count = (
        anime.available_episodes.get(
            "Hindi",
            0
        )
        if anime.available_episodes
        else 0
    )

    if hindi_count:

        lines.append("")

        lines.append(
            f"📚 Hindi Episodes: {hindi_count}"
        )


    # --------------------------------------------------------
    # Hindi availability
    # --------------------------------------------------------

    if anime.hindi_available:

        lines.append(
            "🇮🇳 Hindi Available: Yes"
        )

    else:

        lines.append(
            "🇮🇳 Hindi Available: No"
        )


    # --------------------------------------------------------
    # Movies
    # --------------------------------------------------------

    movies = getattr(
        anime,
        "movies",
        None
    )

    if movies:

        lines.append("")

        lines.append(
            "🎬 Movies:"
        )

        for movie in movies:

            if isinstance(
                movie,
                str
            ):

                movie_title = movie

            else:

                movie_title = getattr(
                    movie,
                    "title",
                    str(movie)
                )

            if movie_title:

                lines.append(
                    f"   • {movie_title}"
                )


    # --------------------------------------------------------
    # Poster
    #
    # Poster URL is NOT printed in the text.
    # Poster itself is sent separately by commands.py.
    # --------------------------------------------------------

    return "\n".join(
        lines
    )


# ============================================================
# FRANCHISE FORMATTER
# ============================================================


def format_franchise_info(
    anime: AnimeInfo,
) -> str:

    lines = []

    franchise_title = (
        anime.title.strip()
        if anime.title
        else "Anime Franchise"
    )

    lines.append(
        f"🎌 {franchise_title}"
    )

    series = getattr(
        anime,
        "franchise_series",
        []
    )

    # --------------------------------------------------------
    # Separate series
    # --------------------------------------------------------

    if series:

        lines.append("")

        lines.append(
            "📺 Hindi Available Series:"
        )

        for item in series:

            item_title = (
                getattr(
                    item,
                    "title",
                    ""
                )
                or "Unknown"
            )

            lines.append(
                f"\n🔹 {item_title}"
            )


            # ------------------------------------------------
            # Seasons
            # ------------------------------------------------

            item_seasons = getattr(
                item,
                "seasons",
                []
            )

            if item_seasons:

                lines.append(
                    "   📂 Seasons:"
                )

                for season in item_seasons:

                    lines.append(
                        f"      • {season}"
                    )


            # ------------------------------------------------
            # Total episodes
            # ------------------------------------------------

            item_total = getattr(
                item,
                "total_episodes",
                0
            )

            if item_total:

                lines.append(
                    f"   🎞 Total Episodes: "
                    f"{item_total}"
                )


            # ------------------------------------------------
            # Hindi episodes count ONLY
            # ------------------------------------------------

            item_hindi = (

                item.available_episodes.get(
                    "Hindi",
                    0
                )

                if item.available_episodes
                else 0

            )

            if item_hindi:

                lines.append(
                    f"   📚 Hindi Episodes: "
                    f"{item_hindi}"
                )


            # ------------------------------------------------
            # Hindi availability
            # ------------------------------------------------

            lines.append(
                "   🇮🇳 Hindi Available: Yes"
            )


    # ========================================================
    # MOVIES
    # ========================================================

    movies = getattr(
        anime,
        "franchise_movies",
        []
    )

    if movies:

        lines.append("")

        lines.append(
            "🎬 Movies:"
        )

        for movie in movies:

            if isinstance(
                movie,
                str
            ):

                movie_title = movie

            else:

                movie_title = getattr(
                    movie,
                    "title",
                    str(movie)
                )

            if movie_title:

                lines.append(
                    f"   • {movie_title}"
                )


    return "\n".join(
        lines
    )


# ============================================================
# MAIN FORMATTER
# ============================================================


def format_anime_info(
    anime: AnimeInfo,
) -> str:

    # --------------------------------------------------------
    # Franchise result
    # --------------------------------------------------------

    franchise_series = getattr(
        anime,
        "franchise_series",
        None
    )

    franchise_movies = getattr(
        anime,
        "franchise_movies",
        None
    )

    if (
        franchise_series
        or franchise_movies
    ):

        result = format_franchise_info(
            anime
        )

    else:

        result = format_single_anime_info(
            anime
        )


    # --------------------------------------------------------
    # Never return an empty Telegram message.
    # --------------------------------------------------------

    if not result.strip():

        title = (

            getattr(
                anime,
                "canonical_title",
                None
            )

            or getattr(
                anime,
                "title",
                None
            )

            or "Unknown Anime"

        )

        return (
            f"🎌 {title}\n\n"
            "❌ No anime information found."
        )


    return result


# ============================================================
# RESULT HELPERS
# ============================================================


def get_hindi_episode_count(
    anime: AnimeInfo,
) -> int:

    available = getattr(
        anime,
        "available_episodes",
        {}
    )

    if not available:

        return 0

    if isinstance(
        available,
        dict
    ):

        value = available.get(
            "Hindi",
            0
        )

        try:

            return int(
                value
            )

        except (
            TypeError,
            ValueError,
        ):

            return 0

    try:

        return int(
            available
        )

    except (
        TypeError,
        ValueError,
    ):

        return 0


# ============================================================
# POSTER HELPER
# ============================================================


def get_poster_url(
    anime: AnimeInfo,
) -> Optional[str]:

    poster = getattr(
        anime,
        "poster_url",
        None
    )

    if not poster:

        poster = getattr(
            anime,
            "poster",
            None
        )

    if not poster:

        return None

    poster = str(
        poster
    ).strip()

    if not poster:

        return None

    if not re.match(
        r"^https?://",
        poster,
        re.IGNORECASE
    ):

        return None

    return poster


# ============================================================
# SAFE TEXT
# ============================================================


def safe_format_text(
    anime: Optional[AnimeInfo],
) -> str:

    if anime is None:

        return (
            "❌ No anime information found."
        )

    try:

        return format_anime_info(
            anime
        )

    except Exception as exc:

        logger.exception(
            "Anime formatter failed: %s",
            exc
        )

        title = (
            getattr(
                anime,
                "title",
                None
            )
            or "Unknown Anime"
        )

        return (
            f"🎌 {title}\n\n"
            "❌ Unable to format anime information."
        )


# ============================================================
# PUBLIC SCRAPER FUNCTION
# ============================================================


async def get_anime_info(
    query: str,
) -> Optional[AnimeInfo]:

    query = clean_text(
        query
    )

    if not query:

        return None

    try:

        async with AnimeScraper() as scraper:

            return await scraper.search(
                query
            )

    except Exception as exc:

        logger.exception(
            "Anime search failed for %r: %s",
            query,
            exc
        )

        return None
# ============================================================
# PART 6/7
# CACHE + HTTP HELPERS + UTILITY FUNCTIONS
# ============================================================


async def fetch(
    session: aiohttp.ClientSession,
    url: str,
) -> str:

    if not url:

        return ""

    try:

        async with session.get(
            url,
            allow_redirects=True,
        ) as response:

            if response.status != 200:

                logger.warning(
                    "HTTP %s for %s",
                    response.status,
                    url
                )

                return ""

            return await response.text(
                errors="ignore"
            )

    except asyncio.TimeoutError:

        logger.warning(
            "Timeout while fetching: %s",
            url
        )

        return ""

    except aiohttp.ClientError as exc:

        logger.warning(
            "HTTP error for %s: %s",
            url,
            exc
        )

        return ""

    except Exception as exc:

        logger.exception(
            "Unexpected fetch error: %s",
            exc
        )

        return ""


# ============================================================
# CACHED FETCH
# ============================================================


async def fetch_cached(
    session: aiohttp.ClientSession,
    url: str,
    ttl: int = 3600,
) -> str:

    if not url:

        return ""

    now = time.time()

    cached = HTTP_CACHE.get(
        url
    )

    if cached:

        timestamp, content = cached

        if (
            now - timestamp
            < ttl
        ):

            return content

    content = await fetch(
        session,
        url
    )

    if content:

        HTTP_CACHE[url] = (
            now,
            content
        )

    return content


# ============================================================
# CACHE CLEANUP
# ============================================================


def cleanup_cache(
    max_age: int = 86400,
) -> None:

    now = time.time()

    expired = []

    for url, value in HTTP_CACHE.items():

        try:

            timestamp = value[0]

            if (
                now - timestamp
                > max_age
            ):

                expired.append(
                    url
                )

        except Exception:

            expired.append(
                url
            )

    for url in expired:

        HTTP_CACHE.pop(
            url,
            None
        )


# ============================================================
# TEXT CLEANING
# ============================================================


def clean_text(
    value: Any,
) -> str:

    if value is None:

        return ""

    text = str(
        value
    )

    text = html.unescape(
        text
    )

    text = re.sub(
        r"\s+",
        " ",
        text
    )

    return text.strip()


# ============================================================
# NORMALIZE TITLE
# ============================================================


def normalize_title(
    title: str,
) -> str:

    title = clean_text(
        title
    ).lower()

    # --------------------------------------------------------
    # Remove punctuation.
    # --------------------------------------------------------

    title = re.sub(
        r"[^\w\s]",
        " ",
        title,
        flags=re.UNICODE
    )

    title = re.sub(
        r"\s+",
        " ",
        title
    )

    return title.strip()


# ============================================================
# TITLE MATCH SCORE
# ============================================================


def title_match_score(
    query: str,
    title: str,
) -> float:

    q = normalize_title(
        query
    )

    t = normalize_title(
        title
    )

    if not q or not t:

        return 0.0

    if q == t:

        return 100.0

    if q in t:

        return 90.0

    if t in q:

        return 80.0

    q_words = set(
        q.split()
    )

    t_words = set(
        t.split()
    )

    if not q_words or not t_words:

        return 0.0

    overlap = len(
        q_words & t_words
    )

    return (
        overlap
        / len(q_words)
    ) * 70.0


# ============================================================
# URL JOIN
# ============================================================


def absolute_url(
    base_url: str,
    value: str,
) -> str:

    if not value:

        return ""

    return urljoin(
        base_url,
        value
    )


# ============================================================
# VALID URL
# ============================================================


def is_valid_url(
    value: str,
) -> bool:

    if not value:

        return False

    return bool(
        re.match(
            r"^https?://",
            value.strip(),
            re.IGNORECASE
        )
    )


# ============================================================
# LANGUAGE HELPERS
# ============================================================


def is_hindi_text(
    text: str,
) -> bool:

    if not text:

        return False

    return bool(
        re.search(
            r"\bhindi\b",
            text,
            re.IGNORECASE
        )
    )


def language_from_text(
    text: str,
) -> Optional[str]:

    if not text:

        return None

    languages = [

        "Hindi",
        "English",
        "Japanese",
        "Tamil",
        "Telugu",
        "Malayalam",
        "Bengali",
        "Kannada",
        "Marathi",
    ]

    lower = text.lower()

    for language in languages:

        if language.lower() in lower:

            return language

    return None


# ============================================================
# NUMBER HELPERS
# ============================================================


def safe_int(
    value: Any,
    default: int = 0,
) -> int:

    if value is None:

        return default

    try:

        return int(
            value
        )

    except (
        TypeError,
        ValueError,
    ):

        return default


# ============================================================
# UNIQUE LIST
# ============================================================


def unique_strings(
    values: Iterable[Any],
) -> list[str]:

    result = []

    seen = set()

    for value in values:

        text = clean_text(
            value
        )

        if not text:

            continue

        key = text.lower()

        if key in seen:

            continue

        seen.add(
            key
        )

        result.append(
            text
        )

    return result


# ============================================================
# HTML ATTRIBUTE HELPER
# ============================================================


def get_first_attribute(
    node: Optional[Tag],
    attributes: list[str],
) -> str:

    if node is None:

        return ""

    for attribute in attributes:

        value = node.get(
            attribute
        )

        if value:

            value = clean_text(
                value
            )

            if value:

                return value

    return ""


# ============================================================
# IMAGE URL HELPER
# ============================================================


def extract_image_url(
    node: Optional[Tag],
    base_url: str,
) -> Optional[str]:

    if node is None:

        return None

    value = get_first_attribute(
        node,
        [
            "src",
            "data-src",
            "data-lazy-src",
            "data-original",
            "data-image",
        ]
    )

    if not value:

        srcset = node.get(
            "srcset"
        )

        if srcset:

            value = (
                srcset.split(",")[0]
                .strip()
                .split(" ")[0]
            )

    if not value:

        return None

    return absolute_url(
        base_url,
        value
    )


# ============================================================
# META VALUE
# ============================================================


def get_meta_content(
    soup: BeautifulSoup,
    selector: str,
) -> str:

    node = soup.select_one(
        selector
    )

    if not node:

        return ""

    return clean_text(
        node.get(
            "content",
            ""
        )
    )


# ============================================================
# FIND FIRST TEXT
# ============================================================


def find_first_text(
    soup: BeautifulSoup,
    selectors: list[str],
) -> str:

    for selector in selectors:

        node = soup.select_one(
            selector
        )

        if not node:

            continue

        value = clean_text(
            node.get_text(
                " ",
                strip=True
            )
        )

        if value:

            return value

    return ""


# ============================================================
# EXTRACT NUMBERS FROM TEXT
# ============================================================


def extract_numbers(
    text: str,
) -> list[int]:

    if not text:

        return []

    values = []

    for match in re.findall(
        r"\b\d+\b",
        text
    ):

        try:

            values.append(
                int(match)
            )

        except ValueError:

            pass

    return values


# ============================================================
# FIND EPISODE COUNT FROM HTML
# ============================================================


def find_episode_count(
    soup: BeautifulSoup,
) -> int:

    text = clean_text(
        soup.get_text(
            " ",
            strip=True
        )
    )

    count = extract_total_episodes(
        text
    )

    if count:

        return count

    # --------------------------------------------------------
    # Count visible episode elements as fallback.
    # --------------------------------------------------------

    selectors = [

        ".episode",

        ".episodes a",

        ".episode-list a",

        ".ep-list a",

        ".episodelist a",

    ]

    maximum = 0

    for selector in selectors:

        found = soup.select(
            selector
        )

        maximum = max(
            maximum,
            len(found)
        )

    return maximum


# ============================================================
# LOGGING HELPER
# ============================================================


def log_anime_summary(
    anime: Optional[AnimeInfo],
) -> None:

    if anime is None:

        logger.info(
            "Anime result: None"
        )

        return

    title = getattr(
        anime,
        "title",
        "Unknown"
    )

    total = safe_int(
        getattr(
            anime,
            "total_episodes",
            0
        )
    )

    hindi = get_hindi_episode_count(
        anime
    )

    logger.info(
        "Anime result: title=%s total=%d hindi=%d",
        title,
        total,
        hindi
    )


# ============================================================
# ERROR RESULT
# ============================================================


def make_error_result(
    query: str,
) -> str:

    query = clean_text(
        query
    )

    if not query:

        return (
            "❌ Please enter an anime name."
        )

    return (
        f"❌ Unable to fetch anime "
        f"information for: {query}\n\n"
        "Ye temporary problem ho sakti hai.\n"
        "Thodi der baad dobara try karo."
    )


# ============================================================
# FINAL PUBLIC RESULT
# ============================================================
async def search_and_format(
    query: str,
) -> tuple[
    Optional[AnimeInfo],
    str,
]:

    query = clean_text(
        query
    )

    if not query:

        return (
            None,
            make_error_result("")
        )

    try:

        anime = await get_anime_info(
            query
        )

        if anime is None:

            return (
                None,
                make_error_result(
                    query
                )
            )

        log_anime_summary(
            anime
        )

        result = safe_format_text(
            anime
        )

        if not result.strip():

            return (
                anime,
                make_error_result(
                    query
                )
            )

        return (
            anime,
            result
        )

    except Exception as exc:

        logger.exception(
            "search_and_format failed: %s",
            exc
        )

        return (
            None,
            make_error_result(
                query
            )
        )






# ============================================================
# FORMAT HELPERS
# ============================================================


def format_episode(
    episode: Episode,
) -> str:

    title = episode.title.strip()

    if title:

        line = (
            f"Episode {episode.number}"
            f" — {title}"
        )

    else:

        line = (
            f"Episode {episode.number}"
        )

    if episode.languages:

        language_text = ", ".join(
            episode.languages
        )

        line += (
            f" [{language_text}]"
        )

    return line


def format_episode_list(
    episodes: list[Episode],
) -> list[str]:

    lines = []

    for episode in episodes:

        lines.append(
            format_episode(
                episode
            )
        )

    return lines


def format_language_list(
    languages: list[str],
) -> str:

    if not languages:
        return "Unknown"

    return ", ".join(
        unique(languages)
    )


def format_platform_list(
    platforms,
) -> str:

    if not platforms:
        return "Unknown"

    if isinstance(
        platforms,
        str
    ):

        return platforms

    return ", ".join(
        unique(platforms)
    )


def format_status(
    status: str,
) -> str:

    mapping = {

        "completed":
            "✅ Completed",

        "ongoing":
            "🔄 Ongoing",

        "upcoming":
            "⏳ Upcoming",

        "unknown":
            "❔ Unknown",
    }

    return mapping.get(
        status,
        "❔ Unknown"
    )


# ============================================================
# FORMAT NORMAL ANIME
# ============================================================


def format_single_anime_info(
    anime: AnimeInfo,
) -> str:

    lines = []

    title = (
        anime.title
        or anime.canonical_title
        or "Unknown Anime"
    )

    lines.append(
        f"🎌 {title}"
    )

    lines.append("")

    if anime.season:

        lines.append(
            f"📺 Season: {anime.season}"
        )

    if anime.release_year:

        lines.append(
            f"📅 Year: {anime.release_year}"
        )

    if anime.total_episodes:

        lines.append(
            f"🎞 Total Episodes: "
            f"{anime.total_episodes}"
        )

    if anime.last_episode:

        lines.append(
            f"▶️ Latest Episode: "
            f"{anime.last_episode}"
        )

    # --------------------------------------------------------
    # Hindi episode count ONLY
    # Individual episode names/numbers are NOT displayed.
    # --------------------------------------------------------

    hindi_count = (
        anime.available_episodes.get(
            "Hindi",
            0
        )
        if anime.available_episodes
        else 0
    )

    if hindi_count:

        lines.append(
            f"🇮🇳 Hindi Episodes: "
            f"{hindi_count}"
        )

    if anime.hindi_available:

        lines.append(
            "🗣 Hindi: ✅ Available"
        )

    else:

        lines.append(
            "🗣 Hindi: ❌ Not Available"
        )

    if anime.languages:

        lines.append(
            f"🌐 Languages: "
            f"{format_language_list(anime.languages)}"
        )

    if anime.platform:

        lines.append(
            f"📡 Platform: "
            f"{format_platform_list(anime.platform)}"
        )

    if anime.dub_by:

        lines.append(
            f"🎙 Dub: {anime.dub_by}"
        )

    if anime.runtime:

        lines.append(
            f"⏱ Runtime: {anime.runtime}"
        )

    if anime.genres:

        lines.append(
            f"🏷 Genre: "
            f"{', '.join(anime.genres)}"
        )

    if anime.status:

        lines.append(
            f"📌 Status: "
            f"{format_status(anime.status)}"
        )

    if anime.schedule:

        lines.append(
            f"🗓 Schedule: "
            f"{anime.schedule}"
        )

    if anime.next_episode:

        lines.append(
            f"⏭ Next Episode: "
            f"{anime.next_episode}"
        )

    if anime.synopsis:

        lines.append("")

        lines.append(
            f"📝 {anime.synopsis}"
        )

    return "\n".join(
        lines
    )


# ============================================================
# PART 7/7 — FRANCHISE FORMATTER + PUBLIC API
# ============================================================


def format_franchise_info(
    anime: AnimeInfo,
) -> str:

    lines = []

    title = (
        anime.title
        or "Anime Franchise"
    )

    lines.append(
        f"🎌 {title}"
    )

    lines.append("")

    # --------------------------------------------------------
    # Separately named series
    # --------------------------------------------------------

    series = getattr(
        anime,
        "franchise_series",
        []
    )

    if series:

        lines.append(
            "📺 Series:"
        )

        for index, item in enumerate(
            series,
            start=1
        ):

            item_title = (
                item.canonical_title
                or item.title
                or "Unknown"
            )

            lines.append(
                f"{index}. {item_title}"
            )

            if item.season:

                lines.append(
                    f"   └─ Season: "
                    f"{item.season}"
                )

            if item.total_episodes:

                lines.append(
                    f"   └─ Total Episodes: "
                    f"{item.total_episodes}"
                )

            hindi_count = (
                item.available_episodes.get(
                    "Hindi",
                    0
                )
                if item.available_episodes
                else 0
            )

            if hindi_count:

                lines.append(
                    f"   └─ Hindi Episodes: "
                    f"{hindi_count}"
                )

            lines.append(
                "   └─ Hindi: ✅ Available"
            )

    else:

        lines.append(
            "📺 Series:"
        )

        lines.append(
            "No Hindi series found."
        )

    # --------------------------------------------------------
    # Movies
    # --------------------------------------------------------

    movies = getattr(
        anime,
        "franchise_movies",
        []
    )

    if movies:

        lines.append("")

        lines.append(
            "🎬 Movies:"
        )

        for index, movie in enumerate(
            movies,
            start=1
        ):

            lines.append(
                f"{index}. {movie}"
            )

    return "\n".join(
        lines
    )


# ============================================================
# MAIN FORMAT FUNCTION
# ============================================================

def format_anime_info(
    anime: AnimeInfo,
) -> str:

    """
    Format AnimeInfo for the Telegram bot.

    Franchise searches are displayed as:

        📺 Series
        🎬 Movies

    Normal anime searches retain the normal output.

    NOTE:
    Poster URL is intentionally NOT printed.
    """

    franchise_key = getattr(
        anime,
        "franchise_key",
        None
    )

    franchise_series = getattr(
        anime,
        "franchise_series",
        []
    )

    franchise_movies = getattr(
        anime,
        "franchise_movies",
        []
    )

    if (
        franchise_key
        or franchise_series
        or franchise_movies
    ):

        return format_franchise_info(
            anime
        )

    result = format_single_anime_info(
        anime
    )

    if not result.strip():

        title = (
            getattr(
                anime,
                "canonical_title",
                None
            )
            or getattr(
                anime,
                "title",
                None
            )
            or "Unknown Anime"
        )

        return (
            f"🎌 {title}\n\n"
            "❌ No anime information found."
        )

    return result


# ============================================================
# BOT HELPER
# ============================================================

async def get_anime_info(
    query: str,
) -> AnimeInfo:

    async with AnimeScraper(
        source="DC"
    ) as scraper:

        return await scraper.scrape(
            query
        )


# ============================================================
# SAFE BOT HELPER
# ============================================================

async def get_formatted_anime_info(
    query: str,
) -> str:

    try:

        anime = await get_anime_info(
            query
        )

        if not anime:

            return (
                "❌ Anime information "
                "not found."
            )

        return format_anime_info(
            anime
        )

    except AnimeNotFound:

        return (
            "❌ Anime not found.\n\n"
            "Anime ka exact naam "
            "try karo."
        )

    except asyncio.TimeoutError:

        return (
            "⏳ Request timeout.\n\n"
            "Thodi der baad dobara "
            "try karo."
        )

    except Exception as exc:

        logger.exception(
            "Anime lookup failed: %s",
            query
        )

        return (
            "❌ Error: Unable to fetch "
            "anime information.\n\n"
            "Ye temporary problem ho "
            "sakti hai.\n"
            "Thodi der baad dobara "
            "try karo."
        )


# ============================================================
# OPTIONAL CLI TEST
# ============================================================

async def _cli_test(
    query: str,
) -> None:

    try:

        result = (
            await get_formatted_anime_info(
                query
            )
        )

        print(result)

    except KeyboardInterrupt:

        print(
            "\nStopped."
        )


# ============================================================
# MODULE ENTRY POINT
# ============================================================

if __name__ == "__main__":

    import sys

    if len(sys.argv) > 1:

        query = " ".join(
            sys.argv[1:]
        )

        asyncio.run(
            _cli_test(
                query
            )
        )

    else:

        print(
            "Usage: python anime_scraper.py "
            "<anime name>"
)

    
                
