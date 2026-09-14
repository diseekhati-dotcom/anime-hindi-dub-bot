"""
anime_scraper.py
Anime Hindi Info Bot - scraper module
"""

from __future__ import annotations

import asyncio
import html
import logging
import re
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import quote_plus, urljoin

import aiohttp
from bs4 import BeautifulSoup


JIKAN_API = "https://api.jikan.moe/v4"
RARE_ANIMES = "https://www.rareanimes.mov"
ANIME_MIRCHI = "https://animemirchi.com"

REQUEST_TIMEOUT = 20

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("anime_scraper")


@dataclass
class SeasonInfo:
    season_number: int
    title: str
    episodes: Optional[int] = None
    aired_from: Optional[str] = None
    aired_to: Optional[str] = None


@dataclass
class DubInfo:
    available: bool = False
    languages: list[str] | None = None
    platforms: list[str] | None = None
    sources: list[str] | None = None
    dub_source: Optional[str] = None


@dataclass
class AnimeInfo:
    title: str
    mal_id: Optional[int] = None
    japanese_title: Optional[str] = None
    type: Optional[str] = None
    status: Optional[str] = None
    status_hindi: Optional[str] = None
    total_episodes: Optional[int] = None
    episodes_released: Optional[int] = None
    season: Optional[str] = None
    seasons: list[SeasonInfo] | None = None
    studios: list[str] | None = None
    aired_from: Optional[str] = None
    aired_to: Optional[str] = None
    next_episode_date: Optional[str] = None
    languages: list[str] | None = None
    dub: DubInfo | None = None
    synopsis: Optional[str] = None
    sources: list[str] | None = None
    checked_at: Optional[str] = None


class HTTPClient:
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None

    async def start(self):
        if self.session is None or self.session.closed:
            timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
            self.session = aiohttp.ClientSession(
                timeout=timeout,
                headers=HEADERS,
            )

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()

    async def get_text(self, url: str) -> Optional[str]:
        await self.start()
        try:
            async with self.session.get(url) as response:
                if response.status != 200:
                    logger.warning("HTTP %s: %s", response.status, url)
                    return None
                return await response.text(errors="ignore")
        except Exception as exc:
            logger.warning("Request failed: %s | %s", url, exc)
            return None

    async def get_json(self, url: str) -> Optional[dict[str, Any]]:
        await self.start()
        try:
            async with self.session.get(url) as response:
                if response.status != 200:
                    logger.warning("HTTP %s: %s", response.status, url)
                    return None
                return await response.json(content_type=None)
        except Exception as exc:
            logger.warning("JSON request failed: %s | %s", url, exc)
            return None


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    value = html.unescape(str(value))
    return re.sub(r"\s+", " ", value).strip()


def unique(items: list[str]) -> list[str]:
    result = []
    seen = set()
    for item in items:
        item = clean_text(item)
        if not item:
            continue
        key = item.lower()
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result


def normalize_title(title: str) -> str:
    title = clean_text(title)
    title = re.sub(r"\bseason\s+\d+\b", "", title, flags=re.I)
    title = re.sub(r"\bs\d+\b", "", title, flags=re.I)
    title = re.sub(r"\bpart\s+\d+\b", "", title, flags=re.I)
    return re.sub(r"\s+", " ", title).strip(" -_:|")


def iso_to_date(value: Optional[str]) -> Optional[str]:
    return value[:10] if value else None


def parse_episode_numbers(text: str) -> list[int]:
    matches = re.findall(
        r"(?:episode|ep)\s*[-.#:]?\s*(\d{1,4})",
        text,
        flags=re.I,
    )
    return [int(x) for x in matches]


def detect_languages(text: str) -> list[str]:
    text_lower = text.lower()

    patterns = {
        "Hindi": ["hindi", "hin", "hindi dub", "hindi dubbed"],
        "English": ["english", "eng", "english dub", "english dubbed"],
        "Tamil": ["tamil", "tam", "tamil dub", "tamil dubbed"],
        "Telugu": ["telugu", "tel", "telugu dub", "telugu dubbed"],
        "Malayalam": ["malayalam", "mal"],
        "Kannada": ["kannada", "kan"],
        "Japanese": ["japanese", "japan", "jap"],
    }

    found = []
    for language, words in patterns.items():
        if any(word in text_lower for word in words):
            found.append(language)
    return unique(found)


