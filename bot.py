"""
Anime Hindi Dub Bot - Main Entry Point
Telegram bot providing information about Hindi-dubbed anime
"""

import logging
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from telegram.ext import (
Application,
CommandHandler,
)

from config import TELEGRAM_BOT_TOKEN
from handlers.commands import (
start_command,
help_command,
anime_command,
)
from handlers.errors import error_handler
from utils.logger import logger

class HealthHandler(BaseHTTPRequestHandler):
"""Simple HTTP health-check endpoint for Render."""

def do_GET(self):
    if self.path == "/" or self.path == "/health":
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Anime Hindi Dub Bot is running!")
    else:
        self.send_response(404)
        self.end_headers()

def log_message(self, format, *args):
    # Keep health-check requests out of the normal HTTP log.
    return

def start_health_server() -> None:
"""Start the HTTP health server in a background thread."""

port = int(os.environ.get("PORT", "10000"))

server = ThreadingHTTPServer(("0.0.0.0", port), HealthHandler)

thread = threading.Thread(
    target=server.serve_forever,
    daemon=True,
)
thread.start()

logger.info(f"Health server started on port {port}")

def main() -> None:
"""
Main function to start the bot.
Starts the health server and Telegram polling.
"""

logger.info("=" * 50)
logger.info("Starting Anime Hindi Dub Bot...")
logger.info("=" * 50)

try:
    # Start HTTP health endpoint for Render.
    start_health_server()

    # Create the Telegram Application.
    application = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .build()
    )

    # Register command handlers.
    logger.info("Registering command handlers...")

    application.add_handler(
        CommandHandler("start", start_command)
    )

    application.add_handler(
        CommandHandler("help", help_command)
    )

    application.add_handler(
        CommandHandler("anime", anime_command)
    )

    # Register error handler.
    application.add_error_handler(error_handler)

    logger.info("Bot initialized successfully")
    logger.info("Commands registered: /start, /help, /anime")
    logger.info("=" * 50)

    # Start Telegram polling.
    logger.info("Starting bot polling...")

    application.run_polling(
        allowed_updates=["message", "edited_message"]
    )

except ValueError as e:
    logger.critical(f"Configuration error: {str(e)}")
    logger.critical(
        "Ensure TELEGRAM_BOT_TOKEN is configured "
        "as an environment variable."
    )
    raise

except KeyboardInterrupt:
    logger.info("Bot interrupted by user")

except Exception as e:
    logger.critical(
        f"Critical error: {str(e)}",
        exc_info=True,
    )
    raise

if name == "main":
main()
