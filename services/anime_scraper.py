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

    available_episodes: dict[str, int] = field(default_factory=dict)

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

    # Franchise / multi-series support.
    # Normal anime keep this empty; franchises such as Naruto/Dragon Ball
    # use it to hold each separate series/season result.
    series: list["AnimeInfo"] = field(default_factory=list)
    movies: list[str] = field(default_factory=list)
    is_franchise: bool = False

    scraped_at: float = field(default_factory=time.time)


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
    timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)

    connector = aiohttp.TCPConnector(
        limit=10,
        limit_per_host=5,
        ssl=False,
    )

    return aiohttp.ClientSession(
        headers=HEADERS,
        timeout=timeout,
        connector=connector,
    )


# ------------------------------------------------------------
# Fetch URL
# ------------------------------------------------------------

async def fetch(
    session: aiohttp.ClientSession,
    url: str,
) -> str:

    logger.info("Fetching: %s", url)

    try:
        async with session.get(url, allow_redirects=True) as response:

            if response.status != 200:
                raise ScraperError(
                    f"HTTP {response.status}: {url}"
                )

            return await response.text(errors="ignore")

    except asyncio.TimeoutError:
        raise ScraperError(f"Timeout: {url}")

    except aiohttp.ClientError as exc:
        raise ScraperError(
            f"Request failed: {url} -> {exc}"
        )


# ------------------------------------------------------------
# Normalize text
# ------------------------------------------------------------

def clean_text(value: str | None) -> str:

    if not value:
        return ""

    value = value.replace("\xa0", " ")
    value = value.replace("\r", " ")
    value = value.replace("\n", " ")

    value = re.sub(r"\s+", " ", value)

    return value.strip()


# ------------------------------------------------------------
# Normalize title for matching
# ------------------------------------------------------------

def normalize_title(title: str) -> str:

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
        title = title.replace(char, " ")

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

    return " ".join(words).strip()


# ------------------------------------------------------------
# Slug normalize
# ------------------------------------------------------------

def normalize_slug(value: str) -> str:

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

def extract_int(value: str | None) -> Optional[int]:

    if not value:
        return None

    match = re.search(r"\b(\d{1,4})\b", value)

    if not match:
        return None

    try:
        return int(match.group(1))
    except ValueError:
        return None


# ------------------------------------------------------------
# Multiple integer extractor
# ------------------------------------------------------------

def extract_ints(value: str | None) -> list[int]:

    if not value:
        return []

    return [
        int(x)
        for x in re.findall(r"\b\d{1,4}\b", value)
    ]


# ------------------------------------------------------------
# Unique preserving order
# ------------------------------------------------------------

def unique(items: list[str]) -> list[str]:

    result = []

    seen = set()

    for item in items:

        item = clean_text(item)

        if not item:
            continue

        key = item.lower()

        if key in seen:
            continue

        seen.add(key)
        result.append(item)

    return result


# ------------------------------------------------------------
# Cache filename
# ------------------------------------------------------------

def cache_file(url: str) -> Path:

    key = normalize_slug(url)

    if not key:
        key = "home"

    return CACHE_DIR / f"{key[:180]}.json"


# ------------------------------------------------------------
# Cache read
# ------------------------------------------------------------

