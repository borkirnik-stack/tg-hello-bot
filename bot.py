import os
import base64
import httpx
from openai import AsyncOpenAI
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

openai_client = AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])
NOTION_TOKEN = os.environ["NOTION_TOKEN"]
NOTION_DB_ID = "8c5db127-9158-4804-a355-302ba8da33f2"
NOTION_HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}

conversations = {}


async def notion_get_tasks() -> str:
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"https://api.notion.com/v1/databases/{NOTION_DB_ID}/query",
            headers=NOTION_HEADERS,
            json={"page_size": 50},
        )
    data = resp.json()
    tasks = []
    for r in data.get("results", []):
        props = r.get("properties", {})
        for val in props.values():
            if val.get("type") == "title":
                title = val.get("title", [])
                name = title[0].get("plain_text", "").strip() if title else ""
                if name and not name[0].isdigit():
                    status_prop = props.get("Status", props.get("Статус", {}))
                    st = ""
                    if status_prop.get("type") == "status" and status_prop.get("status"):
                        st = status_prop["status"].get("name", "")
                    elif status_prop.get("type") == "select" and status_prop.get("select"):
                        st = status_prop["select"].get("name", "")
                    tasks.append(f"• {name}" + (f" [{st}]" if st else ""))
    return "\n".join(tasks) if tasks else "Задач не найдено."


async def notion_add_task(title: str) -> bool:
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://api.notion.com/v1/pages",
            headers=NOTION_HEADERS,
            json={
                "parent": {"database_id": NOTION_DB_ID},
                "properties": {
                    "Name": {"title": [{"text": {"content": title}}]},
                },
            },
        )
    return resp.status_code == 200


async def tasks_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.chat.send_action("typing")
    text = await notion_get_tasks()
    await update.message.reply_text(f"📋 Твои задачи:\n\n{text}")


async def add_task_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    title = " ".join(context.args)
    if not title:
        await update.message.reply_text("Напиши задачу: /add Купить молоко")
        return
    ok = await notion_add_task(title)
    if ok:
        await update.message.reply_text(f"✅ Задача добавлена: {title}")
    else:
        await update.message.reply_text("Ошибка при добавлении задачи.")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conversations[user_id] = []
    await update.message.reply_text(
        "Привет! Я умный бот на основе ChatGPT.\n\n"
        "🤖 Отвечаю на вопросы, помню разговор, читаю картинки\n"
        "📋 /tasks — показать задачи из Notion\n"
        "➕ /add <задача> — добавить задачу в Notion\n"
        "🔄 /reset — сбросить историю чата"
    )


async def chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if user_id not in conversations:
        conversations[user_id] = []

    await update.message.chat.send_action("typing")

    if update.message.photo:
        photo = update.message.photo[-1]
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
    app.add_handler(CommandHandler("tasks", tasks_command))
    app.add_handler(CommandHandler("add", add_task_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat))
    app.add_handler(MessageHandler(filters.PHOTO, chat))

    print("Bot is running...")
    app.run_polling()


if __name__ == "__main__":
    main()
