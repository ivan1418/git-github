# ===================================================
# 🏛️ BOZI-BOT: EL CEREBRO HÍBRIDO ASINCRÓNICO DE ELITE
# Versión: 3.5 (AUTONOMOUS FAILOVER + DYNAMIC ROUTING)
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
# ⚙️ CONFIGURACIÓN
# ---------------------------------------------------
logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

# WISHLIST DE MODELOS GRATUITOS (De más inteligente a más estable)
FREE_MODEL_WISHLIST = [
    "qwen/qwen-2.5-72b-instruct:free",
    "meta-llama/llama-3.1-70b-instruct:free",
    "mistralai/mistral-7b-instruct-v0.1",
    "google/gemma-2-9b-it:free"
]

OPENAI_MODEL = "gpt-4o-mini" # El cerebro de pago para técnica y emergencias

openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)
openrouter_client = AsyncOpenAI(base_url="https://openrouter.ai/api/v1", api_key=OPENROUTER_API_KEY)
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

TECH_KEYWORDS = ["error", "log", "configurá", "ataque", "hacker", "ip", "script", "python", "vulnerabilidad", "crea un proyecto", "hace una tarea, crea una tarea", "lumu", "nmap", "flipper", "proxmark"]

# ---------------------------------------------------
# 🛰️ MOTOR DE AUTONOMÍA (DYNAMIC MODELS)
# ---------------------------------------------------

async def get_best_free_model():
    """Busca en tiempo real qué modelos de la wishlist están online y son free"""
    try:
        response = requests.get("https://openrouter.ai/api/v1/models", timeout=5)
        available_ids = [m['id'] for m in response.json().get('data', [])]
        
        for model in FREE_MODEL_WISHLIST:
            if model in available_ids:
                logging.info(f"🚀 Autonomía: Mejor modelo libre detectado: {model}")
                return model
        return "mistralai/mistral-7b-instruct-v0.1" # Fallback conservador
    except Exception as e:
        logging.error(f"⚠️ Error consultando modelos: {e}")
        return "mistralai/mistral-7b-instruct-v0.1"

# ---------------------------------------------------
# 🧠 MEMORIA SEMÁNTICA (RAG)
# ---------------------------------------------------

async def get_embedding(text):
    try:
        res = await openai_client.embeddings.create(input=text, model="text-embedding-3-small")
        return res.data[0].embedding
    except: return None

async def search_memory(chat_id, query):
    vector = await get_embedding(query)
    if not vector: return ""
    try:
        res = supabase.rpc("match_knowledge", {
            "query_embedding": vector, "match_threshold": 0.5, "match_count": 2, "p_chat_id": chat_id
        }).execute()
        if res.data:
            return "\n\n💡 [CONTEXTO HISTÓRICO]:\n" + "\n".join([d['content'] for d in res.data])
        return ""
    except: return ""

# ---------------------------------------------------
# 🤖 LÓGICA DE PROCESAMIENTO (DOUBLE FAILOVER)
# ---------------------------------------------------

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_text = update.message.text
    if not user_text: return

    await context.bot.send_chat_action(chat_id=chat_id, action=constants.ChatAction.TYPING)
    
    # 1. Recuperar memoria y detectar complejidad
    memoria_contexto = await search_memory(chat_id, user_text)
    is_tech = any(w in user_text.lower() for w in TECH_KEYWORDS)
    
    system_prompt = (
        "Sos Bozi-bot, asistente de elite de Iván. "
        "Respondé siempre en español de Argentina. "
        f"{memoria_contexto}"
    )

    # 2. INTENTO A: OpenAI para temas complejos
    if is_tech:
        logging.info("🧠 Derivando a OpenAI por complejidad técnica.")
        await process_with_model(update, system_prompt, user_text, openai_client, OPENAI_MODEL)
        return

    # 3. INTENTO B: OpenRouter para temas casuales (Mejor Free disponible)
    best_free = await get_best_free_model()
    success = await process_with_model(update, system_prompt, user_text, openrouter_client, best_free)
    
    # 4. INTENTO C: Failover de Emergencia (Si OpenRouter falló con 404/500)
    if not success:
        logging.warning("⚠️ OpenRouter falló. Ejecutando conmutación de emergencia a OpenAI.")
        await process_with_model(update, system_prompt, user_text, openai_client, OPENAI_MODEL)

async def process_with_model(update, system, user, client, model_name):
    """Ejecuta la petición y retorna True si tuvo éxito"""
    try:
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        response = await client.chat.completions.create(
            model=model_name,
            messages=messages,
            timeout=25.0
        )
        answer = response.choices[0].message.content
        await update.message.reply_text(answer)
        return True
    except Exception as e:
        logging.error(f"Error con modelo {model_name}: {e}")
        return False

# ---------------------------------------------------
# 🌐 DASHBOARD Y BOOT
# ---------------------------------------------------

class DashboardHandler(BaseHTTPRequestHandler):
    def do_HEAD(self): self.send_response(200); self.end_headers()
    def do_GET(self):
        self.send_response(200); self.send_header("Content-type", "text/html"); self.end_headers()
        self.wfile.write(b"Bozi-bot Autonomous V3.5 Online")

if __name__ == "__main__":
    for _ in range(2): requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/deleteWebhook?drop_pending_updates=True")
    
    threading.Thread(target=lambda: HTTPServer(("0.0.0.0", int(os.environ.get("PORT", 10000))), DashboardHandler).serve_forever(), daemon=True).start()

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    
    logging.info("🚀 Bozi-bot V3.5 (Self-Healing Mode) Iniciado.")
    time.sleep(5)
    app.run_polling(drop_pending_updates=True)