def read_cache(url: str) -> Optional[dict]:

    path = cache_file(url)

    if not path.exists():
        return None

    try:

        data = json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )

        timestamp = data.get("timestamp", 0)

        if time.time() - timestamp > data.get(
            "ttl",
            ONGOING_CACHE_TTL
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

    path = cache_file(url)

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

    cached = read_cache(url)

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
# SEARCH + TITLE RESOLVER
# ============================================================


# ------------------------------------------------------------
# Known common aliases
# ------------------------------------------------------------

COMMON_ALIASES = {

    "re zero":
        "Re:ZERO -Starting Life in Another World-",

    "rezero":
        "Re:ZERO -Starting Life in Another World-",

    "re:zero":
        "Re:ZERO -Starting Life in Another World-",

    "konosuba":
        "KONOSUBA – God's blessing on this wonderful world!",

    "kono suba":
        "KONOSUBA – God's blessing on this wonderful world!",

    "spy x family":
        "SPY x FAMILY",

    "spy family":
        "SPY x FAMILY",

    "naruto":
        "Naruto",

    "naruto shippuden":
        "Naruto Shippuden",

    # Franchise / multi-series aliases
    "dragon ball":
        "Dragon Ball",
    "dragonball":
        "Dragon Ball",
    "dragon ball z":
        "Dragon Ball Z",
    "dragonball z":
        "Dragon Ball Z",
    "dbz":
        "Dragon Ball Z",
    "dragon ball gt":
        "Dragon Ball GT",
    "dragon ball super":
        "Dragon Ball Super",
    "dbs":
        "Dragon Ball Super",
    "dragon ball daima":
        "Dragon Ball DAIMA",
    "dragon ball super daima":
        "Dragon Ball DAIMA",

    "bleach":
        "Bleach",

    "black torch":
        "BLACK TORCH",

    "one piece":
        "One Piece",

    "op":
        "One Piece",
}


# ------------------------------------------------------------
# Alias resolver
# ------------------------------------------------------------

def resolve_alias(query: str) -> str:

    normalized = normalize_title(query)

    if normalized in COMMON_ALIASES:

        return COMMON_ALIASES[
            normalized
        ]

    return query.strip()


# ------------------------------------------------------------
# Fuzzy score
# ------------------------------------------------------------

def title_score(
    query: str,
    candidate: str,
) -> float:

    q = normalize_title(query)
    c = normalize_title(candidate)

    if not q or not c:
        return 0

    if q == c:
        return 100

    if q in c:
        return 95

    if c in q:
        return 90

    if fuzz:

        token_score = fuzz.token_set_ratio(
            q,
            c
        )

        ratio_score = fuzz.ratio(
            q,
            c
        )

        return max(
            token_score,
            ratio_score
        )

    # Fallback if rapidfuzz isn't installed
    q_words = set(q.split())
    c_words = set(c.split())

    if not q_words:
        return 0

    overlap = len(
        q_words & c_words
    ) / len(q_words)

    return overlap * 100


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

    # Collect article/post links
    links = soup.find_all("a", href=True)

    seen_urls = set()

    for link in links:

        href = link.get("href", "").strip()

        text = clean_text(
            link.get_text(
                " ",
                strip=True
            )
        )

        if not href or not text:
            continue

        if not href.startswith("http"):
            href = urljoin(
                BASE_URL,
                href
            )

        if "rareanimes.mov" not in href:
            continue

        # Ignore navigation URLs
        bad_parts = [
            "/category/",
            "/tag/",
            "/page/",
            "/author/",
            "/feed/",
            "/wp-",
        ]

        if any(
            part in href
            for part in bad_parts
        ):
            continue

        if href in seen_urls:
            continue

        seen_urls.add(href)

        # Avoid tiny navigation labels
        if len(text) < 3:
            continue

        score = title_score(
            query,
            text
        )

        candidates.append(
            SearchCandidate(
                title=text,
                url=href,
                score=score
            )
        )

    candidates.sort(
        key=lambda x: x.score,
        reverse=True
    )

    return candidates


# ------------------------------------------------------------
# Search RareAnimes
# ------------------------------------------------------------

async def search_anime(
    session: aiohttp.ClientSession,
    query: str,
) -> list[SearchCandidate]:

    resolved = resolve_alias(query)

    search_url = SEARCH_URL.format(
        query=quote_plus(resolved)
    )

    html = await fetch_cached(
        session,
        search_url,
        ttl=ONGOING_CACHE_TTL
    )

    candidates = parse_search_results(
        html,
        resolved
    )

    # If alias search gives weak results,
    # try original query too.
    if (
        not candidates
        or candidates[0].score < 55
    ):

        original_url = SEARCH_URL.format(
            query=quote_plus(query)
        )

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

    # Deduplicate
    final = []

    seen = set()

    for candidate in sorted(
        candidates,
        key=lambda x: x.score,
        reverse=True
    ):

        if candidate.url in seen:
            continue

        seen.add(candidate.url)

        final.append(candidate)

    return final[:20]


# ------------------------------------------------------------
# Find best page
# ------------------------------------------------------------

async def find_anime_page(
    session: aiohttp.ClientSession,
    query: str,
) -> SearchCandidate:

    candidates = await search_anime(
        session,
        query
    )

    if not candidates:
        raise AnimeNotFound(
            f"No anime found for: {query}"
        )

    # Minimum reasonable score
    good = [
        c for c in candidates
        if c.score >= 50
    ]

    if not good:
        raise AnimeNotFound(
            f"Anime not confidently matched: {query}"
        )

    best = good[0]

    logger.info(
        "MATCH: %s -> %s [%.1f]",
        query,
        best.title,
        best.score
    )

    return best


# ------------------------------------------------------------
# Get multiple season candidates
# ------------------------------------------------------------

async def find_season_candidates(
    session: aiohttp.ClientSession,
    query: str,
    limit: int = 8,
) -> list[SearchCandidate]:

    candidates = await search_anime(
        session,
        query
    )

    if not candidates:
        return []

    best_score = candidates[0].score

    # Keep candidates reasonably close
    selected = [
        c
        for c in candidates
        if c.score >= max(
            55,
            best_score - 18
        )
    ]

    return selected[:limit]

# ============================================================
# PART 4/7
# PAGE INFO PARSER
# ============================================================


# ------------------------------------------------------------
# Find value after label
# ------------------------------------------------------------

def find_labeled_value(
    text: str,
    label: str,
) -> Optional[str]:

    pattern = re.compile(
        rf"{re.escape(label)}\s*:\s*(.+?)(?=\s+(?:"
        r"Full Name|Season|Episodes|Release Year|RunTime|"
        r"Genre|Language|Quality|Network|Year|Synopsis"
        r")\s*:|$)",
        re.I
    )

    match = pattern.search(text)

    if not match:
        return None

    return clean_text(
        match.group(1)
    )


# ------------------------------------------------------------
# Extract poster
# ------------------------------------------------------------

def extract_poster(
    soup: BeautifulSoup,
) -> Optional[str]:

    # Prefer main/article images
    candidates = []

    for img in soup.find_all("img"):

        src = (
            img.get("data-src")
            or img.get("data-lazy-src")
            or img.get("src")
        )

        if not src:
            continue

        src = urljoin(
            BASE_URL,
            src
        )

        alt = clean_text(
            img.get("alt")
        ).lower()

        candidates.append(
            (
                src,
                alt
            )
        )

    # Try image whose alt/title contains anime
    for src, alt in candidates:

        if (
            "season" in alt
            or "anime" in alt
            or "episode" in alt
        ):
            return src

    return candidates[0][0] if candidates else None


# ------------------------------------------------------------
# Extract page title
# ------------------------------------------------------------

def extract_page_title(
    soup: BeautifulSoup,
) -> str:

    h1 = soup.find("h1")

    if h1:
        return clean_text(
            h1.get_text(
                " ",
                strip=True
            )
        )

    if soup.title:
        return clean_text(
            soup.title.get_text(
                " ",
                strip=True
            )
        )

    return ""


# ------------------------------------------------------------
# Extract info section
# ------------------------------------------------------------

def extract_info_text(
    soup: BeautifulSoup,
) -> str:

    # Find "Anime Series Info"
    marker = soup.find(
        string=re.compile(
            r"Anime\s+Series\s+Info",
            re.I
        )
    )

    if marker:

        parent = marker.parent

        # Try nearby container
        for _ in range(4):

            if not parent:
                break

            text = clean_text(
                parent.get_text(
                    " ",
                    strip=True
                )
            )

            if len(text) > 150:
                return text

            parent = parent.parent

    # Fallback: complete page text
    return clean_text(
        soup.get_text(
            " ",
            strip=True
        )
    )


# ------------------------------------------------------------
# Extract genres
# ------------------------------------------------------------

def parse_genres(
    value: Optional[str],
) -> list[str]:

    if not value:
        return []

    value = value.replace(
        " and ",
        ", "
    )

    return unique(
        [
            x.strip()
            for x in value.split(",")
            if x.strip()
        ]
    )


# ------------------------------------------------------------
# Extract languages
# ------------------------------------------------------------

def parse_languages(
    value: Optional[str],
) -> list[str]:

    if not value:
        return []

    value = re.sub(
        r"\{|\}",
        "",
        value
    )

    value = value.replace(
        "/",
        ","
    )

    value = value.replace(
        "•",
        ","
    )

    return unique(
        [
            x.strip()
            for x in value.split(",")
            if x.strip()
        ]
    )


# ------------------------------------------------------------
# Extract network/platform
# ------------------------------------------------------------

def parse_platforms(
    page_text: str,
) -> list[str]:

    platforms = []

    # Network: Crunchyroll
    network = re.search(
        r"\bNetwork\s*:\s*(.+?)(?=\s+(?:Year|Language|Genre|Quality|Synopsis)\s*:|$)",
        page_text,
        re.I
    )

    if network:

        raw = clean_text(
            network.group(1)
        )

        raw = re.sub(
            r"\s+and\s+",
            ",",
            raw,
            flags=re.I
        )

        parts = re.split(
            r"[,|•;/]+",
            raw
        )

        platforms.extend(
            [
                x.strip()
                for x in parts
                if x.strip()
            ]
        )

    # "telecasted by Jio Cinema"
    patterns = [
        r"telecasted\s+by\s+([A-Za-z0-9 .&+'-]+)",
        r"stream(?:ed)?\s+on\s+([A-Za-z0-9 .&+'-]+)",
        r"available\s+on\s+([A-Za-z0-9 .&+'-]+)",
        r"produced\s+by\s+([A-Za-z0-9 .&+'-]+)",
    ]

    for pattern in patterns:

        for match in re.finditer(
            pattern,
            page_text,
            re.I
        ):

            value = clean_text(
                match.group(1)
            )

            # Don't accidentally grab huge sentences
            value = value.split(".")[0]

            if 1 <= len(value) <= 60:
                platforms.append(value)

    return unique(platforms)


# ------------------------------------------------------------
# Extract dub provider
# ------------------------------------------------------------

def parse_dub_by(
    page_text: str,
) -> Optional[str]:

    patterns = [

        r"dubbed\s+by\s+([A-Za-z0-9 .&+'-]+)",

        r"dub\s+by\s+([A-Za-z0-9 .&+'-]+)",

        r"hindi\s+dub\s+by\s+([A-Za-z0-9 .&+'-]+)",
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            page_text,
            re.I
        )

        if match:

            value = clean_text(
                match.group(1)
            )

            value = value.split(".")[0]

            if len(value) <= 80:
                return value

    return None


# ------------------------------------------------------------
# Parse AnimeInfo from page
# ------------------------------------------------------------

def parse_page_info(
    html: str,
    source_url: str,
) -> AnimeInfo:

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    page_text = clean_text(
        soup.get_text(
            " ",
            strip=True
        )
    )

    info_text = extract_info_text(
        soup
    )

    title = find_labeled_value(
        info_text,
        "Full Name"
    )

    if not title:
        title = extract_page_title(
            soup
        )

    season_raw = find_labeled_value(
        info_text,
        "Season"
    )

    episodes_raw = find_labeled_value(
        info_text,
        "Episodes"
    )

    release_year_raw = find_labeled_value(
        info_text,
        "Release Year"
    )

    runtime = find_labeled_value(
        info_text,
        "RunTime"
    )

    genre_raw = find_labeled_value(
        info_text,
        "Genre"
    )

    language_raw = find_labeled_value(
        info_text,
        "Language"
    )

    synopsis = find_labeled_value(
        info_text,
        "Synopsis"
        )

    anime = AnimeInfo(

        title=clean_text(title),

        canonical_title=clean_text(title),

        aliases=[],

        poster_url=extract_poster(
            soup
        ),

        source_url=source_url,

        source="DC",

        platform=parse_platforms(
            page_text
        ),

        languages=parse_languages(
            language_raw
        ),

        runtime=clean_text(runtime)
        if runtime
        else None,

        genres=parse_genres(
            genre_raw
        ),

        synopsis=clean_text(synopsis)
        if synopsis
        else None,

        dub_by=parse_dub_by(
            page_text
        ),
    )

    # Season
    if season_raw:
        season_number = extract_int(
            season_raw
        )

        if season_number is not None:
            anime.season = season_number

    # Episodes
    if episodes_raw:

        numbers = extract_ints(
            episodes_raw
        )

        if numbers:
            anime.total_episodes = max(
                numbers
            )

    # Release year
    if release_year_raw:

        match = re.search(
            r"\b(19|20)\d{2}\b",
            release_year_raw
        )

        if match:
            anime.release_year = int(
                match.group(0)
            )

    # Hindi availability
    page_lower = page_text.lower()

    anime.hindi_available = (
        "hindi dub" in page_lower
        or "hindi dubbed" in page_lower
        or re.search(
            r"\bhindi\s+(?:dub|sub)\b",
            page_lower
        )
        is not None
        or "language: hindi" in page_lower
    )

    return anime

# ============================================================
# PART 5/7
# EPISODE PARSER
# ============================================================


LANGUAGE_NAMES = [
    "Hindi",
    "English",
    "Japanese",
    "Tamil",
    "Telugu",
    "Malayalam",
    "Kannada",
    "Bengali",
    "Marathi",
    "Korean",
    "Chinese",
    "Spanish",
    "French",
    "German",
    "Arabic",
]


# ------------------------------------------------------------
# Detect languages in episode block
# ------------------------------------------------------------

def detect_episode_languages(
    text: str,
) -> list[str]:

    result = []

    lower = text.lower()

    for language in LANGUAGE_NAMES:

        # Hindi DUB / Hindi Sub / Hindi
        if re.search(
            rf"\b{re.escape(language.lower())}\b",
            lower
        ):
            result.append(language)

    return result


# ------------------------------------------------------------
# Parse episode number
# ------------------------------------------------------------

def parse_episode_number(
    text: str,
) -> Optional[int]:

    patterns = [

        r"\bEpisode\s*[-:]?\s*(\d{1,4})\b",

        r"\bEp\.?\s*[-:]?\s*(\d{1,4})\b",

        r"^\s*(\d{1,4})\s*[-:.]",
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            text,
            re.I
        )

        if match:

            try:
                return int(
                    match.group(1)
                )
            except ValueError:
                pass

    return None


# ------------------------------------------------------------
# Parse episode title
# ------------------------------------------------------------

def parse_episode_title(
    text: str,
    episode_number: int,
) -> str:

    # Remove episode prefix
    cleaned = re.sub(
        rf"^\s*Episode\s*[-:]?\s*0*{episode_number}\s*[-:–—]?\s*",
        "",
        text,
        flags=re.I
    )

    cleaned = re.sub(
        r"\bEpisode\s*[-:]?\s*\d{1,4}\b",
        "",
        cleaned,
        count=1,
        flags=re.I
    )

    # Remove language/link noise
    cleaned = re.sub(
        r"\b(?:Hindi|English|Japanese|Tamil|Telugu)\s+(?:DUB|Sub)\b",
        "",
        cleaned,
        flags=re.I
    )

    cleaned = re.sub(
        r"\b(?:Hindi|English|Japanese|Tamil|Telugu)\b",
        "",
        cleaned,
        flags=re.I
    )

    cleaned = re.sub(
        r"\b(?:WatchMultQuality|StreamBeta|DLBeta|Mega)\b",
        "",
        cleaned,
        flags=re.I
    )

    cleaned = re.sub(
        r"\bNEW!?\b",
        "",
        cleaned,
        flags=re.I
    )

    cleaned = re.sub(
        r"\bSeason\s+Finale\b",
        "",
        cleaned,
        flags=re.I
    )

    cleaned = clean_text(
        cleaned
    )

    cleaned = cleaned.strip(
        " -–—:|"
    )

    return cleaned


# ------------------------------------------------------------
# Find episode containers
# ------------------------------------------------------------

def get_episode_blocks(
    soup: BeautifulSoup,
) -> list[str]:

    blocks = []

    # Search headings and common block elements
    elements = soup.find_all(
        [
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "p",
            "div",
            "article",
        ]
    )

    for element in elements:

        text = clean_text(
            element.get_text(
                " ",
                strip=True
            )
        )

        if not text:
            continue

        if not re.search(
            r"\bEpisode\s+\d{1,4}\b",
            text,
            re.I
        ):
            continue

        # Only use reasonably sized blocks
        if len(text) > 2000:
            continue

        blocks.append(
            text
        )

    # Deduplicate
    result = []

    seen = set()

    for block in blocks:

        key = re.sub(
            r"\s+",
            " ",
            block
        ).lower()

        if key in seen:
            continue

        seen.add(key)

        result.append(
            block
        )

    return result


# ------------------------------------------------------------
# Better episode extraction from page text
# ------------------------------------------------------------

def parse_episodes(
    soup: BeautifulSoup,
) -> list[Episode]:

    episodes: dict[int, Episode] = {}

    # First approach: locate text nodes containing Episode XX
    all_text_elements = soup.find_all(
        [
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "p",
            "div",
            "li",
        ]
    )

    for element in all_text_elements:

        text = clean_text(
            element.get_text(
                " ",
                strip=True
            )
        )

        if not text:
            continue

        number = parse_episode_number(
            text
        )

        if number is None:
            continue

        # Ignore extremely large containers
        if len(text) > 1200:
            continue

        languages = detect_episode_languages(
            text
        )

        title = parse_episode_title(
            text,
            number
        )

        if number not in episodes:

            episodes[number] = Episode(
                number=number,
                title=title,
                languages=languages,
            )

        else:

            existing = episodes[number]

            existing.languages = unique(
                existing.languages
                + languages
            )

            # Prefer a meaningful title
            if (
                len(title) > len(
                    existing.title
                )
            ):
                existing.title = title

    # --------------------------------------------------------
    # Second pass using complete page text.
    # This catches sites where languages are separated from
    # the episode heading.
    # --------------------------------------------------------

    page_text = clean_text(
        soup.get_text(
            " ",
            strip=True
        )
    )

    pattern = re.compile(
        r"(Episode\s+\d{1,4}.*?)(?=Episode\s+\d{1,4}|$)",
        re.I
    )

    for match in pattern.finditer(
        page_text
    ):

        block = clean_text(
            match.group(1)
        )

        number = parse_episode_number(
            block
        )

        if number is None:
            continue

        if len(block) > 3000:
            continue

        languages = detect_episode_languages(
            block
        )

        title = parse_episode_title(
            block,
            number
        )

        if number not in episodes:

            episodes[number] = Episode(
                number=number,
                title=title,
                languages=languages,
            )

        else:

            episodes[number].languages = unique(
                episodes[number].languages
                + languages
            )

            if (
                len(title)
                > len(episodes[number].title)
            ):
                episodes[number].title = title

    result = list(
        episodes.values()
    )

    result.sort(
        key=lambda x: x.number
    )

    return result


# ------------------------------------------------------------
# Count available languages
# ------------------------------------------------------------

def calculate_available_episodes(
    episodes: list[Episode],
) -> dict[str, int]:

    counts = {}

    for episode in episodes:

        for language in episode.languages:

            counts[language] = (
                counts.get(language, 0)
                + 1
            )

    return counts


# ------------------------------------------------------------
# Merge language information
# ------------------------------------------------------------

def merge_languages(
    anime: AnimeInfo,
) -> None:

    languages = list(
        anime.languages
    )

    for episode in anime.episodes:

        languages.extend(
            episode.languages
        )

    anime.languages = unique(
        languages
    )

    anime.available_episodes = (
        calculate_available_episodes(
            anime.episodes
        )
    )

    anime.hindi_available = (
        anime.available_episodes.get(
            "Hindi",
            0
        ) > 0
        or anime.hindi_available
    )


# ------------------------------------------------------------
# Determine last available episode
# ------------------------------------------------------------

def determine_last_episode(
    anime: AnimeInfo,
) -> None:

    if not anime.episodes:
        return

    # Last unique parsed episode
    anime.last_episode = max(
        ep.number
        for ep in anime.episodes
    )

# ============================================================
# PART 6/7
# STATUS / SCHEDULE / METADATA / MAIN SCRAPER
# ============================================================


# ------------------------------------------------------------
# Detect schedule
# ------------------------------------------------------------

def parse_schedule(
    page_text: str,
) -> Optional[str]:

    patterns = [

        r"1\s+New\s+Episode\s+Every\s+([A-Za-z]+)",

        r"New\s+Episode\s+Every\s+([A-Za-z]+)",

        r"Every\s+([A-Za-z]+)",

    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            page_text,
            re.I
        )

        if match:

            day = match.group(1).strip()

            return f"Every {day}"

    # Weekly
    if re.search(
        r"New\s+Episode\s+Every\s+Week",
        page_text,
        re.I
    ):
        return "Every Week"

    return None


# ------------------------------------------------------------
# Parse explicit next episode
# ------------------------------------------------------------

def parse_explicit_next_episode(
    page_text: str,
) -> Optional[int]:

    patterns = [

        r"Next\s+Episode\s*[:\-]?\s*(\d{1,4})",

        r"Upcoming\s+Episode\s*[:\-]?\s*(\d{1,4})",

    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            page_text,
            re.I
        )

        if match:
            return int(
                match.group(1)
            )

    return None


# ------------------------------------------------------------
# Detect completed
# ------------------------------------------------------------

def detect_completed(
    page_text: str,
) -> bool:

    completed_patterns = [

        r"\bCOMPLETED\b",

        r"\bCOMPLETE\b",

        r"\bSeason\s+Finale\b",

        r"\bSeries\s+Finale\b",

        r"\bFinal\s+Episode\b",

    ]

    for pattern in completed_patterns:

        if re.search(
            pattern,
            page_text,
            re.I
        ):
            return True

    return False


# ------------------------------------------------------------
# Detect ongoing
# ------------------------------------------------------------

def detect_ongoing(
    page_text: str,
) -> bool:

    ongoing_patterns = [

        r"New\s+Episode\s+Every",

        r"Every\s+(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)",

        r"\bOngoing\b",

        r"\bNext\s+Episode\b",

        r"\bExpected\s+Release\b",

        r"\bAirs?\b",

    ]

    for pattern in ongoing_patterns:

        if re.search(
            pattern,
            page_text,
            re.I
        ):
            return True

    return False


# ------------------------------------------------------------
# Calculate status
# ------------------------------------------------------------

def determine_status(
    anime: AnimeInfo,
    page_text: str,
) -> None:

    completed = detect_completed(
        page_text
    )

    ongoing = detect_ongoing(
        page_text
    )

    if completed and not ongoing:

        anime.status = "completed"
        return

    if ongoing:

        anime.status = "ongoing"
        return

    # If all declared episodes are available
    if (
        anime.total_episodes
        and anime.last_episode
        and anime.last_episode
        >= anime.total_episodes
    ):

        anime.status = "completed"

    elif anime.last_episode:

        anime.status = "ongoing"

    else:

        anime.status = "unknown"


# ------------------------------------------------------------
# Calculate next episode
# ------------------------------------------------------------

def determine_next_episode(
    anime: AnimeInfo,
    page_text: str,
) -> None:

    if anime.status != "ongoing":
        return

    explicit = parse_explicit_next_episode(
        page_text
    )

    if explicit:
        anime.next_episode = explicit

    elif anime.last_episode is not None:

        anime.next_episode = (
            anime.last_episode + 1
        )


# ------------------------------------------------------------
# Extract date from text
# ------------------------------------------------------------

def parse_date_string(
    value: str,
) -> Optional[str]:

    patterns = [

        r"\b\d{1,2}\s+[A-Za-z]+\s+\d{4}\b",

        r"\b[A-Za-z]+\s+\d{1,2},\s+\d{4}\b",

        r"\b\d{1,2}[/-]\d{1,2}[/-]\d{4}\b",

    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            value
        )

        if match:
            return match.group(0)

    return None


# ------------------------------------------------------------
# Parse last release date
# ------------------------------------------------------------

def parse_last_release(
    soup: BeautifulSoup,
    anime: AnimeInfo,
) -> None:

    # Look at individual episode containers
    episode_blocks = get_episode_blocks(
        soup
    )

    dates = []

    for block in episode_blocks:

        number = parse_episode_number(
            block
        )

        if number is None:
            continue

        date = parse_date_string(
            block
        )

        if date:

            dates.append(
                (
                    number,
                    date
                )
            )

    if dates:

        dates.sort(
            key=lambda x: x[0]
        )

        anime.last_release = dates[-1][1]


# ------------------------------------------------------------
# Try Jikan for studio metadata
# ------------------------------------------------------------

    async def fetch_studio_from_jikan(
    session: aiohttp.ClientSession,
    title: str,
) -> Optional[str]:

    if not title:
        return None

    url = (
        "https://api.jikan.moe/v4/anime"
        f"?q={quote_plus(title)}"
        "&limit=5"
    )

    try:

        async with session.get(
            url,
            headers={
                "User-Agent": USER_AGENT
            }
        ) as response:

            if response.status != 200:
                return None

            data = await response.json()

        results = data.get(
            "data",
            []
        )

        if not results:
            return None

        query_norm = normalize_title(
            title
        )

        best = None
        best_score = 0

        for item in results:

            candidate = item.get(
                "title",
                ""
            )

            score = title_score(
                query_norm,
                candidate
            )

            if score > best_score:

                best_score = score
                best = item

        if not best or best_score < 55:
            return None

        studios = best.get(
            "studios",
            []
        )

        if studios:

            return studios[0].get(
                "name"
            )

    except Exception as exc:

        logger.warning(
            "Jikan studio lookup failed: %s",
            exc
        )

    return None


# ------------------------------------------------------------
# Parse complete page
# ------------------------------------------------------------

def parse_anime_page(
    html: str,
    source_url: str,
) -> AnimeInfo:

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    page_text = clean_text(
        soup.get_text(
            " ",
            strip=True
        )
    )

    anime = parse_page_info(
        html,
        source_url
    )

    anime.episodes = parse_episodes(
        soup
    )

    merge_languages(
        anime
    )

    determine_last_episode(
        anime
    )

    schedule = parse_schedule(
        page_text
    )

    anime.schedule = schedule

    determine_status(
        anime,
        page_text
    )

    determine_next_episode(
        anime,
        page_text
    )

    parse_last_release(
        soup,
        anime
    )

    return anime


# ------------------------------------------------------------
# Franchise detection / aggregation
# ------------------------------------------------------------

FRANCHISE_SERIES = {
    "naruto": {
        "name": "Naruto",
        "queries": ["Naruto", "Naruto Shippuden"],
    },
    "dragon ball": {
        "name": "Dragon Ball",
        "queries": [
            "Dragon Ball",
            "Dragon Ball Z",
            "Dragon Ball GT",
            "Dragon Ball Super",
            "Dragon Ball DAIMA",
        ],
    },
}


def normalize_franchise_query(query: str) -> str:
    q = normalize_title(query)
    if q in ("naruto", "naruto shippuden"):
        return "naruto"
    if q.startswith("dragon ball") or q.startswith("dragonball") or q in ("dbz", "dbs"):
        return "dragon ball"
    return ""


def franchise_series_name(title: str, franchise_key: str) -> Optional[str]:
    n = normalize_title(title)

    if franchise_key == "naruto":
        if "shippuden" in n:
            return "Naruto Shippuden"
        if n == "naruto" or n.startswith("naruto "):
            return "Naruto"

    if franchise_key == "dragon ball":
        if "daima" in n:
            return "Dragon Ball DAIMA"
        if "super" in n:
            return "Dragon Ball Super"
        if re.search(r"\bgt\b", n):
            return "Dragon Ball GT"
        if re.search(r"\bz\b", n):
            return "Dragon Ball Z"
        if n == "dragon ball" or n.startswith("dragon ball "):
            return "Dragon Ball"

    return None


def merge_franchise_results(
    franchise_name: str,
    anime_list: list[AnimeInfo],
) -> AnimeInfo:
    # Group each scraped page into its actual series.
    grouped: dict[str, list[AnimeInfo]] = {}

    franchise_key = normalize_franchise_query(franchise_name)
    if not franchise_key:
        return anime_list[0]

    for anime in anime_list:
        name = franchise_series_name(
            anime.canonical_title or anime.title,
            franchise_key
        )
        if not name:
            continue
        grouped.setdefault(name, []).append(anime)

    # Sort pages by season and remove duplicate URLs.
    series_results: list[AnimeInfo] = []
    for name, pages in grouped.items():
        pages.sort(
            key=lambda x: (
                x.season if x.season is not None else 999,
                x.source_url or ""
            )
        )

        unique_pages: list[AnimeInfo] = []
        seen_urls = set()
        seen_seasons = set()

        for page in pages:
            if page.source_url and page.source_url in seen_urls:
                continue
            if page.season is not None and page.season in seen_seasons:
                continue

            if page.source_url:
                seen_urls.add(page.source_url)
            if page.season is not None:
                seen_seasons.add(page.season)

            page.canonical_title = name
            unique_pages.append(page)

        if not unique_pages:
            continue

        # If multiple RareAnimes pages represent seasons, keep the first
        # object as the series object and retain all season pages in .series.
        base = unique_pages[0]
        base.canonical_title = name
        base.title = name
        base.series = unique_pages
        base.is_franchise = False
        series_results.append(base)

    # Stable franchise order.
    order = {
        "Naruto": 0,
        "Naruto Shippuden": 1,
        "Dragon Ball": 0,
        "Dragon Ball Z": 1,
        "Dragon Ball GT": 2,
        "Dragon Ball Super": 3,
        "Dragon Ball DAIMA": 4,
    }
    series_results.sort(key=lambda x: order.get(x.canonical_title, 99))

    if not series_results:
        raise AnimeNotFound(
            f"No franchise series found for: {franchise_name}"
        )

    # Use the root/first series poster so the franchise card has a relevant
    # poster, never a random result from another anime.
    root = series_results[0]
    aggregate = AnimeInfo(
        title=franchise_name,
        canonical_title=franchise_name,
        poster_url=root.poster_url,
        source_url=root.source_url,
        source=root.source,
        hindi_available=any(x.hindi_available for x in series_results),
        platform=unique(
            p for x in series_results for p in x.platform
        ),
        languages=unique(
            lang for x in series_results for lang in x.languages
        ),
        status=(
            "ongoing"
            if any(x.status == "ongoing" for x in series_results)
            else "completed"
            if all(x.status == "completed" for x in series_results)
            else "unknown"
        ),
        series=series_results,
        is_franchise=True,
    )

    # Keep aggregate's latest useful episode information.
    all_episodes = [
        x.last_episode for x in series_results
        if x.last_episode is not None
    ]
    if all_episodes:
        aggregate.last_episode = max(all_episodes)

    return aggregate


# ------------------------------------------------------------
# Main scraper class
# ------------------------------------------------------------

class AnimeScraper:

    def __init__(
        self,
        source: str = "DC",
    ):

        self.source = source

        self.session: Optional[
            aiohttp.ClientSession
        ] = None

    async def __aenter__(self):

        self.session = (
            await create_session()
        )

        return self

    async def __aexit__(
        self,
        exc_type,
        exc,
        tb,
    ):

        if self.session:

            await self.session.close()

    # --------------------------------------------------------
    # Scrape one page
    # --------------------------------------------------------

    async def scrape_url(
        self,
        url: str,
    ) -> AnimeInfo:

        if not self.session:
            raise RuntimeError(
                "Use AnimeScraper with async context"
            )

        html = await fetch_cached(
            self.session,
            url,
            ttl=ONGOING_CACHE_TTL
        )

        anime = parse_anime_page(
            html,
            url
        )

        anime.source = self.source

        # Completed pages can be cached longer
        if anime.status == "completed":

            write_cache(
                url,
                html,
                COMPLETED_CACHE_TTL
            )

        # Studio lookup concurrently
        try:

            anime.studio = (
                await fetch_studio_from_jikan(
                    self.session,
                    anime.canonical_title
                )
            )

        except Exception:
            anime.studio = None

        return anime

    # --------------------------------------------------------
    # Search and scrape
    # --------------------------------------------------------

    async def scrape(
        self,
        query: str,
    ) -> AnimeInfo:

        if not self.session:
            raise RuntimeError(
                "Use AnimeScraper with async context"
            )

        franchise_key = normalize_franchise_query(query)

        # Only Naruto/Dragon Ball use multi-series aggregation.
        # Every other anime keeps the original single-result behaviour.
        if franchise_key:
            config = FRANCHISE_SERIES[franchise_key]

            candidates: list[SearchCandidate] = []
            seen_urls = set()

            # Search each known series separately. This is more reliable than
            # relying on one broad "dragon ball" search page.
            for series_query in config["queries"]:
                try:
                    found = await search_anime(
                        self.session,
                        series_query
                    )
                except Exception as exc:
                    logger.warning(
                        "Franchise search failed for %s: %s",
                        series_query,
                        exc
                    )
                    continue

                for candidate in found:
                    if candidate.url in seen_urls:
                        continue

                    matched_name = franchise_series_name(
                        candidate.title,
                        franchise_key
                    )
                    if not matched_name:
                        continue

                    seen_urls.add(candidate.url)
                    candidates.append(candidate)

            # Highest confidence first; scrape a bounded number of pages.
            candidates.sort(
                key=lambda x: x.score,
                reverse=True
            )

            scraped: list[AnimeInfo] = []
            for candidate in candidates[:20]:
                try:
                    scraped.append(
                        await self.scrape_url(candidate.url)
                    )
                except Exception as exc:
                    logger.warning(
                        "Could not scrape franchise page %s: %s",
                        candidate.url,
                        exc
                    )

            if scraped:
                return merge_franchise_results(
                    config["name"],
                    scraped
                )

            # Fall back to the normal single-page path if the franchise
            # aggregation found nothing usable.
            candidate = await find_anime_page(
                self.session,
                query
            )
            return await self.scrape_url(candidate.url)

        candidate = await find_anime_page(
            self.session,
            query
        )

        return await self.scrape_url(
            candidate.url
        )

# ============================================================
# PART 7/7
# OUTPUT FORMATTER + TEST
# ============================================================


# ------------------------------------------------------------
# Format episode count
# ------------------------------------------------------------

def format_episode_count(
    anime: AnimeInfo,
) -> str:

    total = anime.total_episodes

    hindi_count = anime.available_episodes.get(
        "Hindi",
        0
    )

    if total is None:

        if hindi_count:
            return str(hindi_count)

        if anime.last_episode:
            return str(
                anime.last_episode
            )

        return "Unknown"

    # If all episodes have Hindi
    if hindi_count >= total:

        return str(total)

    # Partial Hindi availability
    return f"{hindi_count} / {total}"


# ------------------------------------------------------------
# Platform formatting
# ------------------------------------------------------------

def format_platform(
    anime: AnimeInfo,
) -> str:

    if not anime.platform:
        return "Unknown"

    return " • ".join(
        unique(anime.platform)
    )


# ------------------------------------------------------------
# Language formatting
# ------------------------------------------------------------

def format_languages(
    anime: AnimeInfo,
) -> str:

    if not anime.languages:
        return "Unknown"

    return " • ".join(
        anime.languages
    )


# ------------------------------------------------------------
# Status formatting
# ------------------------------------------------------------

def format_status(
    status: str,
) -> str:

    if status == "completed":
        return "✅ Completed"

    if status == "ongoing":
        return "🔴 Ongoing"

    return "⚪ Unknown"


# ------------------------------------------------------------
# Main formatter
# ------------------------------------------------------------

def format_series_block(
    series: AnimeInfo,
    index: int,
) -> list[str]:
    lines = [
        f"{index}. {series.canonical_title or series.title}"
    ]

    # If RareAnimes returned multiple pages/seasons for this series,
    # print each season separately.
    pages = series.series if series.series else [series]

    season_lines = []
    for page in pages:
        season_label = (
            f"Season {page.season}"
            if page.season is not None
            else "Latest"
        )
        season_lines.append(
            f"• {season_label} — {format_episode_count(page)} Episodes"
        )

    lines.extend(season_lines or [
        f"• Latest — {format_episode_count(series)} Episodes"
    ])
    return lines


def format_anime_info(
    anime: AnimeInfo,
) -> str:
    # --------------------------------------------------------
    # Franchise output
    # --------------------------------------------------------
    if anime.is_franchise and anime.series:
        lines = [
            f"🎬 Anime: {anime.canonical_title or anime.title}",
            "",
            "🇮🇳 Hindi Available Series:",
            "",
        ]

        for index, series in enumerate(anime.series, 1):
            lines.extend(
                format_series_block(series, index)
            )
            lines.append("")

        if anime.movies:
            lines.extend([
                "🎬 Movies",
                *[f"• {movie}" for movie in anime.movies],
                "",
            ])

        lines.extend([
            f"📺 Platform: {format_platform(anime)}",
            "",
            f"🇮🇳 Hindi Dub: "
            f"{'✅ Available' if anime.hindi_available else '❌ Not Available'}",
            "",
            f"🌐 Languages: {format_languages(anime)}",
            "",
            f"📊 Status: {format_status(anime.status)}",
            "",
            f"🔎 Source: {anime.source}",
        ])
        return "\n".join(lines).strip()

    # --------------------------------------------------------
    # Normal single-anime output
    # --------------------------------------------------------
    lines = []

    lines.append(
        f"🎬 Anime: {anime.canonical_title or anime.title}"
    )

    hindi = (
        "✅ Available"
        if anime.hindi_available
        else "❌ Not Available"
    )

    lines.append(
        f"🇮🇳 Hindi Dub: {hindi}"
    )

    lines.append(
        f"📺 Platform: {format_platform(anime)}"
    )

    if anime.season is not None:
        lines.append(
            f"📀 Season: {anime.season}"
        )

    lines.append(
        f"🎬 Episodes: {format_episode_count(anime)}"
    )

    lines.append("")
    lines.append(
        f"🌐 Languages: {format_languages(anime)}"
    )

    lines.append("")
    lines.append(
        f"📊 Status: {format_status(anime.status)}"
    )

    if anime.last_episode is not None:
        lines.append("")
        lines.append(
            f"📅 Last Episode: Episode {anime.last_episode}"
        )

    if anime.status == "ongoing":
        if anime.next_episode is not None:
            lines.append(
                f"⏭ Next Episode: Episode {anime.next_episode}"
            )
        if anime.expected_release:
            lines.append(
                f"📅 Expected Release: {anime.expected_release}"
            )
        if anime.schedule:
            lines.append(
                f"⏰ Schedule: {anime.schedule}"
            )

    if anime.studio:
        lines.append("")
        lines.append(
            f"🏢 Studio: {anime.studio}"
        )

    if anime.dub_by:
        lines.append(
            f"🎙 Dub By: {anime.dub_by}"
        )

    # Poster is deliberately kept in the data model, not printed as raw URL.
    # The Telegram/Discord handler should send anime.poster_url as the
    # message/embed image.
    lines.append("")
    lines.append(
        f"🔎 Source: {anime.source}"
    )

    return "\n".join(lines)


# ------------------------------------------------------------
# JSON output
# ------------------------------------------------------------

def anime_to_json(
    anime: AnimeInfo,
) -> str:

    return json.dumps(
        asdict(anime),
        ensure_ascii=False,
        indent=2
    )


# ------------------------------------------------------------
# Simple async runner
# ------------------------------------------------------------

async def main():

    import sys

    if len(sys.argv) < 2:

        print(
            "Usage:\n"
            "python anime_scraper.py "
            "\"re zero\""
        )

        return

    query = " ".join(
        sys.argv[1:]
    )

    started = time.perf_counter()

    try:

        async with AnimeScraper(
            source="DC"
        ) as scraper:

            anime = await scraper.scrape(
                query
            )

        elapsed = (
            time.perf_counter()
            - started
        )

        print()
        print(
            format_anime_info(
                anime
            )
        )

        print()
        print(
            f"⏱ Scrape time: {elapsed:.2f}s"
        )

        # Optional debug:
        # print(anime_to_json(anime))

    except AnimeNotFound as exc:

        print(
            f"❌ {exc}"
        )

    except ScraperError as exc:

        print(
            f"❌ Scraper error: {exc}"
        )

    except Exception as exc:

        logger.exception(
            "Unexpected error"
        )

        print(
            f"❌ Unexpected error: {exc}"
        )


# ------------------------------------------------------------
# Entry point
# ------------------------------------------------------------

if __name__ == "__main__":

    asyncio.run(
        main()
        )

# ============================================================
# BOT HELPER
# ============================================================

async def get_anime_info(query: str) -> AnimeInfo:
    """
    Simple helper for Telegram/Discord bot.

    Example:
        anime = await get_anime_info("re zero")
    """

    async with AnimeScraper(source="DC") as scraper:
        return await scraper.scrape(query)
    
