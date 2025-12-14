import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters

from ocr import ocr_image
from yandex_disk import upload_file
from hf_api import get_embedding

BOT_TOKEN = os.getenv("BOT_TOKEN")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Привет! Загружай документы или задавай вопросы.")

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    photo = update.message.photo[-1]
    file = await photo.get_file()
    image_bytes = await file.download_as_bytearray()
    
    try:
        text = ocr_image(bytes(image_bytes))
    except Exception as e:
        await update.message.reply_text(f"OCR error: {e}")
        return

    # Сохраняем файл на Яндекс.Диск
    file_name = f"/Пациент-Неизвестно-Дата.jpg"
    upload_file(image_bytes, file_name)

    await update.message.reply_text(f"Документ распознан и сохранен.\n\n{text[:4000]}")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.message.text
    await update.message.reply_text(f"Вы запросили: {query}\nОбработка через HF пока в разработке.")

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.run_polling()

if __name__ == "__main__":
    main()
