import os
import logging
import json
import datetime
import requests
import asyncio
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
DATA_FILE = "patients_data.json"  # локальный JSON для текста и эмбеддингов

# Инициализация
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

def get_embedding(text: str):
    """HF Router API - эмбеддинг"""
    url = "https://api-inference.huggingface.co/models/sentence-transformers/all-MiniLM-L6-v2"
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
    """HF Router API - генерация текста"""
    url = "https://api-inference.huggingface.co/models/gpt2"
    headers = {"Authorization": f"Bearer {HF_API_TOKEN}"}
    payload = {
        "inputs": prompt,
        "parameters": {"max_new_tokens": 100},
        "options": {"wait_for_model": True}
    }
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=30)
        resp.raise_for_status()
        result = resp.json()
        if isinstance(result, list) and "generated_text" in result[0]:
            return result[0]["generated_text"]
        else:
            return "Ошибка генерации"
    except Exception as e:
        logging.error("HF text gen error: %s", e)
        return "Ошибка генерации"

def ocr_file(file_path):
    try:
        return pytesseract.image_to_string(file_path, lang="rus")
    except Exception as e:
        logging.error("OCR error: %s", e)
        return ""

async def async_to_thread(func, *args):
    return await asyncio.to_thread(func, *args)

# ----------------------
# Handlers
# ----------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [["Добавить пациента", "Выбрать пациента"], ["Загрузить документ", "Найти документы"], ["Запрос к нейросети"]]
    await update.message.reply_text("Привет! Выберите действие:", reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True))

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    data = load_data()

    # Добавление нового пациента
    if text == "Добавить пациента":
        await update.message.reply_text("Введите имя нового пациента:")
        context.user_data["add_patient"] = True
        return

    if context.user_data.get("add_patient"):
        patient_name = text
        context.user_data["add_patient"] = False
        if not yd.exists(f"{ROOT_FOLDER}/{patient_name}"):
            yd.mkdir(f"{ROOT_FOLDER}/{patient_name}")
        data[patient_name] = []
        save_data(data)
        await update.message.reply_text(f"Пациент {patient_name} добавлен.")
        return

    # Выбор пациента
    if text == "Выбрать пациента":
        if not yd.exists(ROOT_FOLDER):
            yd.mkdir(ROOT_FOLDER)
        # Получаем список папок с пациентами на Диске
        try:
            patient_list = [f["name"] for f in yd.listdir(ROOT_FOLDER) if f["type"] == "dir"]
        except Exception as e:
            logging.error("Yandex Disk list error: %s", e)
            patient_list = list(data.keys())
        kb = [[p] for p in patient_list]
        await update.message.reply_text("Выберите пациента:", reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True))
        context.user_data["choose_patient"] = True
        return

    if context.user_data.get("choose_patient"):
        selected_patient = text
        context.user_data["choose_patient"] = False
        context.user_data["patient"] = selected_patient
        await update.message.reply_text(f"Пациент {selected_patient} выбран.")
        return

    # Загрузка документа
    if text == "Загрузить документ":
        await update.message.reply_text("Отправьте документ (фото или pdf).")
        return

    # Найти документы
    if text == "Найти документы":
        selected_patient = context.user_data.get("patient")
        if not selected_patient:
            await update.message.reply_text("Сначала выберите пациента!")
            return
        patient_docs = data.get(selected_patient, [])
        if not patient_docs:
            await update.message.reply_text("Документов нет.")
            return
        response_text = "\n".join([f"{i+1}. {d['file_name']}" for i, d in enumerate(patient_docs)])
        await update.message.reply_text(f"Документы:\n{response_text}\nОтправьте номер, чтобы получить файл.")
        context.user_data["get_doc"] = True
        return

    if context.user_data.get("get_doc"):
        try:
            idx = int(text) - 1
            selected_patient = context.user_data.get("patient")
            file_info = data[selected_patient][idx]
            remote_path = file_info["remote_path"]
            local_tmp = f"/tmp/{file_info['file_name']}"
            await async_to_thread(yd.download, remote_path, local_tmp)
            await update.message.reply_document(open(local_tmp, "rb"))
        except Exception as e:
            await update.message.reply_text(f"Ошибка: {e}")
        context.user_data["get_doc"] = False
        return

    # Запрос к нейросети
    if text == "Запрос к нейросети":
        await update.message.reply_text("Введите ваш вопрос:")
        context.user_data["ask_hf"] = True
        return

    if context.user_data.get("ask_hf"):
        context.user_data["ask_hf"] = False
        response = await async_to_thread(hf_text_gen, text)
        await update.message.reply_text(f"Ответ нейросети:\n{response}")
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

    try:
        await doc.get_file().download_to_drive(file_path)
        await update.message.reply_text("Файл получен, начинаем обработку...")

        # OCR
        text = await async_to_thread(ocr_file, file_path)

        # Эмбеддинг
        embedding = await async_to_thread(get_embedding, text)

        # Ключевые слова
        tags = [selected_patient] + text.split()[:5]

        # Загружаем на Яндекс.Диск
        remote_folder = f"{ROOT_FOLDER}/{selected_patient}"
        if not yd.exists(remote_folder):
            yd.mkdir(remote_folder)
        remote_path = f"{remote_folder}/{new_name}"
        await async_to_thread(yd.upload, file_path, remote_path)

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

        await update.message.reply_text(
            f"Документ {new_name} загружен и обработан.\nКлючевые слова: {', '.join(tags)}"
        )
    except Exception as e:
        logging.error("Error handling document: %s", e)
        await update.message.reply_text(f"Ошибка при обработке документа: {e}")

# ----------------------
# Основной запуск
# ----------------------
if __name__ == "__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.run_polling()