# anime_service.py
# Single-file Anime information + daily schedule service.
# Sources: RareAnimes, Anime Mirchi, Jikan metadata fallback.
# This module only reads metadata/schedules; it does not extract
# third-party download/watch links.

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import unicodedata
from dataclasses import dataclass, field, asdict
from datetime import date, datetime
from typing import Any, Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup


# =========================
# CONFIG
# =========================

RAREANIMES_BASE = "https://www.rareanimes.mov"
ANIME_MIRCHI_BASE = "https://animemirchi.com"
JIKAN_BASE = "https://api.jikan.moe/v4"

REQUEST_TIMEOUT = 20
REQUEST_DELAY = 0.35
MAX_SEARCH_RESULTS = 10
JIKAN_MIN_SCORE = 55

USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 10) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/140.0 Mobile Safari/537.36 "
    "AnimeInfoBot/1.0"
)

logger = logging.getLogger("anime_service")


# =========================
# DATA MODELS
# =========================

@dataclass
class SeasonInfo:
    number: Optional[int] = None
    name: str = ""
    episodes: Optional[int] = None
    released_episodes: Optional[int] = None
    status: str = ""
    release_date: Optional[str] = None
    next_episode: Optional[int] = None
    next_release: Optional[str] = None
    languages: list[str] = field(default_factory=list)
    platforms: list[str] = field(default_factory=list)
    source: str = ""
    source_url: str = ""
    confidence: float = 0.0


@dataclass
class ScheduleItem:
    anime: str = ""
    season: str = ""
    episode: Optional[int] = None
    date: Optional[str] = None
    time_ist: Optional[str] = None
    languages: list[str] = field(default_factory=list)
    platform: str = ""
    status: str = ""
    source: str = ""
    source_url: str = ""
    confidence: float = 0.0


@dataclass
class AnimeInfo:
    title: str = ""
    canonical_title: str = ""
    poster: Optional[str] = None
    hindi_dub: Optional[bool] = None
    languages: list[str] = field(default_factory=list)
    platforms: list[str] = field(default_factory=list)
    status: str = "Unknown"
    total_episodes: Optional[int] = None
    released_episodes: Optional[int] = None
    last_episode: Optional[int] = None
    last_release: Optional[str] = None
    next_episode: Optional[int] = None
    next_release: Optional[str] = None
    next_time_ist: Optional[str] = None
    studio: Optional[str] = None
    year: Optional[int] = None
    seasons: list[SeasonInfo] = field(default_factory=list)
    source_urls: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    matched_query: str = ""
    confidence: float = 0.0
    is_franchise: bool = False
    raw_titles: list[str] = field(default_factory=list)


# =========================
# GENERAL HELPERS
# =========================

def clean_text(value: Any) -> str:
    if value is None:
        return ""
    value = unicodedata.normalize("NFKC", str(value))
    value = value.replace("\xa0", " ").replace("\u200b", "").replace("\ufeff", "")
    return re.sub(r"\s+", " ", value).strip()


def normalize_title(value: str) -> str:
    value = clean_text(value).lower()
    value = re.sub(
        r"\b(season|part|cour|episode|episodes|ep|hindi|dubbed|dub|"
        r"download|watch|dual audio|multi audio|complete|completed|"
        r"1080p|720p|480p|360p)\b",
        " ",
        value,
        flags=re.I,
    )
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def title_tokens(value: str) -> set[str]:
    return set(normalize_title(value).split())


