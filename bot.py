import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from telegram.ext import Application, CommandHandler

from config import TELEGRAM_BOT_TOKEN
from handlers.commands import start_command, help_command, anime_command
from handlers.errors import error_handler
from utils.logger import logger


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ("/", "/health"):
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"OK")
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        return


def start_health_server():
    port = int(os.environ.get("PORT", "10000"))

    server = ThreadingHTTPServer(
        ("0.0.0.0", port),
        HealthHandler
    )

    thread = threading.Thread(
        target=server.serve_forever,
        daemon=True
    )
    thread.start()

    logger.info(f"Health server started on port {port}")


def main():
    logger.info("Starting Anime Hindi Dub Bot...")

    try:
        start_health_server()

        application = (
            Application.builder()
            .token(TELEGRAM_BOT_TOKEN)
            .build()
        )

        application.add_handler(
            CommandHandler("start", start_command)
        )
        application.add_handler(
            CommandHandler("help", help_command)
        )
        application.add_handler(
            CommandHandler("anime", anime_command)
        )

        application.add_error_handler(error_handler)

        logger.info("Bot initialized successfully")
        logger.info("Starting Telegram polling...")

        application.run_polling(
            allowed_updates=["message", "edited_message"]
        )

    except Exception as e:
        logger.critical(f"Critical error: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    main()
