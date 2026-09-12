from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional, Union
from urllib.parse import quote_plus, urljoin, urlparse

import aiohttp
from bs4 import BeautifulSoup, Tag

try:
    from rapidfuzz import fuzz
except ImportError:
    fuzz = None

BASE_URL = "https://www.rareanimes.mov"
SEARCH_URL = BASE_URL + "/?s={query}"
SOURCE_NAME = "DC"
REQUEST_TIMEOUT = 15
CACHE_DIR = Path("anime_cache")
CACHE_DIR.mkdir(exist_ok=True)
CACHE_TTL = 10 * 60
COMPLETED_CACHE_TTL = 24 * 60 * 60

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/140.0.0.0 Safari/537.36"
)
HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("AnimeScraper")


class AnimeNotFound(Exception):
    pass


class ScraperError(Exception):
    pass


@dataclass
class Episode:
    number: int
    title: str = ""
    languages: list[str] = field(default_factory=list)
    release_date: Optional[str] = None


@dataclass
class SeasonInfo:
    season: Optional[int] = None
    title: str = ""
    url: str = ""
    episodes: Optional[int] = None
    hindi_available: bool = False
    hindi_episodes: Optional[int] = None
    platform: list[str] = field(default_factory=list)
    languages: list[str] = field(default_factory=list)
    status: str = "unknown"


@dataclass
class AnimeInfo:
    title: str = ""
    canonical_title: str = ""
    aliases: list[str] = field(default_factory=list)
    poster_url: Optional[str] = None
    source_url: Optional[str] = None
    source: str = SOURCE_NAME
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
    episodes: list[Episode] = field(default_factory=list)
    seasons: list[SeasonInfo] = field(default_factory=list)
    scraped_at: float = field(default_factory=time.time)


@dataclass
class SeriesInfo:
    title: str = ""
    url: str = ""
    poster_url: Optional[str] = None
    total_episodes: Optional[int] = None
    hindi_available: bool = False
    hindi_episodes: Optional[int] = None
    platform: list[str] = field(default_factory=list)
    languages: list[str] = field(default_factory=list)
    status: str = "unknown"
    seasons: list[SeasonInfo] = field(default_factory=list)


@dataclass
class FranchiseInfo(AnimeInfo):
    # Inherits AnimeInfo so the existing Telegram commands.py remains
    # compatible with franchise results (poster_url/source/etc. stay the same).
    series: list[SeriesInfo] = field(default_factory=list)


ScrapeResult = Union[AnimeInfo, FranchiseInfo]


# ---------------------------------------------------------------------------
# Known franchise maps. These are used only to decide when a query is a
# franchise query. The actual episode/Hindi/platform data is still scraped
# from each matched series page.
# ---------------------------------------------------------------------------
FRANCHISE_FAMILIES: dict[str, list[str]] = {
    "dragon ball": [
        "Dragon Ball",
        "Dragon Ball Z",
        "Dragon Ball GT",
        "Dragon Ball Z Kai",
        "Dragon Ball Super",
        "Super Dragon Ball Heroes",
    ],
    "naruto": [
        "Naruto",
        "Naruto Shippuden",
    ],
    "bleach": [
        "Bleach",
        "Bleach Thousand-Year Blood War",
        "Bleach Thousand Year Blood War",
    ],
}

ALIASES = {
    "db": "Dragon Ball",
    "dragonball": "Dragon Ball",
    "dbz": "Dragon Ball Z",
    "dbs": "Dragon Ball Super",
    "dbgt": "Dragon Ball GT",
    "naruto shippuden": "Naruto Shippuden",
    "naruto shippuden dub": "Naruto Shippuden",
    "re zero": "Re:ZERO -Starting Life in Another World-",
    "rezero": "Re:ZERO -Starting Life in Another World-",
    "konosuba": "KONOSUBA – God's blessing on this wonderful world!",
}

MOVIE_RE = re.compile(r"\b(?:movie|film|ova|special|live\s*action)\b", re.I)
BAD_PATH_RE = re.compile(
    r"/(?:category|tag|author|page|feed|wp-|contact|about|privacy|dmca|privacy-policy)(?:/|$)",
    re.I,
)

