import os
import logging
from dotenv import load_dotenv
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

from utils import format_filename, parse_date_from_text
from ocr import ocr_file
from cloud import YaDiskClient
from AIAnalise import classify_document, extract_keywords, answer_question

# ----------------------
# Настройки
# ----------------------
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
HF_API_TOKEN = os.getenv("HF_API_TOKEN")
YADISK_TOKEN = os.getenv("YADISK_TOKEN")

logging.basicConfig(level=logging.INFO)

ROOT_FOLDER = "MedBot"

yd_client = YaDiskClient(YADISK_TOKEN)

user_data = {}  # user_id -> {patient: str, state: str}

# ----------------------
# Главное меню
# ----------------------
def main_menu_kb():
    kb = [
        ["Выбрать пациента", "Добавить пациента"],
        ["Загрузить документ", "Найти документы"],
        ["Запрос к нейросети", "Очистить чат"]
    ]
    return ReplyKeyboardMarkup(kb, resize_keyboard=True)

# ----------------------
# Обработчики команд
# ----------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Привет! Выберите действие:", reply_markup=main_menu_kb())

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    uid = update.message.from_user.id
    data = user_data.get(uid, {})

    # Очистка чата
    if text.lower() in ["очистить чат"]:
        await update.message.reply_text("Чат очищен!", reply_markup=main_menu_kb())
        user_data[uid] = {}
        return

    # Выбор пациента
    if text.lower() == "выбрать пациента":
        await update.message.reply_text("Введите имя пациента:")
        data["state"] = "choosing_patient"
        user_data[uid] = data
        return

    # Добавление пациента
    if text.lower() == "добавить пациента":
        await update.message.reply_text("Введите имя нового пациента:")
        data["state"] = "adding_patient"
        user_data[uid] = data
        return

    # Найти документы
    if text.lower() == "найти документы":
        await update.message.reply_text("Введите ключевые слова или 'весь список':")
        data["state"] = "finding_docs"
        user_data[uid] = data
        return

    # Загрузить документ
    if text.lower() == "загрузить документ":
        await update.message.reply_text("Отправьте файл:")
        data["state"] = "uploading_doc"
        user_data[uid] = data
        return

    # Запрос к нейросети
    if text.lower() == "запрос к нейросети":
        await update.message.reply_text("Введите ваш вопрос:")
        data["state"] = "ai_query"
        user_data[uid] = data
        return

    # Обработка состояний
    if data.get("state") == "choosing_patient":
        data["patient"] = text
        data["state"] = None
        await update.message.reply_text(f"Пациент выбран: {text}", reply_markup=main_menu_kb())
        user_data[uid] = data
        return

    if data.get("state") == "adding_patient":
        data["patient"] = text
        data["state"] = None
        await update.message.reply_text(f"Пациент добавлен: {text}", reply_markup=main_menu_kb())
        user_data[uid] = data
        return

    if data.get("state") == "finding_docs":
        await update.message.reply_text("Поиск документов пока не реализован полностью.", reply_markup=main_menu_kb())
        data["state"] = None
        user_data[uid] = data
        return

    if data.get("state") == "ai_query":
        response = answer_question(text, data.get("patient"), HF_API_TOKEN)
        await update.message.reply_text(f"Ответ нейросети:\n{response}")
        data["state"] = None
        user_data[uid] = data
        return

    await update.message.reply_text("Неизвестная команда. Используйте меню.", reply_markup=main_menu_kb())

# ----------------------
# Обработчик документов
# ----------------------
async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id
    data = user_data.get(uid, {})
    patient = data.get("patient")
    if not patient:
        await update.message.reply_text("Сначала выберите пациента!", reply_markup=main_menu_kb())
        return

    doc = update.message.document
    file_name = doc.file_name
    local_path = f"/tmp/{file_name}"
    await doc.get_file().download_to_drive(local_path)

    # OCR
    text = ocr_file(local_path)

    # Классификация
    doc_type = classify_document(text, HF_API_TOKEN)
    keywords = extract_keywords(text)
    date_str = parse_date_from_text(text)
    extension = file_name.split(".")[-1]
    formatted_name = format_filename(patient, doc_type, date_str, extension)

    # Загружаем на диск
    remote_doc_folder = f"{ROOT_FOLDER}/{patient}/docs"
    remote_ocr_folder = f"{ROOT_FOLDER}/{patient}/OCR"
    yd_client.ensure_folder(remote_doc_folder)
    yd_client.ensure_folder(remote_ocr_folder)

    yd_client.upload_file(local_path, f"{remote_doc_folder}/{formatted_name}")
    # Сохраняем OCR как txt
    ocr_local_path = f"/tmp/{formatted_name}.txt"
    with open(ocr_local_path, "w", encoding="utf-8") as f:
        f.write(text)
    yd_client.upload_file(ocr_local_path, f"{remote_ocr_folder}/{formatted_name}.txt")

    await update.message.reply_text(
        f"📄 Документ загружен\nНазвание: {formatted_name}\nТип: {doc_type}\nДата: {date_str}\nКлючевые слова: {', '.join(keywords)}",
        reply_markup=main_menu_kb()
    )

# ----------------------
# Запуск бота
# ----------------------
if __name__ == "__main__":
    logging.info("🚀 Бот запускается")
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.run_polling()