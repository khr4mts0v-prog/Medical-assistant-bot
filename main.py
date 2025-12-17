import os
import json
import logging
from datetime import datetime

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.filters import Command

# =====================
# CONFIG
# =====================

BOT_TOKEN = os.getenv("BOT_TOKEN")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
FILES_DIR = os.path.join(DATA_DIR, "files")
PATIENTS_FILE = os.path.join(DATA_DIR, "patients.json")

os.makedirs(FILES_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

# =====================
# HELPERS
# =====================

def load_patients():
    if not os.path.exists(PATIENTS_FILE):
        return {}
    with open(PATIENTS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_patients(data: dict):
    with open(PATIENTS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def main_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Выбрать пациента"), KeyboardButton(text="Добавить пациента")],
            [KeyboardButton(text="Загрузить документ"), KeyboardButton(text="Найти документы")],
            [KeyboardButton(text="Очистить чат")]
        ],
        resize_keyboard=True
    )

# =====================
# FSM
# =====================

class PatientFSM(StatesGroup):
    waiting_for_new_patient = State()
    waiting_for_search = State()
    waiting_for_doc_number = State()

# =====================
# BOT INIT
# =====================

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# =====================
# COMMANDS
# =====================

@dp.message(Command("start"))
async def start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "Привет 👋\nЯ медицинский архив-бот.\nВыбери действие:",
        reply_markup=main_menu()
    )

# =====================
# ADD PATIENT
# =====================

@dp.message(F.text == "Добавить пациента")
async def add_patient_start(message: Message, state: FSMContext):
    await state.set_state(PatientFSM.waiting_for_new_patient)
    await message.answer("Введите имя пациента:")

@dp.message(PatientFSM.waiting_for_new_patient)
async def add_patient_finish(message: Message, state: FSMContext):
    name = message.text.strip()
    patients = load_patients()

    if name in patients:
        await message.answer("❗ Такой пациент уже существует", reply_markup=main_menu())
        await state.clear()
        return

    patients[name] = []
    save_patients(patients)

    await state.clear()
    await message.answer(f"✅ Пациент «{name}» добавлен", reply_markup=main_menu())

# =====================
# SELECT PATIENT
# =====================

@dp.message(F.text == "Выбрать пациента")
async def select_patient(message: Message, state: FSMContext):
    patients = load_patients()
    if not patients:
        await message.answer("Пациентов пока нет")
        return

    kb = [[KeyboardButton(text=name)] for name in patients.keys()]
    await message.answer("Выберите пациента:", reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True))

@dp.message(lambda m: m.text in load_patients().keys())
async def patient_selected(message: Message, state: FSMContext):
    await state.update_data(active_patient=message.text)
    await message.answer(f"👤 Активный пациент: {message.text}", reply_markup=main_menu())

# =====================
# UPLOAD DOCUMENT
# =====================

@dp.message(F.text == "Загрузить документ")
async def wait_document(message: Message, state: FSMContext):
    data = await state.get_data()
    if "active_patient" not in data:
        await message.answer("Сначала выберите пациента")
        return

    await message.answer("Отправьте файл или фото")

@dp.message(F.document | F.photo)
async def handle_document(message: Message, state: FSMContext):
    data = await state.get_data()
    patient = data.get("active_patient")

    if not patient:
        await message.answer("❗ Сначала выберите пациента")
        return

    patients = load_patients()

    if message.document:
        file = message.document
    else:
        file = message.photo[-1]

    file_info = await bot.get_file(file.file_id)
    ext = os.path.splitext(file_info.file_path)[-1] or ".jpg"

    filename = f"{patient}_{datetime.now().strftime('%d-%m-%Y_%H-%M-%S')}{ext}"
    save_path = os.path.join(FILES_DIR, filename)

    await bot.download_file(file_info.file_path, save_path)

    patients[patient].append({
        "name": filename,
        "path": save_path,
        "uploaded": datetime.now().isoformat()
    })

    save_patients(patients)

    await message.answer(
        f"📄 Документ загружен\nНазвание: {filename}",
        reply_markup=main_menu()
    )

# =====================
# SEARCH DOCUMENTS
# =====================

@dp.message(F.text == "Найти документы")
async def search_start(message: Message, state: FSMContext):
    data = await state.get_data()
    if "active_patient" not in data:
        await message.answer("Сначала выберите пациента")
        return

    await state.set_state(PatientFSM.waiting_for_search)
    await message.answer("Введите ключевые слова или «список»")

@dp.message(PatientFSM.waiting_for_search)
async def search_process(message: Message, state: FSMContext):
    query = message.text.lower()
    data = await state.get_data()
    patient = data["active_patient"]
    patients = load_patients()

    docs = patients.get(patient, [])
    if not docs:
        await message.answer("Документов нет", reply_markup=main_menu())
        await state.clear()
        return

    results = docs if query in ["список", "все"] else [
        d for d in docs if query in d["name"].lower()
    ]

    if not results:
        await message.answer("Ничего не найдено", reply_markup=main_menu())
        await state.clear()
        return

    text = "Найденные документы:\n"
    for i, d in enumerate(results, 1):
        text += f"{i}. {d['name']}\n"

    await state.update_data(search_results=results)
    await state.set_state(PatientFSM.waiting_for_doc_number)
    await message.answer(text + "\nОтправьте номер документа")

@dp.message(PatientFSM.waiting_for_doc_number)
async def send_document(message: Message, state: FSMContext):
    data = await state.get_data()
    results = data.get("search_results", [])

    if message.text.lower() == "все":
        for d in results:
            await message.answer_document(open(d["path"], "rb"))
        await state.clear()
        return

    if not message.text.isdigit():
        await message.answer("Введите номер документа")
        return

    idx = int(message.text) - 1
    if idx < 0 or idx >= len(results):
        await message.answer("Неверный номер")
        return

    await message.answer_document(open(results[idx]["path"], "rb"))
    await state.clear()

# =====================
# CLEAR CHAT
# =====================

@dp.message(F.text == "Очистить чат")
async def clear_chat(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("🧹 Готово", reply_markup=main_menu())

# =====================
# RUN
# =====================

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())