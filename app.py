# ===================================================
# 🏛️ BOZI-BOT: EL CEREBRO HÍBRIDO ASINCRÓNICO DE ELITE
# Versión: 3.5.6 (HEALTH-CHECK + SCHEDULER + WEB SEARCH)
# ===================================================

import os
import logging
import requests
import threading
import time
import asyncio
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

FREE_MODEL_WISHLIST = [
    "qwen/qwen-2.5-72b-instruct:free",
    "meta-llama/llama-3.1-70b-instruct:free",
    "mistralai/mistral-7b-instruct-v0.1",
    "google/gemma-2-9b-it:free"
]

OPENAI_MODEL = "gpt-4o-mini"

openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)
openrouter_client = AsyncOpenAI(base_url="https://openrouter.ai/api/v1", api_key=OPENROUTER_API_KEY)
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

TECH_KEYWORDS = ["error", "log", "configurá", "ataque", "hacker", "ip", "script", "python", "vulnerabilidad", "wazuh", "proyecto", "tarea", "nmap", "flipper", "proxmark"]

# ---------------------------------------------------
# 🛠️ UTILIDADES (FILES & WEB)
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
            logging.info(f"✅ Memoria recuperada para {chat_id}")
            return "\n\n💡 [MEMORIA PERSISTENTE]:\n" + "\n".join([d['content'] for d in res.data])
        return ""
    except Exception as e:
        logging.error(f"❌ Error en memoria: {e}")
        return ""

# ---------------------------------------------------
# ⏰ TASK WORKER (SCHEDULER)
# ---------------------------------------------------

async def task_worker(bot):
    while True:
        try:
            now = time.strftime('%Y-%m-%d %H:%M:%S')
            # Requiere columna 'scheduled_at' y 'status' en la tabla 'scheduled_tasks'
            res = supabase.table("scheduled_tasks").select("*").eq("status", "pending").lte("scheduled_at", now).execute()
            
            for task in res.data:
                await bot.send_message(chat_id=task['chat_id'], text=f"🔔 **RECORDATORIO**: {task['description']}", parse_mode='Markdown')
                supabase.table("scheduled_tasks").update({"status": "completed"}).eq("id", task['id']).execute()
                logging.info(f"🚀 Tarea {task['id']} enviada.")
        except Exception as e:
            logging.error(f"⚠️ Error worker: {e}")
        await asyncio.sleep(60)

# ---------------------------------------------------
# 🤖 LÓGICA DE PROCESAMIENTO
# ---------------------------------------------------

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_text = update.message.text
    if not user_text: return

    await context.bot.send_chat_action(chat_id=chat_id, action=constants.ChatAction.TYPING)
    
    rules = get_file_content("rules.txt")
    self_info = get_file_content("self.txt")
    memoria = await search_memory(chat_id, user_text)
    
    web_info = ""
    if any(k in user_text.lower() for k in ["noticia", "vulnerabilidad", "nuevo", "actual", "quién es"]):
        web_info = web_search(user_text)

    system_prompt = (
        f"{self_info}\n\nREGLAS CRÍTICAS:\n{rules}\n\n"
        "REGLA DE IDIOMA: Español de Argentina (voseo).\n"
        f"{memoria}{web_info}"
    )

    is_tech = any(w in user_text.lower() for w in TECH_KEYWORDS)

    if is_tech:
        await process_with_model(update, system_prompt, user_text, openai_client, OPENAI_MODEL)
    else:
        try:
            response = requests.get("https://openrouter.ai/api/v1/models", timeout=5)
            available = [m['id'] for m in response.json().get('data', [])]
            model = next((m for m in FREE_MODEL_WISHLIST if m in available), "mistralai/mistral-7b-instruct-v0.1")
            
            success = await process_with_model(update, system_prompt, user_text, openrouter_client, model, temp=0.8)
            if not success: raise Exception("OpenRouter Fail")
        except:
            await process_with_model(update, system_prompt, user_text, openai_client, OPENAI_MODEL)

async def process_with_model(update, system, user, client, model_name, temp=0.7):
    try:
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        response = await client.chat.completions.create(model=model_name, messages=messages, temperature=temp, timeout=25.0)
        await update.message.reply_text(response.choices[0].message.content)
        return True
    except Exception as e:
        logging.error(f"Error en {model_name}: {e}")
        return False

# ---------------------------------------------------
# 🌐 INFRAESTRUCTURA (RENDER COMPLIANT)
# ---------------------------------------------------

class DashboardHandler(BaseHTTPRequestHandler):
    def do_HEAD(self):
        """Responde a los pings de Render para el Health Check"""
        self.send_response(200)
        self.end_headers()

    def do_GET(self):
        """Responde a las visitas por navegador"""
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        self.wfile.write(b"Bozi-bot V3.5.6 Online - Health Check OK")

if __name__ == "__main__":
    for _ in range(2): requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/deleteWebhook?drop_pending_updates=True")
    
    # Servidor web para el Health Check de Render
    threading.Thread(target=lambda: HTTPServer(("0.0.0.0", int(os.environ.get("PORT", 10000))), DashboardHandler).serve_forever(), daemon=True).start()

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    
    loop = asyncio.get_event_loop()
    loop.create_task(task_worker(app.bot))
    
    logging.info("🚀 Bozi-bot V3.5.6 Iniciado.")
    app.run_polling(drop_pending_updates=True)
