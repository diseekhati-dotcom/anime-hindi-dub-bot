"""
Command handlers for Anime Hindi Dub Bot.

Provides:
- /start
- /help
- /anime <name>

Anime information is fetched live from the scraper.
Poster is supplied by the scraper when available.

No anime episodes, watch links, or copyrighted files
are downloaded, stored, or distributed.
"""

import html
from io import BytesIO
from typing import Dict

import requests
from telegram import Update
from telegram.ext import ContextTypes

from services.anime_scraper import get_anime_info
from utils.logger import logger


# ===================================================================
# START
# ===================================================================

async def start_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
) -> None:

    if not update.message:
        return

    message = (
        "🎬 <b>Welcome to Anime Hindi Dub Bot!</b>\n\n"
        "🔎 <b>Live Anime Search</b>\n"
        "Anime ka naam bhejkar Hindi dub information check karein.\n\n"

        "📌 <b>Example:</b>\n"
        "<code>/anime Naruto</code>\n"
        "<code>/anime Black Torch</code>\n"
        "<code>/anime Solo Leveling</code>\n\n"

        "📋 <b>Information:</b>\n"
        "🇮🇳 Hindi Dub\n"
        "📺 Platform\n"
        "🎙️ Dub By\n"
        "🎞️ Studio\n"
        "📀 Season / Episode\n"
        "🌐 Languages\n"
        "📅 Schedule\n"
        "🖼️ Anime Poster\n\n"

        "ℹ️ Bot sirf anime information provide karta hai."
    )

    await update.message.reply_html(message)


# ===================================================================
# HELP
# ===================================================================

async def help_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
) -> None:

    if not update.message:
        return

    message = (
        "ℹ️ <b>Anime Hindi Dub Bot — Help</b>\n\n"

        "🔎 <b>Live Anime Search</b>\n"
        "<code>/anime &lt;anime name&gt;</code>\n\n"

        "📌 <b>Examples:</b>\n"
        "• <code>/anime Naruto</code>\n"
        "• <code>/anime Black Torch</code>\n"
        "• <code>/anime Solo Leveling</code>\n"
        "• <code>/anime The Exiled Heavy Knight Knows How to Game the System</code>\n\n"

        "📋 <b>Information:</b>\n"
        "🇮🇳 Hindi Dub status\n"
        "📺 Platform\n"
        "🎙️ Dub By\n"
        "🎞️ Studio\n"
        "📀 Season / Episode\n"
        "🌐 Languages\n"
        "📅 Schedule\n"
        "🗓️ Release Date\n"
        "🖼️ Poster\n\n"

        "ℹ️ Bot sirf anime information provide karta hai."
    )

    await update.message.reply_html(message)


# ===================================================================
# ANIME COMMAND
# ===================================================================

