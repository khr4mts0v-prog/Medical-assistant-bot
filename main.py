import os
import json
import re
import logging
import datetime
import requests
from collections import Counter
from dotenv import load_dotenv

from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

import pytesseract
from PIL import Image
from yadisk import YaDisk

# ======================
# НАСТРОЙКИ
# ======================
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
HF_API_TOKEN = os.getenv("HF_API_TOKEN")
YADISK_TOKEN = os.getenv("YADISK_TOKEN")

ROOT_FOLDER = "MedBot"
INDEX_FILE = f"{ROOT_FOLDER}/index.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

yd = YaDisk(token=YADISK_TOKEN)

# ======================
# МЕНЮ
# ======================
def main_menu():
    return ReplyKeyboardMarkup(
        [
            ["Выбрать пациента", "Загрузить документ"],
            ["Найти документы", "Запрос к нейросети"]
        ],
        resize_keyboard=True
    )

# ======================
# ВСПОМОГАТЕЛЬНОЕ
# ======================
def ensure_root():
    if not yd.exists(ROOT_FOLDER):
        yd.mkdir(ROOT_FOLDER)

def load_index():
    try:
        if yd.exists(INDEX_FILE):
            yd.download(INDEX_FILE, "/tmp/index.json")
            with open("/tmp/index.json", "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        logging.error("Ошибка загрузки index.json: %s", e)
    return {}

def save_index(data):
    with open("/tmp/index.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    yd.upload("/tmp/index.json", INDEX_FILE, overwrite=True)

def get_patients():
    ensure_root()
    return [p["name"] for p in yd.listdir(ROOT_FOLDER) if p["type"] == "dir"]

def ocr_image(path):
    try:
        return pytesseract.image_to_string(Image.open(path), lang="rus")
    except Exception as e:
        logging.error("OCR ошибка: %s", e)
        return ""

def detect_doc_type(text):
    t = text.lower()
    if "экг" in t:
        return "ЭКГ"
    if "ээг" in t:
        return "ЭЭГ"
    if "анализ" in t or "кров" in t:
        return "Анализы"
    if "заключение" in t:
        return "Заключение"
    return "Документ"

def extract_date(text):
    patterns = [
        r"\b(\d{2}[.\-]\d{2}[.\-]\d{4})\b",
        r"\b(\d{4})\b"
    ]
    for p in patterns:
        m = re.search(p, text)
        if m:
            try:
                d = m.group(1).replace(".", "-")
                return d
            except:
                pass
    return datetime.datetime.now().strftime("%Y-%m-%d")

def extract_keywords(text, limit=5):
    words = re.findall(r"[А-Яа-яA-Za-z]{5,}", text.lower())
    stop = {"пациент", "исследование", "данные", "результаты"}
    words = [w for w in words if w not in stop]
    return [w for w, _ in Counter(words).most_common(limit)]

def ai_keywords(text):
    url = "https://router.huggingface.co/models/google/flan-t5-small"
    headers = {"Authorization": f"Bearer {HF_API_TOKEN}"}
    prompt = f"Выдели ключевые медицинские термины:\n{text[:1000]}"
    try:
        r = requests.post(url, headers=headers, json={"inputs": prompt}, timeout=30)
        r.raise_for_status()
        out = r.json()[0]["generated_text"]
        return extract_keywords(out)
    except Exception as e:
        logging.warning("AI keywords fallback: %s", e)
        return []

# ======================
# HANDLERS
# ======================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ensure_root()
    await update.message.reply_text(
        "Привет. Выберите действие:",
        reply_markup=main_menu()
    )

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text

    if text == "Выбрать пациента":
        patients = get_patients()
        if not patients:
            await update.message.reply_text("Пациентов нет. Создайте папку на диске.")
            return
        await update.message.reply_text(
            "Выберите пациента:",
            reply_markup=ReplyKeyboardMarkup([[p] for p in patients], resize_keyboard=True)
        )
        context.user_data["mode"] = "select_patient"
        return

    if context.user_data.get("mode") == "select_patient":
        context.user_data["patient"] = text
        context.user_data["mode"] = None
        await update.message.reply_text(
            f"Пациент выбран: {text}",
            reply_markup=main_menu()
        )
        return

    if text == "Загрузить документ":
        await update.message.reply_text("Отправьте файл или фото документа.")
        return

    if text == "Найти документы":
        index = load_index()
        patient = context.user_data.get("patient")
        docs = index.get(patient, [])
        if not docs:
            await update.message.reply_text("Документов нет.")
            return
        msg = "\n".join(d["filename"] for d in docs)
        await update.message.reply_text(msg)
        return

    if text == "Запрос к нейросети":
        context.user_data["mode"] = "ai"
        await update.message.reply_text("Введите запрос.")
        return

    if context.user_data.get("mode") == "ai":
        context.user_data["mode"] = None
        await update.message.reply_text("AI-запрос пока отключён.")
        return

    await update.message.reply_text("Неизвестная команда.", reply_markup=main_menu())

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    patient = context.user_data.get("patient")
    if not patient:
        await update.message.reply_text("Сначала выберите пациента.")
        return

    doc = update.message.document or update.message.photo[-1]
    file = await doc.get_file()
    local_path = f"/tmp/upload"
    await file.download_to_drive(local_path)

    ocr_text = ocr_image(local_path)
    doc_type = detect_doc_type(ocr_text)
    date = extract_date(ocr_text)

    ext = ".jpg"
    filename = f"{patient}_{doc_type}_{date}{ext}"

    remote_dir = f"{ROOT_FOLDER}/{patient}"
    if not yd.exists(remote_dir):
        yd.mkdir(remote_dir)

    remote_path = f"{remote_dir}/{filename}"
    yd.upload(local_path, remote_path, overwrite=True)

    keywords = ai_keywords(ocr_text)
    if not keywords:
        keywords = extract_keywords(ocr_text)

    index = load_index()
    index.setdefault(patient, []).append({
        "filename": filename,
        "path": remote_path,
        "keywords": keywords,
        "date": date,
        "type": doc_type
    })
    save_index(index)

    await update.message.reply_text(
        f"📄 Документ загружен\n\n"
        f"Название: {filename}\n"
        f"Тип: {doc_type}\n"
        f"Дата: {date}\n"
        f"Ключевые слова: {', '.join(keywords) if keywords else 'нет'}",
        reply_markup=main_menu()
    )

# ======================
# ЗАПУСК
# ======================
if __name__ == "__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Document.ALL | filters.PHOTO, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.run_polling()