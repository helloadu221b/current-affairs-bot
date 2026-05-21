import json
import asyncio
import os
from datetime import datetime, timezone

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

BOT_TOKEN  = os.environ["BOT_TOKEN"]
CHANNEL_ID = os.environ["CHANNEL_ID"]
ADMIN_ID   = int(os.environ["ADMIN_ID"])

# POSTING SCHEDULE (24h format, local server time)
POST_HOUR_START = 4   # 4 AM
POST_HOUR_END   = 22  # 10 PM

# INTERVAL BETWEEN POSTS (seconds) — changeable via /setinterval
POST_INTERVAL = 1200  # 20 minutes

# RUNTIME STATE
paused      = False
start_time  = datetime.now(timezone.utc)
posts_sent  = 0
last_posted = None


# ─────────────────────────────────────────
# FILE HELPERS
# ─────────────────────────────────────────

def load_json(filename):
    with open(filename, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(filename, data):
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ─────────────────────────────────────────
# FORMAT HELPERS
# ─────────────────────────────────────────

def format_news(item, label="📰 TODAY NEWS"):
    # NEW STRUCTURED FORMAT (has "title" field)
    if "title" in item:
        facts = item.get("facts", [])
        facts_text = "\n".join(f"▪️ {f}" for f in facts) if facts else ""

        parts = [f"*{label}*\n"]
        parts.append(f"🏛️ *{item['title']}*\n")

        if item.get("who"):
            parts.append(f"👤 *Who →* {item['who']}")
        if item.get("what"):
            parts.append(f"📋 *What →* {item['what']}")
        if item.get("where"):
            parts.append(f"📍 *Where →* {item['where']}")
        if item.get("purpose"):
            parts.append(f"🎯 *Purpose →* {item['purpose']}")

        if facts_text:
            parts.append(f"\n📌 *Important Facts*\n{facts_text}")

        if item.get("exam_angle"):
            parts.append(f"\n⚠️ *Exam Angle →* {item['exam_angle']}")

        if item.get("hashtags"):
            parts.append(f"\n{item['hashtags']}")

        return "\n".join(parts)

    # OLD RAW FORMAT (has "content" field) — kept for backward compatibility
    return f"*{label}*\n\n" + item["content"]


def format_mcq(item, label="📰 TODAY MCQ"):
    options_text = "\n".join(item["options"])
    return (
        f"*{label}*\n\n"
        f"❓ *QUESTION*\n\n"
        f"{item['question']}\n\n"
        f"{options_text}\n\n"
        f"✅ *Answer:* {item['answer']}\n\n"
        f"📝 {item['explanation']}"
    )


def detect_type(item):
    if "question" in item:
        return "mcq"
    return "news"


def format_post(item, label=None):
    is_mcq = item.get("type") == "mcq"

    # DEFAULT LABELS
    if label is None:
        label = "📰 TODAY MCQ" if is_mcq else "📰 TODAY NEWS"

    if is_mcq:
        return format_mcq(item, label)
    return format_news(item, label)


# ─────────────────────────────────────────
# ADMIN CHECK
# ─────────────────────────────────────────

def is_admin(update: Update) -> bool:
    return update.effective_user.id == ADMIN_ID


async def deny(update: Update):
    await update.message.reply_text("⛔ You are not authorized to use this command.")


# ─────────────────────────────────────────
# SCHEDULE CHECK
# ─────────────────────────────────────────

def within_posting_hours() -> bool:
    hour = datetime.now().hour
    return POST_HOUR_START <= hour < POST_HOUR_END


# ─────────────────────────────────────────
# SHARED: PROCESS & ADD ITEMS TO QUEUE
# ─────────────────────────────────────────

async def process_new_items(update: Update, context: ContextTypes.DEFAULT_TYPE, new_items: list):

    queue   = load_json("queue.json")
    archive = load_json("archive.json")
    added   = []

    for item in new_items:

        # SKIP DUPLICATES (check content or question)
        is_duplicate = any(
            existing.get("content") == item.get("content") and
            existing.get("question") == item.get("question")
            for existing in archive
        )

        if is_duplicate:
            print("⚠️ Duplicate skipped")
            continue

        item["type"]           = detect_type(item)
        item["id"]             = f"POST_{len(archive) + len(added) + 1}"
        item["revision_count"] = 0
        added.append(item)

    queue_was_empty = len(queue) == 0

    queue.extend(added)
    archive.extend(added)

    save_json("queue.json", queue)
    save_json("archive.json", archive)

    # PREVIEW FIRST ITEM BEFORE ADDING
    if added:
        preview_text = (
            f"👁 *Preview of first item ({added[0]['type'].upper()}):*\n\n"
            + format_post(added[0])
        )
        await update.message.reply_text(preview_text, parse_mode="Markdown")

    # INSTANT FIRST POST IF QUEUE WAS EMPTY AND IN HOURS
    if queue_was_empty and added and within_posting_hours() and not paused:
        first = queue.pop(0)
        await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text=format_post(first),
            parse_mode="Markdown"
        )
        save_json("queue.json", queue)
        global posts_sent, last_posted
        posts_sent  += 1
        last_posted  = first["id"]
        print(f"✅ Instantly posted: {first['id']}")

    await update.message.reply_text(
        f"✅ *{len(added)} new posts added to queue!*\n"
        f"⏭ Duplicates skipped: {len(new_items) - len(added)}",
        parse_mode="Markdown"
    )


