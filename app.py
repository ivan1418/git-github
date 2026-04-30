# ===================================================
# 🏛️ BOZI-BOT: EL CEREBRO HÍBRIDO ASINCRÓNICO DE ELITE
# Versión: 3.2 (PROJECTS + TASKS + WEB SEARCH + CONFIG FIX)
# ===================================================

import os
import re
import json
import logging
import base64
import asyncio 
import requests
import threading
from datetime import datetime
from zoneinfo import ZoneInfo
from http.server import HTTPServer, BaseHTTPRequestHandler

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
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")

LOCAL_TZ = ZoneInfo("America/Argentina/Buenos_Aires")
OPENAI_MODEL = "gpt-4o-mini"
OPENROUTER_MODEL = "google/gemma-7b-it:free"

openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)
openrouter_client = AsyncOpenAI(base_url="https://openrouter.ai/api/v1", api_key=OPENROUTER_API_KEY)
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# ---------------------------------------------------
# 🏛️ HELPERS DE DATOS
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
# 🔍 WEB SEARCH (TAVILY)
# ---------------------------------------------------
async def search_web(query):
    try:
        url = "https://api.tavily.com/search"
        payload = {
            "api_key": TAVILY_API_KEY,
            "query": query,
            "search_depth": "advanced",
            "max_results": 3
        }
        response = requests.post(url, json=payload)
        results = response.json().get("results", [])
        return "\n".join([f"- {r['title']}: {r['url']}\n  {r['content'][:200]}..." for r in results])
    except Exception as e:
        logging.error(f"Error en Tavily: {e}")
        return ""

