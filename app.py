# ===================================================
# 🏛️ BOZI-BOT: EL CEREBRO HÍBRIDO ASINCRÓNICO DE ELITE
# Versión: 3.5.4 (FILE-BASED CONFIG + DYNAMIC FAILOVER)
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

# WISHLIST DE MODELOS GRATUITOS (Prioridad: Inteligencia -> Estabilidad)
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
# 📁 GESTIÓN DE ARCHIVOS DE CONFIGURACIÓN (.TXT)
# ---------------------------------------------------

def get_file_content(filepath, default=""):
    """Lee archivos como rules.txt o self.txt del repositorio"""
    try:
        if os.path.exists(filepath):
            with open(filepath, 'r', encoding='utf-8') as f:
                return f.read().strip()
        return default
    except Exception as e:
        logging.error(f"Error leyendo {filepath}: {e}")
        return default

# ---------------------------------------------------
# 🧠 MEMORIA Y AUTONOMÍA
# ---------------------------------------------------

async def get_best_free_model():
    """Selecciona el mejor modelo free activo en OpenRouter"""
    try:
        response = requests.get("https://openrouter.ai/api/v1/models", timeout=5)
        available_ids = [m['id'] for m in response.json().get('data', [])]
        for model in FREE_MODEL_WISHLIST:
            if model in available_ids: return model
        return "mistralai/mistral-7b-instruct-v0.1"
    except: return "mistralai/mistral-7b-instruct-v0.1"

async def search_memory(chat_id, query):
    """Búsqueda semántica en Supabase"""
    try:
        res_emb = await openai_client.embeddings.create(input=query, model="text-embedding-3-small")
        vector = res_emb.data[0].embedding
        res = supabase.rpc("match_knowledge", {
            "query_embedding": vector, "match_threshold": 0.5, "match_count": 2, "p_chat_id": chat_id
        }).execute()
        if res.data:
            return "\n\n💡 [MEMORIA PERSISTENTE]:\n" + "\n".join([d['content'] for d in res.data])
        return ""
    except: return ""

# ---------------------------------------------------
# 🤖 LÓGICA DE PROCESAMIENTO
# ---------------------------------------------------

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_text = update.message.text
    if not user_text: return

    await context.bot.send_chat_action(chat_id=chat_id, action=constants.ChatAction.TYPING)
    
    # 1. Cargar configuración desde tus archivos .txt
    rules = get_file_content("rules.txt")
    self_info = get_file_content("self.txt")
    memoria = await search_memory(chat_id, user_text)
    
    # 2. Construir el System Prompt dinámico
    system_prompt = (
        f"{self_info}\n\n"
        f"REGLAS CRÍTICAS:\n{rules}\n\n"
        "REGLA DE IDIOMA: Hablá siempre en español de Argentina (voseo). "
        "No menciones proyectos privados si no te preguntan específicamente.\n"
        f"{memoria}"
    )

    is_tech = any(w in user_text.lower() for w in TECH_KEYWORDS)

    # 3. Ruteo Inteligente con Failover
    if is_tech:
        # Modo Experto (OpenAI)
        await process_with_model(update, system_prompt, user_text, openai_client, OPENAI_MODEL)
    else:
        # Modo Casual (OpenRouter con Failover a OpenAI)
        best_free = await get_best_free_model()
        success = await process_with_model(update, system_prompt, user_text, openrouter_client, best_free, temp=0.8)
        
        if not success:
            logging.warning("Failover: OpenRouter caído, usando OpenAI.")
            await process_with_model(update, system_prompt, user_text, openai_client, OPENAI_MODEL)

async def process_with_model(update, system, user, client, model_name, temp=0.7):
    try:
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        response = await client.chat.completions.create(
            model=model_name, messages=messages, temperature=temp, timeout=25.0
        )
        await update.message.reply_text(response.choices[0].message.content)
        return True
    except Exception as e:
        logging.error(f"Error en {model_name}: {e}")
        return False

# ---------------------------------------------------
# 🌐 INFRAESTRUCTURA Y BOOT
# ---------------------------------------------------

class DashboardHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers()
        self.wfile.write(b"Bozi-bot V3.5.4 Online")

if __name__ == "__main__":
    for _ in range(2): requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/deleteWebhook?drop_pending_updates=True")
    threading.Thread(target=lambda: HTTPServer(("0.0.0.0", int(os.environ.get("PORT", 10000))), DashboardHandler).serve_forever(), daemon=True).start()

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    
    logging.info("🚀 Bozi-bot V3.5.4 Iniciado (File-Config Ready)")
    time.sleep(5)
    app.run_polling(drop_pending_updates=True)