def similarity_score(a: str, b: str) -> float:
    na, nb = normalize_title(a), normalize_title(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 100.0
    if na in nb or nb in na:
        return 90.0

    ta, tb = title_tokens(a), title_tokens(b)
    if not ta or not tb:
        return 0.0

    intersection = len(ta & tb)
    union = len(ta | tb)
    if not union:
        return 0.0

    return min(
        100.0,
        (intersection / union) * 45
        + (intersection / len(ta)) * 30
        + (intersection / len(tb)) * 25,
    )


def unique_list(items: list[str]) -> list[str]:
    out, seen = [], set()
    for item in items:
        item = clean_text(item)
        if not item:
            continue
        key = item.lower()
        if key not in seen:
            seen.add(key)
            out.append(item)
    return out


def parse_int(value: Any) -> Optional[int]:
    text = clean_text(value)
    if not text:
        return None
    m = re.search(r"\b(\d{1,5})\b", text)
    return int(m.group(1)) if m else None


def extract_episode_number(text: str) -> Optional[int]:
    text = clean_text(text)
    for pattern in (
        r"\bepisode\s*[-:#]?\s*(\d{1,5})\b",
        r"\bep\.?\s*[-:#]?\s*(\d{1,5})\b",
    ):
        m = re.search(pattern, text, re.I)
        if m:
            try:
                return int(m.group(1))
            except ValueError:
                pass
    return None


def normalize_status(value: str) -> str:
    text = clean_text(value).lower()
    if any(x in text for x in (
        "ongoing", "airing", "currently airing",
        "currently", "in progress"
    )):
        return "Ongoing"
    if any(x in text for x in (
        "completed", "complete", "finished airing",
        "ended", "finished"
    )):
        return "Completed"
    return "Unknown"


def parse_date_string(value: str) -> Optional[str]:
    value = clean_text(value)
    if not value:
        return None

    for fmt in (
        "%B %d, %Y", "%b %d, %Y",
        "%d %B %Y", "%d %b %Y",
        "%Y-%m-%d", "%d-%m-%Y",
        "%d/%m/%Y", "%m/%d/%Y",
    ):
        try:
            return datetime.strptime(value, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass

    m = re.search(
        r"\b(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|"
        r"May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|"
        r"Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|"
        r"Dec(?:ember)?)\s+(\d{1,2}),?\s+(\d{4})\b",
        value,
        re.I,
    )
    if m:
        raw = f"{m.group(1)} {m.group(2)}, {m.group(3)}"
        for fmt in ("%B %d, %Y", "%b %d, %Y"):
            try:
                return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
            except ValueError:
                pass
    return None


def detect_languages(text: str) -> list[str]:
    text = clean_text(text)
    patterns = {
        "Hindi": (r"\bhindi\b", r"\bहिंदी\b"),
        "English": (r"\benglish\b",),
        "Japanese": (r"\bjapanese\b", r"\b日本語\b"),
        "Tamil": (r"\btamil\b", r"\bதமிழ்\b"),
        "Telugu": (r"\btelugu\b", r"\bతెలుగు\b"),
        "Malayalam": (r"\bmalayalam\b", r"\bമലയാളം\b"),
        "Kannada": (r"\bkannada\b", r"\bಕನ್ನಡ\b"),
        "Bengali": (r"\bbengali\b", r"\bbangla\b", r"\bবাংলা\b"),
        "Marathi": (r"\bmarathi\b",),
        "Chinese": (r"\bchinese\b",),
        "Korean": (r"\bkorean\b",),
        "Spanish": (r"\bspanish\b",),
        "French": (r"\bfrench\b",),
    }
    found = []
    for language, pats in patterns.items():
        if any(re.search(p, text, re.I) for p in pats):
            found.append(language)
    return unique_list(found)


def detect_platforms(text: str) -> list[str]:
    text = clean_text(text)
    platforms = [
        "Crunchyroll", "Sony YAY!", "Sony YAY",
        "JioHotstar", "JioCinema", "Netflix",
        "Amazon Prime Video", "Prime Video",
        "Disney+", "Disney Plus", "Muse India",
        "Ani-One India", "Anime Times", "YouTube",
        "Cartoon Network India", "Cartoon Network",
        "Zee Café", "Zee Cafe", "MX Player",
        "Tata Play", "Hungama",
    ]
    found = []
    lower = text.lower()
    for platform in platforms:
        if platform.lower() in lower:
            found.append(platform)

    out = []
    for item in found:
        key = item.lower()
        if key == "sony yay":
            out.append("Sony YAY!")
        elif key == "prime video":
            out.append("Amazon Prime Video")
        elif key == "zee cafe":
            out.append("Zee Café")
        elif key == "disney plus":
            out.append("Disney+")
        else:
            out.append(item)
    return unique_list(out)


def unique_ints(values: list[int]) -> list[int]:
    return list(dict.fromkeys(values))


def clean_anime_title(title: str) -> str:
    title = clean_text(title)
    for pattern in (
        r"\s*[-|]\s*Rare.*$",
        r"\s*[-|]\s*Anime Mirchi.*$",
        r"\s+Hindi Dubbed.*$",
        r"\s+Hindi Subbed.*$",
        r"\s+Episodes Download.*$",
        r"\s+Download HD.*$",
    ):
        title = re.sub(pattern, "", title, flags=re.I)
    return clean_text(title)


def extract_season_number(title: str, text: str = "") -> Optional[int]:
    for source in (title, text):
        for pattern in (r"\bseason\s*0?(\d{1,2})\b", r"\bs0?(\d{1,2})\b"):
            m = re.search(pattern, source, re.I)
            if m:
                try:
                    n = int(m.group(1))
                    if 1 <= n <= 50:
                        return n
                except ValueError:
                    pass
    return None


def detect_franchise(query: str, titles: list[str]) -> bool:
    q = normalize_title(query)
    markers = [
        "dragon ball", "naruto", "bleach", "jojo",
        "one piece", "pokemon", "digimon", "fate",
        "monogatari", "gundam", "pretty cure",
        "yu gi oh", "attack on titan", "my hero academia",
    ]
    for marker in markers:
        if marker in q:
            matches = [t for t in titles if marker in normalize_title(t)]
            if len(matches) >= 2:
                return True

    count = sum(
        bool(re.search(r"\bseason\s*\d+\b|\bs\d+\b", t, re.I))
        for t in titles
    )
    return count >= 2


# =========================
# HTTP
# =========================

class HTTPClient:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        })
        self.last_request = 0.0

    def get(
        self,
        url: str,
        *,
        params: Optional[dict] = None,
        timeout: int = REQUEST_TIMEOUT,
    ) -> Optional[requests.Response]:
        elapsed = time.time() - self.last_request
        if elapsed < REQUEST_DELAY:
            time.sleep(REQUEST_DELAY - elapsed)

        try:
            response = self.session.get(
                url,
                params=params,
                timeout=timeout,
                allow_redirects=True,
            )
            self.last_request = time.time()
            if response.status_code >= 400:
                logger.warning("HTTP %s: %s", response.status_code, response.url)
                return None
            return response
        except requests.RequestException as exc:
            logger.warning("Request failed: %s | %s", url, exc)
            return None

    def close(self):
        self.session.close()


# =========================
# RAREANIMES
# =========================

