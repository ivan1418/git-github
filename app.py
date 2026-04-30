# ===================================================
# 🏛️ BOZI-BOT: EL CEREBRO HÍBRIDO ASINCRÓNICO DE ELITE
# Versión: 2.8 (TIER 1 OPTIMIZED + AUTO-RETRY + KILL SWITCH)
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

# Telegram e IA
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, CommandHandler, filters
from openai import AsyncOpenAI
from supabase import create_client

# ---------------------------------------------------
# ⚙️ CONFIGURACIÓN
# ---------------------------------------------------
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)

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
    url = f"https://api.telegram.org/bot{token}/deleteWebhook?drop_pending_updates=True"
    try:
        requests.post(url, timeout=10)
        logging.info("🧹 Limpieza de conflictos completada.")
    except Exception as e:
        logging.error(f"❌ Error en Kill Switch: {e}")

# ---------------------------------------------------
# 🏛️ FUNCIONES DE DATOS (REFORZADAS)
# ---------------------------------------------------
async def get_config(chat_id):
    try:
        res = supabase.table("bot_config").select("*").eq("chat_id", chat_id).execute()
        return res.data[0] if res.data else {}
    except: return {}

async def get_history(chat_id):
    try:
        res = supabase.table("bot_memory").select("role, content").eq("chat_id", chat_id).order("created_at", desc=True).limit(10).execute()
        return list(reversed(res.data)) if res.data else []
    except: return []

async def safe_save(chat_id, role, content):
    try:
        supabase.table("bot_memory").insert({"chat_id": chat_id, "role": role, "content": content}).execute()
    except: pass

# ---------------------------------------------------
# 🔥 PROCESAMIENTO DE MENSAJES (OPTIMIZADO TIER 1)
# ---------------------------------------------------
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_text = update.message.text or ""
    status = await update.message.reply_text("...")

    try:
        # 1. Carga de datos
        config = await get_config(chat_id)
        history = await get_history(chat_id)
        
        # 2. Router Optimizado (Ahorra llamadas en Tier 1)
        intent = "NORMAL_CHAT"
        if len(user_text) > 15:
            try:
                route_res = await openai_client.chat.completions.create(
                    model=OPENAI_MODEL_TECNICO,
                    messages=[{"role": "system", "content": "JSON: {'intent': 'NORMAL_CHAT' | 'CIBERSEC_TASK'}"}, {"role": "user", "content": user_text}],
                    response_format={"type": "json_object"},
                    temperature=0
                )
                intent = json.loads(route_res.choices[0].message.content).get("intent", "NORMAL_CHAT")
            except: pass

        # 3. Preparación de mensajes
        with open("self.txt", "r", encoding="utf-8") as f: personality = f.read().strip()
        messages = [{"role": "system", "content": f"{personality}\nFecha: {datetime.now(LOCAL_TZ)}"}]
        for h in history: messages.append({"role": h["role"], "content": h["content"]})
        messages.append({"role": "user", "content": user_text})

        # 4. Generación con Reintento por Rate Limit (429)
        ans = ""
        for attempt in range(3):
            try:
                client = openrouter_client if intent == "NORMAL_CHAT" else openai_client
                model = OPENROUTER_MODEL_CHAT if intent == "NORMAL_CHAT" else OPENAI_MODEL_TECNICO
                
                res = await client.chat.completions.create(model=model, messages=messages, temperature=0.5)
                ans = res.choices[0].message.content
                break 
            except Exception as e:
                if "429" in str(e) and attempt < 2:
                    logging.warning(f"⚠️ Rate limit Tier 1. Reintentando en 2.5s...")
                    await asyncio.sleep(2.5)
                else: raise e

        # 5. Limpieza y Envío
        ans = re.sub(r"\[/?INTERNAL_MONOLOGUE\]|\[/?FINAL_RESPONSE\]", "", ans).strip()
        await context.bot.edit_message_text(chat_id=chat_id, message_id=status.message_id, text=ans)
        await safe_save(chat_id, "user", user_text)
        await safe_save(chat_id, "assistant", ans)

    except Exception as e:
        logging.error(f"❌ ERROR: {e}")
        await context.bot.edit_message_text(chat_id=chat_id, message_id=status.message_id, text=f"Error: {str(e)[:50]}... Reintentá en un momento.")

# ---------------------------------------------------
# START Y BOOT
# ---------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🏛️ Bozi-bot Online. Modo persistente activado.")

if __name__ == "__main__":
    kill_telegram_conflicts(TELEGRAM_TOKEN)
    
    class H(BaseHTTPRequestHandler):
        def do_GET(self): self.send_response(200); self.end_headers(); self.wfile.write(b"OK")
    threading.Thread(target=lambda: HTTPServer(("0.0.0.0", int(os.environ.get("PORT", 10000))), H).serve_forever(), daemon=True).start()
    
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).read_timeout(30).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    
    logging.info("🚀 Bozi-bot V2.8 DESPLEGADO")
    app.run_polling(drop_pending_updates=True)
