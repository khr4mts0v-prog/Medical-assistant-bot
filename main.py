import os
import logging
import datetime
from dotenv import load_dotenv
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

from cloud import YaDiskClient
from ocr import ocr_file
from AIAnalise import classify_document, extract_keywords, answer_question
from utils import format_filename, parse_date_from_text

# ----------------------
# Настройки
# ----------------------
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
YADISK_TOKEN = os.getenv("YADISK_TOKEN")
HF_API_TOKEN = os.getenv("HF_API_TOKEN")

ROOT_FOLDER = "MedBot"

logging.basicConfig(level=logging.INFO)

# ----------------------
# Инициализация
# ----------------------
yd = YaDiskClient(YADISK_TOKEN)

# ----------------------
# Меню
# ----------------------
MAIN_MENU = [
    ["Выбрать пациента", "Добавить пациента"],
    ["Загрузить документ", "Найти документы"],
    ["Запрос к нейросети", "Очистить чат"]
]

# ----------------------
# Состояние пользователя
# ----------------------
user_states = {}  # user_id: {"patient": str, "awaiting": str, "last_search": list}

# ----------------------
# Хелперы
# ----------------------
def get_user_state(user_id):
    if user_id not in user_states:
        user_states[user_id] = {"patient": None, "awaiting": None, "last_search": []}
    return user_states[user_id]

# ----------------------
# Handlers
# ----------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Привет! Выберите действие:", reply_markup=ReplyKeyboardMarkup(MAIN_MENU, resize_keyboard=True))

# Добавить пациента
async def add_patient(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = get_user_state(update.effective_user.id)
    state["awaiting"] = "new_patient"
    await update.message.reply_text("Введите имя нового пациента:")

async def select_patient(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Получаем список пациентов с диска
    patients = yd.list_folders(ROOT_FOLDER)
    if not patients:
        await update.message.reply_text("Пока нет пациентов. Добавьте нового.")
        return
    state = get_user_state(update.effective_user.id)
    state["awaiting"] = "select_patient"
    keyboard = [[p] for p in patients]
    await update.message.reply_text("Выберите пациента:", reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    state = get_user_state(user_id)

    if state["awaiting"] == "new_patient":
        patient_name = text
        yd.create_patient_folder(ROOT_FOLDER, patient_name)
        state["patient"] = patient_name
        state["awaiting"] = None
        await update.message.reply_text(f"Пациент {patient_name} добавлен.", reply_markup=ReplyKeyboardMarkup(MAIN_MENU, resize_keyboard=True))
        return

    if state["awaiting"] == "select_patient":
        if yd.folder_exists(ROOT_FOLDER, text):
            state["patient"] = text
            state["awaiting"] = None
            await update.message.reply_text(f"Выбран пациент {text}.", reply_markup=ReplyKeyboardMarkup(MAIN_MENU, resize_keyboard=True))
        else:
            await update.message.reply_text("Пациент не найден. Введите корректное имя.")
        return

    if text.lower() in ["очистить чат", "стоп", "назад", "/start"]:
        state["awaiting"] = None
        await update.message.reply_text("Чат очищен.", reply_markup=ReplyKeyboardMarkup(MAIN_MENU, resize_keyboard=True))
        return

    # Поиск документов
    if state["awaiting"] == "search_doc":
        patient = state["patient"]
        if not patient:
            await update.message.reply_text("Сначала выберите пациента.")
            return
        query = text.lower()
        docs = yd.list_files(f"{ROOT_FOLDER}/{patient}/docs")
        if query in ["все", "список", "весь список"]:
            msg = "\n".join([f"{i+1}. {d}" for i,d in enumerate(docs)])
            state["last_search"] = docs
            await update.message.reply_text(f"Список документов:\n{msg}")
        elif query.isdigit():
            idx = int(query)-1
            if idx >=0 and idx < len(state["last_search"]):
                file_path = state["last_search"][idx]
                file_local = yd.download_file(file_path)
                await update.message.reply_document(open(file_local,"rb"))
            else:
                await update.message.reply_text("Неверный номер документа.")
        else:
            # Текстовый поиск по ключевым словам
            matching_docs = yd.search_documents(patient, query)
            state["last_search"] = matching_docs
            if matching_docs:
                msg = "\n".join([f"{i+1}. {d}" for i,d in enumerate(matching_docs)])
                await update.message.reply_text(f"Найдены документы:\n{msg}")
            else:
                await update.message.reply_text("Документы не найдены.")
        return

    # Запрос к нейросети
    response = answer_question(text, state.get("patient"))
    await update.message.reply_text(response)

async def find_documents(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = get_user_state(update.effective_user.id)
    if not state["patient"]:
        await update.message.reply_text("Сначала выберите пациента.")
        return
    state["awaiting"] = "search_doc"
    await update.message.reply_text("Введите ключевые слова для поиска документа или 'все' для списка всех документов.")

# Загрузка документа
async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = get_user_state(update.effective_user.id)
    patient = state.get("patient")
    if not patient:
        await update.message.reply_text("Сначала выберите пациента.")
        return

    doc = update.message.document
    if not doc:
        await update.message.reply_text("Пожалуйста, отправьте файл.")
        return

    # Скачиваем файл локально
    file_name = doc.file_name
    file_path = f"/tmp/{file_name}"
    await doc.get_file().download_to_drive(file_path)

    # OCR
    text = ocr_file(file_path)

    # Классификация
    doc_type = classify_document(text)
    keywords = extract_keywords(text)
    doc_date = parse_date_from_text(text) or datetime.datetime.now().strftime("%d-%m-%Y")
    new_name = format_filename(patient, doc_type, doc_date, file_name)

    # Загружаем на Яндекс.Диск
    remote_doc = f"{ROOT_FOLDER}/{patient}/docs/{new_name}"
    remote_ocr = f"{ROOT_FOLDER}/{patient}/OCR/{new_name}.txt"
    yd.upload_file(file_path, remote_doc)
    yd.upload_text(text, remote_ocr)

    await update.message.reply_text(
        f"📄 Документ загружен\n\nНазвание: {new_name}\nТип: {doc_type}\nДата: {doc_date}\nКлючевые слова: {', '.join(keywords)}"
    )

# ----------------------
# Основной запуск
# ----------------------
if __name__ == "__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(CommandHandler("add_patient", add_patient))
    app.add_handler(CommandHandler("select_patient", select_patient))
    app.add_handler(CommandHandler("find_documents", find_documents))
    app.run_polling()