# ─────────────────────────────────────────
# FILE UPLOAD HANDLER (.json file)
# ─────────────────────────────────────────

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not is_admin(update):
        await deny(update)
        return

    document = update.message.document
    if not document:
        return

    # DOWNLOAD AND READ FILE
    file = await context.bot.get_file(document.file_id)
    file_name = document.file_name
    await file.download_to_drive(file_name)

    try:
        new_items = load_json(file_name)
    except Exception:
        await update.message.reply_text("❌ Could not read file. Make sure it is valid JSON.")
        return

    if not isinstance(new_items, list):
        await update.message.reply_text("❌ JSON must be a list `[...]` of items.")
        return

    await process_new_items(update, context, new_items)


# ─────────────────────────────────────────
# TEXT MESSAGE HANDLER (pasted JSON text)
# ─────────────────────────────────────────

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not is_admin(update):
        return  # silently ignore non-admin text

    text = update.message.text.strip()

    # ONLY HANDLE IF IT LOOKS LIKE JSON
    if not (text.startswith("[") or text.startswith("{")):
        return

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        await update.message.reply_text("❌ Invalid JSON. Please check the format and try again.")
        return

    # WRAP SINGLE OBJECT IN A LIST
    if isinstance(data, dict):
        data = [data]

    if not isinstance(data, list):
        await update.message.reply_text("❌ JSON must be a list `[...]` of items.")
        return

    await process_new_items(update, context, data)


