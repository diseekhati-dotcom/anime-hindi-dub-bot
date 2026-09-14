"""
anime_scraper.py
Standalone anime information scraper/service.

Sources:
- RareAnimes
- Anime Mirchi
- Jikan (MyAnimeList metadata fallback)

Install:
    pip install requests beautifulsoup4 lxml

Basic use:
    from anime_scraper import AnimeScraper

    scraper = AnimeScraper()
    info = scraper.scrape("Naruto")
    print(scraper.format_result(info))

The scraper is synchronous so it can be used directly from a normal
python-telegram-bot application.
"""

from __future__ import annotations

import re
import time
import logging
from dataclasses import dataclass, field
from datetime import datetime, date
from difflib import SequenceMatcher
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import quote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

RARE_BASE = "https://www.rareanimes.mov/"
MIRCHI_BASE = "https://animemirchi.com/"
JIKAN_BASE = "https://api.jikan.moe/v4/"

REQUEST_TIMEOUT = 20
JIKAN_TIMEOUT = 15

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("anime_scraper")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class SeasonInfo:
    season: str = ""
    episodes: Optional[int] = None
    released_episodes: Optional[int] = None
    status: str = ""
    languages: List[str] = field(default_factory=list)
    platforms: List[str] = field(default_factory=list)
    release_date: str = ""
    next_episode: str = ""
    url: str = ""


@dataclass
class AnimeInfo:
    title: str = ""
    canonical_title: str = ""
    aliases: List[str] = field(default_factory=list)

    poster: str = ""
    url: str = ""
    source: str = ""

    hindi_dub: Optional[bool] = None
    languages: List[str] = field(default_factory=list)
    platforms: List[str] = field(default_factory=list)
    dub_by: List[str] = field(default_factory=list)

    seasons: List[SeasonInfo] = field(default_factory=list)
    season: str = ""
    episodes: Optional[int] = None
    released_episodes: Optional[int] = None

    status: str = ""
    last_episode: Optional[int] = None
    last_release: str = ""
    next_episode: str = ""

    year: Optional[int] = None
    studio: str = ""
    genres: List[str] = field(default_factory=list)

    confidence: float = 0.0
    error: str = ""


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------

def clean_text(value: Any) -> str:
    if value is None:
        return ""
    value = re.sub(r"\s+", " ", str(value))
    return value.strip(" \t\r\n-–—|")


def normalize_title(value: str) -> str:
    value = clean_text(value).lower()
    value = re.sub(r"\[[^\]]*\]", " ", value)
    value = re.sub(r"\([^)]*\)", " ", value)
    value = value.replace("&", " and ")
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def title_tokens(value: str) -> set[str]:
    return set(normalize_title(value).split())


