# ===================================================
# 🏛️ BOZI-BOT: EL CEREBRO HÍBRIDO ASINCRÓNICO DE ELITE
# Versión: 3.7 (CRUD TASKS + PROJECT PUB + PERFORMANCE)
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
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters
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
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")

OPENAI_MODEL = "gpt-4o"
openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)
openrouter_client = AsyncOpenAI(base_url="https://openrouter.ai/api/v1", api_key=OPENROUTER_API_KEY)
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# ---------------------------------------------------
# 🏎️ PERFORMANCE: TYPING & ASYNC UTILS
# ---------------------------------------------------

async def keep_typing(context, chat_id, stop_event):
    while not stop_event.is_set():
        await context.bot.send_chat_action(chat_id=chat_id, action=constants.ChatAction.TYPING)
        await asyncio.sleep(4)

def get_file_content(filepath, default=""):
    try:
        if os.path.exists(filepath):
            with open(filepath, 'r', encoding='utf-8') as f: return f.read().strip()
        return default
    except: return default

# ---------------------------------------------------
# 🛠️ ACTION LAYER: CRUD DE TAREAS Y PROYECTOS
# ---------------------------------------------------

async def manage_actions(chat_id, text):
    """Detecta intenciones de Creación, Edición o Publicación"""
    low_text = text.lower()
    
    # 1. PUBLICACIÓN DE PROYECTO (Regla 3)
    if "publicalo" in low_text or "generar url" in low_text:
        # Lógica para mover de project_drafts a proyectos públicos (simulado con tabla proyectos)
        try:
            res = supabase.table("projects").insert({"chat_id": int(chat_id), "status": "published"}).execute()
            p_id = res.data[0]['id']
            url = f"{os.getenv('RENDER_EXTERNAL_URL', 'https://bozi-bot.render.com')}/view/{p_id}"
            return f"🚀 **¡Proyecto Publicado!**\nIván, ya podés acceder acá: {url}"
        except: return "❌ Falló la publicación en la base de datos."

    # 2. EDICIÓN / CREACIÓN DE TAREAS
    trigger_words = ["recordame", "agendá", "cambiá", "editá", "borrá", "mañana", "lunes", "martes"]
    if any(w in low_text for w in trigger_words):
        prompt = (
            f"Hoy es {datetime.now()}. Analizá el pedido del usuario. "
            "Si quiere EDITAR o BORRAR, identificá la intención. "
            "Respondé SOLO un JSON: {'action': 'create|update|delete', 'desc': '...', 'date': 'YYYY-MM-DD HH:MM:SS', 'target_id': 'opcional'}"
        )
        try:
            res = await openai_client.chat.completions.create(
                model="gpt-4o-mini", messages=[{"role": "user", "content": prompt + f"\nTexto: {text}"}],
                response_format={ "type": "json_object" }, timeout=12
            )
            data = json.loads(res.choices[0].message.content)
            
            if data['action'] == 'create':
                supabase.table("scheduled_tasks").insert({
                    "chat_id": int(chat_id), "description": data['desc'], "scheduled_at": data['date'], "status": "pending"
                }).execute()
                return f"✅ Tarea agendada: '{data['desc']}'"
            
            elif data['action'] == 'update':
                # Buscamos la última tarea pendiente para ese chat si no hay ID
                last_task = supabase.table("scheduled_tasks").select("id").eq("chat_id", int(chat_id)).eq("status", "pending").order("created_at", desc=True).limit(1).execute()
                if last_task.data:
                    supabase.table("scheduled_tasks").update({"description": data['desc'], "scheduled_at": data['date']}).eq("id", last_task.data[0]['id']).execute()
                    return f"🔄 Tarea actualizada con éxito, Iván."
        except: pass
    return None

# ---------------------------------------------------
# 🤖 ORQUESTADOR PRINCIPAL (LATENCIA OPTIMIZADA)
# ---------------------------------------------------

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_text = update.message.text
    if not user_text: return

    stop_typing = asyncio.Event()
    typing_task = asyncio.create_task(keep_typing(context, chat_id, stop_typing))

    try:
        # Ejecutamos Acción y Memoria en paralelo
        action_future = manage_actions(chat_id, user_text)
        # Búsqueda semántica
        res_emb = await openai_client.embeddings.create(input=user_text, model="text-embedding-3-small")
        mem_res = supabase.rpc("match_knowledge", {"query_embedding": res_emb.data[0].embedding, "match_threshold": 0.5, "match_count": 2, "p_chat_id": int(chat_id)}).execute()
        memoria = "\n\n💡 [MEMORIA]:\n" + "\n".join([d['content'] for d in mem_res.data]) if mem_res.data else ""

        action_result = await action_future
        if action_result:
            await update.message.reply_text(action_result, parse_mode='Markdown')
            return

        # Respuesta de charla/técnica
        rules = get_file_content("rules.txt")
        self_info = get_file_content("self.txt")
        system_prompt = f"{self_info}\n\n{rules}\n\nIdioma: Rosario/Voseo.\n{memoria}"
        
        is_tech = any(w in user_text.lower() for w in ["log", "error", "script", "wazuh", "lumu", "cyber"])
        client = openai_client if is_tech else openrouter_client
        model = OPENAI_MODEL if is_tech else "mistralai/mistral-7b-instruct-v0.1"

        res = await client.chat.completions.create(
            model=model, messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_text}]
        )
        await update.message.reply_text(res.choices[0].message.content)

    finally:
        stop_typing.set()
        await typing_task

# ---------------------------------------------------
# 👁️ VISIÓN E INFRAESTRUCTURA
# ---------------------------------------------------

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    photo_file = await update.message.photo[-1].get_file()
    stop_typing = asyncio.Event()
    typing_task = asyncio.create_task(keep_typing(context, chat_id, stop_typing))
    try:
        res = await openai_client.chat.completions.create(
            model="gpt-4o", messages=[{"role": "user", "content": [
                {"type": "text", "text": "Analizá técnicamente (Senior IT Rosario)."},
                {"type": "image_url", "image_url": {"url": photo_file.file_path}}
            ]}]
        )
        await update.message.reply_text(f"👁️ **Visión**: {res.choices[0].message.content}")
    finally:
        stop_typing.set()
        await typing_task

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

class DashboardHandler(BaseHTTPRequestHandler):
    def do_HEAD(self): self.send_response(200); self.end_headers()
    def do_GET(self):
        self.send_response(200); self.send_header("Content-type", "text/html"); self.end_headers()
        self.wfile.write(b"<html><body><h1>Bozi-bot V3.7: Orchestrator Mode</h1><p>Status: Live</p></body></html>")

if __name__ == "__main__":
    for _ in range(2): requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/deleteWebhook?drop_pending_updates=True")
    threading.Thread(target=lambda: HTTPServer(("0.0.0.0", int(os.environ.get("PORT", 10000))), DashboardHandler).serve_forever(), daemon=True).start()
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    loop = asyncio.get_event_loop()
    loop.create_task(task_worker(app.bot))
    logging.info("🚀 Bozi-bot V3.7 Iniciado.")
    app.run_polling(drop_pending_updates=True)