class RareAnimesSource:
    name = "RareAnimes"

    def __init__(self, http: HTTPClient):
        self.http = http

    def search(self, query: str) -> list[dict]:
        response = self.http.get(RAREANIMES_BASE, params={"s": query})
        if not response:
            return []

        soup = BeautifulSoup(response.text, "lxml")
        results = []

        selectors = (
            "article a[href], .post a[href], .entry-title a[href], "
            "h2 a[href], h3 a[href]"
        )

        for anchor in soup.select(selectors):
            href = anchor.get("href")
            title = clean_text(anchor.get_text(" "))
            if not href or not title:
                continue

            href = urljoin(RAREANIMES_BASE, href)
            if urlparse(href).netloc != urlparse(RAREANIMES_BASE).netloc:
                continue

            score = similarity_score(query, title)
            if score >= 25:
                results.append({"title": title, "url": href, "score": score})

        if not results:
            for anchor in soup.find_all("a", href=True):
                href = urljoin(RAREANIMES_BASE, anchor["href"])
                title = clean_text(anchor.get_text(" "))
                if not title:
                    continue
                if urlparse(href).netloc != urlparse(RAREANIMES_BASE).netloc:
                    continue
                score = similarity_score(query, title)
                if score >= 40:
                    results.append({"title": title, "url": href, "score": score})

        unique = {}
        for item in results:
            unique[item["url"]] = item
        results = list(unique.values())
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:MAX_SEARCH_RESULTS]

    def parse_page(self, url: str, query: str) -> Optional[AnimeInfo]:
        response = self.http.get(url)
        if not response:
            return None

        soup = BeautifulSoup(response.text, "lxml")
        full_text = clean_text(soup.get_text(" "))
        title = self._extract_title(soup)
        if not title:
            return None

        info = AnimeInfo(
            title=title,
            canonical_title=title,
            matched_query=query,
            sources=[self.name],
            source_urls=[url],
        )

        info.poster = self._extract_poster(soup, title)
        info.languages = detect_languages(full_text)
        info.platforms = detect_platforms(full_text)
        info.hindi_dub = True if "Hindi" in info.languages else None
        info.status = normalize_status(full_text)
        info.year = self._extract_year(full_text)
        info.studio = self._extract_studio(full_text)

        season_number = extract_season_number(title, full_text)
        episodes = self._extract_total_episodes(full_text)
        last_episode = max(self._extract_episode_numbers(soup), default=None)

        if last_episode:
            episodes = max(episodes or 0, last_episode)

        season = SeasonInfo(
            number=season_number,
            name=f"Season {season_number}" if season_number else "",
            episodes=episodes,
            released_episodes=episodes,
            status=info.status,
            languages=list(info.languages),
            platforms=list(info.platforms),
            source=self.name,
            source_url=url,
            confidence=0.75,
        )
        info.seasons = [season]
        info.total_episodes = episodes
        info.released_episodes = episodes
        info.last_episode = last_episode or episodes
        info.last_release = self._extract_release_date(full_text)

        field_platform = self._extract_field(
            full_text, ["Network", "Platform", "Channel"]
        )
        if field_platform:
            info.platforms = unique_list(info.platforms + [field_platform])
            info.seasons[0].platforms = list(info.platforms)

        next_ep = self._extract_next_episode(full_text)
        if next_ep:
            info.next_episode = next_ep

        return info

    @staticmethod
    def _extract_title(soup: BeautifulSoup) -> str:
        for selector in ("h1.entry-title", "h1.post-title", "article h1", "main h1", "h1"):
            node = soup.select_one(selector)
            if node:
                value = clean_text(node.get_text(" "))
                if value:
                    return clean_anime_title(value)
        if soup.title:
            return clean_anime_title(soup.title.get_text(" "))
        return ""

    @staticmethod
    def _extract_poster(soup: BeautifulSoup, title: str) -> Optional[str]:
        candidates = []
        for selector in ("article img", ".post img", ".entry-content img", "main img"):
            for img in soup.select(selector):
                src = img.get("src") or img.get("data-src") or img.get("data-lazy-src")
                if not src:
                    continue
                src = urljoin(RAREANIMES_BASE, src)
                alt = clean_text(img.get("alt", ""))
                score = similarity_score(title, alt)
                low = src.lower()
                if any(x in low for x in ("logo", "avatar", "icon", "banner", "telegram")):
                    score -= 100
                candidates.append((score, src))
        if not candidates:
            return None
        candidates.sort(key=lambda x: x[0], reverse=True)
        return candidates[0][1]

    @staticmethod
    def _extract_total_episodes(text: str) -> Optional[int]:
        values = []
        for pattern in (
            r"(?:episodes?|eps?)\s*[:\-]?\s*(\d{1,4})",
            r"(?:this season has|season has)\s*(\d{1,4})\s*episodes?",
        ):
            for m in re.finditer(pattern, text, re.I):
                try:
                    n = int(m.group(1))
                    if 1 <= n <= 2000:
                        values.append(n)
                except ValueError:
                    pass
        return max(values) if values else None

    @staticmethod
    def _extract_episode_numbers(soup: BeautifulSoup) -> list[int]:
        nums = []
        for node in soup.find_all(string=re.compile(r"\b(?:episode|ep)\b", re.I)):
            n = extract_episode_number(clean_text(node))
            if n:
                nums.append(n)
        return unique_ints(nums)

    @staticmethod
    def _extract_year(text: str) -> Optional[int]:
        m = re.search(r"\b(?:release year|year)\s*[:\-]?\s*(20\d{2})\b", text, re.I)
        return int(m.group(1)) if m else None

    @staticmethod
    def _extract_release_date(text: str) -> Optional[str]:
        m = re.search(
            r"(?:release date|released|premiere|last release)\s*[:\-]?\s*"
            r"([A-Za-z]+\s+\d{1,2},?\s+\d{4})",
            text,
            re.I,
        )
        return parse_date_string(m.group(1)) if m else None

    @staticmethod
    def _extract_field(text: str, names: list[str]) -> Optional[str]:
        for name in names:
            m = re.search(
                rf"\b{re.escape(name)}\b\s*[:\-]\s*([^|•\n]{{2,100}})",
                text,
                re.I,
            )
            if m:
                value = clean_text(m.group(1))
                if value:
                    return value
        return None

    @staticmethod
    def _extract_studio(text: str) -> Optional[str]:
        return RareAnimesSource._extract_field(text, ["Studio", "Studios"])

    @staticmethod
    def _extract_next_episode(text: str) -> Optional[int]:
        for pattern in (
            r"next\s+episode\s*[:#\-]?\s*(\d{1,4})",
            r"episode\s*(\d{1,4})\s*(?:next|upcoming)",
        ):
            m = re.search(pattern, text, re.I)
            if m:
                try:
                    return int(m.group(1))
                except ValueError:
                    pass
        return None


