import logging
import os
import json
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from dotenv import load_dotenv

from cloud import YaDisk
from ocr import ocr_image
from AIAnalise import AI
from utils import extract_date_from_text

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
YADISK_TOKEN = os.getenv("YADISK_TOKEN")
HF_TOKEN = os.getenv("HF_API_TOKEN")

logging.basicConfig(level=logging.INFO)

bot = Bot(BOT_TOKEN)
dp = Dispatcher()

disk = YaDisk(YADISK_TOKEN)
ai = AI(HF_TOKEN)

BASE = "MedBot"
PATIENTS_FILE = f"{BASE}/patients.json"

class FSM(StatesGroup):
    patient = State()
    search = State()
    wait_doc = State()

menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="Выбрать пациента"), KeyboardButton(text="Добавить пациента")],
        [KeyboardButton(text="Загрузить документ")],
        [KeyboardButton(text="Найти документы")],
        [KeyboardButton(text="Очистить чат")]
    ],
    resize_keyboard=True
)

def load_patients():
    try:
        disk.download_file(PATIENTS_FILE, "patients.json")
        return json.load(open("patients.json"))
    except:
        return []

def save_patients(patients):
    json.dump(patients, open("patients.json", "w"), ensure_ascii=False, indent=2)
    disk.upload_file("patients.json", PATIENTS_FILE)

@dp.message(F.text == "/start")
async def start(msg: Message):
    await msg.answer("Привет! Выбери действие:", reply_markup=menu)

@dp.message(F.text == "Очистить чат")
async def clear(msg: Message):
    await msg.answer("Чат очищен.", reply_markup=menu)

@dp.message(F.text == "Добавить пациента")
async def add_patient(msg: Message):
    await msg.answer("Введите имя пациента:")
    await dp.fsm.set_state(msg.from_user.id, FSM.patient)

@dp.message(FSM.patient)
async def save_patient(msg: Message, state: FSMContext):
    name = msg.text.strip()
    patients = load_patients()
    if name not in patients:
        patients.append(name)
        save_patients(patients)
        disk.ensure_dir(f"{BASE}/{name}/docs")
        disk.ensure_dir(f"{BASE}/{name}/OCR")
    await state.clear()
    await msg.answer(f"Пациент {name} добавлен.", reply_markup=menu)

@dp.message(F.text == "Загрузить документ")
async def wait_doc(msg: Message):
    await msg.answer("Отправьте документ.")
    await dp.fsm.set_state(msg.from_user.id, FSM.wait_doc)

@dp.message(F.document | F.photo, FSM.wait_doc)
async def handle_doc(msg: Message, state: FSMContext):
    file = msg.document or msg.photo[-1]
    file_path = f"tmp_{file.file_id}"
    await bot.download(file, file_path)

    text = ocr_image(file_path)
    meta = ai.classify_document(text)

    date = meta["date"] or extract_date_from_text(text) or "без_даты"
    filename = f"Документ_{meta['type']}_{date}.jpg"

    disk.upload_file(file_path, f"{BASE}/Неопределённый/docs/{filename}")

    await msg.answer(
        f"📄 Документ загружен\n"
        f"Тип: {meta['type']}\n"
        f"Дата: {date}\n"
        f"Ключевые слова: {', '.join(meta['keywords'])}"
    )
    await state.clear()

if __name__ == "__main__":
    dp.run_polling(bot)