import os
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters
)

BOT_TOKEN = os.getenv("BOT_TOKEN")
print("BOT_TOKEN: ", BOT_TOKEN)

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

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет! Я медицинский архив.",
        reply_markup=main_menu()
    )

async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Функция в разработке")

app = ApplicationBuilder().token(BOT_TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))

if __name__ == "__main__":
    app.run_polling()
