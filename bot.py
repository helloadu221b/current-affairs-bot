import json
import asyncio

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    MessageHandler,
    ContextTypes,
    filters,
)

BOT_TOKEN = "8748070088:AAG2zR3RoY6S1QIpmvBo-cV0vpA5dtIbNig"

CHANNEL_ID = "@affairsmcq"


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

        filtered_news = []

        # CHECK DUPLICATES
        for index, news in enumerate(new_news):

            duplicate = False

            # CHECK AGAINST ARCHIVE
            for old_news in archive:

                # STRICT DUPLICATE CHECK
                if news["content"] == old_news["content"]:

                    duplicate = True

                    print("⚠️ Duplicate skipped")

                    break

            # IF NOT DUPLICATE
            if not duplicate:

                news["id"] = (
                    f"NEWS_{len(archive) + len(filtered_news) + 1}"
                )

                news["revision_count"] = 0

                filtered_news.append(news)

        # CHECK IF QUEUE WAS EMPTY BEFORE ADDING
        queue_was_empty = len(queue) == 0

        # ADD TO QUEUE
        queue.extend(filtered_news)

        # ADD TO ARCHIVE
        archive.extend(filtered_news)

        # SAVE UPDATED QUEUE
        with open("queue.json", "w", encoding="utf-8") as f:
            json.dump(queue, f, ensure_ascii=False, indent=2)

        # SAVE UPDATED ARCHIVE
        with open("archive.json", "w", encoding="utf-8") as f:
            json.dump(archive, f, ensure_ascii=False, indent=2)

        # INSTANT FIRST POST
        if queue_was_empty and filtered_news:

            first_post = queue.pop(0)

            await context.bot.send_message(
                chat_id=CHANNEL_ID,
                text=first_post["content"],
                parse_mode="Markdown"
            )

            print(f"✅ Instantly posted: {first_post['id']}")

            # SAVE UPDATED QUEUE AGAIN
            with open("queue.json", "w", encoding="utf-8") as f:
                json.dump(queue, f, ensure_ascii=False, indent=2)

        await update.message.reply_text(
            f"✅ {len(filtered_news)} new posts added to queue!"
        )


# AUTO POST SYSTEM
async def auto_post(app):

    while True:

        try:

            # LOAD QUEUE
            with open("queue.json", "r", encoding="utf-8") as f:
                queue = json.load(f)

            print(f"📰 Queue size: {len(queue)}")

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

                print("♻️ Queue empty, starting revision mode")

                # LOAD ARCHIVE
                with open("archive.json", "r", encoding="utf-8") as f:
                    archive = json.load(f)

                print(f"📦 Archive size: {len(archive)}")

                # IF ARCHIVE HAS NEWS
                if archive:

                    # ROTATE ARCHIVE
                    old_post = archive.pop(0)

                    # INCREASE REVISION COUNT
                    old_post["revision_count"] += 1

                    # PUT BACK AT END
                    archive.append(old_post)

                    # SAVE UPDATED ARCHIVE
                    with open("archive.json", "w", encoding="utf-8") as f:
                        json.dump(archive, f, ensure_ascii=False, indent=2)

                    revision_text = (
                        f"♻️ *REVISION NEWS*\n\n"
                        + old_post["content"]
                    )

                    await app.bot.send_message(
                        chat_id=CHANNEL_ID,
                        text=revision_text,
                        parse_mode="Markdown"
                    )

                    print(f"♻️ Posted revision: {old_post['id']}")

                else:

                    print("⚠️ Archive empty")

                # WAIT 20 MINUTES
                await asyncio.sleep(1200)

        except Exception as e:

            print(f"❌ AUTO POST ERROR: {e}")

            # WAIT 30 SECONDS BEFORE RETRY
            await asyncio.sleep(30)


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
