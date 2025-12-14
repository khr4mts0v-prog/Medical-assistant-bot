import os
import logging
import pytesseract
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    CallbackQueryHandler,
    ContextTypes,
)
from dotenv import load_dotenv
import yadisk
import requests

# Загрузка переменных окружения
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
YADISK_TOKEN = os.getenv("YADISK_TOKEN")
HF_API_TOKEN = os.getenv("HF_API_TOKEN")

# Настройка логов
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)

# Настройка Tesseract
pytesseract.pytesseract.tesseract_cmd = "/usr/bin/tesseract"

# Подключение к Яндекс.Диску
yd = yadisk.YaDisk(token=YADISK_TOKEN)
ROOT_FOLDER = "/MedBot"

if not yd.exists(ROOT_FOLDER):
    yd.mkdir(ROOT_FOLDER)

# Hugging Face Router URL
HF_EMBEDDING_URL = "https://api-inference.huggingface.co/embeddings/sentence-transformers/all-MiniLM-L6-v2"
HF_TEXTGEN_URL = "https://api-inference.huggingface.co/models/gpt2"
HF_HEADERS = {"Authorization": f"Bearer {HF_API_TOKEN}"}

# Хранилище пациентов и выбранный пациент (память на время работы)
patients = {}  # {patient_name: [documents]}
selected_patient = None

# Функции Hugging Face
def get_embedding(text: str):
    payload = {"inputs": text}
    response = requests.post(HF_EMBEDDING_URL, headers=HF_HEADERS, json=payload, timeout=30)
    if response.status_code == 200:
        return response.json()
    else:
        logging.error("HF embedding error: %s", response.text)
        return []

def hf_text_gen(text: str):
    payload = {"inputs": text}
    response = requests.post(HF_TEXTGEN_URL, headers=HF_HEADERS, json=payload, timeout=30)
    if response.status_code == 200:
        return response.json()[0]["generated_text"]
    else:
        logging.error("HF text gen error: %s", response.text)
        return "Ошибка генерации"

# Обработка команд
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("Добавить пациента", callback_data="add_patient")],
        [InlineKeyboardButton("Выбрать пациента", callback_data="select_patient")],
        [InlineKeyboardButton("Загрузить документ", callback_data="upload_doc")],
        [InlineKeyboardButton("Найти документ", callback_data="search_doc")],
        [InlineKeyboardButton("Запрос к нейронке", callback_data="hf_query")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Выберите действие:", reply_markup=reply_markup)

# Обработка нажатий на кнопки
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global selected_patient
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "add_patient":
        await query.message.reply_text("Введите имя пациента:")
        context.user_data["action"] = "add_patient"

    elif data == "select_patient":
        if not patients:
            await query.message.reply_text("Пациенты отсутствуют. Сначала добавьте пациента.")
            return
        keyboard = [
            [InlineKeyboardButton(name, callback_data=f"select_{name}")] for name in patients.keys()
        ]
        await query.message.reply_text("Выберите пациента:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data.startswith("select_"):
        selected_patient = data.replace("select_", "")
        await query.message.reply_text(f"Пациент выбран: {selected_patient}")

    elif data == "upload_doc":
        if not selected_patient:
            await query.message.reply_text("Сначала выберите пациента.")
            return
        await query.message.reply_text("Отправьте документ (PDF или фото):")
        context.user_data["action"] = "upload_doc"

    elif data == "search_doc":
        if not selected_patient:
            await query.message.reply_text("Сначала выберите пациента.")
            return
        await query.message.reply_text("Введите название документа или запрос:")
        context.user_data["action"] = "search_doc"

    elif data == "hf_query":
        await query.message.reply_text("Введите запрос к нейронке:")
        context.user_data["action"] = "hf_query"

# Обработка текстовых сообщений
async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global selected_patient
    action = context.user_data.get("action")

    if action == "add_patient":
        name = update.message.text.strip()
        if name in patients:
            await update.message.reply_text("Пациент уже существует.")
        else:
            patients[name] = []
            yd.mkdir(f"{ROOT_FOLDER}/{name}")  # Создаем папку на Яндекс.Диске
            await update.message.reply_text(f"Пациент {name} добавлен.")
        context.user_data["action"] = None

    elif action == "search_doc":
        query_text = update.message.text.lower()
        docs = patients.get(selected_patient, [])
        matched = [doc for doc in docs if query_text in doc["name"].lower()]
        if not matched:
            await update.message.reply_text("Документы не найдены.")
        else:
            for doc in matched:
                await update.message.reply_text(f"Документ: {doc['name']}")
                # Отправка файла обратно из Яндекс.Диска
                local_temp = f"/tmp/{doc['name']}"
                yd.download(doc["remote_path"], local_temp)
                await update.message.reply_document(open(local_temp, "rb"))

        context.user_data["action"] = None

    elif action == "hf_query":
        query_text = update.message.text
        response_text = hf_text_gen(query_text)
        await update.message.reply_text(response_text)
        context.user_data["action"] = None

# Обработка документов (PDF, фото)
async def doc_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global selected_patient
    if not selected_patient:
        await update.message.reply_text("Сначала выберите пациента.")
        return

    file = await update.message.document.get_file() if update.message.document else await update.message.photo[-1].get_file()
    file_name = update.message.document.file_name if update.message.document else "photo.jpg"
    local_path = f"/tmp/{file_name}"
    await file.download_to_drive(local_path)

    # OCR для фото
    if not file_name.lower().endswith(".pdf"):
        text = pytesseract.image_to_string(local_path, lang="rus")
    else:
        text = "PDF document"  # PDF без обработки текста (можно расширить)

    # Формируем имя файла: пациент-тип-дата
    from datetime import datetime
    name_processed = f"{selected_patient}-{file_name}-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    remote_path = f"{ROOT_FOLDER}/{selected_patient}/{name_processed}"
    yd.upload(local_path, remote_path, overwrite=True)

    # Сохраняем метаданные
    patients[selected_patient].append({"name": name_processed, "remote_path": remote_path, "text": text})

    await update.message.reply_text(f"Документ {name_processed} загружен и обработан.")

# Основной запуск бота
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    app.add_handler(MessageHandler(filters.Document.ALL | filters.PHOTO, doc_handler))
    app.run_polling()

if __name__ == "__main__":
    main()