"""
Telegram command handlers for Anime Hindi Info Bot.

Commands:
    /start
    /help
    /anime <anime name>

Compatible with services.anime_scraper.AnimeInfo
"""

import html
from typing import Any

from telegram import Update
from telegram.ext import ContextTypes

from services.anime_scraper import (
    AnimeInfo,
    get_anime_info,
    format_anime_info,
)

from utils.logger import logger


# ============================================================
# START COMMAND
# ============================================================

async def start_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Handle /start command."""

    if not update.message:
        return

    user = update.effective_user
    user_id = user.id if user else "unknown"

    logger.info(
        f"Start command received from user {user_id}"
    )

    message = (
        "🎬 Welcome to Anime Hindi Dub Bot!\n\n"
        "Hindi-dubbed anime ki information check karein "
        "aur anime ka poster/details paayein.\n\n"

        "🎯 Use:\n"
        "/anime Naruto\n"
        "/anime Solo Leveling\n"
        "/anime Re Zero\n\n"

        "ℹ️ Commands:\n"
        "/start - Welcome message\n"
        "/help - Help aur examples\n"
        "/anime <name> - Anime search\n\n"

        "💬 Works in:\n"
        "✅ Private chats\n"
        "✅ Telegram groups\n\n"

        "✨ Information:\n"
        "✅ Anime poster\n"
        "✅ Hindi Dub status\n"
        "✅ Platform\n"
        "✅ Season\n"
        "✅ Episodes\n"
        "✅ Languages\n"
        "✅ Status\n"
        "✅ Release information\n"
        "✅ Studio\n"
        "✅ Dub By\n\n"

        "🔎 Source: DC"
    )

    await update.message.reply_text(message)


# ============================================================
# HELP COMMAND
# ============================================================

async def help_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Handle /help command."""

    if not update.message:
        return

    user = update.effective_user
    user_id = user.id if user else "unknown"

    logger.info(
        f"Help command received from user {user_id}"
    )

    message = (
        "ℹ️ Anime Hindi Dub Bot - Help\n\n"

        "1️⃣ /start\n"
        "Bot ka welcome message dikhata hai.\n\n"

        "2️⃣ /help\n"
        "Ye help message dikhata hai.\n\n"

        "3️⃣ /anime <anime_name>\n"
        "Anime search karke available information dikhata hai.\n\n"

        "📝 Examples:\n"
        "/anime Naruto\n"
        "/anime Naruto Shippuden\n"
        "/anime Dragon Ball\n"
        "/anime Bleach\n"
        "/anime Solo Leveling\n"
        "/anime Re Zero\n"
        "/anime Attack on Titan\n"
        "/anime Spy x Family\n"
        "/anime Naruto Movie\n\n"

        "📊 Search Result me:\n"
        "🎬 Anime Name\n"
        "🇮🇳 Hindi Dub\n"
        "📺 Platform\n"
        "📀 Season / Series\n"
        "🎬 Episodes (all matched seasons)\n"
        "🌐 Languages\n"
        "📊 Status\n"
        "📅 Last/Release information\n"
        "⏭ Next Episode (agar available ho)\n"
        "🏢 Studio\n"
        "🎙 Dub By\n"
        "🔎 Source\n\n"

        "💡 Tips:\n"
        "• Short/common anime name bhi try kar sakte ho.\n"
        "• Example: /anime Re Zero\n"
        "• Movie search ke liye naam ke saath Movie likho.\n"
        "• Spelling sahi rakhne par result better milega.\n"
        "• Naruto / Dragon Ball / Bleach jaise multi-season anime ke matched seasons ek result me aa sakte hain.\n\n"

        "🔎 Data source: DC"
    )

    await update.message.reply_text(message)


# ============================================================
# ANIME COMMAND
# ============================================================

