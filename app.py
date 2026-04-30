# ===================================================
# 🏛️ BOZI-BOT: EL CEREBRO HÍBRIDO ASINCRÓNICO DE ELITE
# Versión: 3.1 (VISION + HYBRID FIX + TYPING STATUS)
# ===================================================

import os
import re
import json
import logging
import base64
import asyncio 
from datetime import datetime
from zoneinfo import ZoneInfo

# Telegram e IA
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, constants
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
OPENAI_MODEL = "gpt-4o-mini"
OPENROUTER_MODEL = "google/gemma-7b-it:free"

openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)
openrouter_client = AsyncOpenAI(base_url="https://openrouter.ai/api/v1", api_key=OPENROUTER_API_KEY)
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# ---------------------------------------------------
# 🏛️ HELPERS
# ---------------------------------------------------
async def get_config(chat_id):
    try:
        res = supabase.table("bot_config").select("*").eq("chat_id", chat_id).execute()
        return res.data[0] if res.data else {}
    except: return {}

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
# 👁️ VISIÓN: PROCESAMIENTO DE IMÁGENES
# ---------------------------------------------------
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    # Indicamos que estamos analizando la imagen
    await context.bot.send_chat_action(chat_id=chat_id, action=constants.ChatAction.TYPING)
    status = await update.message.reply_text("🧐 Analizando imagen...")

    try:
        photo_file = await update.message.photo[-1].get_file()
        photo_bytes = await photo_file.download_as_bytearray()
        base64_image = base64.b64encode(photo_bytes).decode('utf-8')

        prompt = update.message.caption or "Analizá esta imagen detalladamente como un experto en ciberseguridad e infraestructura."
        
        # Las imágenes SIEMPRE van a OpenAI (Gemma no tiene visión)
        response = await openai_client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
                    ],
                }
            ],
            max_tokens=500
        )
        
        ans = response.choices[0].message.content
        await context.bot.edit_message_text(chat_id=chat_id, message_id=status.message_id, text=ans)
        await safe_save(chat_id, "user", f"[IMAGEN]: {prompt}")
        await safe_save(chat_id, "assistant", ans)

    except Exception as e:
        await context.bot.edit_message_text(chat_id=chat_id, message_id=status.message_id, text=f"Error analizando imagen: {str(e)[:100]}")

# ---------------------------------------------------
# 🧠 LÓGICA DE MENSAJES (HÍBRIDO REAL)
# ---------------------------------------------------
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_text = update.message.text or ""
    
    # 1. Enviar estado "Escribiendo..."
    await context.bot.send_chat_action(chat_id=chat_id, action=constants.ChatAction.TYPING)
    status = await update.message.reply_text("...")

    try:
        history = await get_history(chat_id)
        
        # 2. Router Híbrido Simplificado
        # Si el texto tiene palabras técnicas, usamos OpenAI. Si es charla, OpenRouter.
        tech_keywords = ["error", "log", "configurá", "ataque", "hacker", "ip", "script", "codigo", "python", "base de datos"]
        is_technical = any(word in user_text.lower() for word in tech_keywords)
        
        # Si es técnico -> OpenAI | Si es charla -> OpenRouter
        client = openai_client if is_technical else openrouter_client
        model = OPENAI_MODEL if is_technical else OPENROUTER_MODEL
        
        logging.info(f"Ruteando mensaje a: {model}")

        messages = [{"role": "system", "content": "Sos Bozi-bot, el asistente experto de Iván. Respondé de forma humana y profesional en español."}]
        for h in history: messages.append({"role": h["role"], "content": h["content"]})
        messages.append({"role": "user", "content": user_text})

        # Generación con un solo reintento de fallback
        try:
            res = await client.chat.completions.create(model=model, messages=messages, temperature=0.7)
            ans = res.choices[0].message.content
        except:
            # Fallback de emergencia a OpenAI si OpenRouter falla
            res = await openai_client.chat.completions.create(model=OPENAI_MODEL, messages=messages)
            ans = res.choices[0].message.content

        await context.bot.edit_message_text(chat_id=chat_id, message_id=status.message_id, text=ans)
        await safe_save(chat_id, "user", user_text)
        await safe_save(chat_id, "assistant", ans)

    except Exception as e:
        await context.bot.edit_message_text(chat_id=chat_id, message_id=status.message_id, text=f"Error: {str(e)[:50]}")

# ---------------------------------------------------
# 🚀 BOOT & COMANDOS
# ---------------------------------------------------
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🏛️ Bozi-bot V3.1 Online.\nAhora puedo ver tus imágenes y fotos de logs.\nIndicador 'Escribiendo' activo.")

if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo)) # Handler de visión
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    
    logging.info("🚀 Bozi-bot V3.1 (Vision + Typing) Iniciado")
    app.run_polling()
