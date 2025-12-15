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

ROOT_FOLDER = "MedBot"
TMP_DIR = "/tmp/medbot"
os.makedirs(TMP_DIR, exist_ok=True)

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
# ВСПОМОГАТЕЛЬНЫЕ
# ======================
def ensure_folder(path):
    if not yd.exists(path):
        yd.mkdir(path)

def get_patients():
    ensure_folder(ROOT_FOLDER)
    return [
        i["name"] for i in yd.listdir(ROOT_FOLDER)
        if i["type"] == "dir"
    ]

def meta_path(patient):
    return f"{ROOT_FOLDER}/{patient}/meta.json"

def load_meta(patient):
    path = meta_path(patient)
    if yd.exists(path):
        with yd.download(path) as f:
            return json.load(f)
    return {"documents": []}

def save_meta(patient, data):
    local = f"{TMP_DIR}/{patient}_meta.json"
    with open(local, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    yd.upload(local, meta_path(patient), overwrite=True)

def ocr_image(path):
    try:
        return pytesseract.image_to_string(
            Image.open(path),
            lang="rus"
        )
    except Exception as e:
        logging.error(f"OCR error: {e}")
        return ""

def extract_date(text):
    for t in text.split():
        if len(t) == 10 and t[2] == "-" and t[5] == "-":
            return t
    return datetime.date.today().strftime("%d-%m-%Y")

# ======================
# HANDLERS
# ======================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("Выберите действие:", reply_markup=MENU)

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    # ===== Очистка =====
    if text == "Очистить чат":
        context.user_data.clear()
        await update.message.reply_text("Чат очищен.", reply_markup=MENU)
        return

    # ===== Добавить пациента =====
    if text == "Добавить пациента":
        context.user_data["state"] = "add_patient"
        await update.message.reply_text("Введите имя пациента:")
        return

    if context.user_data.get("state") == "add_patient":
        patient = text
        base = f"{ROOT_FOLDER}/{patient}"
        ensure_folder(base)
        ensure_folder(f"{base}/docs")
        ensure_folder(f"{base}/ocr")
        save_meta(patient, {"documents": []})
        context.user_data.clear()
        await update.message.reply_text(
            f"Пациент «{patient}» добавлен.",
            reply_markup=MENU
        )
        return

    # ===== Выбор пациента =====
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

    # ===== Загрузка =====
    if text == "Загрузить документ":
        if "patient" not in context.user_data:
            await update.message.reply_text("Сначала выберите пациента.")
            return
        context.user_data["awaiting_file"] = True
        await update.message.reply_text(
            "Отправьте фото или документ.\n"
            "Можно добавить подпись с названием."
        )
        return

    # ===== Поиск документов =====
    if text == "Найти документы":
        patient = context.user_data.get("patient")
        if not patient:
            await update.message.reply_text("Сначала выберите пациента.")
            return

        meta = load_meta(patient)
        if not meta["documents"]:
            await update.message.reply_text("Документов нет.")
            return

        context.user_data["awaiting_doc_choice"] = True
        msg = "Документы:\n"
        for d in meta["documents"]:
            msg += f"• {d['file']}\n"
        msg += "\nМожно выбрать файл ИЛИ написать ключевые слова."
        await update.message.reply_text(msg)
        return

    # ===== Выдача документа =====
    if context.user_data.get("awaiting_doc_choice"):
        patient = context.user_data["patient"]
        meta = load_meta(patient)

        found = None
        for d in meta["documents"]:
            if text.lower() in d["file"].lower():
                found = d
                break

        if not found:
            for d in meta["documents"]:
                ocr_path = f"{ROOT_FOLDER}/{patient}/ocr/{d['file']}.txt"
                if yd.exists(ocr_path):
                    with yd.download(ocr_path) as f:
                        if text.lower() in f.read().lower():
                            found = d
                            break

        if not found:
            await update.message.reply_text("Документ не найден.")
            return

        remote = f"{ROOT_FOLDER}/{patient}/docs/{found['file']}"
        local = f"{TMP_DIR}/{found['file']}"
        yd.download(remote, local)

        await update.message.reply_document(open(local, "rb"))
        context.user_data.pop("awaiting_doc_choice", None)
        return

    await update.message.reply_text("Неизвестная команда.", reply_markup=MENU)

async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("awaiting_file"):
        return

    patient = context.user_data["patient"]
    caption = update.message.caption or "Документ"

    file = update.message.photo[-1] if update.message.photo else update.message.document
    ext = ".jpg" if update.message.photo else os.path.splitext(file.file_name)[1]

    file_obj = await file.get_file()
    local = f"{TMP_DIR}/upload{ext}"
    await file_obj.download_to_drive(local)

    ocr = ocr_image(local)
    date = extract_date(ocr)
    name = f"{patient}_{caption.replace(' ', '_')}_{date}{ext}"

    base = f"{ROOT_FOLDER}/{patient}"
    yd.upload(local, f"{base}/docs/{name}", overwrite=True)

    ocr_local = f"{TMP_DIR}/{name}.txt"
    with open(ocr_local, "w", encoding="utf-8") as f:
        f.write(ocr)
    yd.upload(ocr_local, f"{base}/ocr/{name}.txt", overwrite=True)

    meta = load_meta(patient)
    meta["documents"].append({"file": name})
    save_meta(patient, meta)

    context.user_data.pop("awaiting_file", None)

    await update.message.reply_text(
        f"📄 Документ загружен\n{name}",
        reply_markup=MENU
    )

# ======================
# ЗАПУСК
# ======================
if __name__ == "__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.ALL, handle_file))

    logging.info("MedBot запущен")
    app.run_polling()