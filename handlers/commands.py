"""
Command handlers for Anime Hindi Dub Bot.
"""

import html
from typing import Dict

from telegram import Update
from telegram.ext import ContextTypes

from services.anime_scraper import get_anime_info
from utils.logger import logger


async def start_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
) -> None:

    message = (
        "🎬 <b>Welcome to Anime Hindi Dub Bot!</b>\n\n"
        "Hindi-dubbed anime ki information paane ke liye:\n\n"
        "<code>/anime Naruto</code>\n"
        "<code>/anime Solo Leveling</code>\n\n"
        "📚 Source: Anime Mirchi"
    )

    await update.message.reply_html(message)


async def help_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
) -> None:

    message = (
        "ℹ️ <b>Help</b>\n\n"
        "🎬 <b>/anime &lt;name&gt;</b>\n"
        "Anime ki Hindi-dub information search karein.\n\n"
        "<b>Examples:</b>\n"
        "• /anime Naruto\n"
        "• /anime Solo Leveling\n"
        "• /anime Death Note\n\n"
        "ℹ️ Bot sirf anime information aur source links provide karta hai."
    )

    await update.message.reply_html(message)


async def anime_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
) -> None:

    if not context.args:
        await update.message.reply_html(
            "❌ <b>Anime name missing</b>\n\n"
            "Example:\n"
            "<code>/anime Naruto</code>"
        )
        return

    anime_name = " ".join(context.args).strip()

    loading = await update.message.reply_text(
        f"🔍 Searching for {html.escape(anime_name)}..."
    )

    try:
        anime_info = get_anime_info(anime_name)

        await loading.delete()

        if not anime_info:
            await update.message.reply_html(
                f"😕 <b>Anime not found:</b> "
                f"{html.escape(anime_name)}\n\n"
                "Try another spelling or title."
            )
            return

        response = _format_anime_info(anime_info)

        poster_url = anime_info.get("poster_url")

        if poster_url:
            try:
                await update.message.reply_photo(
                    photo=poster_url,
                    caption=response,
                    parse_mode="HTML",
                )
                return

            except Exception as poster_error:
                logger.warning(
                    "Could not send poster: %s",
                    poster_error,
                )

        await update.message.reply_html(response)

        logger.info(
            "Successfully returned anime info for: %s",
            anime_name,
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
            exc_info=True,
        )

        await update.message.reply_html(
            "❌ <b>Error:</b> Unable to fetch anime information.\n\n"
            "Please try again later."
        )


def _format_anime_info(anime_info: Dict) -> str:

    name = html.escape(
        str(anime_info.get("name", "Unknown"))
    )

    hindi_dub = html.escape(
        str(anime_info.get("hindi_dub", "Status Unknown"))
    )

    platform = anime_info.get("platform")
    english_dub = anime_info.get("english_dub")
    episodes = anime_info.get("episodes")
    hindi_details = anime_info.get("hindi_details")
    source_link = anime_info.get("source_link")

    response = (
        f"🎬 <b>Anime:</b> {name}\n"
        f"🇮🇳 <b>Hindi Dub:</b> {hindi_dub}\n"
    )

    if platform:
        response += (
            f"📺 <b>Platform:</b> "
            f"{html.escape(str(platform))}\n"
        )

    if hindi_details:
        response += (
            f"🎙️ <b>Hindi Dub Details:</b> "
            f"{html.escape(str(hindi_details))}\n"
        )

    if episodes:
        response += (
            f"📺 <b>Episodes:</b> "
            f"{html.escape(str(episodes))}\n"
        )

    if english_dub:
        response += (
            f"🇬🇧 <b>English Dub:</b> "
            f"{html.escape(str(english_dub))}\n"
        )

    if source_link:
        safe_link = html.escape(
            str(source_link),
            quote=True,
        )

        response += (
            f"\n🔎 <a href='{safe_link}'>"
            "Source: Anime Mirchi</a>"
        )

    return response
