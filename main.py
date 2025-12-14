import os
import logging
import json
import datetime
import asyncio
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
DATA_FILE = "patients_data.json"

yd = YaDisk(token=YADISK_TOKEN)
logging.basicConfig(level=logging.INFO)

# ----------------------
# Вспомогательные функции
# ----------------------
def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

async def hf_text_gen(text: str):
    def sync_call():
        url = "https://api-inference.huggingface.co/models/gpt2"
        headers = {"Authorization": f"Bearer {HF_API_TOKEN}"}
        payload = {"inputs": text}
        resp = requests.post(url, headers=headers, json=payload, timeout=30)
        resp.raise_for_status()
        result = resp.json()
        if isinstance(result, list) and "generated_text" in result[0]:
            return result[0]["generated_text"]
        return "Ошибка генерации"
    return await asyncio.to_thread(sync_call)

async def get_embedding(text: str):
    def sync_call():
        url = "https://api-inference.huggingface.co/pipeline/feature-extraction/sentence-transformers/all-MiniLM-L6-v2"
        headers = {"Authorization": f"Bearer {HF_API_TOKEN}"}
        payload = {"inputs": text}
        resp = requests.post(url, headers=headers, json=payload, timeout=30)
        resp.raise_for_status()
        return resp.json()
    return await asyncio.to_thread(sync_call)

def ocr_file(file_path):
    try:
        return pytesseract.image_to_string(file_path, lang="rus")
    except Exception as e:
        logging.error("OCR error: %s", e)
        return ""

# ----------------------
# Обработчики
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
    data = load_data()

    if text.lower() == "добавить пациента":
        await update.message.reply_text("Введите имя нового пациента:", reply_markup=ReplyKeyboardRemove())
        context.user_data["adding_patient"] = True
        return

    if context.user_data.get("adding_patient"):
        patient_name = text
        if patient_name in data:
            await update.message.reply_text("Пациент уже существует")
        else:
            data[patient_name] = []
            save_data(data)
            await update.message.reply_text(f"Пациент {patient_name} добавлен")
        context.user_data["adding_patient"] = False
        return

    if text.lower() == "выбрать пациента":
        if not data:
            await update.message.reply_text("Нет пациентов. Сначала добавьте пациента.")
            return
        kb_patients = [[name] for name in data.keys()]
        await update.message.reply_text("Выберите пациента:", reply_markup=ReplyKeyboardMarkup(kb_patients, resize_keyboard=True))
        context.user_data["choosing_patient"] = True
        return

    if context.user_data.get("choosing_patient"):
        if text in data:
            context.user_data["patient"] = text
            await update.message.reply_text(f"Выбран пациент: {text}")
        else:
            await update.message.reply_text("Пациент не найден")
        context.user_data["choosing_patient"] = False
        return

    if text.lower() == "загрузить документ":
        if not context.user_data.get("patient"):
            await update.message.reply_text("Сначала выберите пациента!")
            return
        await update.message.reply_text("Отправьте файл документа:")
        return

    if text.lower() == "найти документы":
        patient = context.user_data.get("patient")
        if not patient:
            await update.message.reply_text("Сначала выберите пациента!")
            return
        docs = data.get(patient, [])
        if not docs:
            await update.message.reply_text("Документы не найдены")
            return
        msg = "Документы пациента:\n" + "\n".join([d["file_name"] for d in docs])
        await update.message.reply_text(msg)
        return

    if text.lower() == "запрос к нейросети":
        await update.message.reply_text("Введите ваш запрос:")
        context.user_data["hf_request"] = True
        return

    if context.user_data.get("hf_request"):
        response = await hf_text_gen(text)
        await update.message.reply_text(f"Ответ нейросети:\n{response}")
        context.user_data["hf_request"] = False
        return

    await update.message.reply_text("Неизвестная команда. Используйте меню.")

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    patient = context.user_data.get("patient")
    if not patient:
        await update.message.reply_text("Сначала выберите пациента!")
        return

    doc = update.message.document
    file_name = doc.file_name
    new_name = f"{patient}-{file_name}-{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}"
    file_path = f"/tmp/{new_name}"
    await doc.get_file().download_to_drive(file_path)

    # OCR
    text = ocr_file(file_path)
    embedding = await get_embedding(text)
    tags = [patient] + text.split()[:5]

    # Яндекс.Диск
    remote_folder = f"{ROOT_FOLDER}/{patient}"
    if not yd.exists(remote_folder):
        yd.mkdir(remote_folder)
    remote_path = f"{remote_folder}/{new_name}"
    yd.upload(file_path, remote_path)

    # JSON
    patient_docs = data.get(patient, [])
    patient_docs.append({
        "file_name": new_name,
        "remote_path": remote_path,
        "text": text,
        "embedding": embedding,
        "tags": tags
    })
    data[patient] = patient_docs
    save_data(data)

    await update.message.reply_text(f"Документ {new_name} загружен и обработан.\nКлючевые слова: {', '.join(tags)}")

# ----------------------
# Запуск
# ----------------------
if __name__ == "__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.run_polling()