import os
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes

from intent import detect_intent
from entities import extract_entities
from embeddings import get_embedding
from search import search_docs
from storage import load_all_docs

BOT_TOKEN = os.environ["BOT_TOKEN"]

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text

    intent = detect_intent(text)
    entities = extract_entities(text)

    if intent == "search":
        docs = load_all_docs()
        emb = get_embedding(text)
        found = search_docs(emb, docs)

        if not found:
            await update.message.reply_text("Ничего не найдено")
            return

        msg = "\n".join(d["title"] for d in found)
        await update.message.reply_text(msg)

    elif intent == "question":
        await update.message.reply_text("Анализ через HF будет здесь")

    else:
        await update.message.reply_text("Не понял запрос")

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.run_polling()

if __name__ == "__main__":
    main()
