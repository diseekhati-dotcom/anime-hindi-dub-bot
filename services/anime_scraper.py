"""
Anime Mirchi scraper.

Finds public anime information on Anime Mirchi and extracts:
- anime name
- Hindi dub status
- platform
- Hindi-dub details
- episodes
- poster
- source article
"""

import re
import time
from typing import Dict, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from config import (
    ANIME_MIRCHI_BASE_URL,
    REQUEST_TIMEOUT,
    MAX_RETRIES,
    RETRY_DELAY,
)
from utils.logger import logger


class AnimeScraper:

    def __init__(self):
        self.base_url = ANIME_MIRCHI_BASE_URL.rstrip("/")

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

        if not anime_name or not anime_name.strip():
            return None

        query = anime_name.strip()

        logger.info(
            "Searching Anime Mirchi for: %s",
            query,
        )

        # Try WordPress search first.
        search_html = self._request(
            f"{self.base_url}/",
            params={"s": query},
        )

        candidates = []

        if search_html:
            candidates = self._find_candidates(
                search_html,
                query,
            )

        # If WordPress search doesn't return useful
        # results, inspect the homepage as fallback.
        if not candidates:
            homepage = self._request(
                f"{self.base_url}/"
            )

            if homepage:
                candidates = self._find_candidates(
                    homepage,
                    query,
                )

        # Try common Anime Mirchi content sections.
        if not candidates:
            for section in (
                "/streaming/",
                "/anime-india/",
            ):
                page = self._request(
                    urljoin(
                        self.base_url + "/",
                        section.lstrip("/"),
                    )
                )

                if page:
                    candidates.extend(
                        self._find_candidates(
                            page,
                            query,
                        )
                    )

                if candidates:
                    break

        candidates = self._unique_candidates(
            candidates
        )

        if not candidates:
            logger.info(
                "No matching Anime Mirchi article found: %s",
                query,
            )
            return None

        best = self._choose_best_match(
            candidates,
            query,
        )

        logger.info(
            "Selected article: %s",
            best["url"],
        )

        article_html = self._request(
            best["url"]
        )

        if not article_html:
            return None

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

    def _find_candidates(
        self,
        html: str,
        query: str,
    ):
        soup = BeautifulSoup(
            html,
            "html.parser",
        )

        candidates = []

        for link in soup.find_all(
            "a",
            href=True,
        ):
            title = link.get_text(
                " ",
                strip=True,
            )

            href = link.get(
                "href",
                "",
            ).strip()

            if not title or not href:
                continue

            absolute_url = urljoin(
                self.base_url + "/",
                href,
            )

            if not absolute_url.startswith(
                self.base_url
            ):
                continue

            if self._is_good_candidate(
                title,
                query,
                absolute_url,
            ):
                candidates.append({
                    "title": title,
                    "url": absolute_url,
                })

        return candidates

    @staticmethod
    def _is_good_candidate(
        title: str,
        query: str,
        url: str,
    ) -> bool:

        title_lower = title.lower()
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

        if query_words and all(
            word in title_words
            for word in query_words
        ):
            return True

        # Also allow the anime name to appear
        # in the article URL.
        slug = url.lower()

        slug_words = re.findall(
            r"[a-z0-9]+",
            slug,
        )

        return bool(
            query_words
            and all(
                word in slug_words
                for word in query_words
            )
        )

    @staticmethod
    def _unique_candidates(
        candidates,
    ):
        result = []
        seen = set()

        for item in candidates:
            url = item["url"]

            if url in seen:
                continue

            seen.add(url)
            result.append(item)

        return result

    @staticmethod
    def _choose_best_match(
        candidates,
        query: str,
    ) -> Dict:

        query_lower = query.lower().strip()

        # Exact title.
        for item in candidates:
            if (
                item["title"]
                .lower()
                .strip()
                == query_lower
            ):
                return item

        # Title starts with query.
        for item in candidates:
            if (
                item["title"]
                .lower()
                .startswith(query_lower)
            ):
                return item

        # Prefer URLs containing query.
        for item in candidates:
            if query_lower.replace(
                " ",
                "-",
            ) in item["url"].lower():
                return item

        return candidates[0]

    def _parse_article(
        self,
        html: str,
        title: str,
        source_url: str,
    ) -> Dict:

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

        return {
            "name": self._clean_title(
                title,
                soup,
            ),
            "hindi_dub": self._extract_hindi_status(
                text
            ),
            "platform": self._extract_platform(
                text
            ),
            "hindi_details": self._extract_hindi_details(
                text
            ),
            "english_dub": self._extract_english_status(
                text
            ),
            "episodes": self._extract_episodes(
                text
            ),
            "poster_url": self._extract_poster(
                soup,
                source_url,
            ),
            "source_link": source_url,
        }

    @staticmethod
    def _clean_title(
        title: str,
        soup,
    ) -> str:

        # Prefer article H1 when available.
        h1 = soup.find("h1")

        if h1:
            clean = h1.get_text(
                " ",
                strip=True,
            )
        else:
            clean = title

        clean = re.sub(
            r"\s+[-|–]\s+Anime Mirchi.*$",
            "",
            clean,
            flags=re.I,
        )

        return clean.strip()

    @staticmethod
    def _extract_poster(
        soup,
        source_url: str,
    ) -> Optional[str]:

        # WordPress/OpenGraph poster.
        meta = soup.find(
            "meta",
            property="og:image",
        )

        if meta and meta.get("content"):
            return urljoin(
                source_url,
                meta["content"].strip(),
            )

        # Twitter card fallback.
        meta = soup.find(
            "meta",
            attrs={
                "name": "twitter:image"
            },
        )

        if meta and meta.get("content"):
            return urljoin(
                source_url,
                meta["content"].strip(),
            )

        # Article image fallback.
        article = (
            soup.find("article")
            or soup.find("main")
            or soup
        )

        for image in article.find_all(
            "img"
        ):

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

        return None

    @staticmethod
    def _extract_hindi_status(
        text: str,
    ) -> str:

        lower = text.lower()

        negative = (
            "hindi dub not available",
            "hindi dubbed not available",
            "no hindi dub",
            "without hindi dub",
            "hindi audio not available",
            "not available in hindi",
        )

        if any(
            phrase in lower
            for phrase in negative
        ):
            return "Not Available"

        positive = (
            "hindi dub",
            "hindi dubbed",
            "hindi audio",
            "dubbed in hindi",
            "hindi version",
        )

        if any(
            phrase in lower
            for phrase in positive
        ):
            return "Available"

        return "Status Unknown"

    @staticmethod
    def _extract_hindi_details(
        text: str,
    ) -> Optional[str]:

        lower = text.lower()

        if (
            "hindi" in lower
            and "crunchyroll" in lower
        ):
            return (
                "Hindi dub is listed on "
                "Crunchyroll India by Anime Mirchi."
            )

        if "hindi dub" in lower:
            return (
                "Anime Mirchi lists a Hindi dub "
                "for this anime."
            )

        return None

    @staticmethod
    def _extract_platform(
        text: str,
    ) -> Optional[str]:

        lower = text.lower()

        platforms = (
            (
                "Crunchyroll India",
                (
                    "crunchyroll india",
                    "crunchyroll",
                ),
            ),
            (
                "Amazon MX Player",
                ("amazon mx player",),
            ),
            (
                "MX Player",
                ("mx player",),
            ),
            (
                "Netflix",
                ("netflix",),
            ),
            (
                "Amazon Prime Video",
                (
                    "amazon prime",
                    "prime video",
                ),
            ),
            (
                "Disney+ Hotstar",
                (
                    "disney+ hotstar",
                    "disney hotstar",
                ),
            ),
            (
                "ZEE5",
                ("zee5",),
            ),
            (
                "SonyLIV",
                (
                    "sonyliv",
                    "sony liv",
                ),
            ),
        )

        for platform, keywords in platforms:

            if any(
                keyword in lower
                for keyword in keywords
            ):
                return platform

        return None

    @staticmethod
    def _extract_english_status(
        text: str,
    ) -> Optional[str]:

        lower = text.lower()

        if any(
            phrase in lower
            for phrase in (
                "english dub not available",
                "english dubbed not available",
                "no english dub",
            )
        ):
            return "Not Available"

        if any(
            phrase in lower
            for phrase in (
                "english dub",
                "english dubbed",
                "dubbed in english",
                "english audio",
            )
        ):
            return "Available"

        return None

    @staticmethod
    def _extract_episodes(
        text: str,
    ) -> Optional[str]:

        # Try explicit "Episodes: 12"
        match = re.search(
            r"episodes?\s*:\s*(\d+)",
            text,
            re.I,
        )

        if match:
            return match.group(1)

        # Try "12 episodes"
        match = re.search(
            r"(\d+)\s+episodes?",
            text,
            re.I,
        )

        if match:
            return match.group(1)

        return None


anime_scraper = AnimeScraper()


def get_anime_info(
    anime_name: str,
) -> Optional[Dict]:

    return anime_scraper.search_anime(
        anime_name
    )