LANGUAGES = [
    "Hindi", "English", "Japanese", "Tamil", "Telugu", "Malayalam",
    "Kannada", "Bengali", "Marathi", "Korean", "Chinese", "Spanish",
    "French", "German", "Arabic",
]


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------
def clean_text(value: Optional[str]) -> str:
    if not value:
        return ""
    value = value.replace("\xa0", " ").replace("\r", " ").replace("\n", " ")
    return re.sub(r"\s+", " ", value).strip()


def unique(values: list[str]) -> list[str]:
    out, seen = [], set()
    for value in values:
        value = clean_text(value)
        if not value:
            continue
        key = value.casefold()
        if key not in seen:
            seen.add(key)
            out.append(value)
    return out


def normalize_title(value: str) -> str:
    value = value.lower()
    value = value.replace("–", " ").replace("—", " ")
    value = re.sub(r"[^a-z0-9]+", " ", value)
    noise = {"season", "hindi", "dubbed", "dub", "episodes", "episode", "download", "hd", "watch", "online", "full", "complete"}
    return " ".join(w for w in value.split() if w not in noise).strip()


def normalize_slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def first_int(value: Optional[str]) -> Optional[int]:
    if not value:
        return None
    match = re.search(r"\b(\d{1,4})\b", value)
    return int(match.group(1)) if match else None


def all_ints(value: Optional[str]) -> list[int]:
    if not value:
        return []
    return [int(x) for x in re.findall(r"\b\d{1,4}\b", value)]


def title_score(query: str, candidate: str) -> float:
    q, c = normalize_title(query), normalize_title(candidate)
    if not q or not c:
        return 0
    if q == c:
        return 100
    if q in c:
        return 94
    if c in q:
        return 88
    if fuzz:
        return max(fuzz.token_set_ratio(q, c), fuzz.ratio(q, c))
    qw, cw = set(q.split()), set(c.split())
    return (len(qw & cw) / len(qw) * 100) if qw else 0


def is_same_host(url: str) -> bool:
    return "rareanimes.mov" in urlparse(url).netloc.lower()


def is_movie_or_special(title: str, url: str = "") -> bool:
    return bool(MOVIE_RE.search(f"{title} {url}"))


def cache_path(url: str) -> Path:
    return CACHE_DIR / f"{normalize_slug(url)[:180] or 'home'}.json"


# ---------------------------------------------------------------------------
# HTTP/cache
# ---------------------------------------------------------------------------
async def create_session() -> aiohttp.ClientSession:
    return aiohttp.ClientSession(
        headers=HEADERS,
        timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
        connector=aiohttp.TCPConnector(limit=10, limit_per_host=5, ssl=False),
    )


async def fetch(session: aiohttp.ClientSession, url: str) -> str:
    logger.info("FETCH %s", url)
    try:
        async with session.get(url, allow_redirects=True) as response:
            if response.status != 200:
                raise ScraperError(f"HTTP {response.status}: {url}")
            return await response.text(errors="ignore")
    except asyncio.TimeoutError as exc:
        raise ScraperError(f"Timeout: {url}") from exc
    except aiohttp.ClientError as exc:
        raise ScraperError(f"Request failed: {url} -> {exc}") from exc


async def fetch_cached(session: aiohttp.ClientSession, url: str, ttl: int = CACHE_TTL) -> str:
    path = cache_path(url)
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if time.time() - data.get("timestamp", 0) <= data.get("ttl", ttl):
                return data.get("html", "")
        except Exception:
            pass
    html = await fetch(session, url)
    try:
        path.write_text(json.dumps({"timestamp": time.time(), "ttl": ttl, "html": html}, ensure_ascii=False), encoding="utf-8")
    except Exception as exc:
        logger.warning("Cache write failed: %s", exc)
    return html


# ---------------------------------------------------------------------------
# Structured page selection. This is the important fix: never parse the
# complete webpage for anime data. Prefer article/entry-content/main and only
# fall back to a narrow content block.
# ---------------------------------------------------------------------------
def main_content(soup: BeautifulSoup) -> Tag:
    selectors = [
        "article .entry-content",
        "article .post-content",
        "article .content",
        ".entry-content",
        ".post-content",
        ".post-inner",
        "main article",
        "article",
        "main",
    ]
    for selector in selectors:
        node = soup.select_one(selector)
        if node and len(clean_text(node.get_text(" ", strip=True))) >= 80:
            return node
    return soup.body or soup