async def anime_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
) -> None:

    if not update.message:
        return

    # ---------------------------------------------------------------
    # NAME CHECK
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
        "🔎 Live anime search...\n"
        f"🎬 {html.escape(anime_name)}"
    )

    try:

        # -----------------------------------------------------------
        # LIVE SEARCH
        # -----------------------------------------------------------

        anime_info = get_anime_info(
            anime_name
        )

        # Remove loading message.
        try:
            await loading.delete()
        except Exception:
            pass

        # -----------------------------------------------------------
        # NOT FOUND
        # -----------------------------------------------------------

        if not anime_info:

            await update.message.reply_html(
                "😕 <b>Anime not found</b>\n\n"
                f"🔎 Searched: "
                f"<code>{html.escape(anime_name)}</code>\n\n"
                "Try the official English title or another spelling."
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

            # =======================================================
            # METHOD 1 — TELEGRAM DIRECT URL
            # =======================================================

            try:

                await update.message.reply_photo(
                    photo=poster_url,
                    caption=response,
                    parse_mode="HTML"
                )

                logger.info(
                    "Poster sent directly: %s",
                    anime_name
                )

                return

            except Exception as direct_error:

                logger.warning(
                    "Direct poster failed for '%s': %s",
                    anime_name,
                    direct_error
                )

            # =======================================================
            # METHOD 2 — DOWNLOAD ONLY IN MEMORY
            # =======================================================

            try:

                image_response = requests.get(
                    poster_url,
                    headers={
                        "User-Agent": (
                            "Mozilla/5.0 "
                            "AnimeHindiDubBot"
                        )
                    },
                    timeout=20
                )

                image_response.raise_for_status()

                image_data = image_response.content

                if image_data:

                    image_file = BytesIO(
                        image_data
                    )

                    image_file.name = (
                        "anime_poster.jpg"
                    )

                    await update.message.reply_photo(
                        photo=image_file,
                        caption=response,
                        parse_mode="HTML"
                    )

                    logger.info(
                        "Poster sent from memory: %s",
                        anime_name
                    )

                    return

            except Exception as image_error:

                logger.warning(
                    "Poster memory fallback failed for '%s': %s",
                    anime_name,
                    image_error
                )

        # -----------------------------------------------------------
        # INFORMATION WITHOUT POSTER
        # -----------------------------------------------------------

        await update.message.reply_html(
            response
        )

        logger.info(
            "Anime information sent: %s",
            anime_name
        )

    except Exception as error:

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


# ===================================================================
# FORMAT ANIME INFORMATION
# ===================================================================

def _format_anime_info(
    anime_info: Dict
) -> str:
    """Create clean Telegram HTML response."""

    # ---------------------------------------------------------------
    # BASIC
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

    # ---------------------------------------------------------------
    # OPTIONAL FIELDS
    # ---------------------------------------------------------------

    platform = anime_info.get(
        "platform"
    )

    dub_by = anime_info.get(
        "dub_by"
    )

    studio = anime_info.get(
        "studio"
    )

    season = anime_info.get(
        "season"
    )

    episode = anime_info.get(
        "episodes"
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

    source = anime_info.get(
        "source",
        "AnimeDubHindi"
    )

    source_link = anime_info.get(
        "source_link"
    )

    mal_url = anime_info.get(
        "mal_url"
    )

    # ---------------------------------------------------------------
    # BUILD RESPONSE
    # ---------------------------------------------------------------

    response = (
        "🔎 <b>Live Anime Search</b>\n\n"

        f"🎬 <b>Anime:</b> {name}\n"

        f"🇮🇳 <b>Hindi Dub:</b> "
        f"{hindi_dub}\n"
    )

    # Platform
    if platform:

        response += (
            "📺 <b>Platform:</b> "
            f"{html.escape(str(platform))}\n"
        )

    # Dub By
    if dub_by:

        response += (
            "🎙️ <b>Dub By:</b> "
            f"{html.escape(str(dub_by))}\n"
        )

    # Studio
    if studio:

        response += (
            "🎞️ <b>Studio:</b> "
            f"{html.escape(str(studio))}\n"
        )

    # Season
    if season:

        response += (
            "📀 <b>Season:</b> "
            f"{html.escape(str(season))}\n"
        )

    # Episode
    if episode:

        response += (
            "📺 <b>Episode:</b> "
            f"{html.escape(str(episode))}\n"
        )

    # Languages
    if languages:

        response += (
            "🌐 <b>Languages:</b> "
            f"{html.escape(str(languages))}\n"
        )

    # Schedule
    if schedule:

        response += (
            "📅 <b>Schedule:</b> "
            f"{html.escape(str(schedule))}\n"
        )

    # Release date
    if release_date:

        response += (
            "🗓️ <b>Release Date:</b> "
            f"{html.escape(str(release_date))}\n"
        )

    # ---------------------------------------------------------------
    # SOURCE
    # ---------------------------------------------------------------

    response += "\n"

    if source_link:

        response += (
            "🔎 <b>Source:</b> "
            f'<a href="{html.escape(str(source_link), quote=True)}">'
            f"{html.escape(str(source))}"
            "</a>"
        )

    else:

        response += (
            "🔎 <b>Source:</b> "
            f"{html.escape(str(source))}"
        )

    # ---------------------------------------------------------------
    # MAL LINK
    # ---------------------------------------------------------------

    if mal_url:

        response += (
            "\n"
            f'⭐ <a href="{html.escape(str(mal_url), quote=True)}">'
            "MyAnimeList"
            "</a>"
        )

    return response
