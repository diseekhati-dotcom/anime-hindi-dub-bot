# Anime Hindi Dub Bot 🎬

A Telegram bot that provides information about Hindi-dubbed anime from [Anime Mirchi](https://animemirchi.com/).

## Features

- 🎯 Search for anime and check Hindi dub availability
- 📺 Get official platform information where Hindi dubs are available
- 🇬🇧 View English dub availability (when reliably listed)
- 🔗 Direct links to source articles
- ✅ Works in private chats and group chats
- 👥 No administrator privileges required for regular users
- 🛡️ Graceful error handling and comprehensive logging
- 🚀 Render-compatible deployment ready

## Commands

### `/start`
Shows a welcome message and quick overview of how to use the bot.

### `/help`
Displays detailed help information with examples, features, and tips.

### `/anime <anime_name>`
Search for Hindi-dubbed anime information.

**Example:**
```
/anime Naruto
```

**Bot Response:**
```
🎬 Anime: Naruto
🇮🇳 Hindi Dub: Available
📺 Platform: Netflix
🇬🇧 English Dub: Available
🔎 Source Article
```

---

## Project Structure

```
anime-hindi-dub-bot/
├── bot.py                      # Main entry point
├── config.py                   # Configuration & environment variables
├── requirements.txt            # Python dependencies
├── .env.example                # Environment variables template
├── .gitignore                  # Git ignore rules
├── Procfile                    # Render deployment config
├── LICENSE                     # MIT License
├── README.md                   # This file
│
├── handlers/                   # Command & error handlers
│   ├── __init__.py
│   ├── commands.py             # /start, /help, /anime handlers
│   └── errors.py               # Error handling & logging
│
├── services/                   # Business logic & data fetching
│   ├── __init__.py
│   └── anime_scraper.py        # Anime Mirchi scraper
│
└── utils/                      # Utility modules
    ├── __init__.py
    └── logger.py               # Logging configuration
```

---

## Installation & Setup

### Prerequisites

- Python 3.9 or higher
- Telegram account
- Telegram Bot Token (get from [@BotFather](https://t.me/botfather))

### Local Development

1. **Clone the repository**
   ```bash
   git clone https://github.com/diseekhati-dotcom/anime-hindi-dub-bot.git
   cd anime-hindi-dub-bot
   ```

2. **Create and activate virtual environment**
   ```bash
   # On Linux/macOS
   python3 -m venv venv
   source venv/bin/activate

   # On Windows
   python -m venv venv
   venv\Scripts\activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Set up environment variables**
   ```bash
   cp .env.example .env
   ```
   Edit `.env` and add your bot token:
   ```
   TELEGRAM_BOT_TOKEN=your_actual_bot_token_here
   PORT=8000
   ```

5. **Run the bot locally**
   ```bash
   python bot.py
   ```
   You should see:
   ```
   ==================================================
   Starting Anime Hindi Dub Bot...
   ==================================================
   Registering command handlers...
   Bot initialized successfully
   Commands registered: /start, /help, /anime
   ==================================================
   Starting bot polling...
   ```

---

## Deployment to Render

### Step 1: Push to GitHub
Ensure all files are committed and pushed:
```bash
git add .
git commit -m "Initial commit: Anime Hindi Dub Bot"
git push origin main
```

### Step 2: Create Render Service

1. Go to [render.com](https://render.com)
2. Click **"New +"** → **"Web Service"**
3. Connect your GitHub repository (`anime-hindi-dub-bot`)
4. Configure:
   - **Name:** `anime-hindi-dub-bot`
   - **Environment:** Python 3
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `python bot.py`
   - **Instance Type:** Free tier is sufficient

### Step 3: Add Environment Variables

1. In Render dashboard, go to your service
2. Click **"Environment"** tab
3. Add these environment variables:
   - **Key:** `TELEGRAM_BOT_TOKEN`
     **Value:** Your bot token from @BotFather
   - **Key:** `PORT`
     **Value:** `8000`

### Step 4: Deploy

1. Click **"Create Web Service"**
2. Render will automatically deploy when changes are pushed to GitHub
3. Check **"Logs"** tab to verify the bot started successfully

---

## How It Works

### Bot Flow
1. User sends `/anime <anime_name>` command
2. Bot validates the command and anime name
3. Bot queries Anime Mirchi website for Hindi dub information
4. Bot scrapes and parses the webpage
5. Bot extracts:
   - Anime name/title
   - Hindi dub availability status
   - Official platform (if available)
   - English dub information
   - Source article link
6. Bot sends formatted results to user with emojis and links
7. Errors are logged and user-friendly messages are displayed

### Data Source
- **Source:** [Anime Mirchi](https://animemirchi.com/)
- **Type:** Public, freely available information
- **What's Fetched:** Anime metadata and Hindi dub availability
- **What's NOT Done:** 
  - ❌ Downloads or stores anime episodes
  - ❌ Provides illegal streaming links
  - ❌ Distributes copyrighted content

---

## Configuration Files

### `config.py`
Central configuration module that:
- Loads environment variables from `.env`
- Validates required tokens at startup
- Defines API URLs, timeouts, and retry logic
- Sets logging levels and bot behavior

### `.env.example` → `.env`
Template for environment variables. Never commit `.env` to version control!
```
TELEGRAM_BOT_TOKEN=your_token_here
PORT=8000
```

### `Procfile`
Tells Render how to start the bot:
```
worker: python bot.py
```

---

## File Descriptions

### Core Files

| File | Purpose |
|------|---------|
| `bot.py` | Main entry point, initializes Telegram Application, registers handlers |
| `config.py` | Environment variables and configuration constants |
| `requirements.txt` | Python package dependencies |

### Handlers (`handlers/`)

| File | Purpose |
|------|---------|
| `commands.py` | Implements `/start`, `/help`, `/anime` commands |
| `errors.py` | Global error handler, logs exceptions, sends user messages |

### Services (`services/`)

| File | Purpose |
|------|---------|
| `anime_scraper.py` | Web scraper for Anime Mirchi, parses anime info |

### Utils (`utils/`)

| File | Purpose |
|------|---------|
| `logger.py` | Logging configuration (console + file output) |

---

## Error Handling

The bot gracefully handles:

✅ **Network Errors**
- Timeout errors → Retries up to 2 times with 1-second delay
- Connection errors → Retries with exponential backoff
- HTTP errors → Logs and shows user-friendly message

✅ **Data Errors**
- Invalid anime names → Suggests checking spelling
- Missing information → Shows "Status Unknown" or "Not Available"
- Website structure changes → Logs error and notifies user

✅ **Telegram Errors**
- Rate limiting → Respected automatically
- Permission errors → Graceful degradation
- Message delivery failures → Logged for debugging

---

## Logging

Logs are output to:
1. **Console** - Real-time monitoring (DEBUG level)
2. **File** - Persistent storage in `logs/` directory (WARNING level)

**Log Format:**
```
2024-08-30 15:23:45 - anime_hindi_dub_bot - INFO - Anime command received from user 123456789
```

**Log Levels:**
- `DEBUG` - Detailed debugging information
- `INFO` - General information and bot events
- `WARNING` - Warnings and potential issues
- `ERROR` - Errors and exceptions

---

## Group Chat Support

The bot works seamlessly in Telegram groups:

✅ **What Works:**
- Any group member can use `/anime <name>`
- Bot responds to commands without admin privileges
- Works in public and private groups
- Respects Telegram's group permissions

✅ **What Doesn't:**
- No attempt to bypass group security settings
- No requirement for administrator status
- Follows Telegram's official bot behavior

---

## Limitations

⚠️ **Important to Know:**

1. **Search Scope** - Only searches anime with available Hindi dub info on Anime Mirchi
2. **Data Accuracy** - Depends on Anime Mirchi's database; may not be 100% current
3. **Rate Limiting** - Heavy usage may trigger Telegram API rate limits
4. **Website Changes** - If Anime Mirchi changes HTML structure, scraper may need updates
5. **Coverage** - Not all anime have Hindi dub information available

---

## Troubleshooting

### Bot doesn't respond

**Check:**
1. Bot token is correct in `.env`
2. Bot is running: `python bot.py`
3. No firewall/proxy blocking Telegram
4. Check logs for errors

### Anime not found

**Try:**
1. Check spelling of anime name
2. Use English title instead of transliteration
3. Try alternative names (e.g., "AOT" for "Attack on Titan")
4. Visit [Anime Mirchi](https://animemirchi.com/) to verify anime exists

### Deployment issues on Render

**Check:**
1. `TELEGRAM_BOT_TOKEN` environment variable is set
2. Build logs show successful dependency installation
3. Start command is: `python bot.py`
4. Check runtime logs in Render dashboard

---

## Tech Stack

| Component | Technology |
|-----------|------------|
| Bot Framework | [python-telegram-bot](https://python-telegram-bot.org/) v20.7 |
| Web Scraping | [BeautifulSoup4](https://www.crummy.com/software/BeautifulSoup/) |
| HTTP Requests | [Requests](https://docs.python-requests.org/) |
| HTML Parser | [LXML](https://lxml.de/) |
| Env Management | [python-dotenv](https://github.com/theskumar/python-dotenv) |
| Deployment | [Render](https://render.com/) |
| Version Control | [Git](https://git-scm.com/) / [GitHub](https://github.com/) |

---

## Contributing

Contributions are welcome! Here's how:

1. **Fork** the repository
2. **Create** a feature branch: `git checkout -b feature/amazing-feature`
3. **Commit** your changes: `git commit -m 'Add amazing feature'`
4. **Push** to branch: `git push origin feature/amazing-feature`
5. **Open** a Pull Request

**Ideas for contributions:**
- Better anime search algorithm
- Support for more streaming platforms
- Additional anime information (genres, episodes, etc.)
- Multi-language support
- Caching for faster responses
- Database integration for anime data

---

## License

This project is licensed under the MIT License - see [LICENSE](LICENSE) file for details.

---

## Disclaimer

⚠️ **Important:**

- This bot is **not affiliated with or endorsed** by Anime Mirchi, Telegram, or any anime studios
- Built for **educational and informational purposes only**
- **Respects copyright and terms of service** of all sources
- Does **NOT download, store, or distribute** copyrighted anime episodes
- Only displays **publicly available metadata**

---

## Support & Feedback

- 📝 **Issues:** [GitHub Issues](https://github.com/diseekhati-dotcom/anime-hindi-dub-bot/issues)
- 💬 **Discussions:** [GitHub Discussions](https://github.com/diseekhati-dotcom/anime-hindi-dub-bot/discussions)
- 📧 **Contact:** Open an issue for support

---

## Roadmap

🔮 **Planned Features:**
- [ ] Anime database caching for faster searches
- [ ] Support for more information sources
- [ ] Advanced search filters (year, genre, status)
- [ ] User preferences and bookmarks
- [ ] Multi-language support
- [ ] In-line query support for groups

---

## Quick Start Recap

```bash
# 1. Clone
git clone https://github.com/diseekhati-dotcom/anime-hindi-dub-bot.git
cd anime-hindi-dub-bot

# 2. Setup
python -m venv venv
source venv/bin/activate  # or: venv\Scripts\activate (Windows)
pip install -r requirements.txt

# 3. Configure
cp .env.example .env
# Edit .env and add TELEGRAM_BOT_TOKEN

# 4. Run
python bot.py

# 5. Test
# Open Telegram and send: /start
```

---

**Made with ❤️ using python-telegram-bot**

**Last Updated:** August 30, 2024  
**Version:** 1.0.0  
**Status:** Production Ready ✅
