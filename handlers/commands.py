"""
Command handlers for Telegram bot
Handles /start, /help, and /anime commands with poster image support
"""

from telegram import Update
from telegram.ext import ContextTypes
from typing import Optional, Dict
import html

from services.anime_scraper import get_anime_info
from utils.logger import logger


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle /start command
    Sends a welcome message to the user
    
    Args:
        update: Telegram update
        context: Telegram context
    """
    logger.info(f"Start command received from user {update.effective_user.id}")
    
    welcome_message = (
        "🎬 <b>Welcome to Anime Hindi Dub Bot!</b>\n\n"
        "I help you find information about Hindi-dubbed anime from "
        "multiple reliable sources.\n\n"
        "🎯 <b>Use me like this:</b>\n"
        "/anime Naruto\n\n"
        "ℹ️ <b>Available Commands:</b>\n"
        "/start - Show this welcome message\n"
        "/help - Show detailed help\n"
        "/anime &lt;name&gt; - Search for anime\n\n"
        "💡 <b>Works in:</b>\n"
        "✅ Private chats\n"
        "✅ Group chats (no admin privileges needed)\n\n"
        "🎬 <b>Features:</b>\n"
        "✅ Anime poster display\n"
        "✅ Hindi dub verification\n"
        "✅ Platform information\n"
        "✅ Multi-source data\n\n"
        "Use /help for more information!"
    )
    
    await update.message.reply_html(welcome_message)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle /help command
    Sends detailed help message to the user
    
    Args:
        update: Telegram update
        context: Telegram context
    """
    logger.info(f"Help command received from user {update.effective_user.id}")
    
    help_message = (
        "ℹ️ <b>Help - Available Commands</b>\n\n"
        
        "<b>1️⃣ /start</b>\n"
        "Shows the welcome message and quick overview.\n\n"
        
        "<b>2️⃣ /help</b>\n"
        "Shows this help message.\n\n"
        
        "<b>3️⃣ /anime &lt;anime_name&gt;</b>\n"
        "Search for anime and get Hindi dub information with poster.\n\n"
        
        "<b>📝 Examples:</b>\n"
        "/anime Naruto\n"
        "/anime Attack on Titan\n"
        "/anime Spy x Family\n"
        "/anime Naruto Movie\n\n"
        
        "<b>📊 What You'll Get:</b>\n"
        "🎬 <b>Anime Poster</b> - Official poster image\n"
        "📝 <b>Anime Name</b> - Official title\n"
        "🇮🇳 <b>Hindi Dub</b> - Available/Not Verified\n"
        "📺 <b>Platform</b> - Where to watch (Crunchyroll, Netflix, etc.)\n"
        "🎙️ <b>Dub By</b> - Dubbing studio (if available)\n"
        "📀 <b>Season</b> - Season information\n"
        "🎬 <b>Episodes</b> - Episode count/range\n"
        "🔄 <b>Status</b> - Ongoing/Completed\n"
        "🌐 <b>Languages</b> - Available audio languages\n"
        "🗓️ <b>Release Date</b> - Anime release date\n"
        "🔎 <b>Source</b> - Data sources used\n\n"
        
        "<b>✨ Features:</b>\n"
        "✅ Works in private chats and groups\n"
        "✅ No admin privileges required\n"
        "✅ Multi-source verification (AnimeDubHindi, Anime Mirchi, MyAnimeList)\n"
        "✅ Parallel data fetching for fast results (~6-8 seconds)\n"
        "✅ Anime poster display with details\n"
        "✅ Graceful error handling\n\n"
        
        "<b>❌ What This Bot Does NOT Do:</b>\n"
        "🚫 Download or store anime episodes\n"
        "🚫 Provide illegal streaming links\n"
        "🚫 Distribute copyrighted content\n\n"
        
        "<b>📚 Data Sources:</b>\n"
        "• AnimeDubHindi - Hindi dub status, seasons, episodes\n"
        "• Anime Mirchi - Platform and dub information\n"
        "• MyAnimeList/Jikan - Poster, studio, episode count\n\n"
        
        "<b>❓ Tips:</b>\n"
        "• Use exact anime names for better results\n"
        "• Add 'Movie' for movie searches\n"
        "• Check the source links for more details\n"
        "• Works with special characters (e.g., Spy × Family)\n\n"
        
        "Need more help? Try /start"
    )
    
    await update.message.reply_html(help_message)


