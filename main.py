import os
import json
import logging
import datetime
from dotenv import load_dotenv

from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from yadisk import YaDisk
from PIL import Image
import pytesseract

# ======================
# НАСТРОЙКИ
# ======================
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
YADISK_TOKEN = os.getenv("YADISK_TOKEN")

ROOT = "MedBot"
TMP = "/tmp/medbot"
os.makedirs(TMP, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

yd = YaDisk(token=YADISK_TOKEN)

MENU = ReplyKeyboardMarkup(
    [
        ["Выбрать пациента", "Добавить пациента"],
        ["Загрузить документ", "Найти документы"],
        ["Очистить чат"],
    ],
    resize_keyboard=True
)

# ======================
# YADISK HELPERS
# ======================
def ensure_dir(path):
    if not yd.exists(path):
        logging.info(f"Создаю папку: {path}")
        yd.mkdir(path)

def init_patient(patient):
    ensure_dir(ROOT)
    ensure_dir(f"{ROOT}/{patient}")
    ensure_dir(f"{ROOT}/{patient}/docs")
    ensure_dir(f"{ROOT}/{patient}/ocr")

    meta_path = f"{ROOT}/{patient}/meta.json"
    if not yd.exists(meta_path):
        save_meta(patient, {"documents": []})

def get_patients():
    ensure_dir(ROOT)
    return [
        x["name"] for x in yd.listdir(ROOT)
        if x["type"] == "dir"
    ]

def meta_path(patient):
    return f"{ROOT}/{patient}/meta.json"

def load_meta(patient):
    path = meta_path(patient)
    if yd.exists(path):
        with yd.download(path) as f:
            return json.load(f)
    return {"documents": []}

def save_meta(patient, data):
    local = f"{TMP}/{patient}_meta.json"
    with open(local, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    yd.upload(local, meta_path(patient), overwrite=True)

# ======================
# OCR
# ======================
def ocr_image(path):
    try:
        return pytesseract.image_to_string(
            Image.open(path),
            lang="rus"
        )
    except Exception as e:
        logging.error(f"OCR ERROR: {e}")
        return ""

def extract_date(text):
    for word in text.split():
        if len(word) == 10 and word[2] == "-" and word[5] == "-":
            return word
    return datetime.date.today().strftime("%d-%m-%Y")

# ======================
# HANDLERS
# ======================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("Выберите действие:", reply_markup=MENU)

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    if text == "Очистить чат":
        context.user_data.clear()
        await update.message.reply_text("Готово.", reply_markup=MENU)
        return

    if text == "Добавить пациента":
        context.user_data["state"] = "add_patient"
        await update.message.reply_text("Введите имя пациента:")
        return

    if context.user_data.get("state") == "add_patient":
        patient = text
        init_patient(patient)
        context.user_data.clear()
        await update.message.reply_text(
            f"Пациент «{patient}» добавлен",
            reply_markup=MENU
        )
        return

    if text == "Выбрать пациента":
        patients = get_patients()
        kb = [[p] for p in patients]
        await update.message.reply_text(
            "Выберите пациента:",
            reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True)
        )
        return

    if text in get_patients():
        context.user_data["patient"] = text
        await update.message.reply_text(
            f"Выбран пациент: {text}",
            reply_markup=MENU
        )
        return

    if text == "Загрузить документ":
        if "patient" not in context.user_data:
            await update.message.reply_text("Сначала выберите пациента.")
            return
        context.user_data["await_file"] = True
        await update.message.reply_text(
            "Отправьте фото или документ.\n"
            "Можно добавить подпись."
        )
        return

    if text == "Найти документы":
        patient = context.user_data.get("patient")
        if not patient:
            await update.message.reply_text("Сначала выберите пациента.")
            return

        meta = load_meta(patient)
        if not meta["documents"]:
            await update.message.reply_text("Документов нет.")
            return

        context.user_data["search"] = True
        msg = "Документы:\n"
        for d in meta["documents"]:
            msg += f"• {d['file']}\n"
        msg += "\nВведите имя файла или ключевые слова"
        await update.message.reply_text(msg)
        return

    if context.user_data.get("search"):
        patient = context.user_data["patient"]
        meta = load_meta(patient)

        for d in meta["documents"]:
            if text.lower() in d["file"].lower():
                remote = f"{ROOT}/{patient}/docs/{d['file']}"
                local = f"{TMP}/{d['file']}"
                yd.download(remote, local)
                await update.message.reply_document(open(local, "rb"))
                context.user_data.pop("search")
                return

        await update.message.reply_text("Не найдено.")
        return

    await update.message.reply_text("Используйте меню.", reply_markup=MENU)

async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("await_file"):
        return

    patient = context.user_data["patient"]
    init_patient(patient)

    caption = update.message.caption or "Документ"

    file = update.message.photo[-1] if update.message.photo else update.message.document
    ext = ".jpg" if update.message.photo else os.path.splitext(file.file_name)[1]

    file_obj = await file.get_file()
    local = f"{TMP}/upload{ext}"
    await file_obj.download_to_drive(local)

    logging.info("Файл скачан")

    ocr = ocr_image(local)
    date = extract_date(ocr)
    name = f"{patient}_{caption.replace(' ', '_')}_{date}{ext}"

    doc_remote = f"{ROOT}/{patient}/docs/{name}"
    ocr_remote = f"{ROOT}/{patient}/ocr/{name}.txt"

    yd.upload(local, doc_remote, overwrite=True)

    with open(f"{TMP}/{name}.txt", "w", encoding="utf-8") as f:
        f.write(ocr)
    yd.upload(f"{TMP}/{name}.txt", ocr_remote, overwrite=True)

    meta = load_meta(patient)
    meta["documents"].append({"file": name})
    save_meta(patient, meta)

    context.user_data.pop("await_file")

    await update.message.reply_text(
        f"📄 Документ загружен\n{name}",
        reply_markup=MENU
    )

# ======================
# RUN
# ======================
if __name__ == "__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.ALL, handle_file))

    logging.info("MedBot стартовал")
    app.run_polling()