def detect_platform(text: str) -> list[str]:
    text_lower = text.lower()

    patterns = {
        "Crunchyroll": ["crunchyroll"],
        "Sony YAY!": ["sony yay", "sony yay!"],
        "Anime Times": ["anime times"],
        "Ani-One India": ["ani-one india", "ani-one"],
        "Muse India": ["muse india", "muse"],
        "JioHotstar": ["jiohotstar", "jio hotstar"],
        "ZEE5": ["zee5"],
        "Zee Café": ["zee café", "zee cafe"],
        "Amazon Prime Video": ["amazon prime", "prime video"],
        "Netflix": ["netflix"],
    }

    found = []
    for platform, words in patterns.items():
        if any(word in text_lower for word in words):
            found.append(platform)
    return unique(found)


class JikanScraper:
    def __init__(self, client: HTTPClient):
        self.client = client

    async def search(self, anime_name: str) -> Optional[dict]:
        url = f"{JIKAN_API}/anime?q={quote_plus(anime_name)}&limit=5"
        data = await self.client.get_json(url)

        if not data or not data.get("data"):
            return None

        results = data["data"]
        requested = normalize_title(anime_name).lower()

        for anime in results:
            for title in (
                anime.get("title"),
                anime.get("title_english"),
                anime.get("title_japanese"),
            ):
                if title and normalize_title(title).lower() == requested:
                    return anime

        return results[0]

    async def get_full_info(self, anime_id: int) -> Optional[dict]:
        return await self.client.get_json(f"{JIKAN_API}/anime/{anime_id}/full")

    async def get_episodes(self, anime_id: int) -> list[dict]:
        episodes = []
        page = 1

        while True:
            data = await self.client.get_json(
                f"{JIKAN_API}/anime/{anime_id}/episodes?page={page}"
            )
            if not data:
                break

            current = data.get("data", [])
            if not current:
                break

            episodes.extend(current)

            if not data.get("pagination", {}).get("has_next_page", False):
                break

            page += 1
            await asyncio.sleep(0.3)

        return episodes


class RareAnimesScraper:
    def __init__(self, client: HTTPClient):
        self.client = client

    async def search(self, anime_name: str) -> list[dict]:
        url = f"{RARE_ANIMES}/?s={quote_plus(anime_name)}"
        page = await self.client.get_text(url)
        if not page:
            return []

        soup = BeautifulSoup(page, "html.parser")
        results = []

        for link in soup.select("a[href]"):
            title = clean_text(link.get_text(" ", strip=True))
            href = link.get("href")

            if not title or not href or len(title) < 3:
                continue

            if (
                "anime" in title.lower()
                or normalize_title(anime_name).lower() in title.lower()
            ):
                results.append(
                    {
                        "title": title,
                        "url": urljoin(RARE_ANIMES, href),
                    }
                )

        final = []
        seen = set()
        for item in results:
            if item["url"] not in seen:
                seen.add(item["url"])
                final.append(item)

        return final[:10]

    async def parse_page(self, url: str) -> dict:
        page = await self.client.get_text(url)
        if not page:
            return {}

        soup = BeautifulSoup(page, "html.parser")
        text = clean_text(soup.get_text(" ", strip=True))

        data = {
            "url": url,
            "title": clean_text(soup.h1.get_text(" ", strip=True)) if soup.h1 else None,
            "season": None,
            "episodes": None,
            "year": None,
            "runtime": None,
            "languages": detect_languages(text),
            "platforms": detect_platform(text),
            "episode_numbers": parse_episode_numbers(text),
            "raw_text": text,
        }

        season_match = re.search(r"(?:Season|S)\s*[:.-]?\s*(\d+)", text, re.I)
        if season_match:
            data["season"] = int(season_match.group(1))

        for pattern in (
            r"Episodes?\s*[:.-]?\s*(\d+)",
            r"(\d+)\s+Episodes?",
            r"EP\s*[:.-]?\s*(\d+)",
        ):
            match = re.search(pattern, text, re.I)
            if match:
                data["episodes"] = int(match.group(1))
                break

        year_match = re.search(
            r"(?:Release Year|Year)\s*[:.-]?\s*(20\d{2}|19\d{2})",
            text,
            re.I,
        )
        if year_match:
            data["year"] = int(year_match.group(1))

        return data

    async def find_anime(self, anime_name: str) -> list[dict]:
        results = await self.search(anime_name)
        parsed = []

        for result in results:
            info = await self.parse_page(result["url"])
            if info:
                info["search_title"] = result["title"]
                parsed.append(info)

        return parsed


