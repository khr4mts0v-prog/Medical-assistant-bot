import os
import pytesseract
from pdf2image import convert_from_path
from PIL import Image
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from transformers import AutoTokenizer, AutoModel
import yadisk
import torch
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity

# Настройки
BOT_TOKEN = os.getenv("BOT_TOKEN")
YANDEX_TOKEN = os.getenv("YANDEX_TOKEN")

if not BOT_TOKEN or not YANDEX_TOKEN:
    raise ValueError("Не заданы BOT_TOKEN или YANDEX_TOKEN")

# Tesseract
os.environ["TESSDATA_PREFIX"] = "/usr/share/tesseract-ocr/5/tessdata/"

# HuggingFace для эмбеддингов
tokenizer = AutoTokenizer.from_pretrained("sentence-transformers/all-MiniLM-L6-v2")
model = AutoModel.from_pretrained("sentence-transformers/all-MiniLM-L6-v2")

def get_embedding(text):
    inputs = tokenizer(text, return_tensors="pt", truncation=True, padding=True)
    with torch.no_grad():
        outputs = model(**inputs)
    emb = outputs.last_hidden_state.mean(dim=1)
    return emb[0].numpy()

def find_relevant_docs(query, documents, top_n=3):
    query_emb = get_embedding(query)
    sims = [cosine_similarity([query_emb], [doc["embedding"]])[0][0] for doc in documents]
    idx = np.argsort(sims)[::-1][:top_n]
    return [documents[i] for i in idx]

# Яндекс.Диск
y = yadisk.YaDisk(token=YANDEX_TOKEN)
if not y.check_token():
    raise ValueError("Невалидный токен Яндекс.Диска")

def upload_to_yadisk(file_path, patient_name):
    folder = f"/MedicalDocs/{patient_name}"
    if not y.exists(folder):
        y.mkdir(folder)
    file_name = os.path.basename(file_path)
    remote_path = f"{folder}/{file_name}"
    y.upload(file_path, remote_path, overwrite=True)
    return y.get_download_link(remote_path)

# Память
patients = {}
current_patient = {}

# Меню
def main_menu():
    return ReplyKeyboardMarkup(
        [["➕ Добавить документы"], ["🔍 Найти документы"], ["🧠 Запрос к нейросети"], ["👤 Выбрать пациента"]],
        resize_keyboard=True
    )

def patient_menu():
    return ReplyKeyboardMarkup(
        [["Создать нового пациента"], ["Выбрать существующего"], ["⬅️ Назад"]],
        resize_keyboard=True
    )

# OCR
def extract_text(file_path, mime_type):
    text = ""
    try:
        if "pdf" in mime_type:
            images = convert_from_path(file_path)
            for img in images:
                text += pytesseract.image_to_string(img, lang="rus") + "\n"
        else:
            img = Image.open(file_path)
            text = pytesseract.image_to_string(img, lang="rus")
    except Exception as e:
        print("OCR error:", e)
    return text

# Handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try: await update.message.delete()
    except: pass
    await update.message.reply_text("Привет! Я медицинский архив.", reply_markup=main_menu())

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    chat_id = update.message.chat_id
    try: await update.message.delete()
    except: pass

    # Назад
    if text == "⬅️ Назад":
        await update.message.reply_text("Главное меню", reply_markup=main_menu())
        return
    # Выбор пациента
    elif text == "👤 Выбрать пациента":
        await update.message.reply_text("Что хотите сделать с пациентом?", reply_markup=patient_menu())
        return
    # Добавление документа
    elif text == "➕ Добавить документы":
        if chat_id not in current_patient:
            await update.message.reply_text("Сначала выберите пациента.")
            return
        await update.message.reply_text("Пришлите документ (фото или PDF).")
        return
    # Найти документы
    elif text == "🔍 Найти документы":
        if chat_id not in current_patient:
            await update.message.reply_text("Сначала выберите пациента.")
            return
        patient_name = current_patient[chat_id]
        docs = patients.get(patient_name, {}).get("documents", [])
        if not docs:
            await update.message.reply_text(f"У пациента {patient_name} документов нет.")
        else:
            await update.message.reply_text(f"У пациента {patient_name} {len(docs)} документов.")
        return
    # GPT-запрос
    elif text == "🧠 Запрос к нейросети":
        await update.message.reply_text("Функция GPT пока в разработке.")
        return
    # Создать нового пациента
    elif text == "Создать нового пациента":
        await update.message.reply_text("Введите имя нового пациента:")
        context.user_data["creating_patient"] = True
        return
    # Выбрать существующего пациента
    elif text == "Выбрать существующего":
        if not patients:
            await update.message.reply_text("Пациентов нет. Создайте нового.")
            return
        buttons = [[name] for name in patients.keys()]
        await update.message.reply_text("Выберите пациента:", reply_markup=ReplyKeyboardMarkup(buttons, resize_keyboard=True))
        context.user_data["selecting_patient"] = True
        return
    # Ввод имени нового пациента
    elif context.user_data.get("creating_patient"):
        patient_name = text.strip()
        patients.setdefault(patient_name, {"documents": []})
        current_patient[chat_id] = patient_name
        context.user_data["creating_patient"] = False
        await update.message.reply_text(f"Пациент {patient_name} создан и выбран.", reply_markup=main_menu())
        return
    # Выбор существующего пациента
    elif context.user_data.get("selecting_patient"):
        patient_name = text.strip()
        if patient_name in patients:
            current_patient[chat_id] = patient_name
            await update.message.reply_text(f"Пациент {patient_name} выбран.", reply_markup=main_menu())
        else:
            await update.message.reply_text("Пациент не найден. Выберите другого.")
        context.user_data["selecting_patient"] = False
        return
    else:
        await update.message.reply_text("Неизвестная команда.")

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    try: await update.message.delete()
    except: pass

    if chat_id not in current_patient:
        await update.message.reply_text("Сначала выберите пациента.")
        return
    patient_name = current_patient[chat_id]

    if update.message.photo:
        file_id = update.message.photo[-1].file_id
        doc_type = "image/jpeg"
    elif update.message.document:
        file_id = update.message.document.file_id
        doc_type = update.message.document.mime_type
    else:
        await update.message.reply_text("Неподдерживаемый формат документа.")
        return

    file = await context.bot.get_file(file_id)
    tmp_path = f"/tmp/{file_id.replace('/', '_')}"
    await file.download_to_drive(tmp_path)

    text = extract_text(tmp_path, doc_type)
    emb = get_embedding(text)
    url = upload_to_yadisk(tmp_path, patient_name)

    patients.setdefault(patient_name, {}).setdefault("documents", []).append({
        "file_id": file_id,
        "type": doc_type,
        "text": text,
        "embedding": emb,
        "url": url
    })

    await update.message.reply_text(f"Документ добавлен: {url}")

# ===================== Запуск =====================
app = ApplicationBuilder().token(BOT_TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
app.add_handler(MessageHandler(filters.PHOTO | filters.Document.ALL, handle_document))

if __name__ == "__main__":
    app.run_polling()
