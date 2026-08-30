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
        f"🔍 Searching for {anime_name}..."
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

        response = _