async def anime_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Handle /anime <anime name> command."""

    if not update.message:
        return

    user = update.effective_user
    user_id = user.id if user else "unknown"

    chat = update.effective_chat
    chat_type = chat.type if chat else "unknown"

    logger.info(
        f"Anime command received from user {user_id} "
        f"in {chat_type} chat"
    )

    # --------------------------------------------------------
    # Check anime name
    # --------------------------------------------------------

    if not context.args:
        await update.message.reply_text(
            "❌ Usage:\n"
            "/anime <anime name>\n\n"
            "Examples:\n"
            "/anime Naruto\n"
            "/anime Solo Leveling\n"
            "/anime Re Zero"
        )
        return

    anime_name = " ".join(context.args).strip()

    if not anime_name:
        await update.message.reply_text(
            "❌ Please provide an anime name.\n\n"
            "Example:\n"
            "/anime Naruto"
        )
        return

    # --------------------------------------------------------
    # Loading message
    # --------------------------------------------------------

    loading_message = await update.message.reply_text(
        f"🔍 Searching for: {anime_name}\n"
        "⏳ Multiple seasons/series check ho rahi hain..." 
    )

    try:
        # ----------------------------------------------------
        # Fetch information from anime_scraper.py
        # ----------------------------------------------------

        anime_info = await get_anime_info(anime_name)

        # ----------------------------------------------------
        # Delete loading message
        # ----------------------------------------------------

        try:
            await loading_message.delete()
        except Exception as exc:
            logger.debug(
                f"Could not delete loading message: {exc}"
            )

        # ----------------------------------------------------
        # No result
        # ----------------------------------------------------

        if not anime_info:
            await update.message.reply_text(
                f"😕 Anime not found:\n"
                f"{anime_name}\n\n"
                "Try:\n"
                "• Another spelling\n"
                "• English title\n"
                "• Short/common title\n"
                "• Add Movie if it is a movie"
            )

            logger.info(
                f"Anime not found: {anime_name}"
            )
            return

        # ----------------------------------------------------
        # Send result
        # ----------------------------------------------------

        await send_anime_with_poster(
            update,
            anime_info,
        )

        logger.info(
            f"Successfully returned anime info: {anime_name}"
        )

    except Exception as exc:
        logger.exception(
            f"Error processing anime command "
            f"for '{anime_name}': {exc}"
        )

        try:
            await loading_message.delete()
        except Exception:
            pass

        await update.message.reply_text(
            "❌ Error: Unable to fetch anime information.\n\n"
            "Ye temporary problem ho sakti hai.\n"
            "Thodi der baad dobara try karo."
        )


# ============================================================
# SEND ANIME INFORMATION
# ============================================================

async def send_anime_with_poster(
    update: Update,
    anime_info: Any,
) -> None:
    """Send poster + anime information in the same Telegram message."""
    if not update.message:
        return

    try:
        if isinstance(anime_info, AnimeInfo):
            poster_url = anime_info.poster_url
            caption = format_anime_info(anime_info)
        elif isinstance(anime_info, dict):
            poster_url = anime_info.get("poster") or anime_info.get("poster_url")
            caption = _format_dict_anime_info(anime_info)
        else:
            await update.message.reply_text("❌ Invalid anime information received.")
            return

        if not caption or not caption.strip():
            await update.message.reply_text("❌ Anime information empty aa rahi hai.")
            return

        # Telegram photo caption limit is 1024 characters.
        if poster_url and _is_valid_url(poster_url):
            try:
                if len(caption) <= 1024:
                    await update.message.reply_photo(photo=poster_url, caption=caption)
                    return

                split_at = caption.rfind("\n", 0, 1000)
                if split_at <= 0:
                    split_at = 1000
                await update.message.reply_photo(
                    photo=poster_url,
                    caption=caption[:split_at],
                )
                caption = caption[split_at:].lstrip()
            except Exception as exc:
                logger.warning(f"Poster + caption failed: {exc}")

        # If there is no valid poster, or caption continued after the photo,
        # send the remaining text normally.
        while caption:
            if len(caption) <= 4000:
                await update.message.reply_text(caption, disable_web_page_preview=True)
                break
            split_at = caption.rfind("\n", 0, 4000)
            if split_at <= 0:
                split_at = 4000
            await update.message.reply_text(caption[:split_at], disable_web_page_preview=True)
            caption = caption[split_at:].lstrip()

    except Exception as exc:
        logger.exception(f"Error sending anime information: {exc}")
        try:
            await update.message.reply_text("❌ Error sending anime information.")
        except Exception:
            pass


# ============================================================
# URL VALIDATION
# ============================================================

def _is_valid_url(url: str) -> bool:
    """Return True if URL is HTTP/HTTPS."""

    if not isinstance(url, str):
        return False

    url = url.strip()

    return url.startswith(
        (
            "http://",
            "https://",
        )
    )


# ============================================================
# DICT FORMATTER
# ============================================================

def _format_dict_anime_info(
    anime_info: dict,
) -> str:
    """
    Backward-compatible formatter for dictionary data.

    This is only used if another part of the bot sends
    dictionary data instead of AnimeInfo.
    """

    name = _safe_text(
        anime_info.get("name"),
        "Unknown",
    )

    hindi_dub = _safe_text(
        anime_info.get("hindi_dub"),
        "Not Verified",
    )

    platform = _safe_text(
        anime_info.get("platform")
    )

    season = _safe_text(
        anime_info.get("season")
        or anime_info.get("seasons")
    )

    episodes = _safe_text(
        anime_info.get("episodes")
    )

    languages = _safe_text(
        anime_info.get("languages")
    )

    status = _safe_text(
        anime_info.get("status")
    )

    last_episode = _safe_text(
        anime_info.get("last_episode")
    )

    last_release = _safe_text(
        anime_info.get("last_release")
    )

    next_episode = _safe_text(
        anime_info.get("next_episode")
    )

    expected_release = _safe_text(
        anime_info.get("expected_release")
    )

    schedule = _safe_text(
        anime_info.get("schedule")
    )

    studio = _safe_text(
        anime_info.get("studio")
    )

    dub_by = _safe_text(
        anime_info.get("dub_by")
    )

    source = _safe_text(
        anime_info.get("source"),
        "DC",
    )

    lines = [
        f"🎬 Anime: {name}",
        "",
        f"🇮🇳 Hindi Dub: {hindi_dub}",
    ]

    if platform:
        lines.append(
            f"📺 Platform: {platform}"
        )

    if season:
        lines.append(
            f"📀 Season: {season}"
        )

    if episodes:
        lines.append(
            f"🎬 Episodes: {episodes}"
        )

    if languages:
        lines.extend(
            [
                "",
                f"🌐 Languages: {languages}",
            ]
        )

    if status:
        lines.extend(
            [
                "",
                f"📊 Status: {status}",
            ]
        )

    if last_episode:
        lines.append(
            f"📅 Last Episode: {last_episode}"
        )

    if last_release:
        lines.append(
            f"🗓 Last Release: {last_release}"
        )

    if next_episode:
        lines.append(
            f"⏭ Next Episode: {next_episode}"
        )

    if expected_release:
        lines.append(
            f"📅 Expected Release: {expected_release}"
        )

    if schedule:
        lines.append(
            f"⏰ Schedule: {schedule}"
        )

    if studio:
        lines.extend(
            [
                "",
                f"🏢 Studio: {studio}",
            ]
        )

    if dub_by:
        lines.append(
            f"🎙 Dub By: {dub_by}"
        )

    lines.extend(
        [
            "",
            f"🔎 Source: {source}",
        ]
    )

    return "\n".join(lines)


# ============================================================
# SAFE TEXT
# ============================================================

def _safe_text(
    value: Any,
    default: str = "",
) -> str:
    """Convert value to clean display text."""

    if value is None:
        return default

    if isinstance(value, list):
        value = " • ".join(
            str(item)
            for item in value
            if item
        )

    value = str(value).strip()

    return value if value else default






