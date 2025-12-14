import os
import json
import logging
import datetime
import tempfile
import requests

from dotenv import load_dotenv
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters
)

import pytesseract
from PIL import Image
from yadisk import YaDisk

# =====================
# НАСТРОЙКИ
# =====================
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
YADISK_TOKEN = os.getenv("YADISK_TOKEN")
HF_API_TOKEN = os.getenv("HF_API_TOKEN")

ROOT_FOLDER = "MedBot"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

yd = YaDisk(token=YADISK_TOKEN)

# =====================
# МЕНЮ
# =====================
def main_menu():
    return ReplyKeyboardMarkup(
        [
            ["Выбрать пациента", "Добавить пациента"],
            ["Загрузить документ", "Найти документы"],
            ["Запрос к нейросети"]
        ],
        resize_keyboard=True
    )

# =====================
# HF нейросеть
# =====================
def hf_generate(prompt: str) -> str:
    url = "https://router.huggingface.co/models/google/flan-t5-small"
    headers = {
        "Authorization": f"Bearer {HF_API_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "inputs": prompt,
        "parameters": {
            "max_new_tokens": 256,
            "temperature": 0.1
        }
    }
    r = requests.post(url, headers=headers, json=payload, timeout=60)
    r.raise_for_status()
    return r.json()[0]["generated_text"]

def analyze_ocr(text: str) -> dict:
    prompt = f"""
Текст медицинского документа:

{text}

Сделай:
1. Тип исследования
2. Дата исследования (если есть)
3. 5 ключевых слов

Ответ строго в JSON.
"""
    try:
        return json.loads(hf_generate(prompt))
    except Exception as e:
        logging.error("AI OCR error: %s", e)
        return {
            "study_type": "документ",
            "date": "",
            "keywords": []
        }

# =====================
# ЯНДЕКС ДИСК
# =====================
def get_patients():
    if not yd.exists(ROOT_FOLDER):
        yd.mkdir(ROOT_FOLDER)
        return []
    return [
        item["name"]
        for item in yd.listdir(ROOT_FOLDER)
        if item["type"] == "dir"
    ]

# =====================
# OCR
# =====================
def ocr_file(path):
    try:
        img = Image.open(path)
        return pytesseract.image_to_string(img, lang="rus")
    except Exception as e:
        logging.error("OCR error: %s", e)
        return ""

# =====================
# HANDLERS
# =====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        "Привет! Выберите действие:",
        reply_markup=main_menu()
    )

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    logging.info("TEXT: %s", text)

    # --- ожидание имени пациента ---
    if context.user_data.get("await_patient_name"):
        patient = text
        path = f"{ROOT_FOLDER}/{patient}"
        if not yd.exists(path):
            yd.mkdir(path)
        context.user_data.pop("await_patient_name")
        await update.message.reply_text(
            f"Пациент «{patient}» добавлен",
            reply_markup=main_menu()
        )
        return

    # --- ожидание AI запроса ---
    if context.user_data.get("await_ai_query"):
        context.user_data.pop("await_ai_query")
        try:
            answer = hf_generate(text)
            await update.message.reply_text(answer, reply_markup=main_menu())
        except Exception:
            await update.message.reply_text("Ошибка генерации", reply_markup=main_menu())
        return

    # --- команды меню ---
    if text == "Добавить пациента":
        context.user_data["await_patient_name"] = True
        await update.message.reply_text(
            "Введите имя пациента:",
            reply_markup=ReplyKeyboardRemove()
        )
        return

    if text == "Выбрать пациента":
        patients = get_patients()
        if not patients:
            await update.message.reply_text("Пациентов нет", reply_markup=main_menu())
            return
        await update.message.reply_text(
            "Выберите пациента:",
            reply_markup=ReplyKeyboardMarkup([[p] for p in patients], resize_keyboard=True)
        )
        return

    if text in get_patients():
        context.user_data["patient"] = text
        await update.message.reply_text(
            f"Выбран пациент: {text}",
            reply_markup=main_menu()
        )
        return

    if text == "Загрузить документ":
        if not context.user_data.get("patient"):
            await update.message.reply_text(
                "Сначала выберите пациента",
                reply_markup=main_menu()
            )
            return
        context.user_data["await_document"] = True
        await update.message.reply_text(
            "Отправьте фото или PDF документа",
            reply_markup=ReplyKeyboardRemove()
        )
        return

    if text == "Найти документы":
        patient = context.user_data.get("patient")
        if not patient:
            await update.message.reply_text(
                "Сначала выберите пациента",
                reply_markup=main_menu()
            )
            return

        folder = f"{ROOT_FOLDER}/{patient}"
        files = []

        if yd.exists(folder):
            for item in yd.listdir(folder):
                if item["type"] == "file":
                    files.append(item["name"])

        if not files:
            await update.message.reply_text(
                "Документов не найдено",
                reply_markup=main_menu()
            )
            return

        msg = "\n".join(f"• {f}" for f in files)
        await update.message.reply_text(
            f"Документы пациента {patient}:\n{msg}",
            reply_markup=main_menu()
        )
        return

    if text == "Запрос к нейросети":
        context.user_data["await_ai_query"] = True
        await update.message.reply_text(
            "Введите запрос:",
            reply_markup=ReplyKeyboardRemove()
        )
        return

    await update.message.reply_text(
        "Неизвестная команда",
        reply_markup=main_menu()
    )

async def document_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("await_document"):
        return

    context.user_data.pop("await_document")

    patient = context.user_data.get("patient")
    if not patient:
        await update.message.reply_text(
            "Сначала выберите пациента",
            reply_markup=main_menu()
        )
        return

    doc = update.message.document or update.message.photo[-1]
    file = await doc.get_file()

    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        await file.download_to_drive(tmp.name)
        logging.info("File downloaded: %s", tmp.name)
        ocr_text = ocr_file(tmp.name)

    ai = analyze_ocr(ocr_text)
    study = ai.get("study_type", "документ")
    date = ai.get("date") or datetime.date.today().isoformat()
    keywords = ai.get("keywords", [])[:5]

    ext = os.path.splitext(file.file_path)[1]
    filename = f"{patient}-{study}-{date}{ext}"

    remote_folder = f"{ROOT_FOLDER}/{patient}"
    remote_path = f"{remote_folder}/{filename}"

    yd.upload(tmp.name, remote_path, overwrite=True)

    await update.message.reply_text(
        f"📄 Документ загружен\n\n"
        f"Название: {filename}\n"
        f"Ключевые слова: {', '.join(keywords)}",
        reply_markup=main_menu()
    )

# =====================
# MAIN
# =====================
if __name__ == "__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Document.ALL | filters.PHOTO, document_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    logging.info("Bot started")
    app.run_polling()