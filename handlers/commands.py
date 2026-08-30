"""
Command handlers for Anime Hindi Dub Bot.

Provides:
- /start
- /help
- /anime <name>

Anime information comes from AnimeDubHindi schedule.
Poster comes from Jikan API.

No anime episodes/files are downloaded, stored,
or distributed.
"""

import html
from typing import Dict

from telegram import Update
from telegram.ext import ContextTypes

from services.anime_scraper import get_anime_info
from utils.logger import logger


# -------------------------------------------------------------------
# START COMMAND
# -------------------------------------------------------------------

async def start_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
) -> None:

    message = (
        "🎬 <b>Welcome to Anime Hindi Dub Bot!</b>\n\n"
        "🇮🇳 Hindi-dubbed anime ki information "
        "search karein.\n\n"

        "🔎 <b>Example:</b>\n"
        "<code>/anime Naruto</code>\n"
        "<code>/anime Black Torch</code>\n"
        "<code>/anime Solo Leveling</code>\n\n"

        "📚 Bot anime information provide karta hai."
    )

    if update.message:
        await update.message.reply_html(message)


# -------------------------------------------------------------------
# HELP COMMAND
# -------------------------------------------------------------------

async def help_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
) -> None:

    message = (
        "ℹ️ <b>Anime Hindi Dub Bot — Help</b>\n\n"

        "🎬 <b>Anime Search</b>\n"
        "<code>/anime &lt;anime name&gt;</code>\n\n"

        "📌 <b>Examples:</b>\n"
        "• <code>/anime Naruto</code>\n"
        "• <code>/anime Black Torch</code>\n"
        "• <code>/anime Solo Leveling</code>\n"
        "• <code>/anime Mushoku Tensei</code>\n\n"

        "📋 <b>Information:</b>\n"
        "🇮🇳 Hindi Dub status\n"
        "📺 Platform (jab available ho)\n"
        "🎙️ Hindi Dub details\n"
        "📺 Season / Episodes\n"
        "🌐 Available languages\n"
        "📅 Schedule / release information\n\n"

        "🖼️ Anime poster bhi available ho to "
        "show kiya jayega.\n\n"

        "ℹ️ Bot sirf anime information provide karta hai."
    )

    if update.message:
        await update.message.reply_html(message)


# -------------------------------------------------------------------
# ANIME COMMAND
# -------------------------------------------------------------------

async def anime_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
) -> None:

    if not update.message:
        return

    # ---------------------------------------------------------------
    # CHECK ANIME NAME
    # ---------------------------------------------------------------

    if not context.args:

        await update.message.reply_html(
            "❌ <b>Anime name missing</b>\n\n"
            "Example:\n"
            "<code>/anime Naruto</code>"
        )

        return

    anime_name = " ".join(
        context.args
    ).strip()

    # ---------------------------------------------------------------
    # LOADING MESSAGE
    # ---------------------------------------------------------------

    loading = await update.message.reply_text(
        "🔍 Searching for "
        f"{html.escape(anime_name)}..."
    )

    try:

        # -----------------------------------------------------------
        # SEARCH ANIME
        # -----------------------------------------------------------

        anime_info = get_anime_info(
            anime_name
        )

        # Delete loading message
        try:
            await loading.delete()
        except Exception:
            pass

        # -----------------------------------------------------------
        # NOT FOUND
        # -----------------------------------------------------------

        if not anime_info:

            await update.message.reply_html(
                "😕 <b>Anime not found:</b> "
                f"{html.escape(anime_name)}\n\n"

                "Try another spelling or title.\n\n"

                "Example:\n"
                "<code>/anime Black Torch</code>"
            )

            return

        # -----------------------------------------------------------
        # FORMAT INFORMATION
        # -----------------------------------------------------------

        response = _format_anime_info(
            anime_info
        )

        # -----------------------------------------------------------
        # POSTER
        # -----------------------------------------------------------

        poster_url = anime_info.get(
            "poster_url"
        )

        if poster_url:

            try:

                await update.message.reply_photo(
                    photo=poster_url,
                    caption=response,
                    parse_mode="HTML"
                )

                logger.info(
                    "Anime info + poster sent: %s",
                    anime_name
                )

                return

            except Exception as poster_error:

                logger.warning(
                    "Poster could not be sent for %s: %s",
                    anime_name,
                    poster_error
                )

        # -----------------------------------------------------------
        # WITHOUT POSTER
        # -----------------------------------------------------------

        await update.message.reply_html(
            response
        )

        logger.info(
            "Anime information sent: %s",
            anime_name
        )

    except Exception as error:

        # Try deleting loading message
        try:
            await loading.delete()
        except Exception:
            pass

        logger.error(
            "Anime command error for '%s': %s",
            anime_name,
            error,
            exc_info=True
        )

        await update.message.reply_html(
            "❌ <b>Error</b>\n\n"
            "Anime information fetch nahi ho saki.\n"
            "Please try again later."
        )


