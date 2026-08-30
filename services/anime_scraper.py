"""
Anime information service.

This version does NOT depend on Anime Mirchi's search page,
because Render requests can receive HTTP 403.

It uses a small verified local database for known anime and
returns the Anime Mirchi article as the source.

No anime episodes/files are downloaded or stored.
"""

from typing import Dict, Optional
import requests

from utils.logger import logger


# -------------------------------------------------------------------
# VERIFIED ANIME DATA
# -------------------------------------------------------------------

ANIME_DATABASE: Dict[str, Dict] = {
    "naruto": {
        "name": "Naruto",
        "hindi_dub": "Available",
        "platform": "Crunchyroll India",
        "hindi_details": (
            "Anime Mirchi ke mutabik Crunchyroll par available Hindi dub "
            "wahi dub hai jo pehle Sony YAY! par aired hua tha."
        ),
        "original_broadcast": (
            "Sony YAY! — original series ke 220 episodes Hindi me aired hue."
        ),
        "episodes": "220",
        "source_link": (
            "https://animemirchi.com/"
            "naruto-all-episodes-hindi-tamil-telugu-crunchyroll/"
        ),
    },

    "solo leveling": {
        "name": "Solo Leveling",
        "hindi_dub": "Available",
        "platform": "Crunchyroll India",
        "hindi_details": (
            "Season 1 aur Season 2 dono Hindi dub me Crunchyroll India "
            "par available hain."
        ),
        "original_broadcast": None,
        "episodes": "25",
        "source_link": (
            "https://animemirchi.com/solo-leveling-in-india/"
        ),
    },
}


# Alternative names
ALIASES = {
    "naruto uzumaki": "naruto",
    "naruto series": "naruto",
    "naruto 2002": "naruto",
    "solo leveling anime": "solo leveling",
    "solo-leveling": "solo leveling",
}


class AnimeScraper:
    """
    Anime information lookup service.

    Despite the old class name, this version is intentionally NOT
    scraping Anime Mirchi search results.
    """

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "AnimeHindiDubBot/1.0 "
                    "(information-only Telegram bot)"
                )
            }
        )

    def search_anime(self, anime_name: str) -> Optional[Dict]:
        """Find anime information by title."""

        if not anime_name:
            return None

        query = self._normalize(anime_name)

        logger.info("Anime lookup: %s", query)

        # Check alias first
        query = ALIASES.get(query, query)

        if query not in ANIME_DATABASE:
            logger.info("Anime not found in local database: %s", query)
            return None

        info = ANIME_DATABASE[query].copy()

        # Try to obtain a poster URL.
        # If this fails, the bot still sends the text information.
        info["poster_url"] = self._get_poster(info["name"])

        return info

    @staticmethod
    def _normalize(text: str) -> str:
        """Normalize search text."""

        return " ".join(
            text.lower().strip().replace("-", " ").split()
        )

    def _get_poster(self, anime_name: str) -> Optional[str]:
        """
        Get anime poster from Jikan's public metadata API.

        No poster is downloaded or stored by this bot.
        """

        try:
            response = self.session.get(
                "https://api.jikan.moe/v4/anime",
                params={
                    "q": anime_name,
                    "limit": 1,
                },
                timeout=8,
            )

            response.raise_for_status()

            data = response.json().get("data", [])

            if not data:
                return None

            images = data[0].get("images", {})
            jpg = images.get("jpg", {})

            return jpg.get("large_image_url") or jpg.get(
                "image_url"
            )

        except Exception as exc:
            logger.warning(
                "Could not fetch poster for %s: %s",
                anime_name,
                exc,
            )
            return None


anime_scraper = AnimeScraper()


def get_anime_info(anime_name: str) -> Optional[Dict]:
    """Public helper used by the Telegram command handler."""

    return anime_scraper.search_anime(anime_name)