# =========================
# ANIME MIRCHI
# =========================

class AnimeMirchiSource:
    name = "Anime Mirchi"

    def __init__(self, http: HTTPClient):
        self.http = http

    def search(self, query: str) -> list[dict]:
        response = self.http.get(ANIME_MIRCHI_BASE, params={"s": query})
        if not response:
            return []

        soup = BeautifulSoup(response.text, "lxml")
        results = []

        for anchor in soup.select(
            "article a[href], h2 a[href], h3 a[href], .entry-title a[href]"
        ):
            href = anchor.get("href")
            title = clean_text(anchor.get_text(" "))
            if not href or not title:
                continue

            href = urljoin(ANIME_MIRCHI_BASE, href)
            if urlparse(href).netloc != urlparse(ANIME_MIRCHI_BASE).netloc:
                continue

            score = similarity_score(query, title)
            if score >= 25:
                results.append({"title": title, "url": href, "score": score})

        unique = {}
        for item in results:
            unique[item["url"]] = item
        results = list(unique.values())
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:MAX_SEARCH_RESULTS]

    def parse_page(self, url: str, query: str) -> Optional[AnimeInfo]:
        response = self.http.get(url)
        if not response:
            return None

        soup = BeautifulSoup(response.text, "lxml")
        title = self._extract_title(soup)
        if not title:
            return None

        text = clean_text(soup.get_text(" "))

        info = AnimeInfo(
            title=title,
            canonical_title=title,
            matched_query=query,
            sources=[self.name],
            source_urls=[url],
        )
        info.poster = self._extract_poster(soup, title)
        info.languages = detect_languages(text)
        info.platforms = detect_platforms(text)
        info.hindi_dub = True if "Hindi" in info.languages else None
        info.status = normalize_status(text)
        info.year = self._extract_year(text)
        info.studio = self._extract_studio(text)

        self._parse_tables(soup, info)

        schedules = self.parse_schedule_page(url, soup=soup)
        relevant = [
            x for x in schedules
            if similarity_score(query, x.anime) >= 45
        ]
        if relevant:
            item = relevant[0]
            info.languages = unique_list(info.languages + item.languages)
            if item.platform:
                info.platforms = unique_list(info.platforms + [item.platform])
            if item.episode:
                info.next_episode = item.episode
            if item.date:
                info.next_release = item.date
            info.next_time_ist = item.time_ist

        return info

    @staticmethod
    def _extract_title(soup: BeautifulSoup) -> str:
        for selector in ("h1.entry-title", "h1.post-title", "article h1", "main h1", "h1"):
            node = soup.select_one(selector)
            if node:
                value = clean_text(node.get_text(" "))
                if value:
                    return clean_anime_title(value)
        return ""

    @staticmethod
    def _extract_poster(soup: BeautifulSoup, title: str) -> Optional[str]:
        candidates = []
        for img in soup.select("article img, .entry-content img, main img"):
            src = img.get("src") or img.get("data-src") or img.get("data-lazy-src")
            if not src:
                continue
            src = urljoin(ANIME_MIRCHI_BASE, src)
            alt = clean_text(img.get("alt", ""))
            score = similarity_score(title, alt)
            if "logo" in src.lower():
                score -= 100
            candidates.append((score, src))
        if not candidates:
            return None
        candidates.sort(key=lambda x: x[0], reverse=True)
        return candidates[0][1]

    @staticmethod
    def _extract_year(text: str) -> Optional[int]:
        m = re.search(
            r"\b(?:release|premiere|year)\s*[:\-]?\s*(20\d{2})\b",
            text,
            re.I,
        )
        return int(m.group(1)) if m else None

    @staticmethod
    def _extract_studio(text: str) -> Optional[str]:
        m = re.search(
            r"\bstudio(?:s)?\s*[:\-]\s*([^|•\n]{2,100})",
            text,
            re.I,
        )
        return clean_text(m.group(1)) if m else None

    @staticmethod
    def _parse_tables(soup: BeautifulSoup, info: AnimeInfo):
        for table in soup.find_all("table"):
            rows = table.find_all("tr")
            headers = []

            for index, row in enumerate(rows):
                cells = row.find_all(["th", "td"])
                values = [clean_text(c.get_text(" ")) for c in cells]
                if not values:
                    continue

                if index == 0:
                    headers = [x.lower() for x in values]
                    continue

                for i, value in enumerate(values):
                    header = headers[i] if i < len(headers) else ""

                    if "language" in header:
                        info.languages = unique_list(
                            info.languages + detect_languages(value)
                        )

                    if any(x in header for x in ("platform", "network", "channel")):
                        info.platforms = unique_list(
                            info.platforms + detect_platforms(value)
                        )

                    if "episode" in header:
                        ep = parse_int(value)
                        if ep:
                            info.released_episodes = max(
                                info.released_episodes or 0, ep
                            )

    def parse_schedule_page(
        self,
        url: str,
        soup: Optional[BeautifulSoup] = None,
    ) -> list[ScheduleItem]:

        if soup is None:
            response = self.http.get(url)
            if not response:
                return []
            soup = BeautifulSoup(response.text, "lxml")

        results = []

        for table in soup.find_all("table"):
            rows = table.find_all("tr")
            headers = []

            for index, row in enumerate(rows):
                cells = row.find_all(["th", "td"])
                values = [clean_text(c.get_text(" ")) for c in cells]
                if not values:
                    continue

                if index == 0:
                    headers = [v.lower() for v in values]
                    continue

                item = ScheduleItem(source=self.name, source_url=url)

                for i, value in enumerate(values):
                    header = headers[i] if i < len(headers) else ""

                    if any(x in header for x in ("anime", "title")):
                        item.anime = value
                    elif "season" in header:
                        item.season = value
                    elif "episode" in header:
                        item.episode = parse_int(value)
                    elif any(x in header for x in ("premiere", "date", "release")):
                        item.date = parse_date_string(value) or value
                    elif any(x in header for x in ("schedule", "time")):
                        item.time_ist = self._extract_time(value)
                    elif "language" in header:
                        item.languages = detect_languages(value)
                    elif any(x in header for x in ("platform", "network", "channel")):
                        platforms = detect_platforms(value)
                        item.platform = platforms[0] if platforms else value

                if item.anime:
                    if not item.languages:
                        item.languages = detect_languages(" ".join(values))
                    if not item.platform:
                        platforms = detect_platforms(" ".join(values))
                        if platforms:
                            item.platform = platforms[0]
                    results.append(item)

        return results

    @staticmethod
    def _extract_time(text: str) -> Optional[str]:
        for pattern in (
            r"\b(\d{1,2}:\d{2})\s*(AM|PM)\b",
            r"\b(\d{1,2})\s*(AM|PM)\b",
        ):
            m = re.search(pattern, text, re.I)
            if m:
                return f"{m.group(1)} {' '.join(m.groups()[1:]).upper()}" if ":" in m.group(1) else f"{m.group(1)}:00 {m.group(2).upper()}"
        return None


