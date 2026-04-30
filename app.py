# ===================================================
# 🏛️ BOZI-BOT: EL CEREBRO HÍBRIDO ASINCRÓNICO DE ELITE
# Versión: 2.6 (ULTRA-STABLE + DEBUG + KILL SWITCH)
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
# 🧹 KILL SWITCH
# ---------------------------------------------------
def kill_telegram_conflicts(token):
    url = f"https://api.telegram.org/bot{token}/deleteWebhook?drop_pending_updates=True"
    try:
        requests.post(url, timeout=10)
        logging.info("🧹 Limpieza de conflictos completada.")
    except Exception as e:
        logging.error(f"❌ Error en Kill Switch: {e}")

# ---------------------------------------------------
# 🤖 PERSONALIDAD
# ---------------------------------------------------
def load_personality():
    try:
        with open("self.txt", "r", encoding="utf-8") as f:
            return f.read().strip()
    except:
        return "Sos Bozi-bot, asistente técnico de Iván."

PERSONALITY = load_personality()

# ---------------------------------------------------
# 🏛️ FUNCIONES DE DATOS (REFORZADAS CON FALLBACK)
# ---------------------------------------------------
async def get_config(chat_id):
    try:
        res = supabase.table("bot_config").select("*").eq("chat_id", chat_id).execute()
        return res.data[0] if res.data else {}
    except Exception as e:
        logging.error(f"DB Error (Config): {e}")
        return {}

async def get_history(chat_id):
    try:
        res = supabase.table("bot_memory").select("role, content").eq("chat_id", chat_id).order("created_at", desc=True).limit(20).execute()
        return list(reversed(res.data)) if res.data else []
    except Exception as e:
        logging.error(f"DB Error (History): {e}")
        return []

async def safe_save(chat_id, role, content):
    try:
        supabase.table("bot_memory").insert({"chat_id": chat_id, "role": role, "content": content}).execute()
    except Exception as e:
        logging.error(f"DB Error (Save): {e}")

# ---------------------------------------------------
# 🔥 PROCESAMIENTO DE MENSAJES
# ---------------------------------------------------
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_text = update.message.text or ""
    status = await update.message.reply_text("...")

    try:
        # 1. Obtener contexto (con resiliencia)
        config = await get_config(chat_id)
        history = await get_history(chat_id)
        
        # 2. Router (Siempre OpenAI para inteligencia)
        intent = "NORMAL_CHAT"
        try:
            route_res = await openai_client.chat.completions.create(
                model=OPENAI_MODEL_TECNICO,
                messages=[{"role": "system", "content": "Decide intent: NORMAL_CHAT or CIBERSEC_TASK. Return JSON: {'intent': '...'}"}, {"role": "user", "content": user_text}],
                response_format={"type": "json_object"}
            )
            intent = json.loads(route_res.choices[0].message.content).get("intent", "NORMAL_CHAT")
        except: pass

        # 3. Elección de Motor Híbrido
        client = openai_client if intent == "CIBERSEC_TASK" else openrouter_client
        model = OPENAI_MODEL_TECNICO if intent == "CIBERSEC_TASK" else OPENROUTER_MODEL_CHAT

        # 4. Generar respuesta
        messages = [{"role": "system", "content": f"{PERSONALITY}\nResponde de forma natural."}]
        for h in history:
            messages.append({"role": h["role"], "content": h["content"]})
        messages.append({"role": "user", "content": user_text})

        response = await client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.5
        )
        
        ans = response.choices[0].message.content
        
        # Limpieza simple de tags si existieran
        ans = re.sub(r"\[/?INTERNAL_MONOLOGUE\]|\[/?FINAL_RESPONSE\]", "", ans).strip()

        # 5. Enviar y Guardar
        await context.bot.edit_message_text(chat_id=chat_id, message_id=status.message_id, text=ans)
        await safe_save(chat_id, "user", user_text)
        await safe_save(chat_id, "assistant", ans)

    except Exception as e:
        logging.error(f"❌ ERROR CRÍTICO: {e}")
        await context.bot.edit_message_text(chat_id=chat_id, message_id=status.message_id, text=f"Error técnico: {str(e)[:100]}")

# ---------------------------------------------------
# START Y BOOT
# ---------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🏛️ Bozi-bot Elite Online. Sistema reforzado.")

if __name__ == "__main__":
    kill_telegram_conflicts(TELEGRAM_TOKEN)
    
    # Healthcheck para Render
    class H(BaseHTTPRequestHandler):
        def do_GET(self): self.send_response(200); self.end_headers(); self.wfile.write(b"OK")
    threading.Thread(target=lambda: HTTPServer(("0.0.0.0", int(os.environ.get("PORT", 10000))), H).serve_forever(), daemon=True).start()
    
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    
    logging.info("🚀 Bozi-bot V2.6 DESPLEGADO")
    app.run_polling(drop_pending_updates=True)
