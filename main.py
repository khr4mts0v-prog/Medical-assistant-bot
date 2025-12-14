import os
import re
import json
import numpy as np
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from yadisk import YaDisk
import pytesseract
from pdf2image import convert_from_path
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity
from huggingface_hub import InferenceClient

# --- Настройки ---
BOT_TOKEN = os.environ.get("BOT_TOKEN")
YANDEX_TOKEN = os.environ.get("YANDEX_TOKEN")
HF_API_TOKEN = os.environ.get("HF_API_TOKEN")

# Подключение к сервисам
y = YaDisk(token=YANDEX_TOKEN)
hf_client = InferenceClient(HF_API_TOKEN)
model = SentenceTransformer('paraphrase-MiniLM-L6-v2')  # лёгкая модель

# --- Вспомогательные функции ---

def extract_info_and_generate_name(text, patient_name, original_ext=".pdf"):
    keywords = {"ЭЭГ": "eeg", "кардиология": "cardiology", "анализ крови": "blood_test", "ЭКГ": "ecg"}
    study_type = next((v for k,v in keywords.items() if k.lower() in text.lower()), "other")
    dates = re.findall(r'\b\d{2}[./-]\d{2}[./-]\d{4}\b', text)
    procedure_date = dates[0] if dates else datetime.today().strftime("%Y-%m-%d")
    file_name = f"{patient_name.strip().replace(' ','_').lower()}-{study_type}-{procedure_date}{original_ext}"
    return file_name, study_type, procedure_date

def get_embedding(text):
    return model.encode(text)

def save_document(patient_name, file_path, text):
    ext = os.path.splitext(file_path)[1]
    file_name, study_type, procedure_date = extract_info_and_generate_name(text, patient_name, ext)
    remote_folder = f"/MedicalDocs/{patient_name}"
    if not y.exists(remote_folder):
        y.mkdir(remote_folder)
    remote_path = f"{remote_folder}/{file_name}"
    y.upload(file_path, remote_path, overwrite=True)
    
    embedding = get_embedding(text)
    json_data = {"text": text, "embedding": embedding.tolist(), "original_file": remote_path}
    json_name = file_name + ".json"
    local_json = f"/tmp/{json_name}"
    with open(local_json, "w", encoding="utf-8") as f:
        json.dump(json_data, f, ensure_ascii=False)
    y.upload(local_json, f"{remote_folder}/{json_name}", overwrite=True)
    return remote_path

def ocr_from_file(file_path):
    ext = os.path.splitext(file_path)[1].lower()
    text = ""
    if ext == ".pdf":
        pages = convert_from_path(file_path)
        for page in pages:
            text += pytesseract.image_to_string(page, lang='rus')
    else:
        text = pytesseract.image_to_string(file_path, lang='rus')
    return text

def find_docs_in_cloud(patient_name, query, top_n=3):
    folder = f"/MedicalDocs/{patient_name}"
    if not y.exists(folder):
        return []
    files = y.listdir(folder)
    json_files = [f for f in files if f["name"].endswith(".json")]
    docs = []
    for f in json_files:
        local = f"/tmp/{f['name']}"
        y.download(f"{folder}/{f['name']}", local)
        with open(local, "r", encoding="utf-8") as jf:
            doc = json.load(jf)
            docs.append(doc)
    if not docs:
        return []
    query_emb = get_embedding(query)
    sims = [cosine_similarity([query_emb], [np.array(d["embedding"])]).flatten()[0] for d in docs]
    idx = np.argsort(sims)[::-1][:top_n]
    return [docs[i] for i in idx]

def send_docs(update, context, patient_name, docs):
    for doc in docs:
        file_url = doc['original_file']
        local_path = f"/tmp/{os.path.basename(file_url)}"
        y.download(file_url, local_path, overwrite=True)
        context.bot.send_document(chat_id=update.effective_chat.id, document=open(local_path, "rb"))

def ask_hf_model(question, context_text):
    prompt = f"Вот медицинские документы:\n{context_text}\n\nВопрос: {question}\nОтвет коротко и понятно:"
    response = hf_client.text_generation(
        model="tiiuae/falcon-7b-instruct",
        inputs=prompt,
        parameters={"max_new_tokens": 300}
    )
    if isinstance(response, list) and len(response) > 0:
        return response[0]["generated_text"].split("Ответ коротко и понятно:")[-1].strip()
    return "Не удалось получить ответ"

# --- Handlers ---

async def start(update, context):
    context.user_data["current_patient"] = ""
    keyboard = [
        [InlineKeyboardButton("➕ Добавить документы", callback_data='add_doc')],
        [InlineKeyboardButton("🔍 Найти документы", callback_data='find_doc')],
        [InlineKeyboardButton("🧠 Запрос к нейросети", callback_data='query')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Введите имя пациента или выберите действие:", reply_markup=reply_markup)

async def set_patient(update, context):
    context.user_data["current_patient"] = update.message.text.strip()
    await update.message.reply_text(f"Пациент установлен: {context.user_data['current_patient']}")

async def handle_document(update, context):
    patient_name = context.user_data.get("current_patient", "")
    if not patient_name:
        await update.message.reply_text("Сначала введите имя пациента")
        return
    file = await update.message.document.get_file()
    local_path = f"/tmp/{file.file_unique_id}_{update.message.document.file_name}"
    await file.download_to_drive(local_path)
    text = ocr_from_file(local_path)
    remote_path = save_document(patient_name, local_path, text)
    await update.message.reply_text(f"Документ загружен и сохранён: {remote_path}")

async def handle_message(update, context):
    text = update.message.text
    patient_name = context.user_data.get("current_patient", "")
    if not patient_name:
        await set_patient(update, context)
        return

    if "загрузить документы" in text.lower():
        await update.message.reply_text("Отправьте документы для загрузки")
        return

    docs = find_docs_in_cloud(patient_name, text)
    if docs:
        combined_text = "\n\n".join([d["text"] for d in docs])
        answer = ask_hf_model(text, combined_text)
        await update.message.reply_text(answer)
        send_docs(update, context, patient_name, docs)
    else:
        await update.message.reply_text("Документы не найдены или недостаточно информации")

async def button_handler(update, context):
    query = update.callback_query
    await query.answer()
    if query.data == 'add_doc':
        await query.message.reply_text("Отправьте документы для загрузки")
    elif query.data == 'find_doc':
        await query.message.reply_text("Введите запрос для поиска документов")
    elif query.data == 'query':
        await query.message.reply_text("Введите запрос к нейросети")
    await query.message.delete()

# --- Запуск бота ---
app = ApplicationBuilder().token(BOT_TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
app.add_handler(CallbackQueryHandler(button_handler))

app.run_polling()