# =========================
# JIKAN / MAL METADATA
# =========================

class JikanSource:
    name = "Jikan"

    def __init__(self, http: HTTPClient):
        self.http = http

    def search(self, query: str) -> Optional[dict]:
        response = self.http.get(
            f"{JIKAN_BASE}/anime",
            params={"q": query, "limit": 5, "sfw": "true"},
        )
        if not response:
            return None

        try:
            results = response.json().get("data", [])
        except Exception:
            return None

        best, best_score = None, 0.0

        for item in results:
            titles = []
            if item.get("title"):
                titles.append(item["title"])
            titles += [
                x.get("title", "")
                for x in item.get("titles", [])
                if x.get("title")
            ]

            score = max(
                (similarity_score(query, title) for title in titles),
                default=0,
            )

            if item.get("score") is not None and score >= 55:
                score += min(10, float(item["score"]) / 10)

            if score > best_score:
                best_score, best = score, item

        return best if best is not None and best_score >= JIKAN_MIN_SCORE else None

    def to_anime_info(self, data: dict, query: str) -> Optional[AnimeInfo]:
        if not data:
            return None

        title = clean_text(
            data.get("title")
            or data.get("title_english")
            or data.get("title_japanese")
            or ""
        )
        if not title:
            return None

        info = AnimeInfo(
            title=title,
            canonical_title=title,
            matched_query=query,
            sources=[self.name],
        )

        mal_id = data.get("mal_id")
        if mal_id:
            info.source_urls.append(
                f"https://myanimelist.net/anime/{mal_id}"
            )

        images = data.get("images", {}).get("jpg", {})
        info.poster = images.get("large_image_url") or images.get("image_url")

        info.status = (
            "Ongoing" if "currently airing" in str(data.get("status", "")).lower()
            else "Completed" if "finished" in str(data.get("status", "")).lower()
            else "Unknown"
        )

        episodes = data.get("episodes")
        if isinstance(episodes, int):
            info.total_episodes = episodes
            if info.status == "Completed":
                info.released_episodes = episodes
                info.last_episode = episodes

        aired = data.get("aired", {})
        if isinstance(aired, dict) and aired.get("to"):
            info.last_release = str(aired["to"])[:10]

        if isinstance(data.get("year"), int):
            info.year = data["year"]

        studios = [
            x.get("name", "")
            for x in data.get("studios", [])
            if x.get("name")
        ]
        if studios:
            info.studio = ", ".join(unique_list(studios))

        return info


# =========================
# MERGING
# =========================

