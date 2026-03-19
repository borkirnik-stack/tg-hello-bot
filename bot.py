import os
import base64
import json
import time
import threading
import httpx
import uvicorn
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from openai import AsyncOpenAI
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler

web_app = FastAPI()
web_app.mount("/static", StaticFiles(directory="webapp"), name="static")

@web_app.get("/")
async def serve_index():
    return FileResponse("webapp/index.html")

@web_app.get("/chat")
async def serve_chat():
    return FileResponse("webapp/chat.html")

@web_app.post("/api/neurolina")
async def neurolina_chat(request: Request):
    body = await request.json()
    messages = body.get("messages", [])
    system = (
        "Ты Нейролина — умная, дружелюбная и немного ироничная девушка-ассистент "
        "видеопродакшн студии KINEMOTOR PRODUCTION (Москва). "
        "Помогаешь клиентам и команде: брифование, стоимость съёмок, этапы производства, "
        "рекламные ролики, корпоративные фильмы, music video, моушн-графика. "
        "Студия: kinemotor.pro · почта: go@kinemotor.pro · бриф: kinemotor.pro/brief/. "
        "Отвечай коротко, живо и по делу. Всегда на русском. "
        "Если не знаешь точную цену — предложи заполнить бриф."
    )
    response = await openai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "system", "content": system}, *messages],
    )
    return {"reply": response.choices[0].message.content}

openai_client = AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])
NOTION_TOKEN = os.environ["NOTION_TOKEN"]
NOTION_DB_ID = "8c5db127-9158-4804-a355-302ba8da33f2"
PROJECTS_DB_ID = "f76d34df-10da-433d-ab12-68b9d8624d07"
NOTION_ROOT_PAGE_ID = "f273c3c162c24d72922a5fa8251a8303"
NOTION_USER_ID = "6a8b00b8-c9e8-41c3-bcca-9ba4e2223ee9"
NOTION_HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}

NOTION_SECTIONS = {
    "newbiz": "c09cbafe-666f-4986-b052-d97aae4cb60a",
    "нью биз": "c09cbafe-666f-4986-b052-d97aae4cb60a",
    "ньюбиз": "c09cbafe-666f-4986-b052-d97aae4cb60a",
    "продакшн": "9cecff83-7e49-4f54-a5eb-0b3ca89766b5",
    "production": "9cecff83-7e49-4f54-a5eb-0b3ca89766b5",
    "финанс": "057ba715-c30b-4fa3-b375-a5b9935f2f4f",  # финансы/финансах/финансов
    "hr": "cbde043e-2aad-4e20-a7ac-9b0e3f16a6b1",
    "управлени": "0c13ad32-6d3e-46be-83b4-fd22a5b63a27",  # управление/управлении
    "crm": "71a73c06-4a49-451d-abca-fe3e34078227",
    "срм": "71a73c06-4a49-451d-abca-fe3e34078227",
    "проект": "4dd52333-9829-4f10-8fb4-14d49e644005",   # проекты/проектах/проекта
    "задач": "d9014f76-e13d-4a0c-9958-f5dc3d11405f",    # задачи/задачах/задач
    "оплат": "75a22cfb-9371-4e38-9896-5003d6b69a1b",    # оплаты/оплатах
    "поступлени": "f503e4b8-1489-422e-972a-353d331b3917",
    "трат": "f503e4b8-1489-422e-972a-353d331b3917",
    "портфоли": "186bf5c1-9108-80d0-bc66-ff069000926e", # портфолио/портфолиo
    "баз": "9c33eadf-421b-46a8-9528-76d50b0cc182",      # база/базе/базу знаний
    "знани": "9c33eadf-421b-46a8-9528-76d50b0cc182",    # знания/знаниях/знаний
    "оргсхем": "36809ee1-9d98-4d3e-a9ed-f30d0c1b1dec",
    "стратеги": "996deae7-9b3f-4645-842a-2a6ade9e60fb", # стратегия/стратегии
    "pr": "246bf5c1-9108-8065-9926-d0a0ae7a870f",
    "пиар": "246bf5c1-9108-8065-9926-d0a0ae7a870f",
    "архив": "63900bcf-e088-4a28-9f92-fea1437e5819",
}

def detect_notion_section(text: str) -> str | None:
    """Возвращает ID Notion-страницы если в тексте упоминается раздел воркспейса."""
    tl = text.lower()
    for keyword, page_id in NOTION_SECTIONS.items():
        if keyword in tl:
            return page_id
    return None

