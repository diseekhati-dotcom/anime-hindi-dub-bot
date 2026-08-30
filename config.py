"""
Configuration module for Anime Hindi Dub Bot
Loads environment variables and provides configuration constants
"""

import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Telegram Bot Configuration
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')

# Server Configuration (for Render deployment)
PORT = int(os.getenv('PORT', 8000))

# Anime Mirchi API Configuration
ANIME_MIRCHI_BASE_URL = 'https://animemirchi.com'
ANIME_MIRCHI_SEARCH_URL = f'{ANIME_MIRCHI_BASE_URL}/'

# Request Configuration
REQUEST_TIMEOUT = 10  # seconds
MAX_RETRIES = 2
RETRY_DELAY = 1  # seconds

# Bot Configuration
BOT_NAME = 'Anime Hindi Dub Bot'
COMMAND_PREFIX = '/'

# Validation
if not TELEGRAM_BOT_TOKEN:
    raise ValueError(
        "TELEGRAM_BOT_TOKEN is not set. "
        "Please set it in .env file or environment variables."
    )