def page_title(soup: BeautifulSoup, content: Optional[Tag] = None) -> str:
    if content:
        h1 = content.find("h1")
        if h1:
            return clean_text(h1.get_text(" ", strip=True))
    h1 = soup.find("h1")
    if h1:
        return clean_text(h1.get_text(" ", strip=True))
    if soup.title:
        title = clean_text(soup.title.get_text(" ", strip=True))
        title = re.split(r"\s*[|–-]\s*(?:Rare|RareAnimes|Hindi|Dub).*", title, maxsplit=1, flags=re.I)[0]
        return clean_text(title)
    return ""


def remove_noise_nodes(node: Tag) -> None:
    
    for bad in node.select("script,style,noscript,nav,header,footer,aside,.sidebar,.comments,.comment,.related-posts,.recommended,.recommendations"):
        bad.decompose()


def info_text(content: Tag) -> str:
    # Keep the structured information area when the page has one.
    marker = content.find(string=re.compile(r"Anime\s+Series\s+Info", re.I))
    if marker:
        parent = marker.parent
        for _ in range(4):
            if not parent:
                break
            text = clean_text(parent.get_text(" ", strip=True))
            if 100 <= len(text) <= 5000:
                return text
            parent = parent.parent
    return clean_text(content.get_text(" ", strip=True))


def labeled_value(text: str, label: str) -> Optional[str]:
    labels = r"Full Name|Season|Episodes|Release Year|RunTime|Genre|Language|Network|Platform|Status|Synopsis|Quality"
    pattern = re.compile(rf"\b{re.escape(label)}\s*:\s*(.+?)(?=\s+(?:{labels})\s*:|$)", re.I)
    match = pattern.search(text)
    return clean_text(match.group(1)) if match else None


def extract_poster(soup: BeautifulSoup, content: Tag) -> Optional[str]:
    nodes = list(content.find_all("img")) + list(soup.find_all("img"))
    seen = set()
    for img in nodes:
        src = img.get("data-src") or img.get("data-lazy-src") or img.get("src")
        if not src:
            continue
        src = urljoin(BASE_URL, src)
        if src in seen:
            continue
        seen.add(src)
        alt = clean_text(img.get("alt") or img.get("title"))
        if any(x in alt.lower() for x in ("poster", "anime", "season")):
            return src
    return next(iter(seen), None)


def parse_languages(value: Optional[str]) -> list[str]:
    if not value:
        return []
    found = []
    for lang in LANGUAGES:
        if re.search(rf"\b{re.escape(lang)}\b", value, re.I):
            found.append(lang)
    return unique(found)


def parse_platforms(text: str) -> list[str]:
    found: list[str] = []
    patterns = [
        r"\b(?:Network|Platform)\s*:\s*([^|]+?)(?=\s+(?:Year|Language|Genre|Quality|Synopsis|Status)\s*:|$)",
        r"\btelecasted\s+by\s+([^.!]+)",
        r"\bstream(?:ed)?\s+on\s+([^.!]+)",
        r"\bavailable\s+on\s+([^.!]+)",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.I):
            raw = clean_text(match.group(1))
            raw = re.sub(r"\s+(?:and|or)\s+", ",", raw, flags=re.I)
            found.extend(x.strip(" -–—") for x in re.split(r"[,|•;/]+", raw) if x.strip())
    # Never expose generic/irrelevant values as a platform.
    bad = {"unknown", "other websites", "website", "online", "n/a", "na", "-"}
    return [x for x in unique(found) if x.casefold() not in bad]


def parse_dub_by(text: str) -> Optional[str]:
    for pattern in (
        r"\b(?:Hindi\s+)?dubbed?\s+by\s+([^.!|]+)",
        r"\bHindi\s+Dub\s+By\s*:\s*([^|]+)",
    ):
        match = re.search(pattern, text, re.I)
        if match:
            value = clean_text(match.group(1))
            if len(value) <= 80:
                return value
    return None


def hindi_from_text(text: str) -> bool:
    return bool(re.search(r"\bHindi\s*(?:Dub|Dubbed|Sub|Audio)?\b", text, re.I))


def parse_season_number(value: Optional[str], title: str = "") -> Optional[int]:
    number = first_int(value)
    if number is not None:
        return number
    match = re.search(r"\bSeason\s*[-#:]?\s*(\d{1,3})\b", title, re.I)
    return int(match.group(1)) if match else None