# ---------------------------------------------------
# 📁 GESTIÓN DE PROYECTOS Y TAREAS
# ---------------------------------------------------
async def cmd_add_project(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    text = " ".join(context.args)
    if not text or "|" not in text:
        await update.message.reply_text("Uso: /add_project Nombre | URL | Descripcion")
        return
    
    parts = [p.strip() for p in text.split("|")]
    name = parts[0]
    url = parts[1] if len(parts) > 1 else ""
    desc = parts[2] if len(parts) > 2 else ""

    try:
        supabase.table("projects").insert({
            "chat_id": chat_id,
            "name": name,
            "url": url,
            "description": desc
        }).execute()
        await update.message.reply_text(f"✅ Proyecto '{name}' guardado correctamente.")
    except Exception as e:
        await update.message.reply_text(f"❌ Error al guardar: {e}")

async def cmd_list_projects(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    try:
        res = supabase.table("projects").select("*").eq("chat_id", chat_id).execute()
        if not res.data:
            await update.message.reply_text("No tenés proyectos registrados.")
            return
        
        msg = "📂 **Tus Proyectos:**\n\n"
        for p in res.data:
            msg += f"🔹 **{p['name']}**\n🔗 {p['url']}\n📝 {p['description']}\n\n"
        await update.message.reply_text(msg, parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ Error al listar: {e}")

async def cmd_list_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    try:
        res = supabase.table("scheduled_tasks").select("*").eq("chat_id", chat_id).execute()
        if not res.data:
            await update.message.reply_text("No hay tareas programadas.")
            return
        
        msg = "⏳ **Tareas Programadas:**\n\n"
        for t in res.data:
            msg += f"✅ {t['task_name']} - {t['status']}\n📅 {t['due_date']}\n\n"
        await update.message.reply_text(msg)
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")

# ---------------------------------------------------
# ⚙️ CONFIG (FIXED)
# ---------------------------------------------------
async def cmd_config(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    config = await get_config(chat_id)
    modelo = config.get("selected_model", "openai/gemma (hybrid)")
    
    msg = (
        f"⚙️ **Estado de Bozi-bot**\n\n"
        f"👤 **Usuario:** Iván\n"
        f"🧠 **Modelo:** {modelo.upper()}\n"
        f"🛰️ **Web Search:** Activo (Tavily)\n"
        f"👁️ **Visión:** GPT-4o-mini"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

# ---------------------------------------------------
# 👁️ VISIÓN
# ---------------------------------------------------
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await context.bot.send_chat_action(chat_id=chat_id, action=constants.ChatAction.TYPING)
    status = await update.message.reply_text("🧐 Analizando imagen con GPT-4o-mini...")

    try:
        photo_file = await update.message.photo[-1].get_file()
        photo_bytes = await photo_file.download_as_bytearray()
        base64_image = base64.b64encode(photo_bytes).decode('utf-8')
        prompt = update.message.caption or "Analizá esta imagen como experto en ciberseguridad."
        
        response = await openai_client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[{"role": "user", "content": [{"type": "text", "text": prompt}, {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}]}],
            max_tokens=500
        )
        ans = response.choices[0].message.content
        await context.bot.edit_message_text(chat_id=chat_id, message_id=status.message_id, text=ans)
        await safe_save(chat_id, "user", f"[IMAGEN]: {prompt}")
        await safe_save(chat_id, "assistant", ans)
    except Exception as e:
        await context.bot.edit_message_text(chat_id=chat_id, message_id=status.message_id, text=f"Error: {e}")

# ---------------------------------------------------
# 🧠 LÓGICA HÍBRIDA + WEB SEARCH
# ---------------------------------------------------
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_text = update.message.text or ""
    await context.bot.send_chat_action(chat_id=chat_id, action=constants.ChatAction.TYPING)
    status = await update.message.reply_text("...")

    try:
        history = await get_history(chat_id)
        
        # Router: ¿Necesita buscar en internet?
        search_keywords = ["noticias", "quien es", "hackeo reciente", "buscá", "investigá", "ultimo"]
        needs_search = any(word in user_text.lower() for word in search_keywords)
        
        web_context = ""
        if needs_search:
            await context.bot.edit_message_text(chat_id=chat_id, message_id=status.message_id, text="🔍 Buscando en la web...")
            web_context = await search_web(user_text)

        # Router Híbrido
        tech_keywords = ["error", "log", "configurá", "ataque", "hacker", "ip", "script", "codigo", "python", "sql"]
        is_technical = any(word in user_text.lower() for word in tech_keywords) or needs_search
        
        client = openai_client if is_technical else openrouter_client
        model = OPENAI_MODEL if is_technical else OPENROUTER_MODEL
        
        system_prompt = "Sos Bozi-bot, asistente experto de Iván. "
        if web_context:
            system_prompt += f"\nUsa esta info de internet: {web_context}"

        messages = [{"role": "system", "content": system_prompt}]
        for h in history: messages.append({"role": h["role"], "content": h["content"]})
        messages.append({"role": "user", "content": user_text})

        res = await client.chat.completions.create(model=model, messages=messages, temperature=0.7)
        ans = res.choices[0].message.content

        await context.bot.edit_message_text(chat_id=chat_id, message_id=status.message_id, text=ans)
        await safe_save(chat_id, "user", user_text)
        await safe_save(chat_id, "assistant", ans)

    except Exception as e:
        await context.bot.edit_message_text(chat_id=chat_id, message_id=status.message_id, text=f"Error: {str(e)[:50]}")

# ---------------------------------------------------
# 🚀 BOOT
# ---------------------------------------------------
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🏛️ Bozi-bot V3.2 Online.\nProyectos, Tareas y Búsqueda Web activos.")

if __name__ == "__main__":
    url_delete = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/deleteWebhook?drop_pending_updates=True"
    requests.post(url_delete)
    
    class H(BaseHTTPRequestHandler):
        def do_GET(self): self.send_response(200); self.end_headers(); self.wfile.write(b"OK")
    threading.Thread(target=lambda: HTTPServer(("0.0.0.0", int(os.environ.get("PORT", 10000))), H).serve_forever(), daemon=True).start()

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    
    # HANDLERS REGISTRADOS (Fix config y nuevos comandos)
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("config", cmd_config))
    app.add_handler(CommandHandler("add_project", cmd_add_project))
    app.add_handler(CommandHandler("list_projects", cmd_list_projects))
    app.add_handler(CommandHandler("list_tasks", cmd_list_tasks))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    
    logging.info("🚀 Bozi-bot V3.2 (Sprint 1) Iniciado")
    app.run_polling(drop_pending_updates=True)