def title_similarity(a: str, b: str) -> float:
    na, nb = normalize_title(a), normalize_title(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    ratio = SequenceMatcher(None, na, nb).ratio()
    ta, tb = title_tokens(a), title_tokens(b)
    if ta and tb:
        overlap = len(ta & tb) / max(1, len(ta | tb))
    else:
        overlap = 0.0
    return max(ratio, overlap)


def unique_keep_order(items: Iterable[str]) -> List[str]:
    out: List[str] = []
    seen = set()
    for item in items:
        item = clean_text(item)
        key = item.lower()
        if item and key not in seen:
            seen.add(key)
            out.append(item)
    return out


def parse_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    m = re.search(r"\b(\d{1,5})\b", str(value))
    return int(m.group(1)) if m else None


def parse_year(text: str) -> Optional[int]:
    m = re.search(r"\b(19\d{2}|20\d{2}|21\d{2})\b", text or "")
    return int(m.group(1)) if m else None


def extract_episode(text: str) -> Optional[int]:
    patterns = [
        r"(?:episode|ep|e)\s*[:.#-]?\s*(\d{1,4})",
        r"\b(\d{1,4})\s*(?:episodes?|eps?)\b",
    ]
    for p in patterns:
        m = re.search(p, text or "", re.I)
        if m:
            return int(m.group(1))
    return None


def extract_total_episodes(text: str) -> Optional[int]:
    patterns = [
        r"(?:episodes?|eps?)\s*[:\-]?\s*(\d{1,4})",
        r"(?:total\s+episodes?)\s*[:\-]?\s*(\d{1,4})",
    ]
    for p in patterns:
        m = re.search(p, text or "", re.I)
        if m:
            return int(m.group(1))
    return None


def parse_date_text(text: str) -> str:
    if not text:
        return ""

    patterns = [
        r"\b\d{1,2}\s+(?:January|February|March|April|May|June|July|August|"
        r"September|October|November|December)\s+\d{4}\b",
        r"\b(?:January|February|March|April|May|June|July|August|September|"
        r"October|November|December)\s+\d{1,2},\s+\d{4}\b",
        r"\b\d{1,2}[/-]\d{1,2}[/-]\d{4}\b",
    ]
    for p in patterns:
        m = re.search(p, text, re.I)
        if m:
            return m.group(0)
    return ""


def extract_time(text: str) -> str:
    if not text:
        return ""
    m = re.search(
        r"\b(\d{1,2}:\d{2})\s*(AM|PM)\b|\b(\d{1,2})\s*(AM|PM)\b",
        text,
        re.I,
    )
    if not m:
        return ""
    if m.group(1):
        return f"{m.group(1)} {m.group(2).upper()}"
    return f"{m.group(3)} {m.group(4).upper()}"


# ---------------------------------------------------------------------------
# Language/platform detection
# ---------------------------------------------------------------------------

LANGUAGE_PATTERNS = [
    ("Hindi", r"\bhindi\b"),
    ("English", r"\benglish\b"),
    ("Tamil", r"\btamil\b"),
    ("Telugu", r"\btelugu\b"),
    ("Japanese", r"\bjapanese\b|\bsub\b"),
    ("Korean", r"\bkorean\b"),
    ("Chinese", r"\bchinese\b"),
    ("Malayalam", r"\bmalayalam\b"),
    ("Bengali", r"\bbengali\b"),
    ("Spanish", r"\bspanish\b"),
    ("French", r"\bfrench\b"),
    ("German", r"\bgerman\b"),
]

PLATFORM_PATTERNS = [
    ("Crunchyroll", r"\bcrunchyroll\b"),
    ("Sony YAY!", r"\bsony\s*yay!?"),
    ("Cartoon Network India", r"\bcartoon\s*network\s*india\b"),
    ("Cartoon Network", r"\bcartoon\s*network\b"),
    ("JioHotstar", r"\bjio\s*hotstar\b|\bhotstar\b"),
    ("Netflix", r"\bnetflix\b"),
    ("Prime Video", r"\bprime\s*video\b|\bamazon\s*prime\b"),
    ("Disney+", r"\bdisney\s*\+?\b"),
    ("JioCinema", r"\bjiocinema\b"),
    ("Muse India", r"\bmuse\s*india\b"),
    ("Ani-One", r"\bani[\s-]*one\b"),
    ("Anime Times", r"\banime\s*times\b"),
    ("YouTube", r"\byoutube\b"),
    ("MX Player", r"\bmx\s*player\b"),
    ("ZEE5", r"\bzee5\b"),
    ("Airtel Xstream", r"\bairtel\s*xstream\b"),
]

DUB_PATTERNS = [
    ("Crunchyroll", r"\bcrunchyroll\b"),
    ("Sony YAY!", r"\bsony\s*yay!?"),
    ("Ani-One", r"\bani[\s-]*one\b"),
    ("Anime Times", r"\banime\s*times\b"),
    ("Muse India", r"\bmuse\s*india\b"),
    ("Cartoon Network", r"\bcartoon\s*network\b"),
    ("JioHotstar", r"\bjio\s*hotstar\b"),
]


def detect_languages(text: str) -> List[str]:
    result = []
    for name, pattern in LANGUAGE_PATTERNS:
        if re.search(pattern, text or "", re.I):
            result.append(name)
    return result


def detect_platforms(text: str) -> List[str]:
    result = []
    for name, pattern in PLATFORM_PATTERNS:
        if re.search(pattern, text or "", re.I):
            result.append(name)
    return result


def detect_dub_by(text: str) -> List[str]:
    result = []
    for name, pattern in DUB_PATTERNS:
        if re.search(pattern, text or "", re.I):
            result.append(name)
    return result


def detect_hindi(text: str) -> Optional[bool]:
    if not text:
        return None
    if re.search(r"\bhindi\s*(?:dub|audio|dubbed|language)?\b", text, re.I):
        return True
    if re.search(r"\b(?:non[- ]?hindi|no\s+hindi)\b", text, re.I):
        return False
    return None


def detect_status(text: str, episodes: Optional[int] = None) -> str:
    low = (text or "").lower()
    if re.search(r"\bcompleted?\b|\bcomplete\b|\bended\b|\bfinished\b", low):
        return "Completed"
    if re.search(r"\bongoing\b|\bairing\b|\bcurrently airing\b|\bupcoming\b", low):
        return "Ongoing"
    if re.search(r"\bhiatus\b", low):
        return "Hiatus"
    return ""


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

class HTTPClient:
    def __init__(self, timeout: int = REQUEST_TIMEOUT):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(HEADERS)

    def get(self, url: str, **kwargs) -> Optional[requests.Response]:
        try:
            response = self.session.get(
                url,
                timeout=kwargs.pop("timeout", self.timeout),
                allow_redirects=True,
                **kwargs,
            )
            if response.status_code >= 400:
                logger.warning("HTTP %s: %s", response.status_code, url)
                return None
            return response
        except requests.RequestException as exc:
            logger.warning("Request failed: %s (%s)", url, exc)
            return None

    def text(self, url: str) -> str:
        response = self.get(url)
        return response.text if response else ""


# ---------------------------------------------------------------------------
# Search result extraction
# ---------------------------------------------------------------------------

def is_probable_anime_link(url: str, anchor_text: str = "") -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return False
    if any(x in url.lower() for x in [
        "/category/", "/tag/", "/author/", "/page/", "/feed",
        "javascript:", "#", "/wp-admin/",
    ]):
        return False
    text = normalize_title(anchor_text)
    return bool(text) or len(parsed.path.strip("/")) > 2


def collect_links(soup: BeautifulSoup, base_url: str) -> List[Tuple[str, str]]:
    results = []
    for a in soup.find_all("a", href=True):
        href = urljoin(base_url, a.get("href", ""))
        text = clean_text(a.get_text(" ", strip=True))
        if is_probable_anime_link(href, text):
            results.append((href, text))
    seen = set()
    out = []
    for url, text in results:
        if url in seen:
            continue
        seen.add(url)
        out.append((url, text))
    return out


# ---------------------------------------------------------------------------
# RareAnimes source
# ---------------------------------------------------------------------------

class RareAnimesSource:
    name = "RareAnimes"

    def __init__(self, client: HTTPClient):
        self.client = client

    def search(self, query: str, limit: int = 12) -> List[Tuple[str, str]]:
        q = quote(query.strip())
        urls = [
            urljoin(RARE_BASE, f"?s={q}"),
            urljoin(RARE_BASE, f"search/{q}/"),
        ]

        found: List[Tuple[str, str]] = []
        for search_url in urls:
            html = self.client.text(search_url)
            if not html:
                continue
            soup = BeautifulSoup(html, "lxml")
            for url, text in collect_links(soup, search_url):
                # Search results should contain the query in either title or URL.
                score = title_similarity(query, text or url.split("/")[-1])
                if score >= 0.30:
                    found.append((url, text))
            if found:
                break

        # Deduplicate and rank.
        unique = {}
        for url, text in found:
            unique[url] = text
        ranked = sorted(
            unique.items(),
            key=lambda item: title_similarity(query, item[1] or item[0]),
            reverse=True,
        )
        return ranked[:limit]

    def parse_page(self, url: str, query: str = "") -> Optional[AnimeInfo]:
        html = self.client.text(url)
        if not html:
            return None

        soup = BeautifulSoup(html, "lxml")
        full_text = clean_text(soup.get_text(" ", strip=True))

        # Title: prefer h1, then document title.
        title = ""
        h1 = soup.find("h1")
        if h1:
            title = clean_text(h1.get_text(" ", strip=True))
        if not title and soup.title:
            title = clean_text(soup.title.get_text(" ", strip=True))
        title = re.sub(r"\s*[-|–—]\s*(Rare\s*Animes?|RareToon).*$", "", title, flags=re.I)
        title = clean_text(title)

        info = AnimeInfo(
            title=title,
            canonical_title=title,
            url=url,
            source=self.name,
            confidence=title_similarity(query, title) if query else 0.5,
        )

        # Poster.
        poster_candidates = []
        for img in soup.find_all("img"):
            for attr in ("src", "data-src", "data-lazy-src", "data-original"):
                value = img.get(attr)
                if value:
                    poster_candidates.append(urljoin(url, value))
        for value in poster_candidates:
            low = value.lower()
            if not any(x in low for x in ("logo", "avatar", "icon", "emoji")):
                info.poster = value
                break

        # Meta description / OpenGraph can contain useful structured info.
        meta_values = []
        for meta in soup.find_all("meta"):
            value = meta.get("content")
            if value:
                meta_values.append(clean_text(value))
        metadata_text = " ".join(meta_values)

        combined = f"{full_text} {metadata_text}"

        # Key/value extraction.
        labels = {
            "season": [r"season\s*[:\-]?\s*([a-z0-9][a-z0-9 ._-]{0,30})"],
            "episodes": [
                r"(?:episodes?|total\s+episodes?)\s*[:\-]?\s*(\d{1,4})",
                r"episodes?\s+(\d{1,4})",
            ],
            "release_year": [r"release\s*year\s*[:\-]?\s*(\d{4})"],
            "studio": [r"studio\s*[:\-]?\s*([^|•\n]{2,80})"],
            "runtime": [r"runtime\s*[:\-]?\s*([^|•\n]{2,40})"],
        }

        season = ""
        for pattern in labels["season"]:
            m = re.search(pattern, combined, re.I)
            if m:
                season = clean_text(m.group(1))
                break
        if season:
            info.season = season

        episodes = None
        for pattern in labels["episodes"]:
            m = re.search(pattern, combined, re.I)
            if m:
                episodes = int(m.group(1))
                break
        info.episodes = episodes

        year = parse_year(
            " ".join(
                x for x in [
                    combined[:5000],
                    re.search(r"release\s*year.{0,20}", combined, re.I).group(0)
                    if re.search(r"release\s*year.{0,20}", combined, re.I)
                    else "",
                ]
            )
        )
        info.year = year

        # Studio.
        for pattern in labels["studio"]:
            m = re.search(pattern, combined, re.I)
            if m:
                value = clean_text(m.group(1))
                if value and value.lower() not in {"pierrot", "toei"}:
                    info.studio = value
                else:
                    info.studio = value
                break

        info.languages = unique_keep_order(detect_languages(combined))
        info.platforms = unique_keep_order(detect_platforms(combined))
        info.dub_by = unique_keep_order(detect_dub_by(combined))
        info.hindi_dub = detect_hindi(combined)
        info.status = detect_status(combined, episodes)

        release = parse_date_text(combined)
        info.last_release = release

        # Next episode.
        next_patterns = [
            r"next\s+episode.{0,100}",
            r"upcoming\s+episode.{0,100}",
        ]
        for p in next_patterns:
            m = re.search(p, combined, re.I)
            if m:
                info.next_episode = clean_text(m.group(0))[:180]
                break

        # Look for season tables/blocks.
        info.seasons = self._extract_seasons(soup, url, combined, info)
        if info.seasons:
            if not info.season:
                info.season = info.seasons[0].season
            if info.episodes is None:
                info.episodes = info.seasons[0].episodes

        # Avoid accepting a page whose title is clearly unrelated.
        if query and title_similarity(query, title) < 0.28:
            return None

        return info

    def _extract_seasons(
        self,
        soup: BeautifulSoup,
        page_url: str,
        text: str,
        parent: AnimeInfo,
    ) -> List[SeasonInfo]:
        seasons: List[SeasonInfo] = []

        # Tables are the safest structured source.
        for table in soup.find_all("table"):
            rows = table.find_all("tr")
            for row in rows:
                cells = [clean_text(c.get_text(" ", strip=True)) for c in row.find_all(["th", "td"])]
                if not cells:
                    continue
                row_text = " | ".join(cells)
                sm = re.search(r"\bseason\s*([0-9]{1,2}|[ivx]{1,4})\b", row_text, re.I)
                if not sm:
                    continue
                ep = extract_total_episodes(row_text)
                if ep is None:
                    nums = re.findall(r"\b(\d{1,4})\b", row_text)
                    ep = int(nums[-1]) if nums else None
                season_name = f"Season {sm.group(1)}"
                seasons.append(
                    SeasonInfo(
                        season=season_name,
                        episodes=ep,
                        released_episodes=ep,
                        status=detect_status(row_text),
                        languages=detect_languages(row_text),
                        platforms=detect_platforms(row_text),
                        release_date=parse_date_text(row_text),
                        next_episode=extract_time(row_text),
                        url=page_url,
                    )
                )

        # Generic headings.
        for tag in soup.find_all(["h2", "h3", "h4", "strong"]):
            t = clean_text(tag.get_text(" ", strip=True))
            m = re.search(r"\bseason\s*([0-9]{1,2})\b", t, re.I)
            if not m:
                continue
            parent_text = clean_text(
                " ".join(
                    clean_text(x.get_text(" ", strip=True))
                    for x in tag.parent.find_all(["p", "li", "span", "div"], limit=8)
                )
            )
            ep = extract_total_episodes(parent_text)
            if ep is not None:
                seasons.append(
                    SeasonInfo(
                        season=f"Season {m.group(1)}",
                        episodes=ep,
                        released_episodes=ep,
                        status=detect_status(parent_text),
                        languages=detect_languages(parent_text),
                        platforms=detect_platforms(parent_text),
                        release_date=parse_date_text(parent_text),
                        url=page_url,
                    )
                )

        # Deduplicate seasons.
        result = []
        seen = set()
        for s in seasons:
            key = (s.season.lower(), s.episodes)
            if key not in seen:
                seen.add(key)
                result.append(s)
        return result


# ---------------------------------------------------------------------------
# Anime Mirchi source
# ---------------------------------------------------------------------------

class AnimeMirchiSource:
    name = "Anime Mirchi"

    def __init__(self, client: HTTPClient):
        self.client = client

    def search(self, query: str, limit: int = 12) -> List[Tuple[str, str]]:
        q = quote(query.strip())
        search_urls = [
            urljoin(MIRCHI_BASE, f"?s={q}"),
            urljoin(MIRCHI_BASE, f"search/{q}/"),
        ]
        found = []
        for search_url in search_urls:
            html = self.client.text(search_url)
            if not html:
                continue
            soup = BeautifulSoup(html, "lxml")
            for url, text in collect_links(soup, search_url):
                score = title_similarity(query, text or url)
                if score >= 0.28:
                    found.append((url, text))
            if found:
                break

        unique = {}
        for u, t in found:
            unique[u] = t
        ranked = sorted(
            unique.items(),
            key=lambda item: title_similarity(query, item[1] or item[0]),
            reverse=True,
        )
        return ranked[:limit]

    def parse_page(self, url: str, query: str = "") -> Optional[AnimeInfo]:
        html = self.client.text(url)
        if not html:
            return None
        soup = BeautifulSoup(html, "lxml")
        text = clean_text(soup.get_text(" ", strip=True))

        title = ""
        h1 = soup.find("h1")
        if h1:
            title = clean_text(h1.get_text(" ", strip=True))
        if not title and soup.title:
            title = clean_text(soup.title.get_text(" ", strip=True))
        title = re.sub(r"\s*[-|–—]\s*Anime\s*Mirchi.*$", "", title, flags=re.I)
        title = clean_text(title)

        info = AnimeInfo(
            title=title,
            canonical_title=title,
            url=url,
            source=self.name,
            confidence=title_similarity(query, title) if query else 0.5,
        )

        # Poster.
        for img in soup.find_all("img"):
            values = [
                img.get("src"),
                img.get("data-src"),
                img.get("data-lazy-src"),
                img.get("data-original"),
            ]
            for v in values:
                if v:
                    candidate = urljoin(url, v)
                    low = candidate.lower()
                    if not any(x in low for x in ("logo", "avatar", "icon")):
                        info.poster = candidate
                        break
            if info.poster:
                break

        # Tables contain a lot of Anime Mirchi schedule information.
        info.seasons = self._parse_tables(soup, url)

        combined = text
        info.languages = unique_keep_order(detect_languages(combined))
        info.platforms = unique_keep_order(detect_platforms(combined))
        info.dub_by = unique_keep_order(detect_dub_by(combined))
        info.hindi_dub = detect_hindi(combined)
        info.status = detect_status(combined)

        # Prefer numeric data from structured tables.
        if info.seasons:
            info.episodes = sum(
                s.episodes or 0 for s in info.seasons
            ) or None
            info.released_episodes = sum(
                s.released_episodes or 0 for s in info.seasons
            ) or None

            # Merge language/platform data from tables.
            for s in info.seasons:
                info.languages.extend(s.languages)
                info.platforms.extend(s.platforms)
                if s.status and not info.status:
                    info.status = s.status

        info.languages = unique_keep_order(info.languages)
        info.platforms = unique_keep_order(info.platforms)
        info.dub_by = unique_keep_order(info.dub_by)

        if info.episodes is None:
            info.episodes = extract_total_episodes(text)
        if info.year is None:
            info.year = parse_year(text)
        info.last_release = parse_date_text(text)
        info.next_episode = extract_time(text)

        if query and title_similarity(query, title) < 0.24:
            return None
        return info

    def _parse_tables(self, soup: BeautifulSoup, url: str) -> List[SeasonInfo]:
        seasons: List[SeasonInfo] = []

        for table in soup.find_all("table"):
            rows = table.find_all("tr")
            if len(rows) < 2:
                continue

            for row in rows[1:]:
                cells = [
                    clean_text(c.get_text(" ", strip=True))
                    for c in row.find_all(["th", "td"])
                ]
                if not cells:
                    continue
                row_text = " | ".join(cells)

                # Schedule rows may not have a season. Keep them as a
                # schedule-like season only when episode information exists.
                sm = re.search(r"\bseason\s*([0-9]{1,2})\b", row_text, re.I)
                ep = extract_total_episodes(row_text)
                released = None

                # Common "Episode 12 / 24" form.
                frac = re.search(r"\b(\d{1,4})\s*/\s*(\d{1,4})\b", row_text)
                if frac:
                    released = int(frac.group(1))
                    ep = int(frac.group(2))

                if ep is None and released is None:
                    continue

                season_name = f"Season {sm.group(1)}" if sm else ""
                seasons.append(
                    SeasonInfo(
                        season=season_name,
                        episodes=ep,
                        released_episodes=released or ep,
                        status=detect_status(row_text),
                        languages=detect_languages(row_text),
                        platforms=detect_platforms(row_text),
                        release_date=parse_date_text(row_text),
                        next_episode=extract_time(row_text),
                        url=url,
                    )
                )
        return seasons


# ---------------------------------------------------------------------------
# Jikan fallback
# ---------------------------------------------------------------------------

class JikanSource:
    name = "Jikan"

    def __init__(self, client: HTTPClient):
        self.client = client

    def search(self, query: str, limit: int = 5) -> List[AnimeInfo]:
        url = urljoin(JIKAN_BASE, "anime")
        response = self.client.get(
            url,
            params={"q": query, "limit": limit, "sfw": "true"},
            timeout=JIKAN_TIMEOUT,
        )
        if not response:
            return []

        try:
            data = response.json().get("data", [])
        except ValueError:
            return []

        results = []
        for item in data:
            title = clean_text(item.get("title") or item.get("title_english"))
            if not title:
                continue

            aired = item.get("aired") or {}
            from_date = clean_text(aired.get("from", ""))
            last_date = clean_text(aired.get("to", ""))

            status = clean_text(item.get("status", ""))
            if status.lower() == "finished airing":
                status = "Completed"
            elif status.lower() == "currently airing":
                status = "Ongoing"

            studios = item.get("studios") or []
            studio = clean_text(studios[0].get("name")) if studios else ""

            images = item.get("images") or {}
            jpg = images.get("jpg") or {}
            poster = clean_text(jpg.get("large_image_url") or jpg.get("image_url"))

            info = AnimeInfo(
                title=title,
                canonical_title=title,
                aliases=unique_keep_order(
                    [
                        clean_text(item.get("title_english")),
                        clean_text(item.get("title_japanese")),
                    ]
                ),
                poster=poster,
                source=self.name,
                episodes=item.get("episodes"),
                status=status,
                studio=studio,
                year=parse_year(from_date),
                genres=[
                    clean_text(g.get("name"))
                    for g in item.get("genres", [])
                    if clean_text(g.get("name"))
                ],
                confidence=title_similarity(query, title),
            )
            results.append(info)

        return sorted(results, key=lambda x: x.confidence, reverse=True)


# ---------------------------------------------------------------------------
# Validation / merging
# ---------------------------------------------------------------------------

def is_same_anime(query: str, info: AnimeInfo) -> bool:
    if not query or not info.title:
        return True

    score = max(
        title_similarity(query, info.title),
        *(title_similarity(query, a) for a in info.aliases),
    )

    # For very short queries, demand stronger matching.
    q = normalize_title(query)
    if len(q) <= 4:
        return score >= 0.60
    return score >= 0.35


def is_valid_episode_count(value: Optional[int]) -> bool:
    return value is not None and 1 <= value <= 2000


def merge_seasons(*groups: List[SeasonInfo]) -> List[SeasonInfo]:
    out: List[SeasonInfo] = []
    seen: Dict[Tuple[str, Optional[int]], SeasonInfo] = {}

    for group in groups:
        for s in group:
            key = (normalize_title(s.season), s.episodes)
            if not key[0]:
                continue

            if key not in seen:
                seen[key] = SeasonInfo(
                    season=s.season,
                    episodes=s.episodes,
                    released_episodes=s.released_episodes,
                    status=s.status,
                    languages=list(s.languages),
                    platforms=list(s.platforms),
                    release_date=s.release_date,
                    next_episode=s.next_episode,
                    url=s.url,
                )
            else:
                old = seen[key]
                old.languages = unique_keep_order(old.languages + s.languages)
                old.platforms = unique_keep_order(old.platforms + s.platforms)
                if s.released_episodes is not None:
                    old.released_episodes = max(
                        old.released_episodes or 0, s.released_episodes
                    )
                old.status = old.status or s.status
                old.release_date = old.release_date or s.release_date
                old.next_episode = old.next_episode or s.next_episode

    out.extend(seen.values())

    def season_num(s: SeasonInfo):
        m = re.search(r"(\d+)", s.season)
        return int(m.group(1)) if m else 9999

    return sorted(out, key=season_num)


def merge_anime_results(
    results: List[AnimeInfo],
    query: str = "",
) -> Optional[AnimeInfo]:
    valid = [
        r for r in results
        if r and r.title and (not query or is_same_anime(query, r))
    ]
    if not valid:
        return None

    # Highest confidence first, but favor pages containing structured data.
    def score(r: AnimeInfo) -> float:
        data_bonus = 0
        data_bonus += 0.08 if r.episodes else 0
        data_bonus += 0.08 if r.seasons else 0
        data_bonus += 0.05 if r.poster else 0
        data_bonus += 0.04 if r.platforms else 0
        data_bonus += 0.04 if r.languages else 0
        return r.confidence + data_bonus

    base = max(valid, key=score)

    merged = AnimeInfo(
        title=base.title,
        canonical_title=base.canonical_title or base.title,
        aliases=[],
        poster=base.poster,
        url=base.url,
        source=base.source,
        hindi_dub=base.hindi_dub,
        languages=list(base.languages),
        platforms=list(base.platforms),
        dub_by=list(base.dub_by),
        seasons=list(base.seasons),
        season=base.season,
        episodes=base.episodes,
        released_episodes=base.released_episodes,
        status=base.status,
        last_episode=base.last_episode,
        last_release=base.last_release,
        next_episode=base.next_episode,
        year=base.year,
        studio=base.studio,
        genres=list(base.genres),
        confidence=base.confidence,
    )

    for r in valid:
        merged.aliases.extend(r.aliases)
        merged.languages.extend(r.languages)
        merged.platforms.extend(r.platforms)
        merged.dub_by.extend(r.dub_by)
        merged.genres.extend(r.genres)

        if r.hindi_dub is True:
            merged.hindi_dub = True
        elif merged.hindi_dub is None and r.hindi_dub is False:
            merged.hindi_dub = False

        if not merged.poster and r.poster:
            merged.poster = r.poster
        if not merged.studio and r.studio:
            merged.studio = r.studio
        if not merged.year and r.year:
            merged.year = r.year
        if not merged.last_release and r.last_release:
            merged.last_release = r.last_release
        if not merged.next_episode and r.next_episode:
            merged.next_episode = r.next_episode
        if not merged.status and r.status:
            merged.status = r.status

        # Never blindly add a larger episode number from an unrelated page.
        if merged.episodes is None and is_valid_episode_count(r.episodes):
            merged.episodes = r.episodes

    merged.aliases = unique_keep_order(merged.aliases)
    merged.languages = unique_keep_order(merged.languages)
    merged.platforms = unique_keep_order(merged.platforms)
    merged.dub_by = unique_keep_order(merged.dub_by)
    merged.genres = unique_keep_order(merged.genres)

    # Merge season data from same-title sources.
    merged.seasons = merge_seasons(*(r.seasons for r in valid))

    if merged.seasons:
        # If there are real season records, don't use an arbitrary page total.
        total = sum(
            s.episodes for s in merged.seasons
            if is_valid_episode_count(s.episodes)
        )
        released = sum(
            (s.released_episodes or s.episodes or 0)
            for s in merged.seasons
        )
        if total > 0:
            merged.episodes = total
        if released > 0:
            merged.released_episodes = released

    if merged.status.lower() == "ongoing":
        if merged.released_episodes is None:
            merged.released_episodes = merged.episodes

    if merged.status.lower() == "completed":
        merged.released_episodes = merged.episodes

    return merged


# ---------------------------------------------------------------------------
# Main scraper
# ---------------------------------------------------------------------------

class AnimeScraper:
    """
    Main class expected to be imported by bot.py.

    Supported methods:
        scrape(query)
        scrape_anime(query)
        get_anime(query)
        scrape_url(url)
        format_result(info)
        get_anime_text(query)
    """

    def __init__(
        self,
        timeout: int = REQUEST_TIMEOUT,
        use_rare: bool = True,
        use_mirchi: bool = True,
        use_jikan: bool = True,
    ):
        self.client = HTTPClient(timeout)
        self.rare = RareAnimesSource(self.client) if use_rare else None
        self.mirchi = AnimeMirchiSource(self.client) if use_mirchi else None
        self.jikan = JikanSource(self.client) if use_jikan else None

    def scrape(self, query: str) -> Optional[AnimeInfo]:
        query = clean_text(query)
        if not query:
            return None

        results: List[AnimeInfo] = []

        # Search each source independently. One source failing must not break
        # the complete request.
        if self.rare:
            try:
                for url, _ in self.rare.search(query):
                    item = self.rare.parse_page(url, query)
                    if item:
                        results.append(item)
            except Exception:
                logger.exception("RareAnimes scrape failed")

        if self.mirchi:
            try:
                for url, _ in self.mirchi.search(query):
                    item = self.mirchi.parse_page(url, query)
                    if item:
                        results.append(item)
            except Exception:
                logger.exception("Anime Mirchi scrape failed")

        # Jikan is used primarily to identify/correct canonical metadata.
        jikan_results: List[AnimeInfo] = []
        if self.jikan:
            try:
                jikan_results = self.jikan.search(query)
            except Exception:
                logger.exception("Jikan lookup failed")

        # If web sources returned a good result, enrich it with Jikan rather
        # than replacing the source page (which may contain Hindi/platform
        # information).
        best_jikan = jikan_results[0] if jikan_results else None

        merged = merge_anime_results(results, query)

        if merged is None and best_jikan and best_jikan.confidence >= 0.55:
            merged = best_jikan
        elif merged and best_jikan and best_jikan.confidence >= 0.55:
            # Only fill missing canonical metadata from Jikan.
            if not merged.studio:
                merged.studio = best_jikan.studio
            if not merged.poster:
                merged.poster = best_jikan.poster
            if not merged.year:
                merged.year = best_jikan.year
            if not merged.episodes and best_jikan.episodes:
                merged.episodes = best_jikan.episodes
            if not merged.status:
                merged.status = best_jikan.status

            merged.aliases = unique_keep_order(
                merged.aliases + best_jikan.aliases
            )

        if merged:
            self._finalize(merged, query)
        return merged

    # Compatibility aliases for older bot files.
    def scrape_anime(self, query: str) -> Optional[AnimeInfo]:
        return self.scrape(query)

    def get_anime(self, query: str) -> Optional[AnimeInfo]:
        return self.scrape(query)

    def scrape_url(self, url: str) -> Optional[AnimeInfo]:
        host = urlparse(url).netloc.lower()
        if "rareanimes" in host and self.rare:
            return self.rare.parse_page(url)
        if "animemirchi" in host and self.mirchi:
            return self.mirchi.parse_page(url)
        return None

    def _finalize(self, info: AnimeInfo, query: str) -> None:
        info.languages = unique_keep_order(info.languages)
        info.platforms = unique_keep_order(info.platforms)
        info.dub_by = unique_keep_order(info.dub_by)

        if info.hindi_dub is None and "Hindi" in info.languages:
            info.hindi_dub = True

        if info.status.lower() == "completed":
            info.released_episodes = info.episodes
            if info.episodes:
                info.last_episode = info.episodes
        elif info.released_episodes and not info.last_episode:
            info.last_episode = info.released_episodes

        if info.last_episode is None and info.released_episodes:
            info.last_episode = info.released_episodes

        # If no status exists, infer it conservatively.
        if not info.status:
            if info.episodes and info.released_episodes:
                if info.released_episodes >= info.episodes:
                    info.status = "Completed"
                else:
                    info.status = "Ongoing"

        # A plain query must not return an obviously unrelated title.
        if query and not is_same_anime(query, info):
            info.error = "No reliable matching anime result found."

    # -----------------------------------------------------------------------
    # Output
    # -----------------------------------------------------------------------

    def format_result(self, info: Optional[AnimeInfo]) -> str:
        if not info:
            return "❌ Anime information not found."

        if info.error:
            return "❌ Anime information not found for this title."

        title = info.title or info.canonical_title or "Unknown"
        lines = [
            f"🎬 Anime: {title}",
            f"🇮🇳 Hindi Dub: {'✅ Available' if info.hindi_dub is True else '❌ Not Available' if info.hindi_dub is False else '❓ Unknown'}",
        ]

        if info.platforms:
            lines.append("📺 Platform: " + " • ".join(info.platforms))
        else:
            lines.append("📺 Platform: ❓ Not found")

        if info.seasons:
            lines.append("📀 Seasons:")
            for s in info.seasons:
                ep = s.episodes if s.episodes is not None else "?"
                rel = s.released_episodes if s.released_episodes is not None else ep
                if s.status.lower() == "ongoing" and rel != ep:
                    lines.append(f"• {s.season}: {rel} / {ep} Episodes")
                else:
                    lines.append(f"• {s.season}: {ep} Episodes")
        else:
            if info.season:
                lines.append(f"📀 Season: {info.season}")
            if info.episodes is not None:
                if info.status.lower() == "ongoing" and info.released_episodes is not None:
                    lines.append(
                        f"🎬 Episodes: {info.released_episodes} / {info.episodes}"
                    )
                else:
                    lines.append(f"🎬 Episodes: {info.episodes}")

        if info.languages:
            lines.append("🌐 Languages: " + " • ".join(info.languages))

        status = info.status or "Unknown"
        status_icon = "✅" if status.lower() == "completed" else "🔄" if status.lower() == "ongoing" else "ℹ️"
        lines.append(f"📊 Status: {status_icon} {status}")

        if info.last_episode:
            lines.append(f"📅 Last Episode: Episode {info.last_episode}")
        if info.last_release:
            lines.append(f"🗓 Last Release: {info.last_release}")

        if info.next_episode and status.lower() == "ongoing":
            lines.append(f"⏭ Next Episode: {info.next_episode}")

        if info.studio:
            lines.append(f"🏢 Studio: {info.studio}")

        if info.dub_by:
            lines.append("🎙 Dub By: " + " • ".join(info.dub_by))

        lines.append(f"🔎 Source: {info.source or 'Anime Database'}")

        return "\n".join(lines)

    def get_anime_text(self, query: str) -> str:
        return self.format_result(self.scrape(query))


# ---------------------------------------------------------------------------
# Daily schedule support
# ---------------------------------------------------------------------------

@dataclass
class ScheduleItem:
    anime: str
    language: str = ""
    platform: str = ""
    date_text: str = ""
    time_text: str = ""
    status: str = ""
    url: str = ""


class DailyAnimeUpdates:
    """
    Reads schedule/article tables from Anime Mirchi and RareAnimes.

    This intentionally does not invent a release time. If a source does not
    publish a time, the time field remains "Not specified".
    """

    def __init__(self, client: Optional[HTTPClient] = None):
        self.client = client or HTTPClient()

    def scan_pages(self, urls: List[str]) -> List[ScheduleItem]:
        result: List[ScheduleItem] = []

        for url in urls:
            html = self.client.text(url)
            if not html:
                continue

            soup = BeautifulSoup(html, "lxml")
            result.extend(self._scan_tables(soup, url))

        # Deduplicate.
        out = []
        seen = set()
        for item in result:
            key = (
                normalize_title(item.anime),
                item.language.lower(),
                item.platform.lower(),
                item.date_text.lower(),
                item.time_text.lower(),
            )
            if key in seen:
                continue
            seen.add(key)
            out.append(item)
        return out

    def _scan_tables(self, soup: BeautifulSoup, url: str) -> List[ScheduleItem]:
        items = []

        for table in soup.find_all("table"):
            rows = table.find_all("tr")
            if not rows:
                continue

            headers = [
                normalize_title(c.get_text(" ", strip=True))
                for c in rows[0].find_all(["th", "td"])
            ]

            for row in rows[1:]:
                cells = [
                    clean_text(c.get_text(" ", strip=True))
                    for c in row.find_all(["th", "td"])
                ]
                if not cells:
                    continue

                text = " | ".join(cells)
                language = ""
                platform = ""

                langs = detect_languages(text)
                plats = detect_platforms(text)

                if langs:
                    language = " • ".join(langs)
                if plats:
                    platform = " • ".join(plats)

                # Try header-aware extraction.
                anime = cells[0]
                for i, header in enumerate(headers):
                    if i >= len(cells):
                        continue
                    if any(k in header for k in ("anime", "title", "show")):
                        anime = cells[i]
                        break

                # Ignore rows that are clearly not anime entries.
                if len(anime) < 2:
                    continue
                if normalize_title(anime) in {
                    "anime", "title", "show", "name", "episode"
                }:
                    continue

                date_text = parse_date_text(text)
                time_text = extract_time(text)

                items.append(
                    ScheduleItem(
                        anime=anime,
                        language=language,
                        platform=platform,
                        date_text=date_text,
                        time_text=time_text,
                        status=detect_status(text),
                        url=url,
                    )
                )

        return items

    def today(self, pages: List[str]) -> List[ScheduleItem]:
        today = date.today()

        items = self.scan_pages(pages)
        result = []

        for item in items:
            if not item.date_text:
                continue

            parsed = False
            for fmt in (
                "%d %B %Y",
                "%B %d, %Y",
                "%d/%m/%Y",
                "%d-%m-%Y",
            ):
                try:
                    d = datetime.strptime(item.date_text, fmt).date()
                    if d == today:
                        result.append(item)
                    parsed = True
                    break
                except ValueError:
                    pass

            if not parsed:
                # Do not claim "today" from an unparseable date.
                continue

        return result

    @staticmethod
    def format(items: List[ScheduleItem]) -> str:
        if not items:
            return "📅 Aaj ke anime updates nahi mile."

        lines = ["📅 Today's Anime Updates", ""]
        for i, item in enumerate(items, 1):
            lines.append(f"{i}. 🎬 {item.anime}")
            if item.language:
                lines.append(f"   🌐 Language: {item.language}")
            if item.platform:
                lines.append(f"   📺 Platform: {item.platform}")
            lines.append(
                f"   ⏰ Time: {item.time_text or 'Not specified'}"
            )
            if item.status:
                lines.append(f"   📊 Status: {item.status}")
            lines.append("")
        return "\n".join(lines).rstrip()


# ---------------------------------------------------------------------------
# Backward-compatible convenience functions
# ---------------------------------------------------------------------------

_default_scraper: Optional[AnimeScraper] = None


def get_scraper() -> AnimeScraper:
    global _default_scraper
    if _default_scraper is None:
        _default_scraper = AnimeScraper()
    return _default_scraper


def scrape_anime(query: str) -> Optional[AnimeInfo]:
    return get_scraper().scrape(query)


def get_anime_info(query: str) -> Optional[AnimeInfo]:
    return get_scraper().scrape(query)


def get_anime_text(query: str) -> str:
    return get_scraper().get_anime_text(query)


# ---------------------------------------------------------------------------
# CLI test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage:")
        print("  python anime_scraper.py Naruto")
        print("  python anime_scraper.py \"The Promised Neverland\"")
        sys.exit(0)

    query = " ".join(sys.argv[1:]).strip()
    scraper = AnimeScraper()

    print(f"Searching: {query}")
    info = scraper.scrape(query)

    if not info:
        print("❌ No reliable anime result found.")
    else:
        print()
        print(scraper.format_result(info))
        if info.poster:
            print()
            print("Poster:", info.poster)
        if info.url:
            print("Page:", info.url)
