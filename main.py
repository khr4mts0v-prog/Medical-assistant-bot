import asyncio
import logging
import os

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from aiogram.filters import Command
from dotenv import load_dotenv

# --------------------
# Загрузка окружения
# --------------------
load_dotenv(dotenv_path=".env", override=True)

BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN не найден в .env")

# --------------------
# Логи
# --------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

logger = logging.getLogger(__name__)

# --------------------
# Бот
# --------------------
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# --------------------
# Клавиатура
# --------------------
main_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="Выбрать пациента")],
        [KeyboardButton(text="Добавить пациента")],
        [KeyboardButton(text="Загрузить документ")],
        [KeyboardButton(text="Найти документы")],
        [KeyboardButton(text="Очистить чат")],
    ],
    resize_keyboard=True
)

# --------------------
# Хендлеры
# --------------------
@dp.message(Command("start"))
async def start_cmd(message: Message):
    logger.info("Команда /start")
    await message.answer(
        "Привет! Я медицинский ассистент 🤖\nВыбери действие:",
        reply_markup=main_kb
    )


@dp.message(F.text == "Очистить чат")
async def clear_chat(message: Message):
    logger.info("Очистка чата")
    await message.answer("Чат очищен 🧹", reply_markup=main_kb)


@dp.message(F.text == "Добавить пациента")
async def add_patient(message: Message):
    logger.info("Нажата кнопка: Добавить пациента")
    await message.answer(
        "Отправь имя пациента одним сообщением",
        reply_markup=ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="Главное меню")]],
            resize_keyboard=True
        )
    )


@dp.message(F.text == "Выбрать пациента")
async def choose_patient(message: Message):
    logger.info("Нажата кнопка: Выбрать пациента")
    await message.answer("Здесь позже будет список пациентов")


@dp.message(F.text == "Загрузить документ")
async def upload_doc(message: Message):
    logger.info("Нажата кнопка: Загрузить документ")
    await message.answer(
        "Отправь файл или фотографию документа",
        reply_markup=ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="Главное меню")]],
            resize_keyboard=True
        )
    )


@dp.message(F.text == "Найти документы")
async def find_docs(message: Message):
    logger.info("Нажата кнопка: Найти документы")
    await message.answer(
        "Введи ключевые слова или напиши «все»",
        reply_markup=ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="Главное меню")]],
            resize_keyboard=True
        )
    )


@dp.message(F.text == "Главное меню")
async def back_to_menu(message: Message):
    logger.info("Возврат в главное меню")
    await message.answer("Главное меню", reply_markup=main_kb)


@dp.message()
async def fallback(message: Message):
    logger.info(f"Неизвестное сообщение: {message.text}")
    await message.answer(
        "Команда не распознана. Используй меню.",
        reply_markup=main_kb
    )


# --------------------
# Запуск
# --------------------
async def main():
    logger.info("🚀 Бот запускается")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())