class AnimeMirchiScraper:
    def __init__(self, client: HTTPClient):
        self.client = client

    async def search(self, anime_name: str) -> list[dict]:
        url = f"{ANIME_MIRCHI}/?s={quote_plus(anime_name)}"
        page = await self.client.get_text(url)
        if not page:
            return []

        soup = BeautifulSoup(page, "html.parser")
        results = []

        for article in soup.select("article"):
            link = article.select_one("a[href]")
            if not link:
                continue

            title = clean_text(link.get_text(" ", strip=True))
            href = link.get("href")

            if title and href:
                results.append(
                    {
                        "title": title,
                        "url": urljoin(ANIME_MIRCHI, href),
                    }
                )

        return results[:10]

    async def parse_page(self, url: str) -> dict:
        page = await self.client.get_text(url)
        if not page:
            return {}

        soup = BeautifulSoup(page, "html.parser")
        text = clean_text(soup.get_text(" ", strip=True))

        return {
            "url": url,
            "title": clean_text(soup.h1.get_text(" ", strip=True)) if soup.h1 else None,
            "languages": detect_languages(text),
            "platforms": detect_platform(text),
            "raw_text": text,
        }

    async def find_anime(self, anime_name: str) -> list[dict]:
        results = await self.search(anime_name)
        parsed = []

        for result in results:
            info = await self.parse_page(result["url"])
            if info:
                info["search_title"] = result["title"]
                parsed.append(info)

        return parsed


class DubDetector:
    def __init__(self, rare: RareAnimesScraper, mirchi: AnimeMirchiScraper):
        self.rare = rare
        self.mirchi = mirchi

    async def get_dub_info(self, anime_name: str) -> DubInfo:
        rare_results, mirchi_results = await asyncio.gather(
            self.rare.find_anime(anime_name),
            self.mirchi.find_anime(anime_name),
        )

        languages = []
        platforms = []
        sources = []

        for item in rare_results + mirchi_results:
            languages.extend(item.get("languages", []))
            platforms.extend(item.get("platforms", []))
            if item.get("url"):
                sources.append(item["url"])

        languages = unique(languages)
        platforms = unique(platforms)
        sources = unique(sources)

        hindi_available = "Hindi" in languages
        dub_source = None

        if hindi_available:
            for platform in (
                "Crunchyroll",
                "Sony YAY!",
                "Anime Times",
                "Ani-One India",
                "Muse India",
                "JioHotstar",
                "ZEE5",
            ):
                if platform in platforms:
                    dub_source = platform
                    break

            if dub_source is None:
                dub_source = "Verified source"

        return DubInfo(
            available=hindi_available,
            languages=languages,
            platforms=platforms,
            sources=sources,
            dub_source=dub_source,
        )


class AnimeScraper:
    def __init__(self):
        self.client = HTTPClient()
        self.jikan = JikanScraper(self.client)
        self.rare = RareAnimesScraper(self.client)
        self.mirchi = AnimeMirchiScraper(self.client)
        self.dub_detector = DubDetector(self.rare, self.mirchi)

    async def close(self):
        await self.client.close()

    async def get_anime(self, anime_name: str) -> Optional[AnimeInfo]:
        search_result = await self.jikan.search(anime_name)

        if not search_result:
            return None

        mal_id = search_result.get("mal_id")
        full = await self.jikan.get_full_info(mal_id) or search_result

        title = full.get("title") or anime_name
        status = full.get("status")
        status_short = (
            "Ongoing" if status == "Currently Airing"
            else "Completed" if status == "Finished Airing"
            else status
        )

        episodes = full.get("episodes")
        aired = full.get("aired", {})
        studios = [
            item.get("name")
            for item in full.get("studios", [])
            if item.get("name")
        ]

        season = full.get("season")
        year = full.get("year")
        season_name = None

        if season and year:
            season_name = f"{season.title()} {year}"
        elif season:
            season_name = season.title()

        dub_info = await self.dub_detector.get_dub_info(title)

        languages = unique(["Japanese"] + (dub_info.languages or []))

        broadcast = full.get("broadcast", {})
        next_episode = broadcast.get("string") if status_short == "Ongoing" else None

        seasons = []
        if season_name:
            seasons.append(
                SeasonInfo(
                    season_number=1,
                    title=season_name,
                    episodes=episodes,
                    aired_from=iso_to_date(aired.get("from")),
                    aired_to=iso_to_date(aired.get("to")),
                )
            )

        return AnimeInfo(
            title=title,
            mal_id=mal_id,
            japanese_title=full.get("title_japanese"),
            type=full.get("type"),
            status=status,
            status_hindi=status_short,
            total_episodes=episodes,
            episodes_released=episodes,
            season=season_name,
            seasons=seasons,
            studios=studios,
            aired_from=iso_to_date(aired.get("from")),
            aired_to=iso_to_date(aired.get("to")),
            next_episode_date=next_episode,
            languages=languages,
            dub=dub_info,
            synopsis=full.get("synopsis"),
            sources=unique(
                [
                    f"https://myanimelist.net/anime/{mal_id}",
                    *(dub_info.sources or []),
                ]
            ),
            checked_at=datetime.now(timezone.utc).isoformat(),
        )


