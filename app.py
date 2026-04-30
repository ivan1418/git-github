# ===================================================
# 🏛️ BOZI-BOT: EL CEREBRO HÍBRIDO ASINCRÓNICO DE ELITE
# Versión: 2.3 (CORRECCIÓN DE VARIABLES + Supabase REAL)
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

# Telegram y Scheduler
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, CommandHandler, CallbackQueryHandler, filters
from openai import AsyncOpenAI

# Clientes externos
from supabase import create_client

# ---------------------------------------------------
# ⚙️ CONFIGURACIÓN Y VARIABLES CRÍTICAS
# ---------------------------------------------------
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)

# --- VARIABLES DE MEMORIA (DEFINIDAS ARRIBA PARA EVITAR ERROR) ---
MAX_HISTORY_MESSAGES = int(os.getenv("MAX_HISTORY_MESSAGES", "8"))
MAX_OUTPUT_TOKENS = int(os.getenv("MAX_OUTPUT_TOKENS", "1300"))

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

LOCAL_TZ_NAME = "America/Argentina/Buenos_Aires"
LOCAL_TZ = ZoneInfo(LOCAL_TZ_NAME)

# Modelos
OPENAI_MODEL_TECNICO = "gpt-4o-mini"
OPENROUTER_MODEL_CHAT = "google/gemma-4-31b-it:free"

if not all([TELEGRAM_TOKEN, SUPABASE_URL, SUPABASE_KEY, OPENAI_API_KEY, OPENROUTER_API_KEY]):
    raise ValueError("❌ Faltan Variables de Entorno en Render.")

# Clientes
openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)
openrouter_client = AsyncOpenAI(base_url="https://openrouter.ai/api/v1", api_key=OPENROUTER_API_KEY)
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# ---------------------------------------------------
# 🤖 CARGA DE PERSONALIDAD (self.txt)
# ---------------------------------------------------
def load_prompt_file(filename):
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            return f.read().strip()
    except Exception:
        return "Sos Bozi-bot, asistente de Iván."

SELF_PROMPT_CIBERSEC = load_prompt_file("self.txt")

CONTEXT_ROUTER_PROMPT = """
Sos el cerebro estratégico de Bozi-bot. Analizá el mensaje.
Devolvé SOLO JSON: {"intent": "NORMAL_CHAT | CIBERSEC_TASK | PROJECT_EDIT | TASK_CREATE | IMAGE_ANALYSIS", "reason": "explicación"}
"""

def build_runtime_system_prompt(config):
    format_instruction = """
RESPONDÉ OBLIGATORIAMENTE EN ESTE FORMATO:
[INTERNAL_MONOLOGUE] (pensamiento) [/INTERNAL_MONOLOGUE]
[FINAL_RESPONSE] (respuesta para Iván) [/FINAL_RESPONSE]
"""
    return f"{SELF_PROMPT_CIBERSEC}\nMODO: {config.get('mode', 'asistente')}\n{format_instruction}"

# ---------------------------------------------------
# 🧠 LÓGICA HÍBRIDA (Async)
# ---------------------------------------------------
async def get_best_client_and_model(intent: str):
    complex_intents = {"CIBERSEC_TASK", "PROJECT_EDIT", "TASK_CREATE", "IMAGE_ANALYSIS", "CONFIG_UPDATE", "TASK_EDIT_ACTIVE"}
    if intent.upper() in complex_intents:
        return openai_client, OPENAI_MODEL_TECNICO
    return openrouter_client, OPENROUTER_MODEL_CHAT

# ---------------------------------------------------
# 🏛️ HELPERS REALES DE SUPABASE (Async)
# ---------------------------------------------------
async def get_bot_config_async(chat_id):
    """
    Lee la configuración de Iván (como el modelo que usa) de Supabase.
    """
    logging.info(f"🧠 Leyendo config para {chat_id} de Supabase.")
    try:
        # Consultamos la tabla 'bot_config'
        response = supabase.table("bot_config").select("*").eq("chat_id", chat_id).execute()
        if response.data:
            # Si existís, te devolvemos tu config
            return response.data[0]
        else:
            # Si sos nuevo, devolvemos un diccionario vacío
            return {}
            
    except Exception as e:
        logging.error(f"❌ Error leyendo config de Supabase: {e}")
        return {} # Fallback ante error

async def save_memory_async(chat_id, role, content):
    """
    Toma el mensaje de Iván o del Bot y lo guarda en Supabase.
    """
    logging.info(f"💾 Guardando memoria ({role}) en Supabase.")
    try:
        # Usamos el cliente 'supabase' que ya está inicializado arriba
        supabase.table("bot_memory").insert({
            "chat_id": chat_id,
            "role": role,
            "content": content
        }).execute()
        # logging.info("✅ Guardado.")
    except Exception as e:
        logging.error(f"❌ Error guardando memoria en Supabase: {e}")

