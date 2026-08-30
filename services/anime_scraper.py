"""
Anime information service.

Reads anime information from the public AnimeDubHindi schedule page.
Only metadata is used:
- Anime name
- Season
- Episode
- Languages
- Release day/time
- Source

No anime episodes or copyrighted files are downloaded or stored.
"""

import re
from typing import Dict, Optional

import requests
from bs4 import BeautifulSoup

from utils.logger import logger


SCHEDULE_URL = "https://www.animedubhindi.link/schedule.php"


class AnimeScraper:

    def __init__(self):
        self.session = requests.Session()

        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/120.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        })

    def search_anime(
        self,
        anime_name: str
    ) -> Optional[Dict]:

        if not anime_name or not anime_name.strip():
            return None

        query = self._normalize(anime_name)

        logger.info(
            "Searching AnimeDubHindi schedule: %s",
            query
        )

        try:

            response = self.session.get(
                SCHEDULE_URL,
                timeout=15
            )

            response.raise_for_status()

            soup = BeautifulSoup(
                response.text,
                "html.parser"
            )

            result = self._find_anime(
                soup,
                query
            )

            if not result:
                logger.info(
                    "Anime not found: %s",
                    anime_name
                )
                return None

            # Poster from the schedule page if available.
            poster_url = self._get_poster(result)

            result["poster_url"] = poster_url

            return result

        except requests.RequestException as exc:

            logger.error(
                "AnimeDubHindi request failed: %s",
                exc
            )

            return None

        except Exception as exc:

            logger.error(
                "AnimeDubHindi parser error: %s",
                exc,
                exc_info=True
            )

            return None

    def _find_anime(
        self,
        soup: BeautifulSoup,
        query: str
    ) -> Optional[Dict]:

        # Search headings because the schedule uses anime
        # titles as headings.
        headings = soup.find_all(
            ["h1", "h2", "h3", "h4"]
        )

        for heading in headings:

            title = heading.get_text(
                " ",
                strip=True
            )

            if not title:
                continue

            if not self._title_matches(
                title,
                query
            ):
                continue

            # Get the surrounding anime card/container.
            card = heading

            for _ in range(5):

                if card.parent is None:
                    break

                card = card.parent

                text = card.get_text(
                    " ",
                    strip=True
                )

                # Stop when we have enough information.
                if (
                    "Season" in text
                    or "EP" in text
                    or "Hindi" in text
                ):
                    break

            text = card.get_text(
                " ",
                strip=True
            )

            season = self._extract_season(text)
            episode = self._extract_episode(text)
            languages = self._extract_languages(text)
            schedule = self._extract_schedule(text)

            return {
                "name": title,
                "hindi_dub": (
                    "Available"
                    if "Hindi" in languages
                    else "Not Mentioned"
                ),
                "platform": None,
                "hindi_details": (
                    "Hindi language listed on "
                    "AnimeDubHindi schedule."
                    if "Hindi" in languages
                    else None
                ),
                "original_broadcast": None,
                "episodes": episode,
                "season": season,
                "languages": (
                    " • ".join(languages)
                    if languages
                    else None
                ),
                "schedule": schedule,
                "source": "AnimeDubHindi",
                "source_link": SCHEDULE_URL,
            }

        return None

    @staticmethod
    def _normalize(text: str) -> str:

        text = text.lower()
        text = text.replace("-", " ")
        text = re.sub(
            r"[^a-z0-9 ]+",
            " ",
            text
        )

        return " ".join(
            text.split()
        )

    @staticmethod
    def _title_matches(
        title: str,
        query: str
    ) -> bool:

        title_normalized = (
            AnimeScraper._normalize(title)
        )

        if query == title_normalized:
            return True

        if query in title_normalized:
            return True

        query_words = set(
            query.split()
        )

        title_words = set(
            title_normalized.split()
        )

        return query_words.issubset(
            title_words
        )

    @staticmethod
    def _extract_season(
        text: str
    ) -> Optional[str]:

        match = re.search(
            r"\bSeason\s+([0-9]+)\b",
            text,
            re.I
        )

        if match:
            return f"Season {match.group(1)}"

        # Some entries use S1/S4 etc.
        match = re.search(
            r"\bS([0-9]+)\b",
            text,
            re.I
        )

        if match:
            return f"Season {match.group(1)}"

        return None

    @staticmethod
    def _extract_episode(
        text: str
    ) -> Optional[str]:

        match = re.search(
            r"\bEP\s*([0-9]+(?:-[0-9]+)?)\b",
            text,
            re.I
        )

        if match:
            return match.group(1)

        return None

    @staticmethod
    def _extract_languages(
        text: str
    ) -> list:

        possible = [
            "Hindi",
            "Tamil",
            "Telugu",
            "English",
            "Japanese",
        ]

        found = []

        for language in possible:

            if re.search(
                rf"\b{re.escape(language)}\b",
                text,
                re.I
            ):
                found.append(language)

        return found

    @staticmethod
    def _extract_schedule(
        text: str
    ) -> Optional[str]:

        days = (
            "Monday",
            "Tuesday",
            "Wednesday",
            "Thursday",
            "Friday",
            "Saturday",
            "Sunday",
            "Daily",
        )

        for day in days:

            match = re.search(
                rf"\b{day}\b\s+"
                rf"([0-9]{{1,2}}:[0-9]{{2}}\s*[AP]M)",
                text,
                re.I
            )

            if match:
                return (
                    f"{day} "
                    f"{match.group(1)}"
                )

        return None

    @staticmethod
    def _get_poster(
        result: Dict
    ) -> Optional[str]:
        """
        Poster extraction is intentionally conservative.

        The schedule page may contain external image URLs.
        We do not download or store the image ourselves.
        """

        # The current parser focuses on metadata.
        # The existing Jikan poster system can be added
        # separately if required.
        return None


anime_scraper = AnimeScraper()


def get_anime_info(
    anime_name: str
) -> Optional[Dict]:

    return anime_scraper.search_anime(
        anime_name
        )