conversations = {}
WAITING_TASK = 1
_tasks_cache: list = []
_tasks_cache_time: float = 0
CACHE_TTL = 60  # секунд

def build_main_menu() -> ReplyKeyboardMarkup:
    webapp_url = os.environ.get("WEBAPP_URL", "")
    rows = [
        [KeyboardButton("📋 Мои задачи"), KeyboardButton("➕ Добавить задачу")],
        [KeyboardButton("🔄 Сбросить чат")],
    ]
    if webapp_url:
        rows.append([KeyboardButton("✦ Открыть приложение", web_app=WebAppInfo(url=webapp_url))])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)

MAIN_MENU = build_main_menu()

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
    {
        "type": "function",
        "function": {
            "name": "search_notion",
            "description": "Поиск по всему Notion — страницы, базы данных, заметки. Использовать когда пользователь ищет что-то конкретное или хочет найти страницу.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Поисковый запрос"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_databases",
            "description": "Показать все базы данных в Notion к которым есть доступ",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_page_content",
            "description": "Прочитать содержимое конкретной страницы Notion по её ID или URL",
            "parameters": {
                "type": "object",
                "properties": {
                    "page_id": {"type": "string", "description": "ID страницы Notion (из URL или из результатов поиска)"},
                },
                "required": ["page_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_project",
            "description": "Занести новый проект в базу данных Проекты KINEMOTOR. Использовать когда пользователь говорит 'занеси проект', 'добавь проект', 'новый проект'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Название проекта"},
                    "status": {"type": "string", "description": "Статус: 'Лиды / брифинг', 'Взято в работу / Концепция / Поиск интеграции', 'Производство' и др. По умолчанию — 'Лиды / брифинг'"},
                    "budget": {"type": "number", "description": "Бюджет проекта в рублях (если известен)"},
                    "source": {"type": "string", "description": "Откуда проект: 'От кирилла', 'Коммерция первичный', 'Коммерция повторка', 'Ньюбиз первичный' и др."},
                    "producer": {"type": "string", "description": "Продюсер: 'Забирова', 'Зотов', 'Борисов', 'Капитонов' и др."},
                    "responsible": {"type": "array", "items": {"type": "string"}, "description": "Ответственные сотрудники"},
                    "start_date": {"type": "string", "description": "Дата старта работы в формате YYYY-MM-DD"},
                    "deadline": {"type": "string", "description": "Дедлайн подачи в формате YYYY-MM-DD"},
                    "notes": {"type": "string", "description": "Доп. информация по проекту"},
                },
                "required": ["name"],
            },
        },
    },
]


async def notion_get_tasks() -> list:
    global _tasks_cache, _tasks_cache_time
    if _tasks_cache and time.time() - _tasks_cache_time < CACHE_TTL:
        return _tasks_cache
    tasks = []
    cursor = None
    async with httpx.AsyncClient(timeout=30) as client:
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
    _tasks_cache = tasks
    _tasks_cache_time = time.time()
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


async def notion_search(query: str) -> str:
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            "https://api.notion.com/v1/search",
            headers=NOTION_HEADERS,
            json={"query": query, "page_size": 20},
        )
    data = resp.json()
    results = data.get("results", [])
    if not results:
        return f"Ничего не найдено по запросу '{query}'."
    lines = []
    for r in results:
        obj_type = r.get("object", "")
        title = ""
        if obj_type == "page":
            props = r.get("properties", {})
            for val in props.values():
                if val.get("type") == "title":
                    arr = val.get("title", [])
                    title = arr[0].get("plain_text", "").strip() if arr else ""
                    break
            if not title:
                title_obj = r.get("title", [])
                title = title_obj[0].get("plain_text", "Без названия").strip() if title_obj else "Без названия"
            page_id = r["id"].replace("-", "")
            lines.append(f"📄 {title}\n   🔗 https://notion.so/{page_id}")
        elif obj_type == "database":
            title_arr = r.get("title", [])
            title = title_arr[0].get("plain_text", "Без названия").strip() if title_arr else "Без названия"
            db_id = r["id"].replace("-", "")
            lines.append(f"🗃 {title} (база данных)\n   🔗 https://notion.so/{db_id}")
    return "\n\n".join(lines)


