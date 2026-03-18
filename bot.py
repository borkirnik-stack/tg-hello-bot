import os
from openai import AsyncOpenAI
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

openai_client = AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])

# История разговоров: {user_id: [messages]}
conversations = {}


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conversations[user_id] = []
    await update.message.reply_text("Привет! Я умный бот на основе ChatGPT. Помню наш разговор и отвечаю на русском. Спрашивай что угодно!")


async def chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_message = update.message.text

    if user_id not in conversations:
        conversations[user_id] = []

    conversations[user_id].append({"role": "user", "content": user_message})

    await update.message.chat.send_action("typing")

    response = await openai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "Ты полезный ассистент. Отвечай на русском языке. Помни весь контекст разговора."},
            *conversations[user_id],
        ],
    )

    reply = response.choices[0].message.content
    conversations[user_id].append({"role": "assistant", "content": reply})

    await update.message.reply_text(reply)


async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conversations[user_id] = []
    await update.message.reply_text("История очищена. Начнём заново!")


def main():
    token = os.environ["BOT_TOKEN"]
    app = ApplicationBuilder().token(token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat))

    print("Bot is running...")
    app.run_polling()


if __name__ == "__main__":
    main()