# ─────────────────────────────────────────
# COMMANDS
# ─────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    text = (
        "👋 *Welcome to AffairsMCQ Bot!*\n\n"
        "I auto-post news and MCQs to your Telegram channel every 20 minutes.\n\n"

        "━━━━━━━━━━━━━━━━━━\n"
        "📥 *HOW TO ADD CONTENT*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "Send a `.json` file *or* paste JSON text directly here.\n\n"

        "━━━━━━━━━━━━━━━━━━\n"
        "🎮 *COMMANDS*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "📊 /status — Queue size, uptime, last post\n"
        "⏸ /pause — Stop auto-posting\n"
        "▶️ /resume — Resume auto-posting\n"
        "⚡ /next — Force post next item now\n"
        "⏭ /skip — Skip next item in queue\n"
        "📋 /queue — List all pending posts\n"
        "🗑 /clear — Clear entire queue (asks confirm)\n"
        "🕒 /setinterval 30 — Change posting interval\n"
        "📈 /revision — Top revised posts stats\n"
        "📊 /poll — Post next MCQ as a quiz poll\n\n"

        "━━━━━━━━━━━━━━━━━━\n"
        "⏰ *POSTING HOURS*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "Posts go out between *4:00 AM – 10:00 PM* only.\n"
        "Outside these hours the bot waits automatically.\n\n"

        "━━━━━━━━━━━━━━━━━━\n"
        "♻️ *REVISION MODE*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "When queue is empty, old posts are reposted automatically."
    )

    await update.message.reply_text(text, parse_mode="Markdown")


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):

    text = (
        "🆘 *COMMANDS*\n\n"
        "📊 /status — Queue, archive, uptime, interval\n"
        "⏸ /pause — Stop auto-posting\n"
        "▶️ /resume — Resume auto-posting\n"
        "⚡ /next — Force post next item now\n"
        "⏭ /skip — Skip next item in queue\n"
        "📋 /queue — List all pending posts\n"
        "🗑 /clear — Clear entire queue\n"
        "🕒 /setinterval 30 — Change posting interval\n"
        "📈 /revision — Top revised posts stats\n"
        "📊 /poll — Post next MCQ as quiz poll\n"
        "🆘 /help — Show this list"
    )

    await update.message.reply_text(text, parse_mode="Markdown")


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not is_admin(update):
        await deny(update)
        return

    queue   = load_json("queue.json")
    archive = load_json("archive.json")

    uptime_seconds = (datetime.now(timezone.utc) - start_time).seconds
    hours, rem     = divmod(uptime_seconds, 3600)
    minutes, _     = divmod(rem, 60)

    status_text = (
        f"📊 *BOT STATUS*\n\n"
        f"▶️ State: {'⏸ Paused' if paused else '✅ Running'}\n"
        f"📰 Queue: {len(queue)} posts\n"
        f"📦 Archive: {len(archive)} posts\n"
        f"✅ Posts sent this session: {posts_sent}\n"
        f"🕐 Last posted: {last_posted or 'None'}\n"
        f"⏱ Uptime: {hours}h {minutes}m\n"
        f"⏰ Posting hours: {POST_HOUR_START}:00 AM – {POST_HOUR_END}:00 PM\n"
        f"🕒 Interval: {POST_INTERVAL // 60} minutes\n"
        f"🟢 Within hours: {'Yes' if within_posting_hours() else 'No'}"
    )

    await update.message.reply_text(status_text, parse_mode="Markdown")


