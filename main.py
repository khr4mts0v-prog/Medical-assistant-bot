import os
import logging
import json
import datetime
import re
import requests

from dotenv import load_dotenv
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

import pytesseract
from yadisk import YaDisk

# ======================
# НАСТРОЙКИ
# ======================
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
HF_API_TOKEN = os.getenv("HF_API_TOKEN")
YADISK_TOKEN = os.getenv("YADISK_TOKEN")

ROOT_FOLDER = "MedBot"
LOCAL_TMP = "/tmp"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

yd = YaDisk(token=YADISK_TOKEN)

DOC_TYPES = [
    "УЗИ",
    "ЭКГ",
    "ЭЭГ",
    "Рентген",
    "КТ",
    "МРТ",
    "Анализы",
    "Общий анализ крови",
    "Биохимия крови",
    "Гормоны",
    "Моча",
    "Копрограмма",
    "Заключение врача",
    "Выписка",
    "Справка",
    "Протокол исследования",
    "Осмотр специалиста",
    "Назначения",
    "Эпикриз",
    "Другое",
]

# ======================
# ВСПОМОГАТЕЛЬНОЕ
# ======================
def ensure_root():
    if not yd.exists(ROOT_FOLDER):
        yd.mkdir(ROOT_FOLDER)

def get_patients():
    ensure_root()
    return [
        item["name"]
        for item in yd.listdir(ROOT_FOLDER)
        if item["type"] == "dir"
    ]

def extract_date(text: str):
    m = re.search(r"(\d{2}[.\-]\d{2}[.\-]\d{4})", text)
    if m:
        return m.group(1).replace(".", "-")
    return datetime.datetime.now().strftime("%d-%m-%Y")

# ======================
# AI ФУНКЦИИ
# ======================
def ai_detect_doc_type(text: str) -> str:
    url = "https://router.huggingface.co/models/google/flan-t5-base"
    headers = {"Authorization": f"Bearer {HF_API_TOKEN}"}

    prompt = (
        "Определи тип медицинского документа.\n"
        "Ответ строго одним вариантом из списка:\n"
        + ", ".join(DOC_TYPES)
        + "\n\nТекст:\n"
        + text[:1500]
        + "\n\nОтвет:"
    )

    try:
        r = requests.post(
            url,
            headers=headers,
            json={"inputs": prompt},
            timeout=40
        )
        r.raise_for_status()
        out = r.json()[0]["generated_text"].strip()

        for t in DOC_TYPES:
            if t.lower() in out.lower():
                return t

        return "Другое"

    except Exception as e:
        logging.error("AI type error: %s", e)
        return "Документ"

def ai_extract_keywords(text: str):
    url = "https://router.huggingface.co/models/google/flan-t5-base"
    headers = {"Authorization": f"Bearer {HF_API_TOKEN}"}

    prompt = (
        "Выдели 5–7 ключевых медицинских терминов.\n"
        "Только существительные, через запятую.\n\n"
        + text[:1500]
    )

    try:
        r = requests.post(
            url,
            headers=headers,
            json={"inputs": prompt},
            timeout=40
        )
        r.raise_for_status()
        raw = r.json()[0]["generated_text"]
        return [w.strip().lower() for w in raw.split(",") if len(w.strip()) > 2][:7]

    except Exception as e:
        logging.error("AI keywords error: %s", e)
        return []

# ======================
# OCR
# ======================
def ocr_image(path):
    try:
        return pytesseract.image_to_string(path, lang="rus")
    except Exception as e:
        logging.error("OCR error: %s", e)
        return ""

# ======================
# TELEGRAM HANDLERS
# ======================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [
        ["Выбрать пациента", "Добавить пациента"],
        ["Загрузить документ", "Найти документы"],
        ["Запрос к нейросети"],
    ]
    await update.message.reply_text(
        "Выберите действие:",
        reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True)
    )

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    if text == "Добавить пациента":
        context.user_data["await_patient_name"] = True
        await update.message.reply_text("Введите имя пациента:")
        return

    if context.user_data.get("await_patient_name"):
        name = text
        ensure_root()
        yd.mkdir(f"{ROOT_FOLDER}/{name}")
        context.user_data["await_patient_name"] = False
        await update.message.reply_text(f"Пациент «{name}» добавлен.")
        await start(update, context)
        return

    if text == "Выбрать пациента":
        patients = get_patients()
        if not patients:
            await update.message.reply_text("Пациентов пока нет.")
            return
        await update.message.reply_text(
            "Выберите пациента:",
            reply_markup=ReplyKeyboardMarkup(
                [[p] for p in patients],
                resize_keyboard=True
            )
        )
        context.user_data["await_select_patient"] = True
        return

    if context.user_data.get("await_select_patient"):
        context.user_data["patient"] = text
        context.user_data["await_select_patient"] = False
        await update.message.reply_text(f"Выбран пациент: {text}")
        await start(update, context)
        return

    if text == "Запрос к нейросети":
        context.user_data["await_ai_query"] = True
        await update.message.reply_text("Введите запрос:")
        return

    if context.user_data.get("await_ai_query"):
        context.user_data["await_ai_query"] = False
        answer = ai_detect_doc_type(text)
        await update.message.reply_text(f"Ответ:\n{answer}")
        await start(update, context)
        return

    await update.message.reply_text("Неизвестная команда.")

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    patient = context.user_data.get("patient")
    if not patient:
        await update.message.reply_text("Сначала выберите пациента.")
        return

    doc = update.message.document or update.message.photo[-1]
    file = await doc.get_file()
    local_path = f"{LOCAL_TMP}/{file.file_id}.jpg"
    await file.download_to_drive(local_path)

    logging.info("Файл скачан: %s", local_path)

    text = ocr_image(local_path)
    doc_type = ai_detect_doc_type(text)
    keywords = ai_extract_keywords(text)
    date = extract_date(text)

    filename = f"{patient}_{doc_type}_{date}.jpg"
    remote_dir = f"{ROOT_FOLDER}/{patient}"
    remote_path = f"{remote_dir}/{filename}"

    if not yd.exists(remote_dir):
        yd.mkdir(remote_dir)

    yd.upload(local_path, remote_path, overwrite=True)

    await update.message.reply_text(
        f"📄 Документ загружен\n\n"
        f"Название: {filename}\n"
        f"Тип: {doc_type}\n"
        f"Дата: {date}\n"
        f"Ключевые слова: {', '.join(keywords) if keywords else 'нет'}"
    )

    await start(update, context)

# ======================
# MAIN
# ======================
if __name__ == "__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Document.ALL | filters.PHOTO, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    logging.info("Bot started")
    app.run_polling()