def merge_seasons(results: list[AnimeInfo]) -> list[SeasonInfo]:
    seasons: dict[int, SeasonInfo] = {}

    for result in results:
        for season in result.seasons:
            n = season.number
            if n is None or not 1 <= n <= 50:
                continue

            if n not in seasons:
                seasons[n] = SeasonInfo(
                    number=n,
                    name=season.name or f"Season {n}",
                    episodes=season.episodes,
                    released_episodes=season.released_episodes,
                    status=season.status,
                    release_date=season.release_date,
                    next_episode=season.next_episode,
                    next_release=season.next_release,
                    languages=list(season.languages),
                    platforms=list(season.platforms),
                    source=season.source,
                    source_url=season.source_url,
                    confidence=season.confidence,
                )
            else:
                current = seasons[n]
                if season.episodes and (
                    not current.episodes or season.episodes > current.episodes
                ):
                    current.episodes = season.episodes

                if season.released_episodes:
                    current.released_episodes = max(
                        current.released_episodes or 0,
                        season.released_episodes,
                    )

                current.languages = unique_list(
                    current.languages + season.languages
                )
                current.platforms = unique_list(
                    current.platforms + season.platforms
                )

                if season.status == "Ongoing":
                    current.status = "Ongoing"
                elif current.status == "Unknown":
                    current.status = season.status

    return sorted(seasons.values(), key=lambda x: x.number or 999)


def choose_best_title(query: str, titles: list[str]) -> str:
    cleaned = unique_list([clean_anime_title(x) for x in titles if x])
    if not cleaned:
        return query

    return max(
        cleaned,
        key=lambda x: similarity_score(query, x),
    )


def merge_anime_results(
    results: list[AnimeInfo],
    query: str,
) -> Optional[AnimeInfo]:

    good = [
        (similarity_score(query, r.title), r)
        for r in results
        if similarity_score(query, r.title) >= 45
    ]

    if not good:
        return None

    good.sort(key=lambda x: x[0], reverse=True)
    results = [r for _, r in good]

    def completeness(r: AnimeInfo) -> float:
        score = 0
        score += 10 if r.title else 0
        score += 5 if r.poster else 0
        score += 10 if r.hindi_dub is not None else 0
        score += len(r.languages) * 2
        score += len(r.platforms) * 2
        score += 10 if r.total_episodes else 0
        score += 8 if r.released_episodes else 0
        score += 8 if r.status != "Unknown" else 0
        score += 5 if r.studio else 0
        score += len(r.seasons) * 5
        return score + r.confidence * 10

    base = max(results, key=completeness)

    merged = AnimeInfo(
        title=base.title,
        canonical_title=base.canonical_title,
        poster=base.poster,
        hindi_dub=base.hindi_dub,
        status=base.status,
        total_episodes=base.total_episodes,
        released_episodes=base.released_episodes,
        last_episode=base.last_episode,
        last_release=base.last_release,
        next_episode=base.next_episode,
        next_release=base.next_release,
        next_time_ist=base.next_time_ist,
        studio=base.studio,
        year=base.year,
        matched_query=query,
        confidence=max(r.confidence for r in results),
    )

    merged.raw_titles = unique_list([r.title for r in results if r.title])
    merged.title = choose_best_title(query, merged.raw_titles)
    merged.canonical_title = merged.title

    posters = [
        (similarity_score(query, r.title), r.poster)
        for r in results
        if r.poster and similarity_score(query, r.title) >= 55
    ]
    if posters:
        merged.poster = max(posters, key=lambda x: x[0])[1]

    merged.languages = unique_list(
        [v for r in results for v in r.languages]
    )
    merged.platforms = unique_list(
        [v for r in results for v in r.platforms]
    )

    if any(r.hindi_dub is True for r in results):
        merged.hindi_dub = True

    statuses = [r.status for r in results if r.status != "Unknown"]
    if "Ongoing" in statuses:
        merged.status = "Ongoing"
    elif "Completed" in statuses:
        merged.status = "Completed"

    totals = [
        r.total_episodes for r in results
        if r.total_episodes and 1 <= r.total_episodes <= 2000
    ]
    if totals:
        merged.total_episodes = max(totals)

    released = [
        r.released_episodes for r in results
        if r.released_episodes and 1 <= r.released_episodes <= 2000
    ]
    if released:
        merged.released_episodes = max(released)

    last_eps = [
        r.last_episode for r in results
        if r.last_episode and 1 <= r.last_episode <= 2000
    ]
    if last_eps:
        merged.last_episode = max(last_eps)

    if merged.status == "Completed" and merged.total_episodes:
        merged.released_episodes = merged.total_episodes
        merged.last_episode = merged.total_episodes

    releases = [r.last_release for r in results if r.last_release]
    if releases:
        merged.last_release = sorted(releases)[-1]

    next_eps = [r.next_episode for r in results if r.next_episode]
    if next_eps:
        merged.next_episode = min(next_eps)

    next_dates = [r.next_release for r in results if r.next_release]
    if next_dates:
        merged.next_release = sorted(next_dates)[0]

    next_times = [r.next_time_ist for r in results if r.next_time_ist]
    if next_times:
        merged.next_time_ist = next_times[0]

    studios = [r.studio for r in results if r.studio]
    if studios:
        merged.studio = studios[0]

    years = [r.year for r in results if r.year]
    if years:
        merged.year = min(years)

    merged.seasons = merge_seasons(results)
    merged.sources = unique_list(
        [s for r in results for s in r.sources]
    )
    merged.source_urls = unique_list(
        [u for r in results for u in r.source_urls]
    )
    merged.is_franchise = (
        len(merged.seasons) > 1
        or detect_franchise(query, merged.raw_titles)
    )

    validate_result(merged)
    return merged


