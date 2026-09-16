import asyncio
import logging
import os
from datetime import datetime, timezone

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
)

from services.orchestrator import AnimeDubChecker
from services.store import FollowStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("anime-dub-check")

TOKEN = os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is required")

checker = AnimeDubChecker()
store = FollowStore()

def now_ist():
    from zoneinfo import ZoneInfo
    return datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%d %b %Y, %I:%M %p IST")

def buttons(title: str):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔔 Follow", callback_data=f"follow:{title}"),
            InlineKeyboardButton("🔕 Unfollow", callback_data=f"unfollow:{title}")
        ],
        [
            InlineKeyboardButton("🔄 Check now", callback_data=f"check:{title}"),
            InlineKeyboardButton("📅 Schedule", callback_data=f"schedule:{title}")
        ],
        [InlineKeyboardButton("📺 Watch now", callback_data=f"watch:{title}")]
    ])

async def render_result(result):
    return result.to_telegram_text(now_ist())

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "🎬 Anime Dub Check\n\n"
        "Anime ya Anime Movie ki live availability check karne ke liye:\n"
        "/anime Naruto\n"
        "/anime Your Name\n\n"
        "India region, platform, audio, subtitles, episodes aur dub status verify kiya jayega."
    )
    await update.message.reply_text(text)

async def anime_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage:\n/anime <anime ya movie name>")
        return
    title = " ".join(context.args).strip()
    msg = await update.message.reply_text("🔎 Live verification shuru ho rahi hai...")
    try:
        result = await checker.check(title)
        await msg.edit_text(await render_result(result), reply_markup=buttons(result.title))
    except Exception:
        log.exception("check failed")
        await msg.edit_text("❓ Verification complete nahi ho saki. Thodi der baad 🔄 Check now try karein.")

async def text_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    # Plain title messages are supported, but commands remain preferred.
    title = update.message.text.strip()
    if len(title) < 2 or title.startswith("/"):
        return
    await update.message.reply_text(f"🔎 `{title}` check karne ke liye /anime {title} use karein.", parse_mode="Markdown")

async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    action, title = q.data.split(":", 1)
    if action == "follow":
        store.follow(q.from_user.id, title)
        await q.edit_message_reply_markup(reply_markup=buttons(title))
        await q.message.reply_text(f"🔔 Followed: {title}\nBot approximately har 30 minute me update check karega.")
    elif action == "unfollow":
        store.unfollow(q.from_user.id, title)
        await q.message.reply_text(f"🔕 Unfollowed: {title}")
    elif action == "check":
        await q.message.reply_text("🔄 Fresh live check chal raha hai...")
        try:
            result = await checker.check(title, force=True)
            await q.message.reply_text(await render_result(result), reply_markup=buttons(result.title))
        except Exception:
            log.exception("manual check failed")
            await q.message.reply_text("❓ Fresh verification nahi ho saki.")
    elif action == "schedule":
        await q.message.reply_text("📅 Schedule: followed items ko 30-minute monitoring cycle me check kiya jayega. Custom time scheduling ko next release me enable kiya ja sakta hai.")
    elif action == "watch":
        await q.message.reply_text("📺 Watch now sirf verified official watch links hone par result me show honge.")

async def monitor_job(context: ContextTypes.DEFAULT_TYPE):
    for user_id, title in store.all_follows():
        try:
            result = await checker.check(title)
            key = result.notification_key()
            if store.should_notify(user_id, title, key):
                chat = await context.bot.get_chat(user_id)
                await context.bot.send_message(
                    chat_id=chat.id,
                    text="🔔 New Episode / Availability Update\n\n" + await render_result(result),
                    reply_markup=buttons(result.title)
                )
                store.mark_notified(user_id, title, key)
        except Exception:
            log.exception("monitor failed for %s", title)

async def post_init(app):
    # Warm the Playwright browser lazily; no network call is made at startup.
    pass

def main():
    app = Application.builder().token(TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("anime", anime_cmd))
    app.add_handler(CallbackQueryHandler(callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_search))
    app.job_queue.run_repeating(monitor_job, interval=1800, first=60)
    log.info("Anime Dub Check started")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
