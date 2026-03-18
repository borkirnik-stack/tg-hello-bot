import os
import base64
import json
import httpx
from openai import AsyncOpenAI
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler

openai_client = AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])
NOTION_TOKEN = os.environ["NOTION_TOKEN"]
NOTION_DB_ID = "8c5db127-9158-4804-a355-302ba8da33f2"
NOTION_USER_ID = "6a8b00b8-c9e8-41c3-bcca-9ba4e2223ee9"
NOTION_HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}

conversations = {}
WAITING_TASK = 1

MAIN_MENU = ReplyKeyboardMarkup(
    [[KeyboardButton("📋 Мои задачи"), KeyboardButton("➕ Добавить задачу")],
     [KeyboardButton("🔄 Сбросить чат")]],
    resize_keyboard=True,
)

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_tasks",
            "description": "Получить список задач из Notion",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_task",
            "description": "Добавить новую задачу в Notion",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Название задачи"},
                },
                "required": ["title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_task",
            "description": "Найти задачу в Notion по названию и получить ссылку на неё",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Название задачи или часть названия"},
                },
                "required": ["title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "assign_task",
            "description": "Назначить пользователя ответственным за задачу в Notion",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Название задачи или часть названия"},
                },
                "required": ["title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_task_status",
            "description": "Обновить статус задачи в Notion",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Название задачи (или часть названия)"},
                    "status": {"type": "string", "description": "Новый статус: 'Делается', 'Готово', 'Отмена'"},
                },
                "required": ["title", "status"],
            },
        },
    },
]


async def notion_get_tasks() -> list:
    tasks = []
    cursor = None
    async with httpx.AsyncClient() as client:
        while True:
            body = {"page_size": 100}
            if cursor:
                body["start_cursor"] = cursor
            resp = await client.post(
                f"https://api.notion.com/v1/databases/{NOTION_DB_ID}/query",
                headers=NOTION_HEADERS,
                json=body,
            )
            data = resp.json()
            for r in data.get("results", []):
                props = r.get("properties", {})
                for val in props.values():
                    if val.get("type") == "title":
                        title_arr = val.get("title", [])
                        name = title_arr[0].get("plain_text", "").strip() if title_arr else ""
                        if name and not name[0].isdigit():
                            status_prop = props.get("Status", props.get("Статус", {}))
                            st = ""
                            if status_prop.get("type") == "status" and status_prop.get("status"):
                                st = status_prop["status"].get("name", "")
                            elif status_prop.get("type") == "select" and status_prop.get("select"):
                                st = status_prop["select"].get("name", "")
                            tasks.append({"id": r["id"], "title": name, "status": st})
            if data.get("has_more"):
                cursor = data.get("next_cursor")
            else:
                break
    return tasks


async def notion_add_task(title: str) -> str | None:
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://api.notion.com/v1/pages",
            headers=NOTION_HEADERS,
            json={
                "parent": {"database_id": NOTION_DB_ID},
                "properties": {
                    "Название": {"title": [{"text": {"content": title}}]},
                },
            },
        )
    if resp.status_code == 200:
        page_id = resp.json().get("id", "").replace("-", "")
        return f"https://notion.so/{page_id}"
    return None


async def notion_update_status(title_query: str, status: str) -> str:
    tasks = await notion_get_tasks()
    matched = [t for t in tasks if title_query.lower() in t["title"].lower()]
    if not matched:
        return f"Задача '{title_query}' не найдена."
    task = matched[0]
    async with httpx.AsyncClient() as client:
        resp = await client.patch(
            f"https://api.notion.com/v1/pages/{task['id']}",
            headers=NOTION_HEADERS,
            json={
                "properties": {
                    "Status": {"status": {"name": status}},
                }
            },
        )
    if resp.status_code == 200:
        return f"Статус задачи '{task['title']}' обновлён на '{status}'."
    return "Ошибка при обновлении статуса."


async def notion_assign_task(title_query: str) -> str:
    tasks = await notion_get_tasks()
    matched = [t for t in tasks if title_query.lower() in t["title"].lower()]
    if not matched:
        return f"Задача '{title_query}' не найдена."
    task = matched[0]
    async with httpx.AsyncClient() as client:
        resp = await client.patch(
            f"https://api.notion.com/v1/pages/{task['id']}",
            headers=NOTION_HEADERS,
            json={"properties": {"Ответственный": {"people": [{"id": NOTION_USER_ID}]}}},
        )
    if resp.status_code == 200:
        return f"Кирилл назначен ответственным за задачу '{task['title']}'."
    return "Ошибка при назначении ответственного."


