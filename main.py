import os
import logging
import json
import datetime
import requests
from dotenv import load_dotenv
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
import pytesseract
from yadisk import YaDisk

# ----------------------
# Настройки
# ----------------------
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
HF_API_TOKEN = os.getenv("HF_API_TOKEN")
YADISK_TOKEN = os.getenv("YADISK_TOKEN")

ROOT_FOLDER = "MedBot"
DATA_FILE = "patients_data.json"

# Инициализация
yd = YaDisk(token=YADISK_TOKEN)
logging.basicConfig(level=logging.INFO)

# ----------------------
# Helper функции
# ----------------------
def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def get_embedding(text: str):
    """Получение эмбеддинга через HF Router API"""
    url = "https://router.huggingface.co/models/sentence-transformers/all-MiniLM-L6-v2"
    headers = {"Authorization": f"Bearer {HF_API_TOKEN}"}
    payload = {"inputs": text}
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=30)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logging.error("HF embedding error: %s", e)
        return []

def hf_text_gen(prompt: str):
    """HF генерация текста / классификация типа документа и ключевых слов"""
    url = "https://api-inference.huggingface.co/models/google/flan-t5-base"
    headers = {"Authorization": f"Bearer {HF_API_TOKEN}"}
    payload = {"inputs": prompt}
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=60)
        resp.raise_for_status()
        result = resp.json()
        if isinstance(result, list) and len(result) > 0 and "generated_text" in result[0]:
            return result[0]["generated_text"]
        return "Ошибка генерации"
    except Exception as e:
        logging.error("HF text gen error: %s", e)
        return "Ошибка генерации"

def ocr_file(file_path):
    try:
        text = pytesseract.image_to_string(file_path, lang="rus")
        return text
    except Exception as e:
        logging.error("OCR error: %s", e)
        return ""

def extract_date(text):
    """Простейшее извлечение даты из текста OCR"""
    import re
    matches = re.findall(r"(\d{2}[./-]\d{2}[./-]\d{4})", text)
    if matches:
        return matches[0].replace("/", "-").replace(".", "-")
    return datetime.datetime.now().strftime("%d-%m-%Y")

def classify_document(text):
    """Определяем тип документа и ключевые слова"""
    prompt_type = f"Определи тип документа (ЭКГ, УЗИ, анализ крови, ЭЭГ и т.д.) на основе текста: {text[:1000]}"
    doc_type = hf_text_gen(prompt_type).strip()

    prompt_keywords = f"Выдели 5–7 ключевых слов из текста медицинского документа: {text[:1000]}"
    keywords = hf_text_gen(prompt_keywords).strip()
    return doc_type, keywords

# ----------------------
# Handlers
# ----------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [
        ["Добавить пациента", "Выбрать пациента"],
        ["Загрузить документ", "Найти документы"],
        ["Запрос к нейросети"]
    ]
    await update.message.reply_text(
        "Привет! Выберите действие:",
        reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True)
    )

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    data = load_data()

    # Если ожидаем файл
    if context.user_data.get("awaiting_file"):
        await update.message.reply_text("Ожидаю файл, а не текст.")
        return

    # Обработка кнопок
    if text == "Добавить пациента":
        await update.message.reply_text("Введите имя нового пациента:")
        context.user_data["adding_patient"] = True
        return

    if context.user_data.get("adding_patient"):
        patient_name = text
        if patient_name not in data:
            data[patient_name] = []
            save_data(data)
        context.user_data["adding_patient"] = False
        await update.message.reply_text(f"Пациент {patient_name} добавлен.")
        await start(update, context)
        return

    if text == "Выбрать пациента":
        if not data:
            await update.message.reply_text("Сначала добавьте пациента.")
            return
        kb = [[p] for p in data.keys()]
        await update.message.reply_text(
            "Выберите пациента:",
            reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True)
        )
        context.user_data["choosing_patient"] = True
        return

    if context.user_data.get("choosing_patient"):
        if text in data:
            context.user_data["patient"] = text
            context.user_data["choosing_patient"] = False
            await update.message.reply_text(f"Выбран пациент {text}")
            await start(update, context)
        else:
            await update.message.reply_text("Пациент не найден.")
        return

    if text == "Загрузить документ":
        if "patient" not in context.user_data:
            await update.message.reply_text("Сначала выберите пациента!")
            return
        context.user_data["awaiting_file"] = True
        await update.message.reply_text("Пожалуйста, отправьте файл для загрузки.")
        return

    if text == "Найти документы":
        if "patient" not in context.user_data:
            await update.message.reply_text("Сначала выберите пациента!")
            return
        patient = context.user_data["patient"]
        docs = data.get(patient, [])
        if not docs:
            await update.message.reply_text("Документов нет.")
            return
        msg = "Документы:\n"
        for d in docs:
            msg += f"- {d['file_name']}\n"
        await update.message.reply_text(msg)
        return

    if text == "Запрос к нейросети":
        await update.message.reply_text("Отправьте запрос к нейросети:")
        context.user_data["awaiting_query"] = True
        return

    if context.user_data.get("awaiting_query"):
        query = text
        response = hf_text_gen(query)
        await update.message.reply_text(f"Ответ нейросети:\n{response}")
        context.user_data["awaiting_query"] = False
        return

    await update.message.reply_text("Неизвестная команда. Используйте меню.")

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if "patient" not in context.user_data:
        await update.message.reply_text("Сначала выберите пациента!")
        return

    if not context.user_data.get("awaiting_file"):
        await update.message.reply_text("Пожалуйста, используйте кнопку 'Загрузить документ' перед отправкой файла.")
        return

    doc = update.message.document
    file_name = doc.file_name
    patient = context.user_data["patient"]

    new_name = f"{patient}_{file_name}"
    file_path = f"/tmp/{new_name}"
    await doc.get_file().download_to_drive(file_path)
    logging.info(f"Файл загружен локально: {file_path}")

    text = ocr_file(file_path)
    doc_date = extract_date(text)
    doc_type, keywords = classify_document(text)

    # Формируем новое имя файла
    new_name = f"{patient}_{doc_type}_{doc_date}{os.path.splitext(file_name)[1]}"

    # Загружаем на Яндекс.Диск
    remote_folder = f"{ROOT_FOLDER}/{patient}"
    if not yd.exists(remote_folder):
        yd.mkdir(remote_folder)
    remote_path = f"{remote_folder}/{new_name}"
    yd.upload(file_path, remote_path)
    logging.info(f"Файл загружен на Яндекс.Диск: {remote_path}")

    # Сохраняем JSON
    data = load_data()
    patient_docs = data.get(patient, [])
    patient_docs.append({
        "file_name": new_name,
        "remote_path": remote_path,
        "text": text,
        "type": doc_type,
        "date": doc_date,
        "keywords": keywords,
    })
    data[patient] = patient_docs
    save_data(data)

    context.user_data["awaiting_file"] = False

    await update.message.reply_text(
        f"📄 Документ загружен\n\nНазвание: {new_name}\nТип: {doc_type}\nДата: {doc_date}\nКлючевые слова: {keywords}"
    )
    await start(update, context)

# ----------------------
# Основной запуск
# ----------------------
if __name__ == "__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    logging.info("Бот запущен")
    app.run_polling()