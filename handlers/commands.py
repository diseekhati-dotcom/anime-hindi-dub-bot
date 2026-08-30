"""
Command handlers for Telegram bot
Handles /start, /help, and /anime commands
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
        "<a href='https://animemirchi.com/'>Anime Mirchi</a>.\n\n"
        "🎯 <b>Use me like this:</b>\n"
        "/anime Naruto\n\n"
        "ℹ️ <b>Available Commands:</b>\n"
        "/start - Show this welcome message\n"
        "/help - Show detailed help\n"
        "/anime &lt;name&gt; - Search for anime\n\n"
        "💡 <b>Works in:</b>\n"
        "✅ Private chats\n"
        "✅ Group chats (no admin privileges needed)\n\n"
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
        "Search for anime and get Hindi dub information.\n\n"
        
        "<b>📝 Examples:</b>\n"
        "/anime Naruto\n"
        "/anime Attack on Titan\n"
        "/anime Death Note\n\n"
        
        "<b>📊 What You'll Get:</b>\n"
        "🎬 <b>Anime name</b> - Official title\n"
        "🇮🇳 <b>Hindi Dub</b> - Available/Not Available/Status Unknown\n"
        "📺 <b>Platform</b> - Where to watch (if available)\n"
        "🇬🇧 <b>English Dub</b> - If reliably listed\n"
        "🔎 <b>Source</b> - Link to detailed article\n\n"
        
        "<b>✨ Features:</b>\n"
        "✅ Works in private chats and groups\n"
        "✅ No admin privileges required\n"
        "✅ Graceful error handling\n"
        "✅ Fast response times\n\n"
        
        "<b>❌ What This Bot Does NOT Do:</b>\n"
        "🚫 Download or store anime episodes\n"
        "🚫 Provide illegal streaming links\n"
        "🚫 Distribute copyrighted content\n\n"
        
        "<b>📚 Data Source:</b>\n"
        "Information is fetched from <a href='https://animemirchi.com/'>Anime Mirchi</a> - "
        "a trusted source for Hindi anime information.\n\n"
        
        "<b>❓ Tips:</b>\n"
        "• Use exact anime names for better results\n"
        "• Check the source link for more details\n"
        "• If anime not found, try alternate names\n\n"
        
        "Need more help? Try /start"
    )
    
    await update.message.reply_html(help_message)


async def anime_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle /anime command
    Searches for anime and returns Hindi dub information
    
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
            "/anime Attack on Titan",
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
        await loading_message.delete()

        if anime_info:
            # Format and send anime information
            response = _format_anime_info(anime_info)
            await update.message.reply_html(response)
            logger.info(f"Successfully returned anime info for: {anime_name}")
        else:
            # Anime not found
            await update.message.reply_html(
                f"😕 <b>Anime not found:</b> {html.escape(anime_name)}\n\n"
                "Try:\n"
                "• Checking the spelling\n"
                "• Using English title\n"
                "• Using alternative names\n\n"
                "📚 Visit <a href='https://animemirchi.com/'>Anime Mirchi</a> "
                "for more anime titles."
            )
            logger.info(f"Anime not found in database: {anime_name}")

    except Exception as e:
        # Handle unexpected errors
        await loading_message.delete()
        logger.error(f"Error processing anime command for '{anime_name}': {str(e)}")
        await update.message.reply_text(
            "❌ <b>Error:</b> Unable to fetch anime information.\n"
            "This might be temporary. Please try again in a moment.\n\n"
            "If the problem persists, check that the anime name is correct.",
            parse_mode='HTML'
        )


def _format_anime_info(anime_info: Dict) -> str:
    """
    Format anime information for display
    
    Args:
        anime_info: Dictionary with anime information
        
    Returns:
        Formatted HTML string for Telegram
    """
    name = html.escape(anime_info.get('name', 'Unknown'))
    hindi_dub = anime_info.get('hindi_dub', 'Status Unknown')
    platform = anime_info.get('platform')
    english_dub = anime_info.get('english_dub')
    source_link = anime_info.get('source_link')

    # Build response
    response = f"<b>🎬 Anime:</b> {name}\n"
    response += f"<b>🇮🇳 Hindi Dub:</b> {hindi_dub}\n"

    if platform:
        response += f"<b>📺 Platform:</b> {html.escape(platform)}\n"

    if english_dub:
        response += f"<b>🇬🇧 English Dub:</b> {english_dub}\n"

    if source_link:
        response += f"\n<a href='{source_link}'>🔎 Source Article</a>"
    else:
        response += "\n🔎 Source: Not available"

    return response