def format_anime_info(anime: AnimeInfo) -> str:
    dub = anime.dub or DubInfo()

    hindi_status = "✅ Available" if dub.available else "❌ Not Found"
    platforms = " • ".join(dub.platforms or []) or "Not verified"
    languages = " • ".join(anime.languages or []) or "Unknown"
    studios = " • ".join(anime.studios or []) or "Unknown"

    if anime.status_hindi == "Ongoing":
        episode_line = (
            f"📺 <b>Episodes Released:</b> "
            f"{anime.episodes_released or 'Unknown'}"
        )
    else:
        episode_line = (
            f"📺 <b>Episodes:</b> "
            f"{anime.total_episodes or 'Unknown'}"
        )

    text = (
        f"🎬 <b>Anime:</b> {html.escape(anime.title)}\n\n"
        f"🇮🇳 <b>Hindi Dub:</b> {hindi_status}\n"
        f"📡 <b>Platform:</b> {html.escape(platforms)}\n"
        f"📀 <b>Season:</b> {html.escape(anime.season or 'Unknown')}\n"
        f"{episode_line}\n\n"
        f"🌐 <b>Languages:</b> {html.escape(languages)}\n\n"
        f"📊 <b>Status:</b> {html.escape(anime.status_hindi or 'Unknown')}\n\n"
        f"🏢 <b>Studio:</b> {html.escape(studios)}\n"
        f"🎙 <b>Dub By:</b> {html.escape(dub.dub_source or 'Not verified')}\n"
    )

    if anime.next_episode_date:
        text += (
            f"\n⏭ <b>Next Episode:</b> "
            f"{html.escape(anime.next_episode_date)}\n"
        )

    if anime.aired_from:
        text += f"\n📅 <b>Started:</b> {anime.aired_from}\n"

    if anime.aired_to:
        text += f"🏁 <b>Ended:</b> {anime.aired_to}\n"

    text += "\n🔎 <b>Source:</b> Jikan/MAL + Indian dub sources"
    return text


class DailyReleaseTracker:
    def __init__(self, client: HTTPClient):
        self.client = client

    async def get_today_releases(self) -> list[dict]:
        """
        Daily release/schedule articles collect karta hai.
        Site layout badalne par parser ko update karna pad sakta hai.
        """
        releases = []

        for keyword in ("anime", "hindi", "dub", "release", "schedule"):
            url = f"{ANIME_MIRCHI}/?s={quote_plus(keyword)}"
            page = await self.client.get_text(url)

            if not page:
                continue

            soup = BeautifulSoup(page, "html.parser")

            for article in soup.select("article"):
                title_el = article.select_one("h2, h3, .entry-title")
                link_el = article.select_one("a[href]")

                if not title_el or not link_el:
                    continue

                title = clean_text(title_el.get_text(" ", strip=True))
                href = link_el.get("href")

                if not title or not href:
                    continue

                lowered = title.lower()
                if not any(
                    word in lowered
                    for word in ("release", "schedule", "hindi", "dub", "anime")
                ):
                    continue

                releases.append(
                    {
                        "anime": title,
                        "episode": None,
                        "language": [],
                        "platform": None,
                        "time": None,
                        "date": None,
                        "source": urljoin(ANIME_MIRCHI, href),
                    }
                )

        final = []
        seen = set()

        for item in releases:
            key = (item["anime"].lower(), item["source"])
            if key not in seen:
                seen.add(key)
                final.append(item)

        return final


async def fetch_anime(anime_name: str) -> Optional[dict]:
    scraper = AnimeScraper()
    try:
        result = await scraper.get_anime(anime_name)
        return asdict(result) if result else None
    finally:
        await scraper.close()


async def fetch_anime_text(anime_name: str) -> Optional[str]:
    scraper = AnimeScraper()
    try:
        result = await scraper.get_anime(anime_name)
        return format_anime_info(result) if result else None
    finally:
        await scraper.close()


async def fetch_today_releases() -> list[dict]:
    client = HTTPClient()
    try:
        tracker = DailyReleaseTracker(client)
        return await tracker.get_today_releases()
    finally:
        await client.close()


async def main():
    scraper = AnimeScraper()

    try:
        anime = await scraper.get_anime("Naruto")

        if anime:
            print(format_anime_info(anime))
        else:
            print("❌ Anime not found.")

    finally:
        await scraper.close()


if __name__ == "__main__":
    asyncio.run(main())
