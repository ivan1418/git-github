# ===================================================
# 🏛️ BOZI-BOT: EL CEREBRO HÍBRIDO ASINCRÓNICO DE ELITE
# Versión: 4.2 (THE FORTRESS - FULL INTEGRATION)
# ===================================================

import os
import logging
import json
import requests
import threading
import time
import asyncio
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler

from telegram import Update, constants
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, CommandHandler, filters
from openai import AsyncOpenAI
from supabase import create_client

# ---------------------------------------------------
# ⚙️ CONFIGURACIÓN Y CLIENTES
# ---------------------------------------------------
logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")

openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

USER_CONFIG = {"model": "gpt-4o"}
CHAT_HISTORY = {}

# ---------------------------------------------------
# 🧠 MEMORIA SEMÁNTICA Y WEB SEARCH
# ---------------------------------------------------

async def save_to_memory(chat_id, user_text, bot_response):
    content = f"Iván: {user_text}\nBozi-bot: {bot_response}"
    try:
        res_emb = await openai_client.embeddings.create(input=content, model="text-embedding-3-small")
        embedding = res_emb.data[0].embedding
        supabase.table("bot_knowledge").insert({
            "chat_id": int(chat_id), "content": content, "embedding": embedding
        }).execute()
    except Exception as e:
        logging.error(f"Error memoria: {e}")

async def get_semantic_memory(chat_id, query):
    try:
        res_emb = await openai_client.embeddings.create(input=query, model="text-embedding-3-small")
        vector = res_emb.data[0].embedding
        res = supabase.rpc("match_knowledge", {
            "query_embedding": vector, "match_threshold": 0.5, "match_count": 2, "p_chat_id": int(chat_id)
        }).execute()
        return "\n\n💡 [MEMORIA]:\n" + "\n".join([d['content'] for d in res.data]) if res.data else ""
    except: return ""

def web_search(query):
    if not TAVILY_API_KEY: return ""
    try:
        url = "https://api.tavily.com/search"
        payload = {"api_key": TAVILY_API_KEY, "query": query, "search_depth": "smart"}
        res = requests.post(url, json=payload, timeout=8).json()
        return "\n\n🌐 [WEB]:\n" + "\n".join([f"- {r['title']}: {r['url']}" for r in res.get("results", [])[:2]])
    except: return ""

# ---------------------------------------------------
# 🚀 ACCIONES (CRUD + PUB REAL)
# ---------------------------------------------------

async def manage_actions(chat_id, text):
    low_text = text.lower()
    # Publicación Real
    if "publicalo" in low_text:
        try:
            res_ia = await openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "system", "content": "Generá un HTML profesional con Tailwind CSS."},
                          {"role": "user", "content": text}]
            )
            html_code = res_ia.choices[0].message.content
            res_db = supabase.table("projects").insert({
                "chat_id": int(chat_id), "content": html_code, "status": "published"
            }).execute()
            p_id = res_db.data[0]['id']
            return f"🚀 **Proyecto Publicado!**\nURL: {os.getenv('RENDER_EXTERNAL_URL', 'https://bozi.render.com')}/view/{p_id}"
        except Exception as e: return f"❌ Error Pub: {e}"

    # Tareas en Lenguaje Natural
    if any(w in low_text for w in ["recordame", "agendá", "mañana"]):
        try:
            res_ia = await openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "system", "content": f"Hoy es {datetime.now()}. Respondé JSON: {{'desc': '', 'date': 'YYYY-MM-DD HH:MM:SS'}}"},
                          {"role": "user", "content": text}],
                response_format={"type": "json_object"}
            )
            data = json.loads(res_ia.choices[0].message.content)
            supabase.table("scheduled_tasks").insert({
                "chat_id": int(chat_id), "description": data['desc'], "scheduled_at": data['date'], "status": "pending"
            }).execute()
            return f"✅ Agendado: {data['desc']} para {data['date']}"
        except: pass
    return None

# ---------------------------------------------------
# 🤖 HANDLERS
# ---------------------------------------------------

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🏛️ Bozi-bot V4.2 Online.\n/tasks, /projects, /status, /config")

async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"🖥️ **Status**: Online\n🧠 **AI**: {USER_CONFIG['model']}\n📊 **DB**: Supabase Connected")

async def tasks_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    res = supabase.table("scheduled_tasks").select("*").eq("chat_id", update.effective_chat.id).eq("status", "pending").execute()
    msg = "\n".join([f"📌 {t['scheduled_at']}: {t['description']}" for t in res.data]) if res.data else "No hay tareas."
    await update.message.reply_text(f"📝 **Tareas:**\n{msg}")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_text = update.message.text
    if not user_text: return

    await context.bot.send_chat_action(chat_id=chat_id, action=constants.ChatAction.TYPING)
    
    action_res = await manage_actions(chat_id, user_text)
    if action_res: return await update.message.reply_text(action_res, parse_mode='Markdown')

    memoria = await get_semantic_memory(chat_id, user_text)
    web = web_search(user_text) if "actual" in user_text else ""
    
    try:
        res = await openai_client.chat.completions.create(
            model=USER_CONFIG["model"],
            messages=[{"role": "system", "content": f"Dialecto: Rosario/Voseo.\n{memoria}{web}"},
                      {"role": "user", "content": user_text}]
        )
        bot_response = res.choices[0].message.content
        await update.message.reply_text(bot_response)
        asyncio.create_task(save_to_memory(chat_id, user_text, bot_response))
    except Exception as e: await update.message.reply_text(f"❌ Error: {e}")

async def task_worker(bot):
    while True:
        try:
            now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            res = supabase.table("scheduled_tasks").select("*").eq("status", "pending").lte("scheduled_at", now).execute()
            for t in res.data:
                await bot.send_message(chat_id=t['chat_id'], text=f"🔔 **RECORDATORIO**: {t['description']}")
                supabase.table("scheduled_tasks").update({"status": "completed"}).eq("id", t['id']).execute()
        except: pass
        await asyncio.sleep(60)

# ---------------------------------------------------
# 🌐 DASHBOARD & VIEW (URL REAL)
# ---------------------------------------------------

class DashboardHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/view/"):
            p_id = self.path.split("/")[-1]
            res = supabase.table("projects").select("content").eq("id", p_id).execute()
            if res.data:
                self.send_response(200); self.send_header("Content-type", "text/html"); self.end_headers()
                self.wfile.write(res.data[0]['content'].encode())
                return
        self.send_response(200); self.end_headers()
        self.wfile.write(b"Bozi-bot 4.2 Live")

# ---------------------------------------------------
# 🚀 MAIN
# ---------------------------------------------------

if __name__ == "__main__":
    # Servidor Web
    port = int(os.environ.get("PORT", 10000))
    threading.Thread(target=lambda: HTTPServer(("0.0.0.0", port), DashboardHandler).serve_forever(), daemon=True).start()

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("tasks", tasks_cmd))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    
    loop = asyncio.get_event_loop()
    loop.create_task(task_worker(app.bot))
    
    logging.info("🚀 V4.2 Online.")
    app.run_polling()
