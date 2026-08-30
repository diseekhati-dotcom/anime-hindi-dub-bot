"""
Anime information service.

Sources:
- Anime Mirchi: manually verified information
- AnimeDubHindi: information-only metadata

The bot does NOT download, store, or distribute anime episodes/files.
"""

from typing import Dict, Optional
import requests

from utils.logger import logger


# -------------------------------------------------------------------
# ANIME INFORMATION DATABASE
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
        "source": "Anime Mirchi",
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
            "Season 1 aur Season 2 Hindi dub me available hain."
        ),
        "original_broadcast": None,
        "episodes": "25",
        "source": "Anime Mirchi",
        "source_link": (
            "https://animemirchi.com/solo-leveling-in-india/"
        ),
    },

    # ---------------------------------------------------------------
    # AnimeDubHindi information source
    # ---------------------------------------------------------------

    "mushoku tensei": {
        "name": "Mushoku Tensei: Jobless Reincarnation",
        "hindi_dub": "Available",
        "platform": "Muse India",
        "hindi_details": (
            "AnimeDubHindi schedule ke mutabik Season 3 ke liye "
            "Hindi, English aur Japanese audio listed hai."
        ),
        "original_broadcast": None,
        "episodes": None,
        "season": "Season 3",
        "languages": "Hindi • English • Japanese",
        "release_date": "30 Aug 2026",
        "source": "AnimeDubHindi",
        "source_link": (
            "https://www.animedubhindi.link/schedule.php"
        ),
    },
}


# -------------------------------------------------------------------
# ALTERNATIVE TITLES
# -------------------------------------------------------------------

ALIASES = {

    "naruto uzumaki": "naruto",
    "naruto series": "naruto",
    "naruto 2002": "naruto",

    "solo leveling anime": "solo leveling",
    "solo-leveling": "solo leveling",

    "mushoku tensei anime": "mushoku tensei",
    "mushoku tensei jobless reincarnation":
        "mushoku tensei",
    "jobless reincarnation":
        "mushoku tensei",
}


class AnimeScraper:
    """
    Anime information lookup service.

    This intentionally does not scrape download/watch links.
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

    def search_anime(
        self,
        anime_name: str
    ) -> Optional[Dict]:
        """Find anime information by title."""

        if not anime_name:
            return None

        query = self._normalize(anime_name)

        logger.info(
            "Anime lookup: %s",
            query
        )

        # Check aliases
        query = ALIASES.get(
            query,
            query
        )

        # Search local verified information
        if query not in ANIME_DATABASE:

            logger.info(
                "Anime not found in local database: %s",
                query
            )

            return None

        info = ANIME_DATABASE[query].copy()

        # Poster
        info["poster_url"] = self._get_poster(
            info["name"]
        )

        return info

    @staticmethod
    def _normalize(text: str) -> str:
        """Normalize search text."""

        return " ".join(
            text.lower()
            .strip()
            .replace("-", " ")
            .split()
        )

    def _get_poster(
        self,
        anime_name: str
    ) -> Optional[str]:
        """
        Get anime poster from Jikan metadata API.

        Only the poster URL is used.
        Anime episodes/files are not downloaded.
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

            data = response.json().get(
                "data",
                []
            )

            if not data:
                return None

            images = data[0].get(
                "images",
                {}
            )

            jpg = images.get(
                "jpg",
                {}
            )

            return (
                jpg.get("large_image_url")
                or jpg.get("image_url")
            )

        except Exception as exc:

            logger.warning(
                "Could not fetch poster for %s: %s",
                anime_name,
                exc,
            )

            return None


# -------------------------------------------------------------------
# SINGLE SCRAPER INSTANCE
# -------------------------------------------------------------------

anime_scraper = AnimeScraper()


def get_anime_info(
    anime_name: str
) -> Optional[Dict]:
    """Public helper used by the Telegram command handler."""

    return anime_scraper.search_anime(
        anime_name
    )