async def notion_list_databases() -> str:
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            "https://api.notion.com/v1/search",
            headers=NOTION_HEADERS,
            json={"filter": {"value": "database", "property": "object"}, "page_size": 50},
        )
    data = resp.json()
    results = data.get("results", [])
    if not results:
        return "Базы данных не найдены."
    lines = []
    for r in results:
        title_arr = r.get("title", [])
        title = title_arr[0].get("plain_text", "Без названия").strip() if title_arr else "Без названия"
        db_id = r["id"].replace("-", "")
        lines.append(f"🗃 {title}\n   🔗 https://notion.so/{db_id}")
    return f"Базы данных в Notion ({len(lines)}):\n\n" + "\n\n".join(lines)


async def notion_get_page_content(page_id: str) -> str:
    # Очищаем ID от URL и дефисов
    page_id = page_id.strip()
    if "notion.so/" in page_id:
        page_id = page_id.split("notion.so/")[-1].split("?")[0].split("#")[0]
        # убираем имя пользователя если есть (slug-XXXXXXX)
        if "-" in page_id and len(page_id.replace("-", "")) == 32:
            page_id = page_id  # уже с дефисами
        elif len(page_id) > 32:
            page_id = page_id[-32:]
    page_id = page_id.replace("-", "")
    # Форматируем как UUID
    if len(page_id) == 32:
        page_id = f"{page_id[:8]}-{page_id[8:12]}-{page_id[12:16]}-{page_id[16:20]}-{page_id[20:]}"

    async with httpx.AsyncClient(timeout=30) as client:
        # Получаем блоки страницы
        resp = await client.get(
            f"https://api.notion.com/v1/blocks/{page_id}/children?page_size=50",
            headers=NOTION_HEADERS,
        )
    if resp.status_code != 200:
        return f"Ошибка при чтении страницы: {resp.status_code}"
    blocks = resp.json().get("results", [])
    if not blocks:
        return "Страница пустая или нет доступа к содержимому."

    def extract_text(rich_text):
        return "".join(rt.get("plain_text", "") for rt in rich_text).strip()

    async def parse_blocks(block_list, indent=""):
        result = []
        for b in block_list:
            btype = b.get("type", "")
            bd = b.get(btype, {})
            text = extract_text(bd.get("rich_text", []))
            if btype in ("paragraph", "quote"):
                if text:
                    result.append(indent + text)
            elif btype.startswith("heading_"):
                if text:
                    prefix = "#" * int(btype[-1])
                    result.append(indent + f"{prefix} {text}")
            elif btype == "callout":
                icon = bd.get("icon", {})
                emoji = icon.get("emoji", "💡") if icon else "💡"
                if text:
                    result.append(indent + f"{emoji} {text}")
            elif btype == "bulleted_list_item":
                if text:
                    result.append(indent + f"• {text}")
            elif btype == "numbered_list_item":
                if text:
                    result.append(indent + f"— {text}")
            elif btype == "to_do":
                checked = bd.get("checked", False)
                if text:
                    result.append(indent + f"{'✅' if checked else '☐'} {text}")
            elif btype == "divider":
                result.append("---")
            elif btype == "child_page":
                title = bd.get("title", "Без названия")
                child_id = b["id"].replace("-", "")
                result.append(indent + f"📄 {title}\n   🔗 https://notion.so/{child_id}")
            elif btype == "child_database":
                title = bd.get("title", "Без названия")
                child_id = b["id"].replace("-", "")
                result.append(indent + f"🗃 {title}\n   🔗 https://notion.so/{child_id}")
            elif btype == "link_to_page":
                linked = bd.get("page_id") or bd.get("database_id", "")
                linked_id = linked.replace("-", "")
                result.append(indent + f"🔗 https://notion.so/{linked_id}")
            elif btype in ("column_list", "column", "synced_block"):
                try:
                    async with httpx.AsyncClient(timeout=10) as c2:
                        r2 = await c2.get(
                            f"https://api.notion.com/v1/blocks/{b['id']}/children?page_size=50",
                            headers=NOTION_HEADERS,
                        )
                    if r2.status_code == 200:
                        inner = r2.json().get("results", [])
                        result.extend(await parse_blocks(inner, indent))
                except Exception:
                    pass  # недоступный блок — пропускаем
            elif btype == "table":
                result.append(indent + "[таблица]")
        return result

    lines = await parse_blocks(blocks)

    content = "\n".join(lines) if lines else ""

    # Читаем комментарии к странице
    async with httpx.AsyncClient(timeout=30) as client:
        cresp = await client.get(
            f"https://api.notion.com/v1/comments?block_id={page_id}",
            headers=NOTION_HEADERS,
        )
    if cresp.status_code == 200:
        comments = cresp.json().get("results", [])
        if comments:
            comment_lines = ["💬 Комментарии:"]
            for c in comments:
                rich = c.get("rich_text", [])
                text = "".join(rt.get("plain_text", "") for rt in rich).strip()
                created = c.get("created_time", "")[:10]
                author = c.get("created_by", {}).get("id", "")
                if text:
                    comment_lines.append(f"[{created}] {text}")
                # Читаем ответы на комментарий
                disc_id = c.get("discussion_id", "")
                if disc_id:
                    async with httpx.AsyncClient(timeout=30) as client2:
                        dresp = await client2.get(
                            f"https://api.notion.com/v1/comments?block_id={page_id}&discussion_id={disc_id}",
                            headers=NOTION_HEADERS,
                        )
                    if dresp.status_code == 200:
                        replies = [r for r in dresp.json().get("results", []) if r["id"] != c["id"]]
                        for r in replies:
                            rrich = r.get("rich_text", [])
                            rtext = "".join(rt.get("plain_text", "") for rt in rrich).strip()
                            rdate = r.get("created_time", "")[:10]
                            if rtext:
                                comment_lines.append(f"  ↳ [{rdate}] {rtext}")
            content = (content + "\n\n" if content else "") + "\n".join(comment_lines)

    return content if content else "Страница пустая."


