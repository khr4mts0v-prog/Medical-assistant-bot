import os
import pytesseract
from pdf2image import convert_from_path
from PIL import Image
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN is not set in environment variables")

# ========== Память для пациентов ==========
patients = {}
current_patient = {}

# ========== Меню ==========
def main_menu():
    return ReplyKeyboardMarkup(
        [
            ["➕ Добавить документы"],
            ["🔍 Найти документы"],
            ["🧠 Запрос к нейросети"],
            ["👤 Выбрать пациента"]
        ],
        resize_keyboard=True
    )

def patient_menu():
    return ReplyKeyboardMarkup(
        [["Создать нового пациента"], ["Выбрать существующего"], ["⬅️ Назад"]],
        resize_keyboard=True
    )

# ========== Команды ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет! Я медицинский архив.\nВыберите действие:",
        reply_markup=main_menu()
    )

# ========== Выбор пациента ==========
async def select_patient(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Что хотите сделать с пациентом?",
        reply_markup=patient_menu()
    )

async def handle_patient_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    chat_id = update.message.chat_id

    if text == "Создать нового пациента":
        await update.message.reply_text("Введите имя нового пациента:", reply_markup=ReplyKeyboardRemove())
        context.user_data["creating_patient"] = True

    elif text == "Выбрать существующего":
        if not patients:
            await update.message.reply_text("Нет созданных пациентов. Создайте нового.")
            return
        buttons = [[name] for name in patients.keys()]
        buttons.append(["⬅️ Назад"])
        await update.message.reply_text("Выберите пациента:", reply_markup=ReplyKeyboardMarkup(buttons, resize_keyboard=True))
        context.user_data["selecting_patient"] = True

    elif text == "⬅️ Назад":
        await update.message.reply_text("Возврат в главное меню", reply_markup=main_menu())

# ========== Обработка текста ==========
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    chat_id = update.message.chat_id

    # Создание нового пациента
    if context.user_data.get("creating_patient"):
        patient_name = text.strip()
        if patient_name in patients:
            await update.message.reply_text("Пациент с таким именем уже существует.")
        else:
            patients[patient_name] = {"documents": []}
            current_patient[chat_id] = patient_name
            await update.message.reply_text(f"Пациент '{patient_name}' создан и выбран.", reply_markup=main_menu())
        context.user_data["creating_patient"] = False
        return

    # Выбор существующего пациента
    if context.user_data.get("selecting_patient"):
        if text in patients:
            current_patient[chat_id] = text
            await update.message.reply_text(f"Пациент '{text}' выбран.", reply_markup=main_menu())
        elif text == "⬅️ Назад":
            await update.message.reply_text("Возврат в главное меню", reply_markup=main_menu())
        else:
            await update.message.reply_text("Пациент не найден.")
        context.user_data["selecting_patient"] = False
        return

    # Главное меню
    if text == "👤 Выбрать пациента":
        await select_patient(update, context)
    elif text == "➕ Добавить документы":
        if chat_id not in current_patient:
            await update.message.reply_text("Сначала выберите пациента.")
            return
        await update.message.reply_text("Пришлите документ (фото или PDF).")
    elif text in ["🔍 Найти документы", "🧠 Запрос к нейросети"]:
        await update.message.reply_text("Функция пока в разработке.")
        else:
        await update.message.reply_text("Неизвестная команда.")

# ========== OCR ==========
def extract_text_from_file(file_path, mime_type):
    text = ""
    if "pdf" in mime_type:
        images = convert_from_path(file_path)
        for img in images:
            text += pytesseract.image_to_string(img, lang="rus") + "\n"
    else:
        img = Image.open(file_path)
        text = pytesseract.image_to_string(img, lang="rus")
    return text

# ========== Загрузка документов ==========
async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    if chat_id not in current_patient:
        await update.message.reply_text("Сначала выберите пациента.")
        return

    patient_name = current_patient[chat_id]

    # Получаем file_id документа
    if update.message.photo:
        file_id = update.message.photo[-1].file_id
        doc_type = "Фото"
    elif update.message.document:
        file_id = update.message.document.file_id
        doc_type = update.message.document.mime_type
    else:
        await update.message.reply_text("Неизвестный формат файла.")
        return

    # Скачиваем файл временно
    file = await context.bot.get_file(file_id)
    local_path = f"/tmp/{file_id.replace('/', '_')}"
    await file.download_to_drive(local_path)

    # OCR
    ocr_text = extract_text_from_file(local_path, doc_type)

    # Сохраняем документ и текст
    patients[patient_name]["documents"].append({
        "file_id": file_id,
        "type": doc_type,
        "text": ocr_text
    })

    await update.message.reply_text(f"Документ добавлен к пациенту '{patient_name}'.")

# ========== Запуск ==========
app = ApplicationBuilder().token(BOT_TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
app.add_handler(MessageHandler(filters.PHOTO | filters.Document.ALL, handle_document))

if name == "__main__":
    app.run_polling()
