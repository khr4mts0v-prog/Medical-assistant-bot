import os
import logging
import datetime
from dotenv import load_dotenv
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

from yadisk_utils import YandexDiskClient
from ocr_utils import ocr_file
from hf_utils import get_embedding, hf_text_gen

# ----------------------
# Настройки
# ----------------------
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
HF_API_TOKEN = os.getenv("HF_API_TOKEN")
YADISK_TOKEN = os.getenv("YADISK_TOKEN")
ROOT_FOLDER = "MedBot"

logging.basicConfig(level=logging.INFO)

# ----------------------
# Инициализация
# ----------------------
yd_client = YandexDiskClient(YADISK_TOKEN, ROOT_FOLDER)
patients_data = yd_client.load_json()  # Скачиваем JSON с Диска
patients_list = yd_client.list_patients()  # Список папок на Диске

# ----------------------
# Хэндлеры
# ----------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [
        ["Добавить пациента", "Выбрать пациента"],
        ["Загрузить документ", "Найти документы"],
        ["Запрос к нейросети"]
    ]
    await update.message.reply_text("Привет! Выберите действие:", reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True))

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text.startswith("Найти") or text.startswith("Что"):
        response = hf_text_gen(text)
        await update.message.reply_text(f"Ответ нейросети:\n{response}")
        return
    await update.message.reply_text("Неизвестная команда. Используйте меню.")

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    selected_patient = context.user_data.get("patient")
    if not selected_patient:
        await update.message.reply_text("Сначала выберите пациента!")
        return

    doc = update.message.document
    if not doc:
        await update.message.reply_text("Ошибка: файл не найден!")
        return

    # Формируем новое имя файла
    timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    new_name = f"{selected_patient}-{doc.file_name}-{timestamp}"

    # Скачиваем файл во временную папку
    tmp_path = f"/tmp/{new_name}"
    await doc.get_file().download_to_drive(tmp_path)
    logging.info(f"Файл {new_name} загружен во временную папку")

    # OCR
    text = ocr_file(tmp_path)
    logging.info(f"OCR для {new_name} выполнен, первые 50 символов: {text[:50]}")

    # Эмбеддинг
    embedding = get_embedding(text)

    # Теги
    tags = [selected_patient] + text.split()[:5]

    # Загружаем на Яндекс.Диск
    remote_path = yd_client.upload_file(tmp_path, selected_patient, new_name)
    logging.info(f"Файл {new_name} загружен на Яндекс.Диск: {remote_path}")

    # Обновляем JSON
    patients_data.setdefault(selected_patient, []).append({
        "file_name": new_name,
        "remote_path": remote_path,
        "text": text,
        "embedding": embedding,
        "tags": tags
    })
    yd_client.save_json(patients_data)

    await update.message.reply_text(
        f"Документ {new_name} загружен и обработан.\nКлючевые слова: {', '.join(tags)}"
    )

# ----------------------
# Основной запуск
# ----------------------
if __name__ == "__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    logging.info("Бот запущен")
    app.run_polling()