def validate_result(info: AnimeInfo):
    if info.total_episodes is not None and not 1 <= info.total_episodes <= 2000:
        info.total_episodes = None

    if info.released_episodes is not None and not 0 <= info.released_episodes <= 2000:
        info.released_episodes = None

    if info.total_episodes and info.released_episodes:
        info.released_episodes = min(
            info.released_episodes,
            info.total_episodes,
        )

    if info.last_episode and info.total_episodes:
        info.last_episode = min(
            info.last_episode,
            info.total_episodes,
        )

    if "Hindi" in info.languages:
        info.hindi_dub = True

    if info.status == "Completed" and info.total_episodes:
        info.released_episodes = info.total_episodes
        info.last_episode = info.total_episodes

    info.languages = unique_list(info.languages)
    info.platforms = unique_list(info.platforms)


# =========================
# MAIN SERVICE
# =========================

class AnimeService:
    def __init__(self, enable_jikan: bool = True):
        self.http = HTTPClient()
        self.rare = RareAnimesSource(self.http)
        self.mirchi = AnimeMirchiSource(self.http)
        self.jikan = JikanSource(self.http) if enable_jikan else None
        self.cache: dict[str, tuple[float, AnimeInfo]] = {}
        self.cache_ttl = 15 * 60

    async def get_anime(self, query: str) -> Optional[AnimeInfo]:
        query = clean_text(query)
        if not query:
            return None

        key = normalize_title(query)
        cached = self.cache.get(key)
        if cached and time.time() - cached[0] < self.cache_ttl:
            return cached[1]

        result = await asyncio.to_thread(self._get_anime_sync, query)
        if result:
            self.cache[key] = (time.time(), result)
        return result

    def _get_anime_sync(self, query: str) -> Optional[AnimeInfo]:
        results = []

        try:
            for candidate in self.rare.search(query)[:5]:
                if candidate["score"] < 45:
                    continue
                parsed = self.rare.parse_page(candidate["url"], query)
                if parsed:
                    parsed.confidence = candidate["score"] / 100
                    results.append(parsed)
        except Exception as exc:
            logger.exception("RareAnimes error: %s", exc)

        try:
            for candidate in self.mirchi.search(query)[:5]:
                if candidate["score"] < 45:
                    continue
                parsed = self.mirchi.parse_page(candidate["url"], query)
                if parsed:
                    parsed.confidence = max(
                        parsed.confidence,
                        candidate["score"] / 100,
                    )
                    results.append(parsed)
        except Exception as exc:
            logger.exception("Anime Mirchi error: %s", exc)

        if self.jikan:
            try:
                data = self.jikan.search(query)
                if data:
                    info = self.jikan.to_anime_info(data, query)
                    if info:
                        info.confidence = 0.70
                        results.append(info)
            except Exception as exc:
                logger.warning("Jikan error: %s", exc)

        return merge_anime_results(results, query)

    async def get_anime_text(self, query: str) -> Optional[str]:
        info = await self.get_anime(query)
        return format_anime_info(info) if info else None

    async def get_today_updates(
        self,
        target_date: Optional[date] = None,
    ) -> list[ScheduleItem]:
        target_date = target_date or datetime.now().date()
        return await asyncio.to_thread(
            self._get_today_updates_sync,
            target_date,
        )

    def _get_today_updates_sync(
        self,
        target_date: date,
    ) -> list[ScheduleItem]:

        all_items = []

        try:
            response = self.http.get(ANIME_MIRCHI_BASE)
            if response:
                soup = BeautifulSoup(response.text, "lxml")
                urls = []

                for anchor in soup.select(
                    "article a[href], h2 a[href], h3 a[href]"
                ):
                    href = anchor.get("href")
                    if not href:
                        continue
                    href = urljoin(ANIME_MIRCHI_BASE, href)
                    if urlparse(href).netloc == urlparse(ANIME_MIRCHI_BASE).netloc:
                        urls.append(href)

                for url in unique_list(urls)[:15]:
                    try:
                        page = self.http.get(url)
                        if not page:
                            continue
                        page_soup = BeautifulSoup(page.text, "lxml")
                        all_items.extend(
                            self.mirchi.parse_schedule_page(
                                url,
                                soup=page_soup,
                            )
                        )
                    except Exception:
                        continue
        except Exception as exc:
            logger.warning("Daily schedule scan failed: %s", exc)

        target = target_date.isoformat()
        filtered = []

        for item in all_items:
            if not item.date:
                continue
            normalized = parse_date_string(item.date) or item.date
            if normalized == target:
                filtered.append(item)

        unique = {}
        for item in filtered:
            key = (
                normalize_title(item.anime),
                item.season.lower(),
                item.episode,
                item.date,
                item.time_ist,
                tuple(sorted(x.lower() for x in item.languages)),
            )
            unique[key] = item

        output = list(unique.values())
        output.sort(key=lambda x: (x.time_ist or "", x.anime.lower()))
        return output

    async def get_today_updates_text(
        self,
        target_date: Optional[date] = None,
    ) -> str:
        target_date = target_date or datetime.now().date()
        items = await self.get_today_updates(target_date)
        return format_daily_updates(items, target_date)

    def close(self):
        self.http.close()


