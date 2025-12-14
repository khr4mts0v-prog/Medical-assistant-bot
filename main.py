import os
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

# Получаем токен из переменных окружения
BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN is not set in environment variables")

# Меню
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

# Команда /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет! Я медицинский архив.",
        reply_markup=main_menu()
    )

# Обработка текстовых сообщений
async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Функция в разработке")

# Создаём приложение
app = ApplicationBuilder().token(BOT_TOKEN).build()

# Регистрируем обработчики
app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))

# Запуск
if __name__ == "__main__":
    app.run_polling()
