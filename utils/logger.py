"""
Logging configuration for Anime Hindi Dub Bot
"""

import logging
import sys
from datetime import datetime

# Create logger
logger = logging.getLogger('anime_hindi_dub_bot')
logger.setLevel(logging.DEBUG)

# Create console handler with a higher log level
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.DEBUG)

# Create file handler for error logs
log_filename = f"logs/bot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
try:
    import os
    os.makedirs('logs', exist_ok=True)
    file_handler = logging.FileHandler(log_filename)
    file_handler.setLevel(logging.WARNING)
except (OSError, IOError) as e:
    print(f"Warning: Could not create log file: {e}")
    file_handler = None

# Create formatter
formatter = logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# Add formatter to handlers
console_handler.setFormatter(formatter)
if file_handler:
    file_handler.setFormatter(formatter)

# Add handlers to logger
logger.addHandler(console_handler)
if file_handler:
    logger.addHandler(file_handler)
