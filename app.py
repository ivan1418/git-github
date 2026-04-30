# ===================================================
# 🏛️ BOZI-BOT: EL CEREBRO HÍBRIDO ASINCRÓNICO DE ELITE
# Versión: 2.5 (KILL SWITCH + STABLE RESPONSE + Supabase REAL)
# ===================================================

import os
import re
import json
import logging
import threading
import asyncio 
import requests
from datetime import datetime
from zoneinfo import ZoneInfo
from urllib.parse import urlparse
from http.server import HTTPServer, BaseHTTPRequestHandler

# Telegram y IA
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, CommandHandler, CallbackQueryHandler, filters
from openai import AsyncOpenAI
from supabase import create_client

# ---------------------------------------------------
# ⚙️ CONFIGURACIÓN Y VARIABLES
# ---------------------------------------------------
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)

MAX_HISTORY_MESSAGES = int(os.getenv("MAX_HISTORY_MESSAGES", "8"))
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

LOCAL_TZ = ZoneInfo("America/Argentina/Buenos_Aires")
OPENAI_MODEL_TECNICO = "gpt-4o-mini"
OPENROUTER_MODEL_CHAT = "google/gemma-4-31b-it:free"

# Clientes
openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)
openrouter_client = AsyncOpenAI(base_url="https://openrouter.ai/api/v1", api_key=OPENROUTER_API_KEY)
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# ---------------------------------------------------
# 🧹 KILL SWITCH: LIMPIEZA DE CONFLICTOS
# ---------------------------------------------------
def kill_telegram_conflicts(token):
    """Fuerza a Telegram a cerrar cualquier conexión previa para evitar el error de Conflict."""
    url = f"https://api.telegram.org/bot{token}/deleteWebhook?drop_pending_updates=True"
    try:
        response = requests.post(url, timeout=10)
        if response.status_code == 200:
            logging.info("🧹 Sesiones previas y mensajes acumulados eliminados.")
        else:
            logging.warning(f"⚠️ Aviso en limpieza: {response.status_code}")
    except Exception as e:
        logging.error(f"❌ Error en Kill Switch: {e}")

# ---------------------------------------------------
# 🤖 PERSONALIDAD Y PROMPTS
# ---------------------------------------------------
def load_prompt_file(filename):
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            return f.read().strip()
    except Exception: return "Sos Bozi-bot, asistente de Iván."

SELF_PROMPT_CIBERSEC = load_prompt_file("self.txt")

def build_runtime_system_prompt(config):
    return f"{SELF_PROMPT_CIBERSEC}\nMODO: {config.get('mode', 'asistente')}\nFORMATO: [INTERNAL_MONOLOGUE]...[/INTERNAL_MONOLOGUE] [FINAL_RESPONSE]..."

# ---------------------------------------------------
# 🧠 HELPERS DE DATOS (Supabase REAL)
# ---------------------------------------------------
async def get_bot_config_async(chat_id):
    try:
        res = supabase.table("bot_config").select("*").eq("chat_id", chat_id).execute()
        return res.data[0] if res.data else {}
    except: return {}

async def save_memory_async(chat_id, role, content):
    try:
        supabase.table("bot_memory").insert({"chat_id": chat_id, "role": role, "content": content}).execute()
    except Exception as e: logging.error(f"Error Supabase: {e}")

async def get_recent_history_async(chat_id, limit=MAX_HISTORY_MESSAGES):
    try:
        res = supabase.table("bot_memory").select("role, content").eq("chat_id", chat_id).order("created_at", desc=True).limit(limit).execute()
        return list(reversed(res.data)) if res.data else []
    except: return []

async def build_active_context_async(chat_id):
    return f"Fecha/Hora actual: {datetime.now(LOCAL_TZ).strftime('%Y-%m-%d %H:%M:%S')}"

async def classify_contextual_route_async(text, chat_id, history, active_ctx):
    try:
        prompt = "Decidí si el mensaje es NORMAL_CHAT o CIBERSEC_TASK. Devolvé JSON: {'intent': '...'}"
        res = await openai_client.chat.completions.create(
            model=OPENAI_MODEL_TECNICO,
            messages=[{"role": "system", "content": prompt}, {"role": "user", "content": text}],
            response_format={ "type": "json_object" }
        )
        return json.loads(res.choices[0].message.content)
    except: return {"intent": "NORMAL_CHAT"}

async def get_best_client_and_model(intent: str):
    if intent.upper() in ["CIBERSEC_TASK", "PROJECT_EDIT", "IMAGE_ANALYSIS"]:
        return openai_client, OPENAI_MODEL_TECNICO
    return openrouter_client, OPENROUTER_MODEL_CHAT

def build_chat_input(user_text, history, active_context):
    msgs = [{"role": h['role'], "content": h['content']} for h in history]
    msgs.append({"role": "user", "content": f"Context: {active_context}\n{user_text}"})
    return msgs

# ---------------------------------------------------
# 🔥 HANDLER DE MENSAJES (Versión Robusta)
# ---------------------------------------------------
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_text = update.message.text or ""
    status_message = await update.message.reply_text("...")

    try:
        # Carga de contexto
        config = await get_bot_config_async(chat_id)
        history = await get_recent_history_async(chat_id)
        active_ctx = await build_active_context_async(chat_id)
        
        # IA Híbrida
        route = await classify_contextual_route_async(user_text, chat_id, history, active_ctx)
        client, model = await get_best_client_and_model(route.get("intent", "NORMAL_CHAT"))

        # Llamada a IA
        response = await client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": build_runtime_system_prompt(config)}] + build_chat_input(user_text, history, active_ctx),
            temperature=0.4
        )
        
        raw_text = response.choices[0].message.content

        # Limpieza inteligente de respuesta
        if "[FINAL_RESPONSE]" in raw_text:
            final_ans = raw_text.split("[FINAL_RESPONSE]")[-1].replace("[/FINAL_RESPONSE]", "").strip()
        else:
            final_ans = re.sub(r"\[INTERNAL_MONOLOGUE\].*?\[/INTERNAL_MONOLOGUE\]", "", raw_text, flags=re.DOTALL).strip()
        
        if not final_ans: final_ans = raw_text

        await context.bot.edit_message_text(chat_id=chat_id, message_id=status_message.message_id, text=final_ans)
        await save_memory_async(chat_id, "user", user_text)
        await save_memory_async(chat_id, "assistant", final_ans)

    except Exception as e:
        logging.error(f"Error: {e}")
        await context.bot.edit_message_text(chat_id=chat_id, message_id=status_message.message_id, text="Se cruzaron los cables, Iván. Reintentá.")

# ---------------------------------------------------
# INICIO Y SERVER
# ---------------------------------------------------
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"🏛️ Bozi-bot Elite Online.\nKill Switch activado. CEO: Iván.")

if __name__ == "__main__":
    # Limpieza inicial de conflictos
    kill_telegram_conflicts(TELEGRAM_TOKEN)
    
    # Server para Render
    class SimpleH(BaseHTTPRequestHandler):
        def do_GET(self): self.send_response(200); self.end_headers(); self.wfile.write(b"OK")
    threading.Thread(target=lambda: HTTPServer(("0.0.0.0", int(os.environ.get("PORT", 10000))), SimpleH).serve_forever(), daemon=True).start()
    
    # App
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).read_timeout(30).connect_timeout(30).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    
    logging.info("🚀 Bozi-bot Total Secure desplegado.")
    app.run_polling(drop_pending_updates=True)
