import os
import logging
import json
import datetime
import requests
from dotenv import load_dotenv
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
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
DATA_FILE = "patients_data.json"  # локальный JSON для OCR и эмбеддингов

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

def hf_text_gen(text: str):
    """Запрос к HF для генерации текста"""
    url = "https://router.huggingface.co/models/gpt2"
    headers = {"Authorization": f"Bearer {HF_API_TOKEN}"}
    payload = {"inputs": text}
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=30)
        resp.raise_for_status()
        result = resp.json()
        return result[0]["generated_text"] if result else "Ошибка генерации"
    except Exception as e:
        logging.error("HF text gen error: %s", e)
        return "Ошибка генерации"

def ocr_file(file_path):
    try:
        return pytesseract.image_to_string(file_path, lang="rus")
    except Exception as e:
        logging.error("OCR error: %s", e)
        return ""

def list_patients_from_disk():
    """Получаем список пациентов с Яндекс.Диска"""
    if not yd.exists(ROOT_FOLDER):
        yd.mkdir(ROOT_FOLDER)
        return []
    children = yd.listdir(ROOT_FOLDER)
    return [c['name'] for c in children]

# ----------------------
# Handlers
# ----------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Загружаем список пациентов из Яндекс.Диска
    context.user_data['patients'] = list_patients_from_disk()
    kb = [["Добавить пациента", "Выбрать пациента"], ["Загрузить документ", "Найти документы"], ["Запрос к нейросети"]]
    await update.message.reply_text("Привет! Выберите действие:", reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True))

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    data = load_data()

    # Запрос к нейросети
    if text.startswith("Найти") or text.startswith("Что"):
        response = hf_text_gen(text)
        await update.message.reply_text(f"Ответ нейросети:\n{response}")
        return

    # Выбор пациента
    if text == "Выбрать пациента":
        patients = context.user_data.get('patients', [])
        if not patients:
            await update.message.reply_text("Пациентов пока нет.")
            return
        kb = [[p] for p in patients]
        await update.message.reply_text("Выберите пациента:", reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True))
        return

    if text in context.user_data.get('patients', []):
        context.user_data['patient'] = text
        await update.message.reply_text(f"Пациент {text} выбран.", reply_markup=ReplyKeyboardRemove())
        return

    # Добавление нового пациента
    if text == "Добавить пациента":
        await update.message.reply_text("Напишите имя нового пациента:")
        context.user_data['adding_patient'] = True
        return

    if context.user_data.get('adding_patient'):
        patient_name = text
        context.user_data['patients'].append(patient_name)
        context.user_data['patient'] = patient_name
        context.user_data['adding_patient'] = False
        remote_folder = f"{ROOT_FOLDER}/{patient_name}"
        if not yd.exists(remote_folder):
            yd.mkdir(remote_folder)
        await update.message.reply_text(f"Пациент {patient_name} добавлен и выбран.", reply_markup=ReplyKeyboardRemove())
        return

    # Загрузка документа
    if text == "Загрузить документ":
        selected_patient = context.user_data.get("patient")
        if not selected_patient:
            await update.message.reply_text("Сначала выберите пациента!")
            return
        await update.message.reply_text(f"Отправьте документ для пациента {selected_patient}.")
        return

    await update.message.reply_text("Неизвестная команда. Используйте меню.")

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    selected_patient = context.user_data.get("patient")
    if not selected_patient:
        await update.message.reply_text("Сначала выберите пациента!")
        return

    doc = update.message.document
    file_name = doc.file_name
    new_name = f"{selected_patient}-{file_name}-{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}"
    file_path = f"/tmp/{new_name}"
    await doc.get_file().download_to_drive(file_path)

    # OCR
    text = ocr_file(file_path)

    # Эмбеддинг
    embedding = get_embedding(text)

    # Ключевые слова
    tags = [selected_patient] + text.split()[:5]

    # Загружаем на Яндекс.Диск
    remote_folder = f"{ROOT_FOLDER}/{selected_patient}"
    if not yd.exists(remote_folder):
        yd.mkdir(remote_folder)
    remote_path = f"{remote_folder}/{new_name}"
    yd.upload(file_path, remote_path)

    # Сохраняем JSON
    patient_docs = data.get(selected_patient, [])
    patient_docs.append({
        "file_name": new_name,
        "remote_path": remote_path,
        "text": text,
        "embedding": embedding,
        "tags": tags
    })
    data[selected_patient] = patient_docs
    save_data(data)

    await update.message.reply_text(f"Документ {new_name} загружен и обработан.\nКлючевые слова: {', '.join(tags)}")

# ----------------------
# Основной запуск
# ----------------------
if __name__ == "__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.run_polling()