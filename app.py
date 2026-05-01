# ===================================================
# 🏛️ BOZI-BOT: EL CEREBRO HÍBRIDO ASINCRÓNICO DE ELITE
# Versión: 4.0 (COMMANDS FIX + PERSISTENCE + VISION)
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

openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# Configuración persistente en memoria (volátil al reiniciar Render)
USER_CONFIG = {"model": "gpt-4o", "lang": "Rosario/Voseo"}
CHAT_HISTORY = {} # Memoria de corto plazo

# ---------------------------------------------------
# 🛠️ FUNCIONES AUXILIARES
# ---------------------------------------------------

def get_file_content(filepath, default=""):
    try:
        if os.path.exists(filepath):
            with open(filepath, 'r', encoding='utf-8') as f: return f.read().strip()
        return default
    except: return default

async def task_worker(bot):
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

# ---------------------------------------------------
# 🤖 HANDLERS DE COMANDOS (LOS QUE NO RESPONDÍAN)
# ---------------------------------------------------

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🏛️ **Bozi-bot V4.0 Operativo.**\n\nComandos:\n/tasks - Ver pendientes\n/projects - Ver desarrollos\n/config - Ver config actual\n/models - Cambiar cerebro")

async def config_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Responde al comando /config"""
    msg = (f"⚙️ **Configuración Actual:**\n\n"
           f"🧠 Modelo: `{USER_CONFIG['model']}`\n"
           f"🇦🇷 Dialecto: `{USER_CONFIG['lang']}`\n"
           f"📡 Infra: `Render + Supabase`\n"
           f"🔐 Cybersecurity Mode: `Active`")
    await update.message.reply_text(msg, parse_mode='Markdown')

async def models_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Responde al comando /models o /model"""
    if context.args and context.args[0] in ["gpt-4o", "gpt-4o-mini"]:
        USER_CONFIG["model"] = context.args[0]
        return await update.message.reply_text(f"✅ Cerebro cambiado a: `{USER_CONFIG['model']}`", parse_mode='Markdown')
    
    msg = ("🧠 **Modelos disponibles:**\n\n"
           "1. `gpt-4o` (Full Power - Visión/Análisis)\n"
           "2. `gpt-4o-mini` (Fast & Cheap)\n\n"
           "Para cambiar usá: `/models gpt-4o-mini`")
    await update.message.reply_text(msg, parse_mode='Markdown')

async def tasks_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    res = supabase.table("scheduled_tasks").select("*").eq("chat_id", update.effective_chat.id).eq("status", "pending").execute()
    if not res.data: return await update.message.reply_text("📭 No hay tareas pendientes.")
    msg = "\n".join([f"📌 {t['scheduled_at']}: {t['description']}" for t in res.data])
    await update.message.reply_text(f"📝 **Tareas en cola:**\n{msg}")

async def projects_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    res = supabase.table("projects").select("id, status, title").eq("chat_id", update.effective_chat.id).execute()
    msg = "\n".join([f"🚀 ID {p['id']} - {p['status']}" for p in res.data])
    await update.message.reply_text(f"📂 **Proyectos:**\n{msg or 'Sin proyectos.'}")

# ---------------------------------------------------
# 🤖 MENSAJES Y VISIÓN
# ---------------------------------------------------

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_text = update.message.text
    if not user_text: return

    await context.bot.send_chat_action(chat_id=chat_id, action=constants.ChatAction.TYPING)
    
    rules = get_file_content("rules.txt")
    self_info = get_file_content("self.txt")
    
    # Memoria de corto plazo básica
    if chat_id not in CHAT_HISTORY: CHAT_HISTORY[chat_id] = []
    
    messages = [{"role": "system", "content": f"{self_info}\n\n{rules}"}]
    messages.extend(CHAT_HISTORY[chat_id][-6:]) # Enviamos los últimos 6 mensajes de contexto
    messages.append({"role": "user", "content": user_text})

    try:
        res = await openai_client.chat.completions.create(model=USER_CONFIG["model"], messages=messages)
        bot_response = res.choices[0].message.content
        await update.message.reply_text(bot_response)
        
        # Guardar en historial
        CHAT_HISTORY[chat_id].append({"role": "user", "content": user_text})
        CHAT_HISTORY[chat_id].append({"role": "assistant", "content": bot_response})
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    photo_file = await update.message.photo[-1].get_file()
    res = await openai_client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": [
            {"type": "text", "text": "Analizá técnicamente (Senior IT Rosario)."},
            {"type": "image_url", "image_url": {"url": photo_file.file_path}}
        ]}]
    )
    await update.message.reply_text(f"👁️ **Visión**: {res.choices[0].message.content}")

# ---------------------------------------------------
# 🌐 INFRAESTRUCTURA
# ---------------------------------------------------

class DashboardHandler(BaseHTTPRequestHandler):
    def do_HEAD(self): self.send_response(200); self.end_headers()
    def do_GET(self):
        self.send_response(200); self.send_header("Content-type", "text/html"); self.end_headers()
        self.wfile.write(b"<h1>Bozi-bot V4.0: Commands Fixed</h1>")

if __name__ == "__main__":
    threading.Thread(target=lambda: HTTPServer(("0.0.0.0", int(os.environ.get("PORT", 10000))), DashboardHandler).serve_forever(), daemon=True).start()
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    
    # Registro de Comandos (Aquí estaba el fallo)
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("config", config_cmd))
    app.add_handler(CommandHandler("models", models_cmd))
    app.add_handler(CommandHandler("model", models_cmd)) # Alias
    app.add_handler(CommandHandler("tasks", tasks_cmd))
    app.add_handler(CommandHandler("projects", projects_cmd))
    
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    
    loop = asyncio.get_event_loop()
    loop.create_task(task_worker(app.bot))
    
    logging.info("🚀 Bozi-bot V4.0 (Commands Ready) Iniciado.")
    app.run_polling(drop_pending_updates=True)
