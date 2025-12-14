import os
import logging
import datetime
from dotenv import load_dotenv

from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters
)

import pytesseract
from PIL import Image
from yadisk import YaDisk

# =====================
# НАСТРОЙКИ
# =====================
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
YADISK_TOKEN = os.getenv("YADISK_TOKEN")

ROOT_FOLDER = "MedBot"

# =====================
# ЛОГИ
# =====================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)
logger = logging.getLogger("medbot")

# =====================
# YANDEX DISK
# =====================
yd = YaDisk(token=YADISK_TOKEN)

# =====================
# ВСПОМОГАТЕЛЬНЫЕ
# =====================
def ensure_root():
    logger.info("Проверяем папку MedBot")
    if not yd.exists(ROOT_FOLDER):
        yd.mkdir(ROOT_FOLDER)
        logger.info("Создана папка MedBot")

def list_patients():
    ensure_root()
    items = yd.listdir(ROOT_FOLDER)
    patients = [item["name"] for item in items if item["type"] == "dir"]
    logger.info("Найденные пациенты: %s", patients)
    return patients

def ocr_image(path: str) -> str:
    try:
        logger.info("OCR файла %s", path)
        img = Image.open(path)
        text = pytesseract.image_to_string(img, lang="rus")
        return text
    except Exception as e:
        logger.exception("OCR ошибка")
        return ""

# =====================
# HANDLERS
# =====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("/start")
    kb = [
        ["➕ Добавить пациента", "👤 Выбрать пациента"],
        ["📄 Загрузить документ", "📂 Список документов"],
    ]
    await update.message.reply_text(
        "МедБот запущен. Выберите действие:",
        reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True)
    )

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    logger.info("TEXT: %s", text)

    # --- Добавить пациента ---
    if text == "➕ Добавить пациента":
        context.user_data["mode"] = "add_patient"
        await update.message.reply_text("Введите имя пациента:")
        return

    if context.user_data.get("mode") == "add_patient":
        patient = text
        path = f"{ROOT_FOLDER}/{patient}"
        if yd.exists(path):
            await update.message.reply_text("Пациент уже существует")
        else:
            yd.mkdir(path)
            await update.message.reply_text(f"Пациент {patient} добавлен")
        context.user_data["mode"] = None
        return

    # --- Выбор пациента ---
    if text == "👤 Выбрать пациента":
        patients = list_patients()
        if not patients:
            await update.message.reply_text("Пациентов нет")
            return
        kb = [[p] for p in patients]
        context.user_data["mode"] = "select_patient"
        await update.message.reply_text(
            "Выберите пациента:",
            reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True)
        )
        return

    if context.user_data.get("mode") == "select_patient":
        context.user_data["patient"] = text
        context.user_data["mode"] = None
        await update.message.reply_text(f"Выбран пациент: {text}")
        return

    # --- Список документов ---
    if text == "📂 Список документов":
        patient = context.user_data.get("patient")
        if not patient:
            await update.message.reply_text("Сначала выберите пациента")
            return

        folder = f"{ROOT_FOLDER}/{patient}"
        files = yd.listdir(folder)
        names = [f["name"] for f in files if f["type"] == "file"]
        if not names:
            await update.message.reply_text("Документов нет")
        else:
            await update.message.reply_text(
                "Документы:\n" + "\n".join(names)
            )
        return

    # --- Загрузка ---
    if text == "📄 Загрузить документ":
        if not context.user_data.get("patient"):
            await update.message.reply_text("Сначала выберите пациента")
            return
        context.user_data["mode"] = "upload"
        await update.message.reply_text("Отправьте фото или документ")
        return

    await update.message.reply_text("Неизвестная команда")

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("DOCUMENT handler вызван")

    if context.user_data.get("mode") != "upload":
        logger.info("Документ без режима upload — игнор")
        return

    patient = context.user_data.get("patient")
    if not patient:
        await update.message.reply_text("Пациент не выбран")
        return

    try:
        if update.message.document:
            tg_file = update.message.document
            filename = tg_file.file_name
        else:
            tg_file = update.message.photo[-1]
            filename = "photo.jpg"

        local_path = f"/tmp/{filename}"
        file = await tg_file.get_file()
        await file.download_to_drive(local_path)

        logger.info("Файл скачан: %s", local_path)

        # OCR
        text = ocr_image(local_path)

        # Яндекс диск
        remote_folder = f"{ROOT_FOLDER}/{patient}"
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        remote_file = f"{remote_folder}/{ts}_{filename}"
        yd.upload(local_path, remote_file)

        if text.strip():
            txt_path = f"/tmp/{ts}_ocr.txt"
            with open(txt_path, "w", encoding="utf-8") as f:
                f.write(text)
            yd.upload(txt_path, f"{remote_folder}/{ts}_ocr.txt")

        await update.message.reply_text(
            "Документ загружен и обработан.\n"
            f"OCR символов: {len(text)}"
        )

    except Exception as e:
        logger.exception("Ошибка обработки документа")
        await update.message.reply_text(f"Ошибка: {e}")

    finally:
        context.user_data["mode"] = None

# =====================
# MAIN
# =====================
def main():
    logger.info("Запуск бота")
    ensure_root()

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Document.ALL | filters.PHOTO, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    app.run_polling()

if __name__ == "__main__":
    main()