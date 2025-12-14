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
# Настройки и загрузка .env
# ----------------------
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
HF_API_TOKEN = os.getenv("HF_API_TOKEN")
YADISK_TOKEN = os.getenv("YADISK_TOKEN")

ROOT_FOLDER = "MedBot"
DATA_FILE = "patients_data.json"

# ----------------------
# Логирование
# ----------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ----------------------
# Инициализация ЯД
# ----------------------
try:
    yd = YaDisk(token=YADISK_TOKEN)
    if not yd.check_token():
        logger.error("Ошибка токена Яндекс.Диска")
except Exception as e:
    logger.exception("Не удалось подключиться к Яндекс.Диску: %s", e)
    yd = None

# ----------------------
# Работа с локальным JSON
# ----------------------
def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# ----------------------
# OCR
# ----------------------
def ocr_file(file_path):
    try:
        text = pytesseract.image_to_string(file_path, lang="rus")
        logger.info("OCR успешно выполнен, %d символов", len(text))
        return text
    except Exception as e:
        logger.exception("OCR ошибка: %s", e)
        return ""

# ----------------------
# Hugging Face Router API
# ----------------------
def get_embedding(text: str):
    url = "https://router.huggingface.co/models/sentence-transformers/all-MiniLM-L6-v2"
    headers = {"Authorization": f"Bearer {HF_API_TOKEN}"}
    payload = {"inputs": text}
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=30)
        resp.raise_for_status()
        result = resp.json()
        logger.info("Эмбеддинг получен, размер: %d", len(result))
        return result
    except Exception as e:
        logger.exception("HF embedding ошибка: %s", e)
        return []

def hf_text_gen(text: str):
    url = "https://router.huggingface.co/models/gpt2"
    headers = {"Authorization": f"Bearer {HF_API_TOKEN}"}
    payload = {"inputs": text}
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=30)
        resp.raise_for_status()
        result = resp.json()
        output = result[0]["generated_text"] if result else "Ошибка генерации"
        logger.info("HF текст успешно сгенерирован")
        return output
    except Exception as e:
        logger.exception("HF text gen ошибка: %s", e)
        return "Ошибка генерации"

# ----------------------
# Telegram Handlers
# ----------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [
        ["Добавить пациента", "Выбрать пациента"],
        ["Загрузить документ", "Найти документы"],
        ["Запрос к нейросети"]
    ]
    await update.message.reply_text("Привет! Выберите действие:", reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True))
    logger.info("Стартовый экран отправлен")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    data = load_data()

    # Запрос к нейросети
    if text.startswith("Найти") or text.startswith("Что") or text.startswith("Пациент"):
        response = hf_text_gen(text)
        await update.message.reply_text(f"Ответ нейросети:\n{response}")
        logger.info("HF ответ: %s", response)
        return

    # Простейшая логика меню
    if text == "Добавить пациента":
        await update.message.reply_text("Введите имя нового пациента:")
        context.user_data["action"] = "add_patient"
        return
    elif text == "Выбрать пациента":
        patients = list(data.keys())
        if not patients:
            await update.message.reply_text("Пациентов пока нет. Сначала добавьте пациента.")
            return
        await update.message.reply_text(f"Доступные пациенты: {', '.join(patients)}\nВведите имя для выбора:")
        context.user_data["action"] = "select_patient"
        return
    elif text == "Загрузить документ":
        if "patient" not in context.user_data:
            await update.message.reply_text("Сначала выберите пациента!")
            return
        await update.message.reply_text("Отправьте документ или фото для загрузки:")
        context.user_data["action"] = "upload_doc"
        return
    elif text == "Найти документы":
        if "patient" not in context.user_data:
            await update.message.reply_text("Сначала выберите пациента!")
            return
        docs = data.get(context.user_data["patient"], [])
        if not docs:
            await update.message.reply_text("Документов пока нет")
        else:
            doc_list = "\n".join([d["file_name"] for d in docs])
            await update.message.reply_text(f"Документы пациента:\n{doc_list}")
        return
    elif text == "Запрос к нейросети":
        await update.message.reply_text("Введите текст запроса к нейросети:")
        context.user_data["action"] = "hf_query"
        return

    # Действия после выбора пациента
    action = context.user_data.get("action")
    if action == "add_patient":
        patient_name = text
        data[patient_name] = []
        save_data(data)
        await update.message.reply_text(f"Пациент {patient_name} добавлен!")
        logger.info("Добавлен пациент: %s", patient_name)
        context.user_data["action"] = None
    elif action == "select_patient":
        if text not in data:
            await update.message.reply_text("Пациент не найден")
            return
        context.user_data["patient"] = text
        await update.message.reply_text(f"Пациент {text} выбран!")
        context.user_data["action"] = None
    elif action == "hf_query":
        response = hf_text_gen(text)
        await update.message.reply_text(f"Ответ нейросети:\n{response}")
        context.user_data["action"] = None
    else:
        await update.message.reply_text("Неизвестная команда. Используйте меню.")

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("action") != "upload_doc":
        await update.message.reply_text("Сначала выберите пациента и нажмите 'Загрузить документ'")
        return

    data = load_data()
    selected_patient = context.user_data.get("patient")
    if not selected_patient:
        await update.message.reply_text("Сначала выберите пациента!")
        return

    doc = update.message.document
    if not doc:
        await update.message.reply_text("Файл не найден. Попробуйте ещё раз.")
        return

    file_name = doc.file_name
    timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    new_name = f"{selected_patient}-{file_name}-{timestamp}"
    local_path = f"/tmp/{new_name}"

    # Скачивание
    try:
        await doc.get_file().download_to_drive(local_path)
        logger.info("Файл %s скачан локально", new_name)
    except Exception as e:
        logger.exception("Ошибка скачивания файла: %s", e)
        await update.message.reply_text("Не удалось скачать файл")
        return

    # OCR
    text = ocr_file(local_path)

    # Эмбеддинг
    embedding = get_embedding(text)

    # Яндекс.Диск
    remote_folder = f"{ROOT_FOLDER}/{selected_patient}"
    try:
        if not yd.exists(remote_folder):
            yd.mkdir(remote_folder)
            logger.info("Создана папка на ЯД: %s", remote_folder)
        remote_path = f"{remote_folder}/{new_name}"
        yd.upload(local_path, remote_path)
        logger.info("Файл загружен на ЯД: %s", remote_path)
    except Exception as e:
        logger.exception("Ошибка загрузки на ЯД: %s", e)
        await update.message.reply_text("Не удалось загрузить файл на Яндекс.Диск")
        return

    # Сохранение данных
    patient_docs = data.get(selected_patient, [])
    tags = [selected_patient] + text.split()[:5]
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
    context.user_data["action"] = None

# ----------------------
# Основной запуск
# ----------------------
if __name__ == "__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    logger.info("Бот запущен")
    app.run_polling()