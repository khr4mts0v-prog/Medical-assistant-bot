import os
import datetime
import tempfile
import json
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes
)
import pytesseract
import yadisk
import requests

# -------------------------
# 1. Токены из .env
# -------------------------
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
HF_API_TOKEN = os.getenv("HF_API_TOKEN")
YADISK_TOKEN = os.getenv("YADISK_TOKEN")

if not all([BOT_TOKEN, HF_API_TOKEN, YADISK_TOKEN]):
    raise ValueError("Не все токены заполнены в .env")

# -------------------------
# 2. Инициализация клиентов
# -------------------------
yd = yadisk.YaDisk(token=YADISK_TOKEN)
if not yd.check_token():
    raise ValueError("Ошибка аутентификации Яндекс.Диска")

os.makedirs("uploads", exist_ok=True)

# -------------------------
# 3. База эмбеддингов и пациенты
# -------------------------
DB_FILE = "db.json"
if os.path.exists(DB_FILE):
    with open(DB_FILE, "r", encoding="utf-8") as f:
        db = json.load(f)
else:
    db = {"patients": {}}  # структура: {"patients": {"Имя": {"docs": {filename: {...}}}}}

# -------------------------
# 4. Меню
# -------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("Добавить пациента", callback_data="add_patient")],
        [InlineKeyboardButton("Выбрать пациента", callback_data="select_patient")],
        [InlineKeyboardButton("Добавить документ", callback_data="add_doc")],
        [InlineKeyboardButton("Список документов", callback_data="list_docs")],
        [InlineKeyboardButton("Запрос к нейронке", callback_data="query_nn")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    if update.message:
        await update.message.reply_text("Выберите действие:", reply_markup=reply_markup)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message:
        await update.message.reply_text("Используйте меню или отправляйте текстовые команды.")

# -------------------------
# 5. Обработка кнопок
# -------------------------
current_patient = {}  # chat_id -> selected patient

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
        chat_id = str(query.message.chat_id)

        if query.data == "add_patient":
            await query.message.reply_text("Введите имя нового пациента:")
            context.user_data["expect_patient_name"] = True

        elif query.data == "select_patient":
            if not db["patients"]:
                await query.message.reply_text("Пациенты пока не добавлены.")
                return
            keyboard = [
                [InlineKeyboardButton(name, callback_data=f"sel_patient:{name}")]
                for name in db["patients"].keys()
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.message.reply_text("Выберите пациента:", reply_markup=reply_markup)

        elif query.data.startswith("sel_patient:"):
            name = query.data.split(":", 1)[1]
            current_patient[chat_id] = name
            await query.message.reply_text(f"Выбран пациент: {name}")

        elif query.data == "add_doc":
            if chat_id not in current_patient:
                await query.message.reply_text("Сначала выберите пациента!")
            else:
                await query.message.reply_text("Отправьте документ или фото.")

        elif query.data == "list_docs":
            if chat_id not in current_patient:
                await query.message.reply_text("Сначала выберите пациента!")
            else:
                patient = current_patient[chat_id]
                docs = db["patients"].get(patient, {}).get("docs", {})
                if not docs:
                    await query.message.reply_text("Документы отсутствуют.")
                    return
                msg_text = "\n".join(docs.keys())
                keyboard = [
                    [InlineKeyboardButton(name, callback_data=f"get_doc:{name}")]
                    for name in docs.keys()
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await query.message.reply_text("Документы пациента:", reply_markup=reply_markup)

        elif query.data.startswith("get_doc:"):
            fname = query.data.split(":", 1)[1]
            patient = current_patient.get(chat_id)
            if not patient:
                await query.message.reply_text("Пациент не выбран!")
                return
            remote_path = db["patients"][patient]["docs"][fname]["yadisk_path"]
            with tempfile.NamedTemporaryFile() as tmp_file:
                yd.download(remote_path, tmp_file.name)
                tmp_file.flush()
                await query.message.reply_document(open(tmp_file.name, "rb"), filename=fname)

# -------------------------
# 6. OCR и генерация имени файла
# -------------------------
def ocr_document(file_path: str) -> str:
    try:
        text = pytesseract.image_to_string(file_path, lang="rus")
        return text
    except Exception as e:
        print(f"OCR error: {e}")
        return ""

def generate_filename(patient: str, study: str, date_str: str, ext: str):
    return f"{patient}-{study}-{date_str}.{ext}"

# -------------------------
# 7. Получение эмбеддинга через HF
# -------------------------
def get_embedding(text: str):
    url = "https://api-inference.huggingface.co/models/sentence-transformers/all-MiniLM-L6-v2"
    headers = {"Authorization": f"Bearer {HF_API_TOKEN}"}
    payload = {"inputs": text}
    response = requests.post(url, headers=headers, json=payload, timeout=30)
    if response.status_code == 200:
        return response.json()
    else:
        print("HF API error:", response.text)
        return []

# -------------------------
# 8. Загрузка на Яндекс.Диск
# -------------------------
def upload_to_yadisk(local_path: str, remote_folder="/MedicalDocs/"):
    filename = os.path.basename(local_path)
    remote_path = os.path.join(remote_folder, filename)
    if not yd.exists(remote_folder):
        yd.mkdir(remote_folder)
    yd.upload(local_path, remote_path, overwrite=True)
    return remote_path

# -------------------------
# 9. Обработка документов/фото
# -------------------------
async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg:
        return

    chat_id = str(msg.chat_id)
    if chat_id not in current_patient:
        await msg.reply_text("Сначала выберите пациента!")
        return
    patient = current_patient[chat_id]

    if msg.document:
        file = msg.document
        ext = file.file_name.split(".")[-1]
    elif msg.photo:
        file = msg.photo[-1]
        ext = "jpg"
    else:
        await msg.reply_text("Это не документ или фото.")
        return

    file_obj = await file.get_file()
    date_str = datetime.datetime.now().strftime("%Y%m%d")
    filename = generate_filename(patient, "Исследование", date_str, ext)
    local_path = os.path.join("uploads", filename)
    await file_obj.download_to_drive(local_path)

    # OCR
    text = ocr_document(local_path)
    txt_path = local_path + ".txt"
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(text)

    # Эмбеддинг
    emb = get_embedding(text)

    # Загрузка в облако
    remote_file = upload_to_yadisk(local_path)
    remote_txt = upload_to_yadisk(txt_path)

    # Сохраняем в базу
    if patient not in db["patients"]:
        db["patients"][patient] = {"docs": {}}
    db["patients"][patient]["docs"][filename] = {
        "text": text,
        "embedding": emb,
        "yadisk_path": remote_file,
        "yadisk_txt_path": remote_txt
    }

    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)

    await msg.reply_text(
        f"Документ и текст успешно загружены:\n{remote_file}\n{remote_txt}"
    )

# -------------------------
# 10. Обработка текста (нейронка или команды)
# -------------------------
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.text:
        return
    chat_id = str(msg.chat_id)
    text = msg.text.lower()

    # Если ожидаем имя пациента
    if context.user_data.get("expect_patient_name"):
        context.user_data["expect_patient_name"] = False
        patient_name = msg.text.strip()
        if patient_name in db["patients"]:
            await msg.reply_text("Пациент уже существует!")
        else:
            db["patients"][patient_name] = {"docs": {}}
            with open(DB_FILE, "w", encoding="utf-8") as f:
                json.dump(db, f, ensure_ascii=False, indent=2)
            await msg.reply_text(f"Пациент {patient_name} добавлен.")
        return

    # Поиск документов по пациенту
    patient = current_patient.get(chat_id)
    if not patient:
        await msg.reply_text("Сначала выберите пациента!")
        return

    # Ищем совпадения
    results = []
    for fname, data in db["patients"][patient]["docs"].items():
        if text in data["text"].lower():
            results.append(fname)

    if not results:
        await msg.reply_text("Документы не найдены.")
        return

    for fname in results:
        remote_path = db["patients"][patient]["docs"][fname]["yadisk_path"]
        with tempfile.NamedTemporaryFile() as tmp_file:
            yd.download(remote_path, tmp_file.name)
            tmp_file.flush()
            await msg.reply_document(open(tmp_file.name, "rb"), filename=fname)

# -------------------------
# 11. Регистрация обработчиков
# -------------------------
def register_handlers(app):
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.Document.ALL | filters.PHOTO, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

# -------------------------
# 12. Запуск бота
# -------------------------
if __name__ == "__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    register_handlers(app)
    print("Бот стартует...")
    app.run_polling()