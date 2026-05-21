import json
import asyncio
import os

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    MessageHandler,
    ContextTypes,
    filters,
)

BOT_TOKEN = os.environ["BOT_TOKEN"]
CHANNEL_ID = "@affairsmcq"


# ─────────────────────────────────────────
# FORMAT HELPERS
# ─────────────────────────────────────────

def format_news(item):
    return item["content"]


def format_mcq(item):
    options_text = "\n".join(item["options"])
    text = (
        f"❓ *QUESTION*\n\n"
        f"{item['question']}\n\n"
        f"{options_text}\n\n"
        f"✅ *Answer:* {item['answer']}\n\n"
        f"📝 {item['explanation']}"
    )
    return text


def detect_type(item):
    if "question" in item:
        return "mcq"
    return "news"


def format_post(item):
    if item.get("type") == "mcq":
        return format_mcq(item)
    return format_news(item)


def get_parse_mode(item):
    # MCQ and news both use standard Markdown
    return "Markdown"


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
# FILE UPLOAD HANDLER
# ─────────────────────────────────────────

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):

    document = update.message.document
    if not document:
        return

    # DOWNLOAD FILE
    file = await context.bot.get_file(document.file_id)
    file_name = document.file_name
    await file.download_to_drive(file_name)

    new_items = load_json(file_name)
    queue = load_json("queue.json")
    archive = load_json("archive.json")

    added = []

    for item in new_items:

        # SKIP DUPLICATES
        is_duplicate = any(
            existing.get("content") == item.get("content") and
            existing.get("question") == item.get("question")
            for existing in archive
        )

        if is_duplicate:
            print("⚠️ Duplicate skipped")
            continue

        # SET METADATA
        item["type"] = detect_type(item)
        item["id"] = f"POST_{len(archive) + len(added) + 1}"
        item["revision_count"] = 0

        added.append(item)

    queue_was_empty = len(queue) == 0

    queue.extend(added)
    archive.extend(added)

    save_json("queue.json", queue)
    save_json("archive.json", archive)

    # INSTANT FIRST POST IF QUEUE WAS EMPTY
    if queue_was_empty and added:
        first = queue.pop(0)
        await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text=format_post(first),
            parse_mode="Markdown"
        )
        print(f"✅ Instantly posted: {first['id']}")
        save_json("queue.json", queue)

    await update.message.reply_text(
        f"✅ {len(added)} new posts added to queue!"
    )


# ─────────────────────────────────────────
# AUTO POST LOOP
# ─────────────────────────────────────────

async def auto_post(app):

    while True:

        try:

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

            else:

                # REVISION MODE — REPOST FROM ARCHIVE
                print("♻️ Queue empty, starting revision mode")
                archive = load_json("archive.json")
                print(f"📦 Archive size: {len(archive)}")

                if archive:

                    old_post = archive.pop(0)
                    old_post["revision_count"] += 1
                    archive.append(old_post)
                    save_json("archive.json", archive)

                    revision_text = f"♻️ *REVISION*\n\n" + format_post(old_post)

                    await app.bot.send_message(
                        chat_id=CHANNEL_ID,
                        text=revision_text,
                        parse_mode="Markdown"
                    )
                    print(f"♻️ Posted revision: {old_post['id']}")

                else:
                    print("⚠️ Archive is empty")

            # WAIT 20 MINUTES
            await asyncio.sleep(1200)

        except Exception as e:
            print(f"❌ AUTO POST ERROR: {e}")
            await asyncio.sleep(30)


# ─────────────────────────────────────────
# START BOT
# ─────────────────────────────────────────

app = ApplicationBuilder().token(BOT_TOKEN).build()

app.add_handler(MessageHandler(filters.ATTACHMENT, handle_document))

app.job_queue.run_once(
    lambda context: asyncio.create_task(auto_post(app)),
    when=1
)

print("🚀 Bot is running...")
app.run_polling()
