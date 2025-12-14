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

def get_patients_list():
    """Подтягиваем список пациентов с Яндекс.Диска"""
    try:
        if not yd.exists(ROOT_FOLDER):
            yd.mkdir(ROOT_FOLDER)
        items = yd.listdir(ROOT_FOLDER)
        return [item["name"] for item in items]
    except Exception as e:
        logging.error("Error fetching patients: %s", e)
        return []

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

# ----------------------
# Handlers
# ----------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [["Добавить пациента", "Выбрать пациента"],
          ["Загрузить документ", "Найти документы"],
          ["Запрос к нейросети"]]
    await update.message.reply_text(
        "Привет! Выберите действие:", 
        reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True)
    )

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    data = load_data()
    patients_list = get_patients_list()

    # --- Обработка меню ---
    if text == "Добавить пациента":
        await update.message.reply_text("Введите имя нового пациента:")
        context.user_data["action"] = "add_patient"
        return
    elif text == "Выбрать пациента":
        if not patients_list:
            await update.message.reply_text("Пациенты не найдены. Добавьте пациента.")
            return
        kb = [[p] for p in patients_list]
        await update.message.reply_text("Выберите пациента:", reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True))
        context.user_data["action"] = "select_patient"
        return
    elif text == "Загрузить документ":
        await update.message.reply_text("Отправьте документ для загрузки")
        context.user_data["action"] = "upload_doc"
        return
    elif text == "Найти документы":
        await update.message.reply_text("Введите запрос для поиска документов")
        context.user_data["action"] = "search_doc"
        return
    elif text == "Запрос к нейросети":
        await update.message.reply_text("Введите ваш запрос к нейросети")
        context.user_data["action"] = "hf_query"
        return

    # --- Действие в зависимости от контекста ---
    action = context.user_data.get("action")
    if action == "add_patient":
        # Создаем папку на Яндекс.Диске
        new_patient = text
        remote_folder = f"{ROOT_FOLDER}/{new_patient}"
        if not yd.exists(remote_folder):
            yd.mkdir(remote_folder)
        await update.message.reply_text(f"Пациент {new_patient} добавлен.")
        context.user_data.pop("action")
        return
    elif action == "select_patient":
        if text in patients_list:
            context.user_data["patient"] = text
            await update.message.reply_text(f"Выбран пациент: {text}")
        else:
            await update.message.reply_text("Пациент не найден")
        context.user_data.pop("action")
        return
    elif action == "search_doc":
        # Поиск по документам (текст + теги)
        patient = context.user_data.get("patient")
        if not patient:
            await update.message.reply_text("Сначала выберите пациента")
            context.user_data.pop("action")
            return
        patient_docs = data.get(patient, [])
        results = [d for d in patient_docs if text.lower() in d["text"].lower() or text.lower() in d["file_name"].lower()]
        if not results:
            await update.message.reply_text("Документы не найдены")
        else:
            msg = "Найденные документы:\n" + "\n".join([d["file_name"] for d in results])
            await update.message.reply_text(msg)
            # При желании: отправка файлов
            for d in results:
                file_path = f"/tmp/{d['file_name']}"
                yd.download(d["remote_path"], file_path)
                await update.message.reply_document(open(file_path, "rb"))
        context.user_data.pop("action")
        return
    elif action == "hf_query":
        response = hf_text_gen(text)
        await update.message.reply_text(f"Ответ нейросети:\n{response}")
        context.user_data.pop("action")
        return
    else:
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

    # Теги
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