async def get_recent_history_async(chat_id, limit=MAX_HISTORY_MESSAGES):
    try:
        res = supabase.table("bot_memory").select("role, content").eq("chat_id", chat_id).order("created_at", desc=True).limit(limit).execute()
        return list(reversed(res.data)) if res.data else []
    except: return []

async def build_active_context_async(chat_id):
    # Contexto simplificado para estabilidad
    return f"Time: {datetime.now(LOCAL_TZ)}"

async def classify_contextual_route_async(text, chat_id, history, active_ctx):
    try:
        res = await openai_client.chat.completions.create(
            model=OPENAI_MODEL_TECNICO,
            messages=[{"role": "system", "content": CONTEXT_ROUTER_PROMPT}, {"role": "user", "content": f"Context: {active_ctx}\nMsg: {text}"}],
            response_format={ "type": "json_object" }
        )
        return json.loads(res.choices[0].message.content)
    except: return {"intent": "NORMAL_CHAT"}

def build_chat_input(user_text, history, active_context):
    messages = []
    for h in history:
        messages.append({"role": h['role'], "content": h['content']})
    messages.append({"role": "user", "content": f"Context: {active_context}\n{user_text}"})
    return messages

# ---------------------------------------------------
# 🔥 MANEJO DE MENSAJES (Streaming)
# ---------------------------------------------------
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_text = update.message.text or ""
    status_message = None 
    full_response_raw_text = ""

    try:
        config = await get_bot_config_async(chat_id)
        history = await get_recent_history_async(chat_id)
        active_ctx = await build_active_context_async(chat_id)
        route = await classify_contextual_route_async(user_text, chat_id, history, active_ctx)
        intent = route.get("intent", "NORMAL_CHAT")

        client, model = await get_best_client_and_model(intent)
        input_msgs = build_chat_input(user_text, history, active_ctx)

        response_stream = await client.chat.completions.create(
            model=model, messages=[{"role": "system", "content": build_runtime_system_prompt(config)}] + input_msgs,
            temperature=0.4, stream=True
        )

        status_message = await update.message.reply_text("...")
        words_to_edit = 0

        async for chunk in response_stream:
            content = getattr(chunk.choices[0].delta, 'content', "")
            if not content: continue
            full_response_raw_text += content
            
            if "[FINAL_RESPONSE]" in full_response_raw_text:
                final_text = full_response_raw_text.split("[FINAL_RESPONSE]")[-1].replace("[/FINAL_RESPONSE]", "").strip()
                words_to_edit += 1
                if words_to_edit > 15 or "\n" in content:
                    try:
                        await context.bot.edit_message_text(chat_id=chat_id, message_id=status_message.message_id, text=final_text)
                        await asyncio.sleep(0.05)
                    except: pass
                    words_to_edit = 0

        final_ans = full_response_raw_text.split("[FINAL_RESPONSE]")[-1].replace("[/FINAL_RESPONSE]", "").strip() if "[FINAL_RESPONSE]" in full_response_raw_text else full_response_raw_text
        await context.bot.edit_message_text(chat_id=chat_id, message_id=status_message.message_id, text=final_ans)
        await save_memory_async(chat_id, "user", user_text)
        await save_memory_async(chat_id, "assistant", final_ans)
        
    except Exception as e:
        logging.error(f"Error: {e}")

# ---------------------------------------------------
# PANEL Y START
# ---------------------------------------------------
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"🏛️ Bozi-bot Elite Online.\nModo Híbrido Async activado.\nCEO: Iván.")

def start_typing_loop_sync(chat_id: int):
    # Simplificado para no fallar
    return lambda: None

# ---------------------------------------------------
# INICIO
# ---------------------------------------------------
# ---------------------------------------------------
# INICIO (VERSION REFORZADA)
# ---------------------------------------------------
if __name__ == "__main__":
    # Server simple para Render
    class SimpleH(BaseHTTPRequestHandler):
        def do_GET(self): 
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"OK")
    
    threading.Thread(target=lambda: HTTPServer(("0.0.0.0", int(os.environ.get("PORT", 10000))), SimpleH).serve_forever(), daemon=True).start()
    
    # --- CONFIGURACIÓN REFORZADA CONTRA TIMEOUTS ---
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).read_timeout(30).write_timeout(30).connect_timeout(30).pool_timeout(30).build()
    
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    
    logging.info("Bozi-bot Central Brain (Reinforced) listo.")
    
    # Agregamos drop_pending_updates para limpiar mensajes viejos acumulados
    app.run_polling(drop_pending_updates=True, timeout=20)