async def anime_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle /anime command
    Searches for anime and returns Hindi dub information with poster
    
    Args:
        update: Telegram update
        context: Telegram context
    """
    logger.info(
        f"Anime command received from user {update.effective_user.id} "
        f"in {'private' if update.message.chat.type == 'private' else 'group'} chat"
    )
    
    # Check if anime name is provided
    if not context.args or len(context.args) == 0:
        await update.message.reply_text(
            "❌ <b>Usage:</b> /anime &lt;anime_name&gt;\n\n"
            "Examples:\n"
            "/anime Naruto\n"
            "/anime Death Note\n"
            "/anime Spy x Family\n"
            "/anime Naruto Movie",
            parse_mode='HTML'
        )
        return

    # Get anime name from arguments
    anime_name = ' '.join(context.args).strip()
    
    if not anime_name or len(anime_name) == 0:
        await update.message.reply_text(
            "❌ Please provide an anime name.\n"
            "Example: /anime Naruto"
        )
        return

    # Show loading message
    loading_message = await update.message.reply_text(
        f"🔍 Searching for '<b>{html.escape(anime_name)}</b>'...",
        parse_mode='HTML'
    )

    try:
        # Fetch anime information
        anime_info = get_anime_info(anime_name)

        # Delete loading message
        try:
            await loading_message.delete()
        except Exception as e:
            logger.debug(f"Could not delete loading message: {e}")

        if anime_info:
            # Send anime information with poster
            await send_anime_with_poster(update, anime_info)
            logger.info(f"Successfully returned anime info for: {anime_name}")
        else:
            # Anime not found
            await update.message.reply_html(
                f"😕 <b>Anime not found:</b> {html.escape(anime_name)}\n\n"
                "Try:\n"
                "• Checking the spelling\n"
                "• Using English title\n"
                "• Using alternative names\n"
                "• Adding 'Movie' if searching for a movie"
            )
            logger.info(f"Anime not found in database: {anime_name}")

    except Exception as e:
        # Handle unexpected errors
        try:
            await loading_message.delete()
        except:
            pass
        logger.error(f"Error processing anime command for '{anime_name}': {str(e)}")
        await update.message.reply_text(
            "❌ <b>Error:</b> Unable to fetch anime information.\n"
            "This might be temporary. Please try again in a moment.\n\n"
            "If the problem persists, check that the anime name is correct.",
            parse_mode='HTML'
        )


async def send_anime_with_poster(update: Update, anime_info: Dict) -> None:
    """
    Send anime information with poster image
    
    Args:
        update: Telegram update
        anime_info: Dictionary with anime information
    """
    poster_url = anime_info.get('poster_url')
    caption = _format_anime_info(anime_info)

    try:
        # If poster URL is available, send as photo with caption
        if poster_url and _is_valid_url(poster_url):
            try:
                await update.message.reply_photo(
                    photo=poster_url,
                    caption=caption,
                    parse_mode='HTML'
                )
                logger.debug(f"Sent anime info with poster: {poster_url}")
                return
            except Exception as e:
                logger.warning(f"Failed to send poster from URL {poster_url}: {e}")
                # Fall back to text-only if poster fails

        # If no poster or poster failed, send as text
        await update.message.reply_html(caption)
        logger.debug("Sent anime info as text (no poster)")

    except Exception as e:
        logger.error(f"Error sending anime message: {e}")
        await update.message.reply_text("Error sending anime information.")


def _is_valid_url(url: str) -> bool:
    """Check if URL is valid."""
    if not url:
        return False
    return url.startswith(('http://', 'https://'))


def _format_anime_info(anime_info: Dict) -> str:
    """
    Format anime information for display
    
    Args:
        anime_info: Dictionary with anime information
        
    Returns:
        Formatted HTML string for Telegram
    """
    name = html.escape(anime_info.get('name', 'Unknown'))
    hindi_dub = anime_info.get('hindi_dub', 'Not Verified')
    platform = anime_info.get('platform')
    dub_by = anime_info.get('dub_by')
    seasons = anime_info.get('seasons')
    episodes = anime_info.get('episodes')
    status = anime_info.get('status')
    languages = anime_info.get('languages')
    release_date = anime_info.get('release_date')
    source = anime_info.get('source', 'DC')
    source_link = anime_info.get('source_link')
    mal_url = anime_info.get('mal_url')

    # Build response
    response = f"<b>🎬 Anime:</b> {name}\n"
    response += f"<b>🇮🇳 Hindi Dub:</b> {hindi_dub}\n"

    if platform:
        response += f"<b>📺 Platform:</b> {html.escape(platform)}\n"

    if dub_by:
        response += f"<b>🎙️ Dub By:</b> {html.escape(dub_by)}\n"

    if seasons:
        response += f"<b>📀 Season:</b> {seasons}\n"

    if episodes:
        response += f"<b>🎬 Episodes:</b> {episodes}\n"

    if status:
        response += f"<b>🔄 Status:</b> {status}\n"

    if languages:
        response += f"<b>🌐 Languages:</b> {languages}\n"

    if release_date:
        response += f"<b>🗓️ Release Date:</b> {release_date}\n"

    response += f"\n<b>🔎 Source:</b> {source}"

    if source_link:
        response += f" • <a href='{source_link}'>View Article</a>"
    
    if mal_url:
        response += f" • <a href='{mal_url}'>MyAnimeList</a>"

    return response
