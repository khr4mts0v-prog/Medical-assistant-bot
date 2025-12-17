import os
import logging
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from cloud import YaDiskClient
from ocr import ocr_file
from AIAnalise import classify_document, extract_keywords, answer_question
from utils import format_filename, parse_date_from_text

# ----------------------
# Настройки
# ----------------------
logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN")
HF_API_TOKEN = os.getenv("HF_API_TOKEN")
YADISK_TOKEN = os.getenv("YADISK_TOKEN")

ROOT_FOLDER = "MedBot"
DATA_FILE = "patients_data.json"

# Инициализация клиента Яндекс.Диска
yd = YaDiskClient(YADISK_TOKEN)

# ----------------------
# Handlers
# ----------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [["Добавить пациента", "Выбрать пациента"],
          ["Загрузить документ", "Найти документы"],
          ["Запрос к нейросети", "Очистить чат"]]
    await update.message.reply_text("Привет! Выберите действие:", reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True))

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    state = context.user_data

    # Очистка чата
    if text.lower() in ["очистить чат", "стоп", "назад", "/start", "хватит"]:
        await update.message.reply_text("Главное меню:", reply_markup=ReplyKeyboardMarkup([["Главное меню"]], resize_keyboard=True))
        state.clear()
        return

    # Обработка запроса к нейросети
    if state.get("patient"):
        response = answer_question(text, state.get("patient"), HF_API_TOKEN)
        await update.message.reply_text(f"Ответ нейросети:\n{response}")
        return

    await update.message.reply_text("Неизвестная команда. Используйте меню.")

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = context.user_data
    selected_patient = state.get("patient")
    if not selected_patient:
        await update.message.reply_text("Сначала выберите пациента!")
        return

    doc = update.message.document
    file_name = doc.file_name
    file_path = f"/tmp/{file_name}"
    await doc.get_file().download_to_drive(file_path)

    # OCR
    text = ocr_file(file_path)

    # Классификация документа и ключевые слова
    doc_type = classify_document(text)
    keywords = extract_keywords(text)

    # Формирование названия файла
    doc_date = parse_date_from_text(text)
    if not doc_date:
        from datetime import datetime
        doc_date = datetime.now().strftime("%d-%m-%Y")
    new_file_name = format_filename(selected_patient, doc_type, doc_date)

    # Загрузка на Яндекс.Диск
    remote_folder_docs = f"{ROOT_FOLDER}/{selected_patient}/docs"
    remote_folder_ocr = f"{ROOT_FOLDER}/{selected_patient}/OCR"

    yd.upload_file(file_path, f"{remote_folder_docs}/{new_file_name}")
    # Сохраняем OCR текст на диск
    ocr_txt_path = f"/tmp/{new_file_name}.txt"
    with open(ocr_txt_path, "w", encoding="utf-8") as f:
        f.write(text)
    yd.upload_file(ocr_txt_path, f"{remote_folder_ocr}/{new_file_name}.txt")

    await update.message.reply_text(f"📄 Документ загружен\nНазвание: {new_file_name}\nТип: {doc_type}\nДата: {doc_date}\nКлючевые слова: {', '.join(keywords)}")

# ----------------------
# Запуск
# ----------------------
if __name__ == "__main__":
    logging.info("🚀 Бот запускается")
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    logging.info("Start polling")
    app.run_polling()