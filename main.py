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

# Папка на Яндекс.Диске
ROOT_FOLDER = "MedBot"

# Инициализация
yd = YaDisk(token=YADISK_TOKEN)
logging.basicConfig(level=logging.INFO)

# ----------------------
# Helper функции
# ----------------------
def sync_patients_from_yadisk():
    """Синхронизируем пациентов с Яндекс.Диска"""
    data = {}
    if not yd.exists(ROOT_FOLDER):
        yd.mkdir(ROOT_FOLDER)
    try:
        items = yd.listdir(ROOT_FOLDER)
        for item in items:
            if item["type"] == "dir":
                data[item["name"]] = []  # пустой список документов
    except Exception as e:
        logging.error("Ошибка при синхронизации пациентов с Яндекс.Диска: %s", e)
    return data

def ocr_file(file_path):
    try:
        return pytesseract.image_to_string(file_path, lang="rus")
    except Exception as e:
        logging.error("OCR error: %s", e)
        return ""

def get_embedding(text: str):
    """Получение эмбеддинга через HF Router API"""
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

def hf_text_gen(text: str):
    """Запрос к HF для генерации текста"""
    url = "https://api-inference.huggingface.co/models/gpt2"
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

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [["Добавить пациента", "Выбрать пациента"],
          ["Загрузить документ", "Найти документы"],
          ["Запрос к нейросети"]]
    await update.message.reply_text("Привет! Выберите действие:", reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True))

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    data = sync_patients_from_yadisk()
    
    if text == "Добавить пациента":
        context.user_data["action"] = "add_patient"
        await update.message.reply_text("Введите имя нового пациента:")
        return
    
    if text == "Выбрать пациента":
        if not data:
            await update.message.reply_text("Пациентов нет, добавьте сначала.")
            return
        kb = [[name] for name in data.keys()]
        await update.message.reply_text("Выберите пациента:", reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True))
        context.user_data["action"] = "select_patient"
        return
    
    if text == "Загрузить документ":
        if "patient" not in context.user_data:
            await update.message.reply_text("Сначала выберите пациента!")
            return
        await update.message.reply_text("Отправьте документ (фото или PDF) для загрузки.")
        context.user_data["action"] = "upload_document"
        return
    
    if text == "Найти документы":
        if "patient" not in context.user_data:
            await update.message.reply_text("Сначала выберите пациента!")
            return
        patient = context.user_data["patient"]
        try:
            items = yd.listdir(f"{ROOT_FOLDER}/{patient}")
            doc_list = "\n".join([f"{i['name']}" for i in items if i["type"]=="file"])
            if not doc_list:
                await update.message.reply_text("Документы отсутствуют.")
                return
            context.user_data["action"] = "send_document"
            kb = [[i['name']] for i in items if i["type"]=="file"]
            await update.message.reply_text(f"Документы пациента {patient}:\n{doc_list}\nВыберите документ для получения:", 
                                            reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True))
        except Exception as e:
            logging.error(e)
            await update.message.reply_text("Ошибка получения документов.")
        return
    
    if text == "Запрос к нейросети":
        context.user_data["action"] = "hf_query"
        await update.message.reply_text("Введите запрос для нейросети:")
        return

    # Обработка действия пользователя
    action = context.user_data.get("action")
    
    if action == "add_patient":
        patient_name = text
        folder_path = f"{ROOT_FOLDER}/{patient_name}"
        if not yd.exists(folder_path):
            yd.mkdir(folder_path)
        context.user_data["patient"] = patient_name
        await update.message.reply_text(f"Пациент {patient_name} добавлен и выбран.")
        context.user_data["action"] = None
        return
    
    if action == "select_patient":
        patient_name = text
        if patient_name not in data:
            await update.message.reply_text("Такого пациента нет.")
            return
        context.user_data["patient"] = patient_name
        await update.message.reply_text(f"Выбран пациент: {patient_name}")
        context.user_data["action"] = None
        return
    
    if action == "send_document":
        patient = context.user_data["patient"]
        doc_name = text
        file_path = f"/tmp/{doc_name}"
        remote_path = f"{ROOT_FOLDER}/{patient}/{doc_name}"
        try:
            yd.download(remote_path, file_path)
            await update.message.reply_document(open(file_path, "rb"))
        except Exception as e:
            logging.error(e)
            await update.message.reply_text("Ошибка при скачивании документа.")
        context.user_data["action"] = None
        return
    
    if action == "hf_query":
        response = hf_text_gen(text)
        await update.message.reply_text(f"Ответ нейросети:\n{response}")
        context.user_data["action"] = None
        return
    
    await update.message.reply_text("Неизвестная команда. Используйте меню.")

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    action = context.user_data.get("action")
    if action != "upload_document":
        await update.message.reply_text("Сначала выберите действие 'Загрузить документ' из меню.")
        return
    if "patient" not in context.user_data:
        await update.message.reply_text("Сначала выберите пациента!")
        return
    
    patient = context.user_data["patient"]
    doc = update.message.document
    file_name = doc.file_name
    new_name = f"{patient}-{file_name}-{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}"
    
    file_path = f"/tmp/{new_name}"
    await doc.get_file().download_to_drive(file_path)
    
    # OCR
    text = ocr_file(file_path)
    
    # Эмбеддинг
    embedding = get_embedding(text)
    
    # Ключевые слова для проверки запроса
    keywords = [patient] + text.split()[:5]
    
    # Загрузка на Яндекс.Диск
    remote_folder = f"{ROOT_FOLDER}/{patient}"
    if not yd.exists(remote_folder):
        yd.mkdir(remote_folder)
    remote_path = f"{remote_folder}/{new_name}"
    yd.upload(file_path, remote_path)
    
    await update.message.reply_text(f"Документ {new_name} загружен и обработан.\nКлючевые слова: {', '.join(keywords)}")
    context.user_data["action"] = None

# ----------------------
# Основной запуск
# ----------------------
if __name__ == "__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.run_polling()