def parse_total_episodes(info: str) -> Optional[int]:
    raw = labeled_value(info, "Episodes")
    # IMPORTANT: use the first integer. Pages can say "25 (220 total)".
    return first_int(raw)


def parse_status(text: str, total: Optional[int], last: Optional[int]) -> str:
    if re.search(r"\b(?:completed|complete|season\s+finale|series\s+finale|final\s+episode)\b", text, re.I):
        return "completed"
    if re.search(r"\b(?:ongoing|next\s+episode|expected\s+release|new\s+episode\s+every|airs?)\b", text, re.I):
        return "ongoing"
    if total and last and last >= total:
        return "completed"
    if last:
        return "ongoing"
    return "unknown"


def parse_schedule(text: str) -> Optional[str]:
    patterns = (
        r"New\s+Episode\s+Every\s+([A-Za-z]+)",
        r"1\s+New\s+Episode\s+Every\s+([A-Za-z]+)",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            return f"Every {match.group(1)}"
    return "Every Week" if re.search(r"New\s+Episode\s+Every\s+Week", text, re.I) else None


def parse_date(text: str) -> Optional[str]:
    patterns = (
        r"\b\d{1,2}\s+[A-Za-z]+\s+\d{4}\b",
        r"\b[A-Za-z]+\s+\d{1,2},\s+\d{4}\b",
        r"\b\d{1,2}[/-]\d{1,2}[/-]\d{4}\b",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(0)
    return None


# ---------------------------------------------------------------------------
# Episode extraction. We deliberately inspect small content blocks instead of
# using the complete page text, so comments/recommended posts do not become
# fake episodes.
# ---------------------------------------------------------------------------
def episode_number(text: str) -> Optional[int]:
    for pattern in (
        r"\bEpisode\s*[-:#]?\s*(\d{1,4})\b",
        r"\bEp\.?\s*[-:#]?\s*(\d{1,4})\b",
    ):
        match = re.search(pattern, text, re.I)
        if match:
            return int(match.group(1))
    return None


def episode_title(text: str, number: int) -> str:
    text = re.sub(rf"\bEpisode\s*[-:#]?\s*0*{number}\b", "", text, count=1, flags=re.I)
    text = re.sub(r"\b(?:Hindi|English|Japanese|Tamil|Telugu)\s+(?:DUB|SUB)\b", "", text, flags=re.I)
    text = re.sub(r"\b(?:Watch|Download|Stream|Quality|1080p|720p|480p)\b", "", text, flags=re.I)
    return clean_text(text).strip(" -–—:|")


def parse_episodes(content: Tag) -> list[Episode]:
    episodes: dict[int, Episode] = {}
    # Smallest useful containers first.
    nodes = content.select("li, h2, h3, h4, h5, p")
    if not nodes:
        nodes = content.find_all(["div", "article"])
    for node in nodes:
        text = clean_text(node.get_text(" ", strip=True))
        if not text or len(text) > 700:
            continue
        num = episode_number(text)
        if num is None:
            continue
        langs = parse_languages(text)
        title = episode_title(text, num)
        existing = episodes.get(num)
        if not existing:
            episodes[num] = Episode(number=num, title=title, languages=langs, release_date=parse_date(text))
        else:
            existing.languages = unique(existing.languages + langs)
            if len(title) > len(existing.title):
                existing.title = title
            existing.release_date = existing.release_date or parse_date(text)
    result = list(episodes.values())
    result.sort(key=lambda x: x.number)
    return result


def build_anime_info(html: str, url: str) -> AnimeInfo:
    soup = BeautifulSoup(html, "html.parser")
    content = main_content(soup)
    remove_noise_nodes(content)
    info = info_text(content)
    title = clean_text(labeled_value(info, "Full Name") or page_title(soup, content))
    season_raw = labeled_value(info, "Season")
    lang_raw = labeled_value(info, "Language")
    episodes_total = parse_total_episodes(info)
    episodes = parse_episodes(content)
    languages = unique(parse_languages(lang_raw) + [x for ep in episodes for x in ep.languages])
    hindi_count = sum("Hindi" in ep.languages for ep in episodes)
    full_text = clean_text(content.get_text(" ", strip=True))
    hindi = hindi_from_text(info) or hindi_count > 0
    last_episode = max((ep.number for ep in episodes), default=None)
    status = parse_status(full_text, episodes_total, last_episode)
    available = {"Hindi": hindi_count} if hindi_count else {}
    # If the site's page explicitly says Hindi and is completed, its declared
    # season total is the authoritative Hindi count even when episode links are
    # not individually listed.
    if hindi and status == "completed" and episodes_total:
        available["Hindi"] = episodes_total
        hindi_count = episodes_total
    return AnimeInfo(
        title=title,
        canonical_title=title,
        poster_url=extract_poster(soup, content),
        source_url=url,
        source=SOURCE_NAME,
        hindi_available=hindi,
        platform=parse_platforms(info + " " + full_text),
        season=parse_season_number(season_raw, title),
        total_episodes=episodes_total,
        available_episodes=available,
        languages=languages,
        status=status,
        last_episode=last_episode,
        last_release=next((ep.release_date for ep in reversed(episodes) if ep.release_date), None),
        next_episode=(last_episode + 1 if status == "ongoing" and last_episode is not None else None),
        schedule=parse_schedule(full_text),
        dub_by=parse_dub_by(full_text),
        episodes=episodes,
    )


# ---------------------------------------------------------------------------
# Search result parsing. Only links inside actual result/article containers
# are accepted. Sidebar/footer/recommended links are ignored.
# ---------------------------------------------------------------------------
@dataclass
class Candidate:
    title: str
    url: str
    score: float


def result_links(soup: BeautifulSoup) -> list[Tag]:
    containers = soup.select("article, .post, .search-result, .result, .entry, .post-item")
    links: list[Tag] = []
    seen = set()
    for container in containers:
        for a in container.find_all("a", href=True):
            href = urljoin(BASE_URL, a.get("href", "").strip())
            if href not in seen:
                seen.add(href)
                links.append(a)
    # Fallback for themes without article wrappers: only main/search content.
    if not links:
        root = soup.select_one("main, #content, .content, .site-main") or soup
        for a in root.find_all("a", href=True):
            href = urljoin(BASE_URL, a.get("href", "").strip())
            if href not in seen:
                seen.add(href)
                links.append(a)
    return links


def parse_search_results(html: str, query: str) -> list[Candidate]:
    soup = BeautifulSoup(html, "html.parser")
    candidates = []
    seen = set()
    for a in result_links(soup):
        href = urljoin(BASE_URL, a.get("href", "").strip())
        if not is_same_host(href) or href in seen or BAD_PATH_RE.search(urlparse(href).path):
            continue
        text = clean_text(a.get_text(" ", strip=True))
        if not text:
            text = urlparse(href).path.rstrip("/").split("/")[-1].replace("-", " ")
        if len(text) < 3 or is_movie_or_special(text, href):
            continue
        seen.add(href)
        slug = urlparse(href).path.rstrip("/").split("/")[-1].replace("-", " ")
        score = max(title_score(query, text), title_score(query, slug))
        candidates.append(Candidate(text, href, score))
    candidates.sort(key=lambda x: x.score, reverse=True)
    return candidates


async def search_candidates(session: aiohttp.ClientSession, query: str, pages: int = 4) -> list[Candidate]:
    """Search the source for ANY anime, not only hard-coded franchises.

    The franchise table is used only when the user searches a known family name.
    Every other query follows this generic search path, so new/unknown anime are
    still discovered normally. Multiple WordPress pagination styles are tried.
    """
    all_candidates: list[Candidate] = []
    term = ALIASES.get(normalize_title(query), query.strip())

    urls = [SEARCH_URL.format(query=quote_plus(term))]
    for page in range(2, pages + 1):
        urls.append(f"{BASE_URL}/page/{page}/?s={quote_plus(term)}")
        urls.append(SEARCH_URL.format(query=quote_plus(term)) + f"&paged={page}")

    seen_urls = set()
    for url in urls:
        if url in seen_urls:
            continue
        seen_urls.add(url)
        try:
            html = await fetch_cached(session, url)
            all_candidates.extend(parse_search_results(html, term))
        except Exception as exc:
            logger.warning("Search failed for %s: %s", url, exc)

    best: dict[str, Candidate] = {}
    for c in all_candidates:
        if c.url not in best or c.score > best[c.url].score:
            best[c.url] = c
    return sorted(best.values(), key=lambda x: x.score, reverse=True)


# ---------------------------------------------------------------------------
# Franchise detection and series grouping
# ---------------------------------------------------------------------------
def franchise_key(query: str) -> Optional[str]:
    norm = normalize_title(query)
    for key in FRANCHISE_FAMILIES:
        if norm == normalize_title(key):
            return key
    return None


def is_exact_series_query(query: str) -> bool:
    norm = normalize_title(query)
        for names in FRANCHISE_FAMILIES.values():
        if any(norm == normalize_title(name) for name in names):
            return True
    return False


def family_title_from_anime(anime: AnimeInfo, fallback: str) -> str:
    title = anime.canonical_title or anime.title or fallback
    title = re.sub(r"\s+Season\s+\d+\b", "", title, flags=re.I)
    return clean_text(title)


def series_from_anime(anime: AnimeInfo, fallback: str) -> SeriesInfo:
    return SeriesInfo(
        title=family_title_from_anime(anime, fallback),
        url=anime.source_url or "",
        poster_url=anime.poster_url,
        total_episodes=anime.total_episodes,
        hindi_available=anime.hindi_available,
        hindi_episodes=anime.available_episodes.get("Hindi"),
        platform=anime.platform,
        languages=anime.languages,
        status=anime.status,
    )


def merge_series_seasons(pages: list[AnimeInfo], title: str) -> SeriesInfo:
    pages = sorted(pages, key=lambda x: (x.season is None, x.season or 999, x.source_url or ""))
    first = pages[0]
    seasons = []
    total = 0
    hindi_total = 0
    platforms, languages = [], []
    status = "completed"
    for anime in pages:
        seasons.append(SeasonInfo(
            season=anime.season,
            title=anime.canonical_title or anime.title,
            url=anime.source_url or "",
            episodes=anime.total_episodes,
            hindi_available=anime.hindi_available,
            hindi_episodes=anime.available_episodes.get("Hindi"),
            platform=anime.platform,
            languages=anime.languages,
            status=anime.status,
        ))
        if anime.total_episodes:
            total += anime.total_episodes
        if anime.available_episodes.get("Hindi"):
            hindi_total += anime.available_episodes["Hindi"]
        platforms.extend(anime.platform)
        languages.extend(anime.languages)
        if anime.status == "ongoing":
            status = "ongoing"
        elif anime.status != "completed":
            status = "unknown" if status == "completed" else status
    if not seasons:
        status = "unknown"
    return SeriesInfo(
        title=title,
        url=first.source_url or "",
        poster_url=first.poster_url,
        total_episodes=total or None,
        hindi_available=any(x.hindi_available for x in pages),
        hindi_episodes=hindi_total or None,
        platform=unique(platforms),
        languages=unique(languages),
        status=status,
        seasons=seasons,
    )


# ---------------------------------------------------------------------------
# Main scraper
# ---------------------------------------------------------------------------
class AnimeScraper:
    def __init__(self, source: str = SOURCE_NAME):
        self.source = source
        self.session: Optional[aiohttp.ClientSession] = None

    async def __aenter__(self):
        self.session = await create_session()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if self.session:
            await self.session.close()

    async def scrape_url(self, url: str) -> AnimeInfo:
        if not self.session:
            raise RuntimeError("Use AnimeScraper with async context")
        html = await fetch_cached(self.session, url)
        anime = build_anime_info(html, url)
        anime.source = self.source
        if anime.status == "completed":
            try:
                cache_path(url).write_text(
                    json.dumps({"timestamp": time.time(), "ttl": COMPLETED_CACHE_TTL, "html": html}, ensure_ascii=False),
                    encoding="utf-8",
                )
            except Exception:
                pass
        return anime

    async def _scrape_many(self, candidates: list[Candidate], limit: int = 20) -> list[AnimeInfo]:
        sem = asyncio.Semaphore(5)
        async def one(candidate: Candidate):
            async with sem:
                try:
                    return await self.scrape_url(candidate.url)
                except Exception as exc:
                    logger.warning("Page failed %s: %s", candidate.url, exc)
                    return None
        values = await asyncio.gather(*(one(c) for c in candidates[:limit]))
        return [x for x in values if x is not None]

    async def scrape_franchise(self, query: str, family_key: str) -> FranchiseInfo:
        candidates = await search_candidates(self.session, query, pages=4)
        family_names = FRANCHISE_FAMILIES[family_key]
        selected: list[Candidate] = []
        for candidate in candidates:
            score = max(title_score(name, candidate.title) for name in family_names)
            if score >= 70:
                selected.append(candidate)
        # If search missed one family member, search it directly.
        existing_norm = {normalize_title(c.title) for c in selected}
        for name in family_names:
            if normalize_title(name) in existing_norm:
                continue
            more = await search_candidates(self.session, name, pages=2)
            selected.extend([c for c in more if title_score(name, c.title) >= 65][:3])
        # Deduplicate URLs and exclude movies/specials.
        unique_candidates: dict[str, Candidate] = {}
        for c in selected:
            if is_movie_or_special(c.title, c.url):
                continue
            old = unique_candidates.get(c.url)
            if old is None or c.score > old.score:
                unique_candidates[c.url] = c
        pages = await self._scrape_many(list(unique_candidates.values()), limit=30)

        grouped: dict[str, list[AnimeInfo]] = {}
        for anime in pages:
            title = family_title_from_anime(anime, "")
            best_name = max(family_names, key=lambda n: title_score(n, title)) if title else ""
            if best_name and title_score(best_name, title) >= 65:
                grouped.setdefault(normalize_title(best_name), []).append(anime)

        series: list[SeriesInfo] = []
        for name in family_names:
            items = grouped.get(normalize_title(name), [])
            if not items:
                continue
            # Franchise mode groups season pages into ONE series.
            series.append(merge_series_seasons(items, name))

        if not series:
            raise AnimeNotFound(f"No franchise series found for: {query}")
        poster = next((s.poster_url for s in series if s.poster_url), None)
        return FranchiseInfo(
            title=query.strip(),
            poster_url=poster,
            source=self.source,
            series=series,
            hindi_available=any(s.hindi_available for s in series),
            scraped_at=time.time(),
        )

    async def scrape_series(self, query: str) -> AnimeInfo:
        # Generic path for every anime that is NOT a known franchise query.
        # This is deliberately independent of FRANCHISE_FAMILIES.
        candidates = await search_candidates(self.session, query, pages=4)
        good = [c for c in candidates if c.score >= 65 and not is_movie_or_special(c.title, c.url)]

        # A second, broader pass prevents valid anime with unusual source titles
        # from being rejected just because the search title score is low.
        if not good:
            broader = await search_candidates(self.session, query, pages=6)
            good = [c for c in broader if not is_movie_or_special(c.title, c.url)][:25]

        if not good:
            raise AnimeNotFound(f"No anime found for: {query}")
        # Scrape candidates because a specific series may have separate season pages.
        pages = await self._scrape_many(good[:25], limit=25)
        wanted = [p for p in pages if title_score(query, family_title_from_anime(p, "")) >= 65 or title_score(query, p.title) >= 70]
        if not wanted:
            wanted = pages[:1]
        if len(wanted) == 1:
            return wanted[0]
        merged = merge_series_seasons(wanted, ALIASES.get(normalize_title(query), query.strip()))
        base = wanted[0]
        return AnimeInfo(
            title=merged.title,
            canonical_title=merged.title,
            poster_url=merged.poster_url,
            source_url=base.source_url,
            source=self.source,
            hindi_available=merged.hindi_available,
            platform=merged.platform,
            total_episodes=merged.total_episodes,
            available_episodes={"Hindi": merged.hindi_episodes} if merged.hindi_episodes else {},
            languages=merged.languages,
            status=merged.status,
            seasons=merged.seasons,
            last_episode=max((p.last_episode or 0 for p in wanted), default=0) or None,
            next_episode=(max((p.last_episode or 0 for p in wanted), default=0) + 1 if merged.status == "ongoing" else None),
            schedule=next((p.schedule for p in wanted if p.schedule), None),
            last_release=next((p.last_release for p in reversed(wanted) if p.last_release), None),
            dub_by=next((p.dub_by for p in wanted if p.dub_by), None),
            episodes=[ep for p in wanted for ep in p.episodes],
        )

    async def scrape(self, query: str) -> ScrapeResult:
        if not self.session:
            raise RuntimeError("Use AnimeScraper with async context")
        query = clean_text(query)
        if not query:
            raise AnimeNotFound("Anime name is empty")
        family = franchise_key(query)
        if family:
            return await self.scrape_franchise(query, family)
        return await self.scrape_series(query)


# ---------------------------------------------------------------------------
# Formatting. No quality and no poster URL are printed.
# ---------------------------------------------------------------------------
def platform_text(values: list[str]) -> str:
    return " • ".join(unique(values)) if values else "—"


def language_text(values: list[str]) -> str:
    return " • ".join(unique(values)) if values else "—"


def status_text(status: str) -> str:
    return {"completed": "✅ Completed", "ongoing": "🔄 Ongoing"}.get(status, "⚪ Unknown")


def format_episode_total(total: Optional[int], hindi: Optional[int]) -> str:
    if total is None:
        return str(hindi) if hindi else "Unknown"
    if hindi is not None and hindi >= total:
        return str(total)
    if hindi:
        return f"{hindi} / {total}"
    return str(total)


def format_series_info(series: SeriesInfo, number: int) -> list[str]:
    lines = [
        f"   {number:02d}. {series.title}",
        f"       🎞 Episodes: {format_episode_total(series.total_episodes, series.hindi_episodes)}",
        f"       🇮🇳 Hindi Dub: {'✅ Available' if series.hindi_available else '❌ Not Available'}",
        f"       📺 Platform: {platform_text(series.platform)}",
    ]
    return lines


def format_franchise_info(franchise: FranchiseInfo) -> str:
    lines = [f"🎬 Anime: {franchise.title}", "", "📀 Series:", ""]
    for i, series in enumerate(franchise.series, 1):
        lines.extend(format_series_info(series, i))
        if i != len(franchise.series):
            lines.append("")
    lines += ["", f"📊 Overall Hindi Dub: {'✅ Available' if franchise.hindi_available else '❌ Not Available'}", "", f"🔎 Source: {franchise.source}"]
    return "\n".join(lines)


def format_anime_info(anime: AnimeInfo) -> str:
    if isinstance(anime, FranchiseInfo):
        return format_franchise_info(anime)

    lines = [f"🎬 Anime: {anime.canonical_title or anime.title}"]
    if anime.seasons:
        lines += ["", "📀 Seasons:"]
        for season in anime.seasons:
            label = f"Season {season.season:02d}" if season.season is not None else season.title
            lines.append(f"   {label} — {season.episodes or 'Unknown'} Episodes")
    lines += [
        "",
        f"🇮🇳 Hindi Dub: {'✅ Available' if anime.hindi_available else '❌ Not Available'}",
        f"📺 Platform: {platform_text(anime.platform)}",
        f"🎞 Episodes: {format_episode_total(anime.total_episodes, anime.available_episodes.get('Hindi'))}",
        f"🌐 Languages: {language_text(anime.languages)}",
        f"📊 Status: {status_text(anime.status)}",
    ]
    if anime.status == "ongoing":
        if anime.last_episode is not None:
            lines.append(f"📅 Last Episode: Episode {anime.last_episode}")
        if anime.next_episode is not None:
            lines.append(f"⏭ Next Episode: Episode {anime.next_episode}")
        if anime.expected_release:
            lines.append(f"📅 Expected Release: {anime.expected_release}")
        if anime.schedule:
            lines.append(f"⏰ Schedule: {anime.schedule}")
    lines += ["", f"🔎 Source: {anime.source}"]
    return "\n".join(lines)


def format_result(result: ScrapeResult) -> str:
    if isinstance(result, FranchiseInfo):
        return format_franchise_info(result)
    return format_anime_info(result)


def anime_to_json(result: ScrapeResult) -> str:
    return json.dumps(asdict(result), ensure_ascii=False, indent=2)


async def get_anime_info(query: str) -> ScrapeResult:
    async with AnimeScraper(source=SOURCE_NAME) as scraper:
        return await scraper.scrape(query)


async def main() -> None:
    import sys
    if len(sys.argv) < 2:
        print('Usage: python anime_scraper.py "Dragon Ball"')
        return
    query = " ".join(sys.argv[1:])
    try:
        async with AnimeScraper() as scraper:
            result = await scraper.scrape(query)
        print(format_result(result))
    except (AnimeNotFound, ScraperError) as exc:
        print(f"❌ {exc}")
    except Exception as exc:
        logger.exception("Unexpected error")
        print(f"❌ Unexpected error: {exc}")


if __name__ == "__main__":
    asyncio.run(main())
        
