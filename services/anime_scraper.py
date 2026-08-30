"""
Anime Mirchi Web Scraper Service
Fetches Hindi-dubbed anime information from Anime Mirchi.
"""

import re
import time
from typing import Dict, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from config import (
    ANIME_MIRCHI_BASE_URL,
    ANIME_MIRCHI_SEARCH_URL,
    REQUEST_TIMEOUT,
    MAX_RETRIES,
    RETRY_DELAY,
)

from utils.logger import logger


class AnimeScraper:
    """Scraper for Anime Mirchi."""

    def __init__(self):
        self.base_url = ANIME_MIRCHI_BASE_URL.rstrip("/")
        self.search_url = ANIME_MIRCHI_SEARCH_URL

        self.session = requests.Session()

        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/120.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.9",
        })

    def search_anime(self, anime_name: str) -> Optional[Dict]:
        """Search for an anime."""

        if not anime_name or not anime_name.strip():
            return None

        query = anime_name.strip()

        logger.info("Searching for anime: %s", query)

        html = self._request(
            self.search_url,
            params={"s": query},
        )

        if not html:
            return None

        soup = BeautifulSoup(
            html,
            "html.parser",
        )

        candidates = []

        for link in soup.find_all("a", href=True):
            title = link.get_text(" ", strip=True)
            href = link.get("href", "").strip()

            if not title or not href:
                continue

            if self._matches(title, query):
                candidates.append({
                    "title": title,
                    "url": urljoin(
                        self.base_url + "/",
                        href,
                    ),
                })

        # Remove duplicate URLs
        unique = []
        seen = set()

        for item in candidates:
            if item["url"] in seen:
                continue

            seen.add(item["url"])
            unique.append(item)

        if not unique:
            logger.info(
                "Anime not found: %s",
                query,
            )
            return None

        best = self._best_match(
            unique,
            query,
        )

        article_html = self._request(
            best["url"]
        )

        if not article_html:
            return {
                "name": best["title"],
                "hindi_dub": "Status Unknown",
                "platform": None,
                "hindi_details": None,
                "english_dub": None,
                "episodes": None,
                "poster_url": None,
                "source_link": best["url"],
            }

        return self._parse_article(
            article_html,
            best["title"],
            best["url"],
        )

    def _request(
        self,
        url: str,
        params=None,
    ) -> Optional[str]:
        """Fetch webpage with retries."""

        for attempt in range(
            MAX_RETRIES + 1
        ):
            try:
                response = self.session.get(
                    url,
                    params=params,
                    timeout=REQUEST_TIMEOUT,
                )

                response.raise_for_status()

                return response.text

            except requests.RequestException as error:

                logger.warning(
                    "Request failed %s/%s: %s",
                    attempt + 1,
                    MAX_RETRIES + 1,
                    error,
                )

                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_DELAY)

        return None

    def _parse_article(
        self,
        html: str,
        title: str,
        source_url: str,
    ) -> Dict:
        """Parse anime article."""

        soup = BeautifulSoup(
            html,
            "html.parser",
        )

        article = (
            soup.find("article")
            or soup.find("main")
            or soup.body
            or soup
        )

        text = article.get_text(
            " ",
            strip=True,
        )

        poster_url = self._extract_poster(
            article,
            source_url,
        )

        platform = self._extract_platform(
            text
        )

        hindi_details = self._extract_hindi_details(
            text
        )

        return {
            "name": self._clean_title(title),
            "hindi_dub": self._extract_hindi_status(
                text
            ),
            "platform": platform,
            "hindi_details": hindi_details,
            "english_dub": self._extract_english_status(
                text
            ),
            "episodes": self._extract_episodes(
                text
            ),
            "poster_url": poster_url,
            "source_link": source_url,
        }

    @staticmethod
    def _extract_poster(
        article,
        source_url: str,
    ) -> Optional[str]:
        """Extract poster image URL."""

        # Try OpenGraph image first
        parent = article

        image = parent.find(
            "img",
            src=True,
        )

        if image:
            src = (
                image.get("src")
                or image.get("data-src")
                or image.get("data-lazy-src")
            )

            if src:
                return urljoin(
                    source_url,
                    src,
                )

        # Try lazy-loaded images
        for image in article.find_all("img"):
            src = (
                image.get("data-src")
                or image.get("data-lazy-src")
                or image.get("src")
            )

            if src:
                return urljoin(
                    source_url,
                    src,
                )

        return None

    @staticmethod
    def _clean_title(
        title: str,
    ) -> str:
        """Clean title."""

        title = re.sub(
            r"\s+[-|–]\s+Anime Mirchi.*$",
            "",
            title,
            flags=re.I,
        )

        return title.strip()

    @staticmethod
    def _matches(
        title: str,
        query: str,
    ) -> bool:
        """Check search result match."""

        title_lower = title.lower().strip()
        query_lower = query.lower().strip()

        if query_lower in title_lower:
            return True

        query_words = re.findall(
            r"[a-z0-9]+",
            query_lower,
        )

        title_words = re.findall(
            r"[a-z0-9]+",
            title_lower,
        )

        return bool(
            query_words
            and all(
                word in title_words
                for word in query_words
            )
        )

    @staticmethod
    def _best_match(
        candidates,
        query: str,
    ) -> Dict:
        """Choose best search result."""

        query_lower = query.lower().strip()

        for item in candidates:
            if (
                item["title"]
                .lower()
                .strip()
                == query_lower
            ):
                return item

        for item in candidates:
            if (
                item["title"]
                .lower()
                .startswith(query_lower)
            ):
                return item

        return candidates[0]

    @staticmethod
    def _extract_hindi_status(
        text: str,
    ) -> str:
        """Detect Hindi dub status."""

        lower = text.lower()

        negative = [
            "hindi dub not available",
            "hindi dubbed not available",
            "no hindi dub",
            "without hindi dub",
            "hindi audio not available",
            "not available in hindi",
        ]

        for phrase in negative:
            if phrase in lower:
                return "Not Available"

        positive = [
            "hindi dub",
            "hindi dubbed",
            "hindi audio",
            "dubbed in hindi",
            "hindi version",
        ]

        for phrase in positive:
            if phrase in lower:
                return "Available"

        return "Status Unknown"

    @staticmethod
    def _extract_hindi_details(
        text: str,
    ) -> Optional[str]:
        """Extract useful Hindi-dub information."""

        lower = text.lower()

        if "crunchyroll" in lower and (
            "sony yay" in lower
            or "sony yay!" in lower
        ):
            return (
                "Anime Mirchi ke mutabik "
                "Crunchyroll par available Hindi dub "
                "wahi dub hai jo pehle Sony YAY! par "
                "aired hua tha."
            )

        if "sony yay" in lower:
            return (
                "Hindi dub Sony YAY! par "
                "aired hua tha."
            )

        return None

    @staticmethod
    def _extract_platform(
        text: str,
    ) -> Optional[str]:
        """Detect platform."""

        lower = text.lower()

        platforms = [
            (
                "Crunchyroll India",
                ["crunchyroll"],
            ),
            (
                "Amazon MX Player",
                ["amazon mx player"],
            ),
            (
                "MX Player",
                ["mx player"],
            ),
            (
                "Netflix",
                ["netflix"],
            ),
            (
                "Amazon Prime Video",
                ["amazon prime", "prime video"],
            ),
            (
                "Disney+ Hotstar",
                ["disney+ hotstar", "disney hotstar"],
            ),
            (
                "Disney+",
                ["disney+", "disney plus"],
            ),
            (
                "ZEE5",
                ["zee5"],
            ),
            (
                "SonyLIV",
                ["sonyliv", "sony liv"],
            ),
        ]

        for platform, keywords in platforms:
            for keyword in keywords:
                if keyword in lower:
                    return platform

        return None

    @staticmethod
    def _extract_english_status(
        text: str,
    ) -> Optional[str]:
        """Detect English dub."""

        lower = text.lower()

        negative = [
            "english dub not available",
            "english dubbed not available",
            "no english dub",
        ]

        for phrase in negative:
            if phrase in lower:
                return "Not Available"

        positive = [
            "english dub",
            "english dubbed",
            "dubbed in english",
            "english audio",
        ]

        for phrase in positive:
            if phrase in lower:
                return "Available"

        return None

    @staticmethod
    def _extract_episodes(
        text: str,
    ) -> Optional[str]:
        """Extract episode count."""

        patterns = [
            r"(\d+)\s*/\s*(\d+)\s*episodes?",
            r"(\d+)\s*episodes?",
        ]

        for pattern in patterns:

            match = re.search(
                pattern,
                text,
                re.I,
            )

            if match:

                if match.lastindex == 2:
                    return (
                        f"{match.group(1)}/"
                        f"{match.group(2)}"
                    )

                return match.group(1)

        return None


anime_scraper = AnimeScraper()


def get_anime_info(
    anime_name: str,
) -> Optional[Dict]:
    """Return anime information."""

    return anime_scraper.search_anime(
        anime_name
                )
