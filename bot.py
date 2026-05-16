import json
import asyncio

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    MessageHandler,
    ContextTypes,
    filters,
)

BOT_TOKEN = "8935035246:AAG2uZfeGfuRAj6ImYZMW0says8bPy2zUs4"

CHANNEL_ID = "@newsofexams"


# RECEIVE JSON FILE
async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):

    document = update.message.document

    if document:

        file = await context.bot.get_file(document.file_id)

        file_name = document.file_name

        await file.download_to_drive(file_name)

        # LOAD NEW NEWS
        with open(file_name, "r", encoding="utf-8") as f:
            new_news = json.load(f)

        # LOAD EXISTING QUEUE
        with open("queue.json", "r", encoding="utf-8") as f:
            queue = json.load(f)

        # LOAD ARCHIVE
        with open("archive.json", "r", encoding="utf-8") as f:
            archive = json.load(f)

        # ADD UNIQUE IDs + REVISION COUNT
        for index, news in enumerate(new_news):

            news["id"] = f"NEWS_{len(archive) + index + 1}"

            news["revision_count"] = 0

        # ADD TO QUEUE
        queue.extend(new_news)

        # ADD TO ARCHIVE
        archive.extend(new_news)

        # SAVE UPDATED QUEUE
        with open("queue.json", "w", encoding="utf-8") as f:
            json.dump(queue, f, ensure_ascii=False, indent=2)

        # SAVE UPDATED ARCHIVE
        with open("archive.json", "w", encoding="utf-8") as f:
            json.dump(archive, f, ensure_ascii=False, indent=2)

        await update.message.reply_text(
            f"✅ {len(new_news)} posts added to queue!"
        )


# AUTO POST SYSTEM
async def auto_post(app):

    while True:

        # LOAD QUEUE
        with open("queue.json", "r", encoding="utf-8") as f:
            queue = json.load(f)

        # IF QUEUE HAS POSTS
        if queue:

            # TAKE FIRST POST
            post = queue.pop(0)

            # SEND TO CHANNEL
            await app.bot.send_message(
                chat_id=CHANNEL_ID,
                text=post["content"],
                parse_mode="Markdown"
            )

            print(f"✅ Posted: {post['id']}")

            # SAVE UPDATED QUEUE
            with open("queue.json", "w", encoding="utf-8") as f:
                json.dump(queue, f, ensure_ascii=False, indent=2)

            # WAIT 20 MINUTES
            await asyncio.sleep(1200)

        else:

            print("⏳ Queue empty")

            # CHECK AGAIN AFTER 20 MINUTES
            await asyncio.sleep(1200)


app = ApplicationBuilder().token(BOT_TOKEN).build()

# RECEIVE FILES
app.add_handler(
    MessageHandler(filters.ATTACHMENT, handle_document)
)

print("🚀 Bot is running...")


# START AUTO POSTER
app.job_queue.run_once(
    lambda context: asyncio.create_task(auto_post(app)),
    when=1
)

app.run_polling()
