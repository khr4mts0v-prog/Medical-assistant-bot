import os
import datetime
import tempfile
import json
import requests
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes
)
import pytesseract
from huggingface_hub import InferenceClient
import yadisk

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
hf_client = InferenceClient(token=HF_API_TOKEN)
yd = yadisk.YaDisk(token=YADISK_TOKEN)

if not yd.check_token():
    raise ValueError("Ошибка аутентификации Яндекс.Диска")

os.makedirs("uploads", exist_ok=True)

# -------------------------
# 3. База эмбеддингов
# -------------------------
EMBED_DB_FILE = "embeddings.json"
if os.path.exists(EMBED_DB_FILE):
    with open(EMBED_DB_FILE, "r", encoding="utf-8") as f:
        embed_db = json.load(f)
else:
    embed_db = {}

# -------------------------
# 4. Меню
# -------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("Добавить документ", callback_data="add_doc")],
        [InlineKeyboardButton("Найти документ", callback_data="find_doc")],
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
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
        if query.data == "add_doc":
            await query.message.reply_text("Отправьте документ или фото.")
        elif query.data == "find_doc":
            await query.message.reply_text("Введите название или параметры документа.")
        elif query.data == "query_nn":
            await query.message.reply_text("Введите запрос к нейронке (например: что назначил кардиолог ребенку?).")
        else:
            await query.message.reply_text("Неизвестная команда.")

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
# 7. Эмбеддинг через HF
# -------------------------
def get_embedding(text: str):
    response = hf_client.text_generation(model="gpt2", inputs=text)
    return response  # Можно хранить текст или список

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
    filename = generate_filename("Пациент", "Исследование", date_str, ext)
    local_path = os.path.join("uploads", filename)
    await file_obj.download_to_drive(local_path)

    # OCR
    text = ocr_document(local_path)
    txt_path = local_path + ".txt"
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(text)

    # Эмбеддинг
    emb = get_embedding(text)

    # Сохраняем в базу
    embed_db[filename] = {"text": text, "embedding": emb}
    with open(EMBED_DB_FILE, "w", encoding="utf-8") as f:
        json.dump(embed_db, f, ensure_ascii=False, indent=2)

    # Загрузка в облако
    remote_file = upload_to_yadisk(local_path)
    remote_txt = upload_to_yadisk(txt_path)

    await msg.reply_text(
        f"Документ и текст успешно загружены на Яндекс.Диск:\n{remote_file}\n{remote_txt}"
    )

# -------------------------
# 10. Поиск по тексту и возврат файлов
# -------------------------
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.text:
        return
    query = msg.text.lower()

    # Ищем похожие документы
    results = []
    for fname, data in embed_db.items():
        if query in data["text"].lower():
            results.append(fname)

    if not results:
        await msg.reply_text("Документы не найдены.")
        return

    for fname in results:
        remote_path = f"/MedicalDocs/{fname}"
        if yd.exists(remote_path):
            # Скачиваем во временный файл
            with tempfile.NamedTemporaryFile() as tmp_file:
                yd.download(remote_path, tmp_file.name)
                tmp_file.flush()
                await msg.reply_document(open(tmp_file.name, "rb"), filename=fname)
            # Также отдаем текстовый файл
            remote_txt = remote_path + ".txt"
            if yd.exists(remote_txt):
                with tempfile.NamedTemporaryFile() as tmp_txt:
                    yd.download(remote_txt, tmp_txt.name)
                    tmp_txt.flush()
                    await msg.reply_document(open(tmp_txt.name, "rb"), filename=fname + ".txt")

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