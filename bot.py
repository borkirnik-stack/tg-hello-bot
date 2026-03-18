import os
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Привет!")


async def hello(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Привет!")


def main():
    token = os.environ["BOT_TOKEN"]
    app = ApplicationBuilder().token(token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, hello))

    print("Bot is running...")
    app.run_polling()


if __name__ == "__main__":
    main()
