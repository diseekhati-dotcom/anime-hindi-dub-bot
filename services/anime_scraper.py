"""
Anime Mirchi Web Scraper Service
Fetches Hindi-dubbed anime information from Anime Mirchi.
"""

import re
import time
from typing import Dict, Optional
from urllib.parse import quote, urljoin

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
"""Scraper for publicly available Anime Mirchi information."""

def __init__(self):
    self.base_url = ANIME_MIRCHI_BASE_URL.rstrip("/")
    self.search_url = ANIME_MIRCHI_SEARCH_URL

    self.session = requests.Session()
    self.session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        }
    )

def search_anime(self, anime_name: str) -> Optional[Dict]:
    """Search Anime Mirchi and return matching anime information."""

    if not anime_name or not anime_name.strip():
        return None

    query = anime_name.strip()
    logger.info("Searching Anime Mirchi for: %s", query)

    html = self._request(
        self.search_url,
        params={"s": query},
    )

    if not html:
        return None

    soup = BeautifulSoup(html, "html.parser")

    # First try normal WordPress search-result links.
    candidates = []

    for link in soup.find_all("a", href=True):
        title = link.get_text(" ", strip=True)
        href = link.get("href", "").strip()

        if not title or not href:
            continue

        if self._is_matching_title(title, query):
            candidates.append(
                {
                    "title": title,
                    "url": urljoin(self.base_url + "/", href),
                }
            )

    # Remove duplicates.
    unique = []
    seen = set()

    for candidate in candidates:
        url = candidate["url"]

        if url not in seen:
            seen.add(url)
            unique.append(candidate)

    if not unique:
        logger.info("No Anime Mirchi search result found for: %s", query)
        return None

    # Prefer the closest title match.
    best = self._choose_best_match(unique, query)

    # Fetch the actual article page.
    article_html = self._request(best["url"])

    if not article_html:
        return {
            "name": best["title"],
            "hindi_dub": "Status Unknown",
            "platform": None,
            "english_dub": None,
            "episodes": None,
            "source_link": best["url"],
        }

    return self._parse_article(
        article_html,
        best["title"],
        best["url"],
    )

def _request(self, url: str, params=None) -> Optional[str]:
    """Request a page with retries."""

    for attempt in range(MAX_RETRIES + 1):
        try:
            response = self.session.get(
                url,
                params=params,
                timeout=REQUEST_TIMEOUT,
            )
            response.raise_for_status()

            return response.text

        except requests.RequestException as exc:
            logger.warning(
                "Request failed (%s/%s): %s",
                attempt + 1,
                MAX_RETRIES + 1,
                exc,
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
    """Extract information from an Anime Mirchi article."""

    soup = BeautifulSoup(html, "html.parser")

    # Prefer article/main content instead of the whole page.
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

    return {
        "name": self._clean_title(title),
        "hindi_dub": self._extract_hindi_status(text),
        "platform": self._extract_platform(text),
        "english_dub": self._extract_english_status(text),
        "episodes": self._extract_episodes(text),
        "source_link": source_url,
    }

@staticmethod
def _clean_title(title: str) -> str:
    """Clean common search-result title noise."""

    title = re.sub(
        r"\s+[-|–]\s+Anime Mirchi.*$",
        "",
        title,
        flags=re.I,
    )

    return title.strip()

@staticmethod
def _is_matching_title(title: str, query: str) -> bool:
    """Check whether a search result is relevant."""

    title_words = set(
        re.findall(r"[a-z0-9]+", title.lower())
    )
    query_words = set(
        re.findall(r"[a-z0-9]+", query.lower())
    )

    if not query_words:
        return False

    title_lower = title.lower()
    query_lower = query.lower()

    if query_lower in title_lower:
        return True

    # All query words should occur in the title.
    return query_words.issubset(title_words)

@staticmethod
def _choose_best_match(
    candidates,
    query: str,
) -> Dict:
    """Choose the closest title match."""

    query_lower = query.lower().strip()

    # Exact title match first.
    for item in candidates:
        if item["title"].lower().strip() == query_lower:
            return item

    # Then title beginning with the query.
    for item in candidates:
        if item["title"].lower().startswith(query_lower):
            return item

    return candidates[0]

@staticmethod
def _extract_hindi_status(text: str) -> str:
    """Detect Hindi-dub information."""

    lower = text.lower()

    negative_patterns = (
        "hindi dub not available",
        "hindi dubbed not available",
        "no hindi dub",
        "without hindi dub",
        "hindi audio not available",
        "not available in hindi",
    )

    for pattern in negative_patterns:
        if pattern in lower:
            return "Not Available"

    positive_patterns = (
        "hindi dub",
        "hindi dubbed",
        "hindi audio",
        "dubbed in hindi",
        "hindi version",
    )

    for pattern in positive_patterns:
        if pattern in lower:
            return "Available"

    return "Status Unknown"

@staticmethod
def _extract_platform(text: str) -> Optional[str]:
    """Find streaming platform mentioned in the article."""

    lower = text.lower()

    platforms = (
        ("Crunchyroll", ("crunchyroll",)),
        ("Amazon MX Player", ("amazon mx player",)),
        ("MX Player", ("mx player",)),
        ("Netflix", ("netflix",)),
        ("Amazon Prime Video", ("amazon prime", "prime video")),
        ("Disney+ Hotstar", ("disney+ hotstar", "disney hotstar")),
        ("Disney+", ("disney+", "disney plus")),
        ("ZEE5", ("zee5",)),
        ("SonyLIV", ("sonyliv", "sony liv")),
    )

    for platform, keywords in platforms:
        if any(keyword in lower for keyword in keywords):
            return platform

    return None

@staticmethod
def _extract_english_status(text: str) -> Optional[str]:
    """Find English-dub information when explicitly mentioned."""

    lower = text.lower()

    negative = (
        "english dub not available",
        "english dubbed not available",
        "no english dub",
    )

    if any(item in lower for item in negative):
        return "Not Available"

    positive = (
        "english dub",
        "english dubbed",
        "dubbed in english",
        "english audio",
    )

    if any(item in lower for item in positive):
        return "Available"

    return None

@staticmethod
def _extract_episodes(text: str) -> Optional[str]:
    """Extract a simple episode count when explicitly mentioned."""

    patterns = (
        r"(\d+)\s*(?:/\s*(\d+))?\s*episodes?",
        r"(\d+)\s*episodes?\s*(?:in total)?",
    )

    for pattern in patterns:
        match = re.search(pattern, text, re.I)

        if match:
            if match.group(2):
                return f"{match.group(1)}/{match.group(2)}"
            return match.group(1)

    return None

anime_scraper = AnimeScraper()

def get_anime_info(anime_name: str) -> Optional[Dict]:
"""Return anime information for the supplied name."""

return anime_scraper.search_anime(anime_name)