# =========================
# FORMATTERS
# =========================

def format_hindi_status(info: AnimeInfo) -> str:
    if info.hindi_dub is True:
        return "🇮🇳 Hindi Dub: ✅ Available"
    if info.hindi_dub is False:
        return "🇮🇳 Hindi Dub: ❌ Not Found"
    return "🇮🇳 Hindi Dub: ⚠️ Information unavailable"


def format_anime_info(info: AnimeInfo) -> str:
    lines = [
        f"🎬 Anime: {info.title}",
        "",
        format_hindi_status(info),
    ]

    lines.append(
        "📺 Platform: "
        + (" • ".join(info.platforms) if info.platforms else "⚠️ Not confirmed")
    )

    if info.seasons:
        lines.extend(["", "📀 Seasons:"])
        for s in info.seasons:
            n = s.number if s.number else "?"
            if s.episodes and s.released_episodes and s.released_episodes < s.episodes:
                ep = f"{s.released_episodes}/{s.episodes}"
            elif s.episodes:
                ep = str(s.episodes)
            elif s.released_episodes:
                ep = f"{s.released_episodes} released"
            else:
                ep = "Unknown"

            lines.append(f"• Season {n}: {ep} Episodes")
    elif info.total_episodes:
        if (
            info.status == "Ongoing"
            and info.released_episodes
            and info.released_episodes < info.total_episodes
        ):
            lines.append(
                f"🎞 Episodes: {info.released_episodes}/{info.total_episodes}"
            )
        else:
            lines.append(f"🎞 Episodes: {info.total_episodes}")
    elif info.released_episodes:
        lines.append(f"🎞 Episodes Released: {info.released_episodes}")

    if info.languages:
        lines.append("🌐 Languages: " + " • ".join(info.languages))

    status = {
        "Ongoing": "🔄 Ongoing",
        "Completed": "✅ Completed",
    }.get(info.status, "⚠️ Unknown")
    lines.append(f"📊 Status: {status}")

    if info.last_episode:
        lines.append(f"📅 Last Episode: Episode {info.last_episode}")

    if info.last_release:
        lines.append(f"🗓 Last Release: {info.last_release}")

    if info.status == "Ongoing":
        if info.next_episode:
            lines.append(f"⏭ Next Episode: Episode {info.next_episode}")
        if info.next_release:
            lines.append(f"🗓 Next Release: {info.next_release}")
        if info.next_time_ist:
            lines.append(f"⏰ Time: {info.next_time_ist} IST")

    if info.studio:
        lines.append(f"🏢 Studio: {info.studio}")

    if info.sources:
        lines.append("🔎 Source: " + " • ".join(info.sources))

    return "\n".join(lines)


def format_daily_updates(
    items: list[ScheduleItem],
    target_date: date,
) -> str:
    date_display = target_date.strftime("%d %B %Y")
    lines = [
        "📅 TODAY'S ANIME DUB UPDATE",
        date_display,
        "",
    ]

    if not items:
        lines.append(
            "ℹ️ Aaj ke liye confirmed anime/dub schedule nahi mila."
        )
        lines.append("")
        lines.append("🔎 Source: Anime Mirchi")
        return "\n".join(lines)

    hindi = [x for x in items if "Hindi" in x.languages]
    other = [x for x in items if "Hindi" not in x.languages]

    def add_group(title: str, group: list[ScheduleItem]):
        if not group:
            return
        lines.extend([title, ""])
        for i, item in enumerate(group, 1):
            lines.append(f"{i}. 🎬 {item.anime}")
            if item.season:
                lines.append(f"   📀 {item.season}")
            if item.episode:
                lines.append(f"   🎞 Episode {item.episode}")
            if item.languages:
                lines.append("   🌐 " + " • ".join(item.languages))
            if item.platform:
                lines.append(f"   📺 {item.platform}")
            if item.time_ist:
                lines.append(f"   ⏰ {item.time_ist} IST")
            lines.append("")

    add_group("🇮🇳 HINDI DUB", hindi)
    add_group("🌐 OTHER LANGUAGE UPDATES", other)

    lines.extend([
        "━━━━━━━━━━━━━━━━",
        "🔎 Source: Anime Mirchi",
    ])
    return "\n".join(lines)


# =========================
# JSON HELPERS
# =========================

def anime_to_dict(info: AnimeInfo) -> dict:
    return asdict(info)


def schedule_to_dict(item: ScheduleItem) -> dict:
    return asdict(item)


def anime_to_json(info: AnimeInfo) -> str:
    return json.dumps(anime_to_dict(info), ensure_ascii=False, indent=2)


# =========================
# DIRECT TEST
# =========================

async def _test_anime(query: str):
    service = AnimeService()
    try:
        info = await service.get_anime(query)
        if not info:
            print("❌ Anime information not found.")
            return
        print(format_anime_info(info))
    finally:
        service.close()


async def _test_today():
    service = AnimeService()
    try:
        print(await service.get_today_updates_text())
    finally:
        service.close()


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        if sys.argv[1].lower() == "today":
            asyncio.run(_test_today())
        else:
            asyncio.run(_test_anime(" ".join(sys.argv[1:])))
    else:
        print("Usage:")
        print("  python anime_service.py Naruto")
        print("  python anime_service.py Solo Leveling")
        print("  python anime_service.py today")