async def run_tool(name: str, args: dict) -> str:
    if name == "find_task":
        tasks = await notion_get_tasks()
        query = args["title"].lower()
        matched = [t for t in tasks if query in t["title"].lower()]
        if not matched:
            return f"Задача '{args['title']}' не найдена в Notion."
        lines = [f"• {t['title']}" + (f" [{t['status']}]" if t["status"] else "") + f"\n  🔗 https://notion.so/{t['id'].replace('-', '')}" for t in matched]
        return "\n".join(lines)
    if name == "get_tasks":
        tasks = await notion_get_tasks()
        if not tasks:
            return "Задач не найдено."
        db_url = f"https://notion.so/{NOTION_DB_ID.replace('-', '')}"
        lines = [f"• {t['title']}" + (f" [{t['status']}]" if t["status"] else "") + f" — https://notion.so/{t['id'].replace('-', '')}" for t in tasks]
        return "\n".join(lines) + f"\n\n📂 База данных: {db_url}"
    elif name == "add_task":
        url = await notion_add_task(args["title"])
        return f"Задача '{args['title']}' добавлена в Notion.\n🔗 {url}" if url else "Ошибка при добавлении задачи."
    elif name == "assign_task":
        return await notion_assign_task(args["title"])
    elif name == "update_task_status":
        return await notion_update_status(args["title"], args["status"])
    return "Неизвестная функция."


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conversations[user_id] = []
    await update.message.reply_text(
        "Привет! Я умный бот. Просто пиши что нужно — я сам разберусь.\n\n"
        "Например: «занеси задачу купить молоко» или «покажи мои задачи»",
        reply_markup=MAIN_MENU,
    )


async def chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text if update.message.text else ""

    if user_id not in conversations:
        conversations[user_id] = []

    if text == "📋 Мои задачи":
        await update.message.chat.send_action("typing")
        tasks = await notion_get_tasks()
        result = "\n".join(f"• {t['title']}" + (f" [{t['status']}]" if t["status"] else "") for t in tasks) if tasks else "Задач не найдено."
        await update.message.reply_text(f"📋 Твои задачи:\n\n{result}", reply_markup=MAIN_MENU)
        return

    if text == "🔄 Сбросить чат":
        conversations[user_id] = []
        await update.message.reply_text("История очищена.", reply_markup=MAIN_MENU)
        return

    thinking_msg = await update.message.reply_text("⏳")

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
        conversations[user_id].append({"role": "user", "content": text})

    response = await openai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": (
                "Ты полезный ассистент. Отвечай на русском языке. Помни весь контекст разговора. "
                "У тебя есть доступ к Notion пользователя — ты можешь читать задачи, добавлять новые и менять их статус. "
                "Если пользователь просит что-то сделать с задачами — используй соответствующие функции."
            )},
            *conversations[user_id],
        ],
        tools=TOOLS,
        tool_choice="auto",
    )

    msg = response.choices[0].message

    # Если GPT хочет вызвать функцию
    if msg.tool_calls:
        tool_results = []
        for tc in msg.tool_calls:
            args = json.loads(tc.function.arguments)
            result = await run_tool(tc.function.name, args)
            tool_results.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result,
            })

        conversations[user_id].append(msg)
        conversations[user_id].extend(tool_results)

        final = await openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Ты полезный ассистент. Отвечай на русском языке."},
                *conversations[user_id],
            ],
        )
        reply = final.choices[0].message.content
        conversations[user_id].append({"role": "assistant", "content": reply})
    else:
        reply = msg.content
        conversations[user_id].append({"role": "assistant", "content": reply})

    await thinking_msg.edit_text(reply, reply_markup=MAIN_MENU)


async def add_task_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Напиши задачу, которую добавить в Notion:")
    return WAITING_TASK


async def add_task_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    title = update.message.text.strip()
    ok = await notion_add_task(title)
    if ok:
        await update.message.reply_text(f"✅ Задача добавлена: {title}", reply_markup=MAIN_MENU)
    else:
        await update.message.reply_text("Ошибка при добавлении.", reply_markup=MAIN_MENU)
    return ConversationHandler.END


async def add_task_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Отмена.", reply_markup=MAIN_MENU)
    return ConversationHandler.END


def main():
    token = os.environ["BOT_TOKEN"]
    app = ApplicationBuilder().token(token).build()

    add_task_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^➕ Добавить задачу$"), add_task_start)],
        states={
            WAITING_TASK: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_task_save)],
        },
        fallbacks=[CommandHandler("cancel", add_task_cancel)],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(add_task_conv)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat))
    app.add_handler(MessageHandler(filters.PHOTO, chat))

    print("Bot is running...")
    app.run_polling()


if __name__ == "__main__":
    main()
