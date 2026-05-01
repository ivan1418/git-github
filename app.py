# ===================================================
# 🏛️ BOZI-BOT: EL CEREBRO HÍBRIDO ASINCRÓNICO DE ELITE
# Versión: 3.9.2 (DEPLOY FIX + HTML REAL + PERSISTENCE)
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
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)
openrouter_client = AsyncOpenAI(base_url="https://openrouter.ai/api/v1", api_key=OPENROUTER_API_KEY)
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

USER_CONFIG = {"model": "gpt-4o"} 

# ---------------------------------------------------
# 🛠️ FUNCIONES DE INFRAESTRUCTURA (DEFINIDAS PRIMERO)
# ---------------------------------------------------

def get_file_content(filepath, default=""):
    try:
        if os.path.exists(filepath):
            with open(filepath, 'r', encoding='utf-8') as f: return f.read().strip()
        return default
    except: return default

async def task_worker(bot):
    """Revisa tareas programadas cada minuto"""
    while True:
        try:
            now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            res = supabase.table("scheduled_tasks").select("*").eq("status", "pending").lte("scheduled_at", now).execute()
            for t in res.data:
                await bot.send_message(chat_id=t['chat_id'], text=f"🔔 **RECORDATORIO**: {t['description']}")
                supabase.table("scheduled_tasks").update({"status": "completed"}).eq("id", t['id']).execute()
        except Exception as e:
            logging.error(f"⚠️ Error worker: {e}")
        await asyncio.sleep(60)

async def save_interaction_to_memory(chat_id, user_text, bot_response):
    """Aprendizaje continuo con embeddings"""
    content = f"Iván: {user_text}\nBozi-bot: {bot_response}"
    try:
        res_emb = await openai_client.embeddings.create(input=content, model="text-embedding-3-small")
        embedding = res_emb.data[0].embedding
        supabase.table("bot_knowledge").insert({
            "chat_id": int(chat_id), "content": content, "embedding": embedding
        }).execute()
    except Exception as e:
        logging.error(f"❌ Error memoria: {e}")

# ---------------------------------------------------
# 🚀 ACCIONES: PUBLICACIÓN REAL (HTML)
# ---------------------------------------------------

async def publish_project_content(chat_id, user_text):
    if "publicalo" not in user_text.lower(): return None
    try:
        res = await openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": "Generá HTML5 profesional con Tailwind CDN."},
                      {"role": "user", "content": f"Proyecto: {user_text}"}]
        )
        html_code = res.choices[0].message.content
        res_db = supabase.table("projects").insert({
            "chat_id": int(chat_id), "content": html_code, "status": "published"
        }).execute()
        return f"🚀 **Publicado!** ID: {res_db.data[0]['id']}\nCódigo guardado en la columna 'content'."
    except Exception as e:
        return f"❌ Error: {e}"

# ---------------------------------------------------
# 🤖 HANDLERS DE TELEGRAM
# ---------------------------------------------------

async def model_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.args and context.args[0] in ["gpt-4o", "gpt-4o-mini"]:
        USER_CONFIG["model"] = context.args[0]
        await update.message.reply_text(f"✅ Modelo: {USER_CONFIG['model']}")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_text = update.message.text
    if not user_text: return

    await context.bot.send_chat_action(chat_id=chat_id, action=constants.ChatAction.TYPING)

    # 1. Acción de publicación
    pub_res = await publish_project_content(chat_id, user_text)
    if pub_res:
        return await update.message.reply_text(pub_res)

    # 2. Memoria y Generación
    rules = get_file_content("rules.txt")
    self_info = get_file_content("self.txt")
    
    try:
        res = await openai_client.chat.completions.create(
            model=USER_CONFIG["model"],
            messages=[{"role": "system", "content": f"{self_info}\n\n{rules}"}, {"role": "user", "content": user_text}]
        )
        bot_response = res.choices[0].message.content
        await update.message.reply_text(bot_response)
        await save_interaction_to_memory(chat_id, user_text, bot_response)
    except Exception as e:
        await update.message.reply_text(f"❌ Fallo técnico: {e}")

# ---------------------------------------------------
# 🌐 INFRAESTRUCTURA (RENDER)
# ---------------------------------------------------

class DashboardHandler(BaseHTTPRequestHandler):
    def do_HEAD(self): self.send_response(200); self.end_headers()
    def do_GET(self):
        self.send_response(200); self.send_header("Content-type", "text/html"); self.end_headers()
        self.wfile.write(b"<h1>Bozi-bot V3.9.2 Online</h1>")

if __name__ == "__main__":
    # Iniciar servidor Health Check
    threading.Thread(target=lambda: HTTPServer(("0.0.0.0", int(os.environ.get("PORT", 10000))), DashboardHandler).serve_forever(), daemon=True).start()

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("model", model_cmd))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    
    # Iniciar Worker y Polling
    loop = asyncio.get_event_loop()
    loop.create_task(task_worker(app.bot)) # <--- DEFINIDA ARRIBA, YA NO FALLA
    
    logging.info(f"🚀 Bozi-bot V3.9.2 Ready.")
    app.run_polling(drop_pending_updates=True)
