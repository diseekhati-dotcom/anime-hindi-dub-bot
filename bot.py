"""
Anime Hindi Dub Bot - Main Entry Point
Telegram bot providing information about Hindi-dubbed anime.
"""

import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from telegram.ext import Application, CommandHandler

from config import TELEGRAM_BOT_TOKEN
from handlers.commands import (
start_command,
help_command,
anime_command,
)
from handlers.errors import error_handler
from utils.logger import logger

class HealthHandler(BaseHTTPRequestHandler):
"""HTTP health endpoint for Render."""

def do_GET(self):
    if self.path in ("/", "/health"):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"OK")
    else:
        self.send_response(404)
        self.end_headers()

def log_message(self, format, *args):
    # Don't print UptimeRobot/health-check requests.
    pass

def start_health_server():
"""Start the Render health server in the background."""

port = int(os.environ.get("PORT", "10000"))

server = ThreadingHTTPServer(
    ("0.0.0.0", port),
    HealthHandler,
)

thread = threading.Thread(
    target=server.serve_forever,
    daemon=True,
)
thread.start()

logger.info(f"Health server running on port {port}")

def main() -> None:
"""Start the Telegram bot."""

logger.info("=" * 50)
logger.info("Starting Anime Hindi Dub Bot...")
logger.info("=" * 50)

try:
    # Start HTTP server required by Render Web Service.
    start_health_server()

    # Create Telegram application.
    application = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .build()
    )

    # Telegram commands.
    application.add_handler(
        CommandHandler("start", start_command)
    )

    application.add_handler(
        CommandHandler("help", help_command)
    )

    application.add_handler(
        CommandHandler("anime", anime_command)
    )

    # Error handler.
    application.add_error_handler(error_handler)

    logger.info("Bot initialized successfully.")
    logger.info("Commands: /start, /help, /anime")
    logger.info("Starting Telegram polling...")

    # Start Telegram bot.
    application.run_polling(
        allowed_updates=["message", "edited_message"]
    )

except ValueError as e:
    logger.critical(f"Configuration error: {e}")
    logger.critical(
        "Make sure TELEGRAM_BOT_TOKEN is configured "
        "in Render Environment Variables."
    )
    raise

except KeyboardInterrupt:
    logger.info("Bot stopped.")

except Exception as e:
    logger.critical(
        f"Critical error: {e}",
        exc_info=True,
    )
    raise

if name == "main":
main()
