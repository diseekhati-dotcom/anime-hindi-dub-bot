# Anime Dub Check — Phase 1

Telegram bot for conservative live availability checking of anime and anime movies.

## Included
- `/start`
- `/anime <title>`
- Anime + movie mode
- India region
- Playwright Chromium browser
- 10 requested platform adapters
- `✅/❌/❓`-style verification architecture (unknown remains `❓`)
- 30-minute cache/monitor cycle
- Follow / Unfollow / Check now / Schedule / Watch now buttons
- Official-page candidate links only when a positive check has evidence

## Important
This is a working Phase-1 foundation, not a promise that every streaming service exposes all metadata publicly.
Some services require login, region checks, CAPTCHA, app-only access, or dynamically hide audio information.
In those cases the bot deliberately returns `❓ Unable to verify` instead of guessing.

The next hardening step is to replace the generic adapter for each service with a dedicated, tested parser for its current page structure.

## Render
Build:
`pip install -r requirements.txt && playwright install --with-deps chromium`

Start:
`python bot.py`

Environment:
`BOT_TOKEN=<your Telegram bot token>`

This is a Worker service because the Telegram bot uses long polling.