async def cmd_pause(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not is_admin(update):
        await deny(update)
        return

    global paused
    paused = True
    await update.message.reply_text("⏸ Bot paused. Posts will not be sent until resumed.")


async def cmd_resume(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not is_admin(update):
        await deny(update)
        return

    global paused
    paused = False
    await update.message.reply_text("▶️ Bot resumed. Posting will continue.")


async def cmd_next(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not is_admin(update):
        await deny(update)
        return

    queue = load_json("queue.json")

    if not queue:
        await update.message.reply_text("❌ Queue is empty, nothing to post.")
        return

    post = queue.pop(0)
    await context.bot.send_message(
        chat_id=CHANNEL_ID,
        text=format_post(post),
        parse_mode="Markdown"
    )
    save_json("queue.json", queue)

    global posts_sent, last_posted
    posts_sent  += 1
    last_posted  = post["id"]

    await update.message.reply_text(f"✅ Force posted: *{post['id']}*", parse_mode="Markdown")


async def cmd_skip(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not is_admin(update):
        await deny(update)
        return

    queue = load_json("queue.json")

    if not queue:
        await update.message.reply_text("❌ Queue is empty, nothing to skip.")
        return

    skipped = queue.pop(0)
    save_json("queue.json", queue)
    await update.message.reply_text(f"⏭ Skipped: *{skipped['id']}*", parse_mode="Markdown")


async def cmd_queue(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not is_admin(update):
        await deny(update)
        return

    queue = load_json("queue.json")

    if not queue:
        await update.message.reply_text("📭 Queue is empty.")
        return

    lines = [f"📋 *Queue ({len(queue)} items):*\n"]
    for i, item in enumerate(queue[:20], 1):
        label = item.get("question", item.get("content", ""))[:60]
        lines.append(f"{i}. [{item['type'].upper()}] {label}...")

    if len(queue) > 20:
        lines.append(f"\n...and {len(queue) - 20} more.")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_clear(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not is_admin(update):
        await deny(update)
        return

    # STORE PENDING CONFIRMATION
    context.user_data["awaiting_clear_confirm"] = True
    await update.message.reply_text(
        "⚠️ Are you sure you want to clear the entire queue?\n\nReply /confirmclear to confirm or /cancel to abort."
    )


async def cmd_confirmclear(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not is_admin(update):
        await deny(update)
        return

    if not context.user_data.get("awaiting_clear_confirm"):
        await update.message.reply_text("Nothing to confirm.")
        return

    queue = load_json("queue.json")
    count = len(queue)
    save_json("queue.json", [])
    context.user_data["awaiting_clear_confirm"] = False
    await update.message.reply_text(f"🗑 Queue cleared! {count} posts removed.")


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["awaiting_clear_confirm"] = False
    await update.message.reply_text("✅ Cancelled.")


async def cmd_setinterval(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not is_admin(update):
        await deny(update)
        return

    if not context.args:
        await update.message.reply_text("Usage: /setinterval <minutes>\nExample: /setinterval 30")
        return

    try:
        minutes = int(context.args[0])
        if minutes < 1:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Please provide a valid number of minutes (minimum 1).")
        return

    global POST_INTERVAL
    POST_INTERVAL = minutes * 60
    await update.message.reply_text(f"✅ Posting interval set to *{minutes} minutes*.", parse_mode="Markdown")


async def cmd_revision(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not is_admin(update):
        await deny(update)
        return

    archive = load_json("archive.json")

    if not archive:
        await update.message.reply_text("📭 Archive is empty.")
        return

    sorted_archive = sorted(archive, key=lambda x: x.get("revision_count", 0), reverse=True)
    top = sorted_archive[:10]

    lines = ["📈 *Top Revised Posts:*\n"]
    for i, item in enumerate(top, 1):
        label = item.get("question", item.get("content", ""))[:50]
        lines.append(f"{i}. [{item['id']}] revised {item['revision_count']}x — {label}...")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ─────────────────────────────────────────
# DAILY REPORT
# ─────────────────────────────────────────

async def send_daily_report(context: ContextTypes.DEFAULT_TYPE):

    queue   = load_json("queue.json")
    archive = load_json("archive.json")

    report = (
        f"📅 *DAILY REPORT*\n\n"
        f"✅ Posts sent today: {posts_sent}\n"
        f"📰 Queue remaining: {len(queue)}\n"
        f"📦 Archive total: {len(archive)}\n"
        f"⏰ Posting hours: {POST_HOUR_START}:00 AM – {POST_HOUR_END}:00 PM\n"
        f"🕒 Interval: {POST_INTERVAL // 60} minutes"
    )

    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=report,
        parse_mode="Markdown"
    )
    print("📅 Daily report sent to admin")


# ─────────────────────────────────────────
# AUTO POST LOOP
# ─────────────────────────────────────────

async def auto_post(app):

    global posts_sent, last_posted, POST_INTERVAL

    while True:

        try:

            # RESPECT POSTING HOURS
            if not within_posting_hours():
                print(f"🌙 Outside posting hours ({POST_HOUR_START}:00–{POST_HOUR_END}:00), sleeping 60s")
                await asyncio.sleep(60)
                continue

            # RESPECT PAUSE
            if paused:
                print("⏸ Bot is paused, sleeping 60s")
                await asyncio.sleep(60)
                continue

            queue = load_json("queue.json")
            print(f"📰 Queue size: {len(queue)}")

            if queue:

                # POST NEXT ITEM FROM QUEUE
                post = queue.pop(0)
                await app.bot.send_message(
                    chat_id=CHANNEL_ID,
                    text=format_post(post),
                    parse_mode="Markdown"
                )
                print(f"✅ Posted: {post['id']}")
                save_json("queue.json", queue)
                posts_sent  += 1
                last_posted  = post["id"]

            else:

                # REVISION MODE
                print("♻️ Queue empty, starting revision mode")
                archive = load_json("archive.json")
                print(f"📦 Archive size: {len(archive)}")

                if archive:

                    old_post = archive.pop(0)
                    old_post["revision_count"] += 1
                    archive.append(old_post)
                    save_json("archive.json", archive)

                    revision_label = "♻️ REVISION MCQ" if old_post.get("type") == "mcq" else "♻️ REVISION NEWS"

                    await app.bot.send_message(
                        chat_id=CHANNEL_ID,
                        text=format_post(old_post, label=revision_label),
                        parse_mode="Markdown"
                    )
                    print(f"♻️ Posted revision: {old_post['id']}")
                    posts_sent  += 1
                    last_posted  = old_post["id"]

                else:
                    print("⚠️ Archive is empty")

            # ALERT ADMIN IF ERROR SENDS FAIL
            await asyncio.sleep(POST_INTERVAL)

        except Exception as e:
            print(f"❌ AUTO POST ERROR: {e}")
            try:
                await app.bot.send_message(
                    chat_id=ADMIN_ID,
                    text=f"❌ *Bot Error:*\n`{e}`",
                    parse_mode="Markdown"
                )
            except Exception:
                pass
            await asyncio.sleep(30)


# ─────────────────────────────────────────
# POLL FORMAT FOR MCQ
# ─────────────────────────────────────────

async def post_as_poll(bot, item):
    options = item["options"]

    # FIND WHICH OPTION IS CORRECT (match by starting letter e.g. "D)")
    correct_index = next(
        (i for i, o in enumerate(options) if o.startswith(item["answer"][0])),
        0
    )

    # STRIP "A) " PREFIX FROM OPTIONS FOR TELEGRAM POLL
    clean_options = [o[3:].strip() if len(o) > 3 else o for o in options]

    await bot.send_poll(
        chat_id=CHANNEL_ID,
        question=item["question"][:300],
        options=clean_options,
        type="quiz",
        correct_option_id=correct_index,
        explanation=item.get("explanation", "")[:200],
        is_anonymous=True
    )


async def cmd_poll(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not is_admin(update):
        await deny(update)
        return

    queue = load_json("queue.json")

    # FIND THE NEXT MCQ IN QUEUE
    mcq_index = next(
        (i for i, item in enumerate(queue) if item.get("type") == "mcq"),
        None
    )

    if mcq_index is None:
        await update.message.reply_text("❌ No MCQ found in the queue.")
        return

    # REMOVE FROM QUEUE AND POST AS POLL
    item = queue.pop(mcq_index)
    await post_as_poll(context.bot, item)
    save_json("queue.json", queue)

    global posts_sent, last_posted
    posts_sent  += 1
    last_posted  = item["id"]

    await update.message.reply_text(
        f"✅ Posted MCQ *{item['id']}* as a quiz poll!",
        parse_mode="Markdown"
    )


# ─────────────────────────────────────────
# START BOT
# ─────────────────────────────────────────

app = ApplicationBuilder().token(BOT_TOKEN).build()

# FILE HANDLER (json file attachment)
app.add_handler(MessageHandler(filters.ATTACHMENT, handle_document))

# TEXT HANDLER (pasted json text)
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

# COMMANDS
app.add_handler(CommandHandler("start",        cmd_start))
app.add_handler(CommandHandler("help",         cmd_help))
app.add_handler(CommandHandler("status",       cmd_status))
app.add_handler(CommandHandler("pause",        cmd_pause))
app.add_handler(CommandHandler("resume",       cmd_resume))
app.add_handler(CommandHandler("next",         cmd_next))
app.add_handler(CommandHandler("skip",         cmd_skip))
app.add_handler(CommandHandler("queue",        cmd_queue))
app.add_handler(CommandHandler("clear",        cmd_clear))
app.add_handler(CommandHandler("confirmclear", cmd_confirmclear))
app.add_handler(CommandHandler("cancel",       cmd_cancel))
app.add_handler(CommandHandler("setinterval",  cmd_setinterval))
app.add_handler(CommandHandler("revision",     cmd_revision))
app.add_handler(CommandHandler("poll",         cmd_poll))

# DAILY REPORT — every day at 11 PM
app.job_queue.run_daily(
    send_daily_report,
    time=datetime.now().replace(hour=23, minute=0, second=0).time()
)

# AUTO POST LOOP
app.job_queue.run_once(
    lambda context: asyncio.create_task(auto_post(app)),
    when=1
)

print("🚀 Bot is running...")
app.run_polling()
