"""
Error handling and logging for Telegram bot
"""

from telegram import Update
from telegram.ext import ContextTypes
from utils.logger import logger


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Log the error and send a message to notify the user about it
    
    Args:
        update: Telegram update
        context: Telegram context with error
    """
    logger.error(
        msg="Exception while handling an update:",
        exc_info=context.error
    )

    # Send error message to user if update is available
    if update and update.effective_message:
        try:
            await update.effective_message.reply_text(
                "❌ An error occurred while processing your request. "
                "Please try again later or contact support."
            )
        except Exception as e:
            logger.error(f"Failed to send error message: {str(e)}")


async def handle_invalid_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle invalid or unrecognized commands
    
    Args:
        update: Telegram update
        context: Telegram context
    """
    if update.message:
        logger.warning(f"Invalid command received: {update.message.text}")
        await update.message.reply_text(
            "❓ Sorry, I didn't recognize that command.\n\n"
            "Use /help to see available commands."
        )
