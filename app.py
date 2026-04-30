# ===================================================
# 🏛️ BOZI-BOT: EL CEREBRO HÍBRIDO ASINCRÓNICO DE ELITE
# Versión: 3.0 (FULL COMMANDS + MANUAL SELECT + KILL SWITCH)
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
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, CommandHandler, CallbackQueryHandler, filters
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
        logging.info("🧹 Conflictos de Telegram limpiados.")
    except Exception as e:
        logging.error(f"❌ Error en Kill Switch: {e}")

# ---------------------------------------------------
# 🏛️ FUNCIONES DE DATOS (Supabase)
# ---------------------------------------------------
async def get_config(chat_id):
    try:
        res = supabase.table("bot_config").select("*").eq("chat_id", chat_id).execute()
        return res.data[0] if res.data else {}
    except: return {}

async def update_model_pref(chat_id, model_name):
    try:
        supabase.table("bot_config").upsert({
            "chat_id": chat_id, 
            "selected_model": model_name,
            "updated_at": datetime.now(LOCAL_TZ).isoformat()
        }).execute()
    except Exception as e:
        logging.error(f"Error guardando modelo: {e}")

async def get_history(chat_id):
    try:
        res = supabase.table("bot_memory").select("role, content").eq("chat_id", chat_id).order("created_at", desc=True).limit(20).execute()
        return list(reversed(res.data)) if res.data else []
    except: return []

async def safe_save(chat_id, role, content):
    try:
        supabase.table("bot_memory").insert({"chat_id": chat_id, "role": role, "content": content}).execute()
    except: pass

# ---------------------------------------------------
# 🔥 COMANDOS (Handlers)
# ---------------------------------------------------
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🏛️ Bozi-bot Elite Online.\nUsa /models para elegir tu IA o /config para ver el estado.\nCEO: Iván.")

async def cmd_config(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    config = await get_config(chat_id)
    
    modelo = config.get("selected_model", "openai (default)")
    modo = config.get("mode", "asistente")
    
    texto = (
        f"⚙️ *Configuración de Bozi-bot*\n\n"
        f"🧠 *Modelo Activo:* {modelo.upper()}\n"
        f"🛠️ *Modo:* {modo}\n"
        f"📅 *Actualizado:* {config.get('updated_at', 'N/A')}"
    )
    await update.message.reply_text(texto, parse_mode="Markdown")

async def cmd_models(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🤖 OpenAI (gpt-4o-mini)", callback_data='set_mod_openai')],
        [InlineKeyboardButton("☁️ OpenRouter (Gemma Gratis)", callback_data='set_mod_gemma')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Iván, seleccioná el cerebro activo:", reply_markup=reply_markup)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    nuevo_modelo = "openai" if query.data == 'set_mod_openai' else "gemma"
    await update_model_pref(query.message.chat_id, nuevo_modelo)
    await query.edit_message_text(text=f"✅ Ahora estoy usando {nuevo_modelo.upper()}.")

# ---------------------------------------------------
# 🧠 PROCESAMIENTO DE MENSAJES
# ---------------------------------------------------
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_text = update.message.text or ""
    status = await update.message.reply_text("...")

    try:
        config = await get_config(chat_id)
        history = await get_history(chat_id)
        pref = config.get("selected_model", "openai")
        
        try:
            with open("self.txt", "r", encoding="utf-8") as f: personality = f.read().strip()
        except: personality = "Sos Bozi-bot, asistente de Iván."

        messages = [{"role": "system", "content": f"{personality}\nFecha: {datetime.now(LOCAL_TZ)}"}]
        for h in history: messages.append({"role": h["role"], "content": h["content"]})
        messages.append({"role": "user", "content": user_text})

        ans = ""
        # Lógica de motores con orden según preferencia
        engines = [(openai_client, OPENAI_MODEL_TECNICO), (openrouter_client, OPENROUTER_MODEL_CHAT)]
        if pref == "gemma": engines = list(reversed(engines))

        for client, model in engines:
            try:
                res = await client.chat.completions.create(model=model, messages=messages, temperature=0.5)
                ans = res.choices[0].message.content
                break 
            except Exception as e:
                if "429" in str(e):
                    logging.warning(f"⚠️ Rate limit en {model}. Reintentando con motor alternativo...")
                    continue
                else: raise e

        if not ans: raise Exception("Sin respuesta de los proveedores de IA.")

        # Limpieza de tags y respuesta limpia
        ans = re.sub(r"\[/?INTERNAL_MONOLOGUE\]|\[/?FINAL_RESPONSE\]", "", ans).strip()
        
        await context.bot.edit_message_text(chat_id=chat_id, message_id=status.message_id, text=ans)
        await safe_save(chat_id, "user", user_text)
        await safe_save(chat_id, "assistant", ans)

    except Exception as e:
        logging.error(f"❌ ERROR: {e}")
        await context.bot.edit_message_text(chat_id=chat_id, message_id=status.message_id, text=f"Error: {str(e)[:60]}...")

# ---------------------------------------------------
# BOOT
# ---------------------------------------------------
if __name__ == "__main__":
    kill_telegram_conflicts(TELEGRAM_TOKEN)
    
    class H(BaseHTTPRequestHandler):
        def do_GET(self): self.send_response(200); self.end_headers(); self.wfile.write(b"OK")
    threading.Thread(target=lambda: HTTPServer(("0.0.0.0", int(os.environ.get("PORT", 10000))), H).serve_forever(), daemon=True).start()
    
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).read_timeout(30).build()
    
    # Registro de Handlers
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("models", cmd_models))
    app.add_handler(CommandHandler("config", cmd_config))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    
    logging.info("🚀 Bozi-bot V3.0 (Full Deploy) DESPLEGADO")
    app.run_polling(drop_pending_updates=True)