# -------------------------------------------------------------------
# FORMAT ANIME INFORMATION
# -------------------------------------------------------------------

def _format_anime_info(
    anime_info: Dict
) -> str:
    """Create Telegram HTML response."""

    # ---------------------------------------------------------------
    # BASIC INFORMATION
    # ---------------------------------------------------------------

    name = html.escape(
        str(
            anime_info.get(
                "name",
                "Unknown"
            )
        )
    )

    hindi_dub = html.escape(
        str(
            anime_info.get(
                "hindi_dub",
                "Status Unknown"
            )
        )
    )

    platform = anime_info.get(
        "platform"
    )

    hindi_details = anime_info.get(
        "hindi_details"
    )

    episodes = anime_info.get(
        "episodes"
    )

    season = anime_info.get(
        "season"
    )

    languages = anime_info.get(
        "languages"
    )

    schedule = anime_info.get(
        "schedule"
    )

    release_date = anime_info.get(
        "release_date"
    )

    # ---------------------------------------------------------------
    # START RESPONSE
    # ---------------------------------------------------------------

    response = (
        f"🎬 <b>Anime:</b> {name}\n"
        f"🇮🇳 <b>Hindi Dub:</b> {hindi_dub}\n"
    )

    # ---------------------------------------------------------------
    # PLATFORM
    # ---------------------------------------------------------------

    if platform:

        response += (
            "📺 <b>Platform:</b> "
            f"{html.escape(str(platform))}\n"
        )

    # ---------------------------------------------------------------
    # HINDI DETAILS
    # ---------------------------------------------------------------

    if hindi_details:

        response += (
            "🎙️ <b>Hindi Dub Details:</b> "
            f"{html.escape(str(hindi_details))}\n"
        )

    # ---------------------------------------------------------------
    # SEASON
    # ---------------------------------------------------------------

    if season:

        response += (
            "📀 <b>Season:</b> "
            f"{html.escape(str(season))}\n"
        )

    # ---------------------------------------------------------------
    # EPISODES
    # ---------------------------------------------------------------

    if episodes:

        response += (
            "📺 <b>Episode:</b> "
            f"{html.escape(str(episodes))}\n"
        )

    # ---------------------------------------------------------------
    # LANGUAGES
    # ---------------------------------------------------------------

    if languages:

        response += (
            "🌐 <b>Languages:</b> "
            f"{html.escape(str(languages))}\n"
        )

    # ---------------------------------------------------------------
    # SCHEDULE
    # ---------------------------------------------------------------

    if schedule:

        response += (
            "📅 <b>Schedule:</b> "
            f"{html.escape(str(schedule))}\n"
        )

    # ---------------------------------------------------------------
    # RELEASE DATE
    # ---------------------------------------------------------------

    if release_date:

        response += (
            "🗓️ <b>Release Date:</b> "
            f"{html.escape(str(release_date))}\n"
        )

    # ---------------------------------------------------------------
    # SOURCE NAME ONLY
    # ---------------------------------------------------------------

    response += (
        "\n🔎 <b>Source:</b> AnimeDubHindi"
    )

    return response
