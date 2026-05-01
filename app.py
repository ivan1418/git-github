# ===================================================
# 🏛️ BOZI-BOT: EL CEREBRO HÍBRIDO ASINCRÓNICO DE ELITE
# Versión: 3.6.1 (FULL EXECUTIVE: VISION + TASKS + WEB)
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

# Usamos GPT-4o para visión y razonamiento lógico de tareas
OPENAI_MODEL = "gpt-4o"
FREE_MODEL_WISHLIST = [
    "qwen/qwen-2.5-72b-instruct:free",
    "meta-llama/llama-3.1-70b-instruct:free",
    "mistralai/mistral-7b-instruct-v0.1"
]

openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)
openrouter_client = AsyncOpenAI(base_url="https://openrouter.ai/api/v1", api_key=OPENROUTER_API_KEY)
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

TECH_KEYWORDS = ["error", "log", "configurá", "ataque", "hacker", "ip", "script", "python", "vulnerabilidad", "wazuh", "proyecto", "tarea", "nmap", "flipper", "proxmark"]

# ---------------------------------------------------
# 🛠️ UTILIDADES (FILES, WEB & TASKS)
# ---------------------------------------------------

def get_file_content(filepath, default=""):
    try:
        if os.path.exists(filepath):
            with open(filepath, 'r', encoding='utf-8') as f:
                return f.read().strip()
        return default
    except Exception as e:
        logging.error(f"Error leyendo {filepath}: {e}")
        return default

def web_search(query):
    if not TAVILY_API_KEY: return ""
    try:
        url = "https://api.tavily.com/search"
        payload = {"api_key": TAVILY_API_KEY, "query": query, "search_depth": "smart", "max_results": 2}
        response = requests.post(url, json=payload, timeout=10)
        results = response.json().get("results", [])
        return "\n\n🌐 [INFO WEB RECIENTE]:\n" + "\n".join([f"- {r['title']}: {r['content']} ({r['url']})" for r in results])
    except: return ""

async def extract_and_save_task(chat_id, text):
    """Detecta intenciones de recordatorios e inserta en DB"""
    prompt = (
        "Extraé tareas del texto. Si hay intención de recordar algo futuro, "
        "respondé SOLO un JSON: {'desc': 'qué recordar', 'date': 'YYYY-MM-DD HH:MM:SS'}. "
        f"Hoy es {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}. Texto: {text}"
    )
    try:
        res = await openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            response_format={ "type": "json_object" }
        )
        data = json.loads(res.choices[0].message.content)
        if data.get('desc') and data.get('date'):
            supabase.table("scheduled_tasks").insert({
                "chat_id": int(chat_id),
                "description": data['desc'],
                "scheduled_at": data['date'],
                "status": "pending"
            }).execute()
            return f"✅ Entendido Iván, ya agendé: '{data['desc']}' para el {data['date']}."
    except: pass
    return None

# ---------------------------------------------------
# 🧠 MEMORIA SEMÁNTICA
# ---------------------------------------------------

async def search_memory(chat_id, query):
    try:
        res_emb = await openai_client.embeddings.create(input=query, model="text-embedding-3-small")
        vector = res_emb.data[0].embedding
        res = supabase.rpc("match_knowledge", {
            "query_embedding": vector,
            "match_threshold": 0.5,
            "match_count": 2,
            "p_chat_id": int(chat_id)
        }).execute()
        if res.data:
            return "\n\n💡 [MEMORIA PERSISTENTE]:\n" + "\n".join([d['content'] for d in res.data])
        return ""
    except Exception as e:
        logging.error(f"❌ Error memoria: {e}")
        return ""

# ---------------------------------------------------
# ⏰ TASK WORKER (SCHEDULER)
# ---------------------------------------------------

async def task_worker(bot):
    """Revisa la tabla scheduled_tasks cada minuto"""
    while True:
        try:
            now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            res = supabase.table("scheduled_tasks").select("*").eq("status", "pending").lte("scheduled_at", now).execute()
            for task in res.data:
                await bot.send_message(chat_id=task['chat_id'], text=f"🔔 **RECORDATORIO**: {task['description']}", parse_mode='Markdown')
                supabase.table("scheduled_tasks").update({"status": "completed"}).eq("id", task['id']).execute()
                logging.info(f"🚀 Tarea {task['id']} enviada.")
        except Exception as e:
            logging.error(f"⚠️ Error worker: {e}")
        await asyncio.sleep(60)

# ---------------------------------------------------
# 👁️ VISIÓN (HANDLER DE FOTOS)
# ---------------------------------------------------

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await context.bot.send_chat_action(chat_id=chat_id, action=constants.ChatAction.TYPING)
    photo_file = await update.message.photo[-1].get_file()
    
    response = await openai_client.chat.completions.create(
        model="gpt-4o",
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": "Analizá esta imagen técnicamente como un Senior IT de Rosario. Sé directo."},
                {"type": "image_url", "image_url": {"url": photo_file.file_path}},
            ],
        }]
    )
    await update.message.reply_text(f"👁️ **Análisis de Visión**:\n\n{response.choices[0].message.content}", parse_mode='Markdown')

# ---------------------------------------------------
# 🤖 MENSAJES DE TEXTO
# ---------------------------------------------------

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_text = update.message.text
    if not user_text: return

    await context.bot.send_chat_action(chat_id=chat_id, action=constants.ChatAction.TYPING)
    
    # 1. Chequeo de Tareas Automáticas
    task_confirm = await extract_and_save_task(chat_id, user_text)
    if task_confirm:
        await update.message.reply_text(task_confirm)
        return

    # 2. Procesamiento Normal con Reglas y Memoria
    rules = get_file_content("rules.txt")
    self_info = get_file_content("self.txt")
    memoria = await search_memory(chat_id, user_text)
    web_info = web_search(user_text) if any(k in user_text.lower() for k in ["actual", "noticia", "vulnerabilidad"]) else ""

    system_prompt = f"{self_info}\n\nREGLAS:\n{rules}\n\nREGLA IDIOMA: Rosario/Voseo.\n{memoria}{web_info}"

    is_tech = any(w in user_text.lower() for w in TECH_KEYWORDS)
    client = openai_client if is_tech else openrouter_client
    model = OPENAI_MODEL if is_tech else "mistralai/mistral-7b-instruct-v0.1"

    try:
        messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_text}]
        res = await client.chat.completions.create(model=model, messages=messages, temperature=0.7)
        await update.message.reply_text(res.choices[0].message.content)
    except Exception as e:
        logging.error(f"Error procesando mensaje: {e}")

# ---------------------------------------------------
# 🌐 INFRAESTRUCTURA (RENDER)
# ---------------------------------------------------

class DashboardHandler(BaseHTTPRequestHandler):
    def do_HEAD(self):
        self.send_response(200); self.end_headers()
    def do_GET(self):
        self.send_response(200); self.send_header("Content-type", "text/html"); self.end_headers()
        self.wfile.write(b"<html><body><h1>Bozi-bot V3.6.1 Online</h1></body></html>")

if __name__ == "__main__":
    # Servidor Health Check
    threading.Thread(target=lambda: HTTPServer(("0.0.0.0", int(os.environ.get("PORT", 10000))), DashboardHandler).serve_forever(), daemon=True).start()

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo)) # <--- Visión Activa
    
    loop = asyncio.get_event_loop()
    loop.create_task(task_worker(app.bot)) # <--- Worker Activado
    
    logging.info("🚀 Bozi-bot V3.6.1 Iniciado.")
    app.run_polling(drop_pending_updates=True)
