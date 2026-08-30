"""
Anime Hindi Dub Bot - Main Entry Point
Telegram bot providing information about Hindi-dubbed anime
"""

import logging
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
)

from config import TELEGRAM_BOT_TOKEN
from handlers.commands import (
    start_command,
    help_command,
    anime_command,
)
from handlers.errors import error_handler, handle_invalid_command
from utils.logger import logger


def main() -> None:
    """
    Main function to start the bot
    Sets up handlers and starts polling
    """
    logger.info("=" * 50)
    logger.info("Starting Anime Hindi Dub Bot...")
    logger.info("=" * 50)

    try:
        # Create the Application
        application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

        # Register command handlers
        logger.info("Registering command handlers...")
        application.add_handler(CommandHandler("start", start_command))
        application.add_handler(CommandHandler("help", help_command))
        application.add_handler(CommandHandler("anime", anime_command))

        # Register error handler
        application.add_error_handler(error_handler)

        # Log bot start
        logger.info("Bot initialized successfully")
        logger.info("Commands registered: /start, /help, /anime")
        logger.info("=" * 50)

        # Start the Bot
        logger.info("Starting bot polling...")
        application.run_polling(allowed_updates=['message', 'edited_message'])

    except ValueError as e:
        logger.critical(f"Configuration error: {str(e)}")
        logger.critical("Ensure TELEGRAM_BOT_TOKEN is set in .env file")
        raise
    except KeyboardInterrupt:
        logger.info("Bot interrupted by user")
    except Exception as e:
        logger.critical(f"Critical error: {str(e)}", exc_info=True)
        raise


if __name__ == '__main__':
    main()
