import os
from openai import AsyncOpenAI
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

openai_client = AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Привет! Я умный бот на основе ChatGPT. Спрашивай что угодно!")


async def chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_message = update.message.text
    await update.message.chat.send_action("typing")

    response = await openai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "Ты полезный ассистент. Отвечай на русском языке."},
            {"role": "user", "content": user_message},
        ],
    )

    reply = response.choices[0].message.content
    await update.message.reply_text(reply)


def main():
    token = os.environ["BOT_TOKEN"]
    app = ApplicationBuilder().token(token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat))

    print("Bot is running...")
    app.run_polling()


if __name__ == "__main__":
    main()
