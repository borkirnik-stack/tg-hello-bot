import os
import base64
from openai import AsyncOpenAI
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

openai_client = AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])

# История разговоров: {user_id: [messages]}
conversations = {}


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conversations[user_id] = []
    await update.message.reply_text("Привет! Я умный бот на основе ChatGPT. Помню наш разговор, отвечаю на русском и умею читать картинки. Спрашивай что угодно!")


async def chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if user_id not in conversations:
        conversations[user_id] = []

    await update.message.chat.send_action("typing")

    # Обработка картинки
    if update.message.photo:
        photo = update.message.photo[-1]  # самое большое фото
        file = await context.bot.get_file(photo.file_id)
        file_bytes = await file.download_as_bytearray()
        image_b64 = base64.b64encode(file_bytes).decode("utf-8")

        caption = update.message.caption or "Что на этой картинке?"

        content = [
            {"type": "text", "text": caption},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
        ]
        conversations[user_id].append({"role": "user", "content": content})
    else:
        user_message = update.message.text
        conversations[user_id].append({"role": "user", "content": user_message})

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
    app.add_handler(MessageHandler(filters.PHOTO, chat))

    print("Bot is running...")
    app.run_polling()


if __name__ == "__main__":
    main()
