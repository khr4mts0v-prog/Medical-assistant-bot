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
# ВСПОМОГАТЕЛЬНОЕ
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

def hf_generate(prompt: str) -> str:
    url = "https://router.huggingface.co/models/google/flan-t5-small"
    headers = {
        "Authorization": f"Bearer {HF_API_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "inputs": prompt,
        "parameters": {"max_new_tokens": 256, "temperature": 0.1}
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
        return {"study_type": "документ", "date": "", "keywords": []}

def get_patients():
    if not yd.exists(ROOT_FOLDER):
        yd.mkdir(ROOT_FOLDER)
        return []
    return [
        item["name"]
        for item in yd.listdir(ROOT_FOLDER)
        if item["type"] == "dir"
    ]

def load_index(patient):
    path = f"{ROOT_FOLDER}/{patient}/index.json"
    if yd.exists(path):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            yd.download(path, f.name)
            return json.load(open(f.name, encoding="utf-8"))
    return []

def save_index(patient, data):
    path = f"{ROOT_FOLDER}/{patient}/index.json"
    with tempfile.NamedTemporaryFile(delete=False, mode="w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        yd.upload(f.name, path, overwrite=True)

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

    # Добавление пациента
    if context.user_data.get("await_patient_name"):
        patient = text
        path = f"{ROOT_FOLDER}/{patient}"
        if not yd.exists(path):
            yd.mkdir(path)
            save_index(patient, [])
        context.user_data.pop("await_patient_name")
        await update.message.reply_text(
            f"Пациент «{patient}» добавлен",
            reply_markup=main_menu()
        )
        return

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

    if text == "Найти документы":
        patient = context.user_data.get("patient")
        if not patient:
            await update.message.reply_text("Сначала выберите пациента", reply_markup=main_menu())
            return
        docs = load_index(patient)
        if not docs:
            await update.message.reply_text("Документов нет", reply_markup=main_menu())
            return
        msg = "\n".join(f"• {d['file']}" for d in docs)
        await update.message.reply_text(f"Документы:\n{msg}", reply_markup=main_menu())
        return

    if text == "Запрос к нейросети":
        context.user_data["await_ai_query"] = True
        await update.message.reply_text("Введите запрос:", reply_markup=ReplyKeyboardRemove())
        return

    if context.user_data.get("await_ai_query"):
        context.user_data.pop("await_ai_query")
        try:
            answer = hf_generate(text)
            await update.message.reply_text(answer, reply_markup=main_menu())
        except Exception as e:
            await update.message.reply_text("Ошибка генерации", reply_markup=main_menu())
        return

    await update.message.reply_text("Неизвестная команда", reply_markup=main_menu())

async def document_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    patient = context.user_data.get("patient")
    if not patient:
        await update.message.reply_text("Сначала выберите пациента", reply_markup=main_menu())
        return

    doc = update.message.document or update.message.photo[-1]
    file = await doc.get_file()

    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        await file.download_to_drive(tmp.name)
        ocr_text = ocr_file(tmp.name)

    ai = analyze_ocr(ocr_text)
    study = ai.get("study_type", "документ")
    date = ai.get("date") or datetime.date.today().isoformat()
    keywords = ai.get("keywords", [])[:5]

    filename = f"{patient}-{study}-{date}{os.path.splitext(file.file_path)[1]}"
    remote_folder = f"{ROOT_FOLDER}/{patient}"
    remote_path = f"{remote_folder}/{filename}"

    yd.upload(tmp.name, remote_path, overwrite=True)

    index = load_index(patient)
    index.append({
        "file": filename,
        "study": study,
        "date": date,
        "keywords": keywords
    })
    save_index(patient, index)

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