"""
commands.py
Telegram commands for Anime Hindi Info Bot

Requires:
    python-telegram-bot==22.7
"""

from __future__ import annotations

import html
import logging

from telegram import Update
from telegram.constants import ChatType
from telegram.ext import CommandHandler, ContextTypes

from anime_scraper import fetch_anime_text, fetch_today_releases


logger = logging.getLogger(__name__)


async def start_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not update.message:
        return

    text = (
        "👋 <b>Welcome to Anime Hindi Info Bot!</b>\n\n"
        "🎬 Anime info check karo:\n"
        "<code>/anime Naruto</code>\n\n"
        "📅 Aaj ke releases:\n"
        "<code>/today</code>\n\n"
        "📢 Daily updates ON:\n"
        "<code>/subscribe</code>\n\n"
        "❌ Daily updates OFF:\n"
        "<code>/unsubscribe</code>\n\n"
        "❓ Commands:\n"
        "<code>/help</code>"
    )

    await update.message.reply_text(text, parse_mode="HTML")


async def help_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not update.message:
        return

    text = (
        "🤖 <b>Anime Hindi Info Bot</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "🎬 <b>Anime Information</b>\n"
        "<code>/anime Naruto</code>\n"
        "<code>/anime One Piece</code>\n\n"
        "📅 <b>Today's Releases</b>\n"
        "<code>/today</code>\n\n"
        "📢 <b>Daily Updates</b>\n"
        "<code>/subscribe</code>\n"
        "<code>/unsubscribe</code>\n\n"
        "ℹ️ <b>Bot</b>\n"
        "<code>/start</code>\n"
        "<code>/help</code>"
    )

    await update.message.reply_text(text, parse_mode="HTML")


async def anime_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not update.message:
        return

    if not context.args:
        await update.message.reply_text(
            "❌ Anime name missing.\n\n"
            "Example:\n"
            "<code>/anime Naruto</code>\n"
            "<code>/anime One Piece</code>",
            parse_mode="HTML",
        )
        return

    anime_name = " ".join(context.args).strip()

    loading = await update.message.reply_text(
        "🔎 <b>Searching...</b>\n"
        f"🎬 {html.escape(anime_name)}\n\n"
        "⏳ Sources check kiye ja rahe hain...",
        parse_mode="HTML",
    )

    try:
        result = await fetch_anime_text(anime_name)

        if not result:
            await loading.edit_text(
                "❌ <b>Anime nahi mila.</b>\n\n"
                "Anime ka naam dobara check karo.",
                parse_mode="HTML",
            )
            return

        await loading.edit_text(
            result,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )

    except Exception:
        logger.exception("Anime command error")

        await loading.edit_text(
            "⚠️ <b>Something went wrong.</b>\n\n"
            "Thodi der baad dobara try karo.",
            parse_mode="HTML",
        )


async def today_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not update.message:
        return

    loading = await update.message.reply_text(
        "🔎 <b>Today's anime releases check kar raha hoon...</b>",
        parse_mode="HTML",
    )

    try:
        releases = await fetch_today_releases()

        if not releases:
            await loading.edit_text(
                "📅 <b>TODAY'S ANIME UPDATES</b>\n\n"
                "ℹ️ Aaj ke verified releases nahi mile.",
                parse_mode="HTML",
            )
            return

        lines = [
            "📅 <b>TODAY'S ANIME UPDATES</b>",
            "━━━━━━━━━━━━━━━━━━",
            "",
        ]

        for index, item in enumerate(releases, start=1):
            anime = html.escape(
                str(item.get("anime", "Unknown"))
            )
            episode = item.get("episode") or "Unknown"
            languages = item.get("language", [])
            platform = item.get("platform") or "Unknown"
            release_time = item.get("time") or "Time not verified"

            if isinstance(languages, list):
                language_text = (
                    " • ".join(map(str, languages))
                    if languages
                    else "Unknown"
                )
            else:
                language_text = str(languages)

            lines.extend([
                f"{index}️⃣ <b>{anime}</b>",
                f"   ├─ 📺 Episode: {html.escape(str(episode))}",
                f"   ├─ 🌐 Language: {html.escape(language_text)}",
                f"   ├─ 📡 Platform: {html.escape(str(platform))}",
                f"   └─ 🕐 Time: {html.escape(str(release_time))}",
                "",
            ])

        lines.extend([
            "━━━━━━━━━━━━━━━━━━",
            "🇮🇳 Timezone: IST",
        ])

        await loading.edit_text(
            "\n".join(lines),
            parse_mode="HTML",
            disable_web_page_preview=True,
        )

    except Exception:
        logger.exception("Today command error")

        await loading.edit_text(
            "⚠️ <b>Today's updates fetch nahi ho paayi.</b>",
            parse_mode="HTML",
        )


def get_subscriptions(
    context: ContextTypes.DEFAULT_TYPE,
) -> set[int]:
    return context.application.bot_data.setdefault(
        "subscriptions",
        set(),
    )


async def subscribe_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not update.message or not update.effective_chat:
        return

    subscriptions = get_subscriptions(context)
    chat_id = update.effective_chat.id

    if chat_id in subscriptions:
        await update.message.reply_text(
            "✅ Is chat me daily anime updates already ON hain."
        )
        return

    subscriptions.add(chat_id)

    chat_type = update.effective_chat.type

    if chat_type == ChatType.PRIVATE:
        target = "DM"
    elif chat_type in (ChatType.GROUP, ChatType.SUPERGROUP):
        target = "Group"
    else:
        target = "Chat"

    await update.message.reply_text(
        "✅ <b>Daily Updates ON</b>\n\n"
        f"📢 {target} me daily anime release updates bheje jayenge.",
        parse_mode="HTML",
    )


async def unsubscribe_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not update.message or not update.effective_chat:
        return

    subscriptions = get_subscriptions(context)
    chat_id = update.effective_chat.id

    if chat_id not in subscriptions:
        await update.message.reply_text(
            "ℹ️ Is chat me daily updates already OFF hain."
        )
        return

    subscriptions.discard(chat_id)

    await update.message.reply_text(
        "❌ <b>Daily Updates OFF</b>\n\n"
        "Ab is chat me automatic daily anime updates nahi aayengi.",
        parse_mode="HTML",
    )


def register_commands(application):
    """Register all bot commands on a python-telegram-bot Application."""

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("anime", anime_command))
    application.add_handler(CommandHandler("today", today_command))
    application.add_handler(CommandHandler("subscribe", subscribe_command))
    application.add_handler(CommandHandler("unsubscribe", unsubscribe_command))

    logger.info("Anime bot commands registered.")