async def notion_create_project(args: dict) -> str:
    props = {
        "Проекты": {"title": [{"text": {"content": args["name"]}}]},
        "Статус": {"status": {"name": args.get("status", "Лиды / брифинг")}},
    }
    if args.get("budget"):
        props["Бюджет проекта"] = {"number": args["budget"]}
    if args.get("source"):
        props["Откуда проект"] = {"select": {"name": args["source"]}}
    if args.get("producer"):
        props["Продюсер"] = {"select": {"name": args["producer"]}}
    if args.get("responsible"):
        props["Ответственный"] = {"multi_select": [{"name": r} for r in args["responsible"]]}
    if args.get("start_date"):
        props["Старт работы"] = {"date": {"start": args["start_date"]}}
    if args.get("deadline"):
        props["Дедлайн подачи"] = {"date": {"start": args["deadline"]}}
    if args.get("notes"):
        props["Доп. информация // От тендеровика"] = {"rich_text": [{"text": {"content": args["notes"]}}]}

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            "https://api.notion.com/v1/pages",
            headers=NOTION_HEADERS,
            json={"parent": {"database_id": PROJECTS_DB_ID}, "properties": props},
        )
    if resp.status_code == 200:
        page_id = resp.json().get("id", "").replace("-", "")
        return f"✅ Проект «{args['name']}» занесён в базу.\n🔗 https://notion.so/{page_id}"
    return f"Ошибка при создании проекта: {resp.status_code} {resp.text[:200]}"


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
        # Показываем только активные задачи (со статусом), либо последние 30
        active = [t for t in tasks if t["status"] and t["status"] not in ("Отмена",)]
        show = active[:30] if active else tasks[:30]
        db_url = f"https://notion.so/{NOTION_DB_ID.replace('-', '')}"
        lines = [f"• {t['title']}" + (f" [{t['status']}]" if t["status"] else "") for t in show]
        return "\n".join(lines) + f"\n\nВсего задач: {len(tasks)}\n📂 {db_url}"
    elif name == "add_task":
        url = await notion_add_task(args["title"])
        return f"Задача '{args['title']}' добавлена в Notion.\n🔗 {url}" if url else "Ошибка при добавлении задачи."
    elif name == "assign_task":
        return await notion_assign_task(args["title"])
    elif name == "update_task_status":
        return await notion_update_status(args["title"], args["status"])
    elif name == "search_notion":
        return await notion_search(args["query"])
    elif name == "list_databases":
        return await notion_list_databases()
    elif name == "get_page_content":
        return await notion_get_page_content(args["page_id"])
    elif name == "create_project":
        return await notion_create_project(args)
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

    try:
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
            # Авто-подгрузка Notion раздела если упоминается в сообщении
            user_msg = text
            section_id = detect_notion_section(text) if text else None
            if section_id:
                try:
                    notion_data = await notion_get_page_content(section_id)
                    if notion_data and not notion_data.startswith("Ошибка") and notion_data != "Страница пустая.":
                        user_msg = f"{text}\n\n📋 [Данные из Notion]\n{notion_data}"
                except Exception:
                    pass
            conversations[user_id].append({"role": "user", "content": user_msg})

        response = await openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": (
                    "Ты полезный ассистент Кирилла в компании KINEMÓTOR PRODUCTION (видеопродакшн, Москва). "
                    "Отвечай на русском языке. Помни весь контекст разговора. "
                    "У тебя есть ПОЛНЫЙ доступ к Notion воркспейса KINEMÓTOR. "
                    "Корневая страница воркспейса: f273c3c162c24d72922a5fa8251a8303. "
                    "Структура воркспейса (основные разделы и их ID):\n"
                    "- NewBiz: c09cbafe-666f-4986-b052-d97aae4cb60a\n"
                    "- Продакшн: 9cecff83-7e49-4f54-a5eb-0b3ca89766b5\n"
                    "- Финансы: 057ba715-c30b-4fa3-b375-a5b9935f2f4f\n"
                    "- HR: cbde043e-2aad-4e20-a7ac-9b0e3f16a6b1\n"
                    "- Управление: 0c13ad32-6d3e-46be-83b4-fd22a5b63a27\n"
                    "- CRM: 71a73c06-4a49-451d-abca-fe3e34078227\n"
                    "- Проекты КМ (страница): 4dd52333-9829-4f10-8fb4-14d49e644005\n"
                    "- База проектов (БД): f76d34df-10da-433d-ab12-68b9d8624d07\n"
                    "- Задачи и проверочные списки: d9014f76-e13d-4a0c-9958-f5dc3d11405f\n"
                    "- Оплаты: 75a22cfb-9371-4e38-9896-5003d6b69a1b\n"
                    "- Поступления и траты: f503e4b8-1489-422e-972a-353d331b3917\n"
                    "- Портфолио: 186bf5c1-9108-80d0-bc66-ff069000926e\n"
                    "- База знаний: 9c33eadf-421b-46a8-9528-76d50b0cc182\n"
                    "- Оргсхема: 36809ee1-9d98-4d3e-a9ed-f30d0c1b1dec\n"
                    "- Стратегия: 996deae7-9b3f-4645-842a-2a6ade9e60fb\n"
                    "- PR: 246bf5c1-9108-8065-9926-d0a0ae7a870f\n"
                    "- Архив: 63900bcf-e088-4a28-9f92-fea1437e5819\n"
                    "ВАЖНО: когда пользователь спрашивает про любой раздел — CRM, Финансы, HR, Продакшн, NewBiz и т.д. — "
                    "ТЫ ОБЯЗАН вызвать get_page_content с ID из списка выше. НИКОГДА не отвечай по памяти. "
                    "Если пользователь говорит 'занеси проект', 'добавь проект', 'новый проект' — используй create_project. "
                    "Спроси только то чего точно нет в сообщении (минимум вопросов). Название обязательно, остальное опционально."
                )},
                *conversations[user_id],
            ],
            tools=TOOLS,
            tool_choice="auto",
        )

        msg = response.choices[0].message

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

        await thinking_msg.edit_text(reply)

    except Exception as e:
        import traceback
        traceback.print_exc()
        try:
            await thinking_msg.edit_text(f"Ошибка: {str(e)[:300]}")
        except Exception as e2:
            print(f"Failed to edit thinking_msg: {e2}")
            await update.message.reply_text(f"Ошибка: {str(e)[:300]}")


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


async def preload_cache(app):
    print("Preloading Notion tasks cache...")
    await notion_get_tasks()
    print(f"Cache loaded: {len(_tasks_cache)} tasks")


def main():
    token = os.environ["BOT_TOKEN"]
    app = ApplicationBuilder().token(token).post_init(preload_cache).build()

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

    # Запускаем веб-сервер в отдельном потоке
    port = int(os.environ.get("PORT", 8080))
    web_thread = threading.Thread(
        target=lambda: uvicorn.run(web_app, host="0.0.0.0", port=port, log_level="warning"),
        daemon=True,
    )
    web_thread.start()
    print(f"Web server started on port {port}")

    print("Bot is running...")
    app.run_polling()


if __name__ == "__main__":
    main()
