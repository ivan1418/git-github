# ===================================================
# 🏛️ BOZI-BOT: EL CEREBRO HÍBRIDO ASINCRÓNICO DE ELITE
# Versión: 3.2.2 (MODELS FIX + CONFIG SYNC + OPENROUTER 404 FIX)
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
OPENAI_MODEL_NAME = "gpt-4o-mini"
# --- FIX: Modelo gratis estable ---
OPENROUTER_MODEL_NAME = "mistralai/mistral-7b-instruct:free" 

openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)
openrouter_client = AsyncOpenAI(base_url="https://openrouter.ai/api/v1", api_key=OPENROUTER_API_KEY)
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# Palabras clave globales
TECH_KEYWORDS = ["error", "log", "configurá", "ataque", "hacker", "ip", "script", "codigo", "python", "sql", "clase", "vulnerabilidad"]
SEARCH_KEYWORDS = ["noticias", "quien es", "hackeo reciente", "buscá", "investigá", "ultimo", "hoy", "argentina"]

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
    parts = [p.strip() for p in text.split("|")]; name = parts[0]
    url = parts[1] if len(parts) > 1 else ""; desc = parts[2] if len(parts) > 2 else ""
    try:
        supabase.table("projects").insert({"chat_id": chat_id, "name": name, "url": url, "description": desc}).execute()
        await update.message.reply_text(f"✅ Proyecto '{name}' guardado.")
    except Exception as e: await update.message.reply_text(f"❌ Error: {e}")

async def cmd_list_projects(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        res = supabase.table("projects").select("*").eq("chat_id", update.effective_chat.id).execute()
        if not res.data: await update.message.reply_text("No hay proyectos."); return
        msg = "📂 **Tus Proyectos:**\n\n"
        for p in res.data: msg += f"🔹 **{p['name']}**\n🔗 {p['url']}\n📝 {p['description']}\n\n"
        await update.message.reply_text(msg, parse_mode="Markdown")
    except Exception as e: await update.message.reply_text(f"❌ Error: {e}")

async def cmd_list_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        res = supabase.table("scheduled_tasks").select("*").eq("chat_id", update.effective_chat.id).execute()
        if not res.data: await update.message.reply_text("No hay tareas."); return
        msg = "⏳ **Tareas:**\n\n"
        for t in res.data: msg += f"✅ {t['task_name']} - {t['status']}\n📅 {t['due_date']}\n\n"
        await update.message.reply_text(msg)
    except Exception as e: await update.message.reply_text(f"❌ Error: {e}")

# ---------------------------------------------------
# ⚙️ CONFIG (SYNCED FIX)
# ---------------------------------------------------
async def cmd_config(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # --- FIX: Sincronización real con el híbrido ---
    msg = (
        f"⚙️ **Estado Real de Bozi-bot**\n\n"
        f"👤 **Usuario:** Iván\n"
        f"🧠 **Lógica:** Híbrida Inteligente Activa\n"
        f"➡️ **Cerebro Superior (Complejo):** {OPENAI_MODEL_NAME.upper()}\n"
        f"➡️ **Cerebro Chat (Casual):** Mistral 7B (Free)\n\n"
        f"🛰️ **Web Search:** Tavily Activo\n"
        f"👁️ **Visión:** GPT-4o-mini"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

# ---------------------------------------------------
# 🤖 MODEL SELECTION (FIXED HANDLER)
# ---------------------------------------------------
async def cmd_models(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # --- FIX: Función de models agregada ---
    keyboard = [
        [InlineKeyboardButton("🧠 Forzar OpenAI (gpt-4o-mini)", callback_data='set_mod_openai')],
        [InlineKeyboardButton("☁️ Forzar OpenRouter (Mistral Free)", callback_data='set_mod_mistral')],
        [InlineKeyboardButton("🔄 Activar Híbrido Automático", callback_data='set_mod_hybrid')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Iván, seleccioná el cerebro activo:", reply_markup=reply_markup)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    nuevo = "openai" if query.data == 'set_mod_openai' else ("mistral" if query.data == 'set_mod_mistral' else "hybrid")
    try:
        supabase.table("bot_config").upsert({"chat_id": query.message.chat_id, "selected_model": nuevo, "updated_at": datetime.now(LOCAL_TZ).isoformat()}).execute()
        await query.edit_message_text(text=f"✅ Configuración actualizada: Ahora estoy usando {nuevo.upper()}.")
    except Exception as e: await query.edit_message_text(text=f"❌ Error guardando config: {e}")

# ---------------------------------------------------
# 👁️ VISIÓN (ALWAYS OPENAI)
# ---------------------------------------------------
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await context.bot.send_chat_action(chat_id=chat_id, action=constants.ChatAction.TYPING)
    status = await update.message.reply_text("🧐 Analizando imagen con GPT-4o-mini...")
    try:
        file = await update.message.photo[-1].get_file(); bytes = await file.download_as_bytearray()
        img64 = base64.b64encode(bytes).decode('utf-8')
        prompt = update.message.caption or "Analizá esta imagen como experto en seguridad."
        res = await openai_client.chat.completions.create(model=OPENAI_MODEL_NAME, messages=[{"role": "user", "content": [{"type": "text", "text": prompt}, {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img64}"}}]}], max_tokens=500)
        ans = res.choices[0].message.content
        await context.bot.edit_message_text(chat_id=chat_id, message_id=status.message_id, text=ans)
        await safe_save(chat_id, "user", f"[IMAGEN]: {prompt}"); await safe_save(chat_id, "assistant", ans)
    except Exception as e: await context.bot.edit_message_text(chat_id=chat_id, message_id=status.message_id, text=f"Error: {e}")

# ---------------------------------------------------
# 🧠 LÓGICA DE MENSAJES (HÍBRIDO REAL)
# ---------------------------------------------------
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_text = update.message.text or ""
    await context.bot.send_chat_action(chat_id=chat_id, action=constants.ChatAction.TYPING)
    status = await update.message.reply_text("...")
    try:
        history = await get_history(chat_id)
        config = await get_config(chat_id)
        
        needs_search = any(word in user_text.lower() for word in SEARCH_KEYWORDS)
        web_context = ""
        if needs_search:
            await context.bot.edit_message_text(chat_id=chat_id, message_id=status.message_id, text="🔍 Buscando en la web...")
            web_context = await search_web(user_text)

        is_technical = any(word in user_text.lower() for word in TECH_KEYWORDS) or needs_search
        
        # Preferencia de usuario
        pref = config.get("selected_model", "hybrid")
        
        # Router Híbrido Final
        if pref == "openai":
            client = openai_client; model = OPENAI_MODEL_NAME
        elif pref == "mistral":
            client = openrouter_client; model = OPENROUTER_MODEL_NAME
        else: # hybrid
            client = openai_client if is_technical else openrouter_client
            model = OPENAI_MODEL_NAME if is_technical else OPENROUTER_MODEL_NAME
        
        system = "Sos Bozi-bot, asistente experto de Iván."
        if web_context: system += f"\nInfo web: {web_context}"
        messages = [{"role": "system", "content": system}]
        for h in history: messages.append({"role": h["role"], "content": h["content"]})
        messages.append({"role": "user", "content": user_text})

        try:
            res = await client.chat.completions.create(model=model, messages=messages, temperature=0.7)
            ans = res.choices[0].message.content
        except: # Emergency Fallback
            res = await openai_client.chat.completions.create(model=OPENAI_MODEL_NAME, messages=messages)
            ans = res.choices[0].message.content

        await context.bot.edit_message_text(chat_id=chat_id, message_id=status.message_id, text=ans)
        await safe_save(chat_id, "user", user_text); await safe_save(chat_id, "assistant", ans)
    except Exception as e: await context.bot.edit_message_text(chat_id=chat_id, message_id=status.message_id, text=f"Error: {str(e)[:50]}")

# ---------------------------------------------------
# 🚀 BOOT
# ---------------------------------------------------
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🏛️ Bozi-bot V3.2.2 Online.\n Fix aplicado en /models y /config.")

if __name__ == "__main__":
    url_delete = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/deleteWebhook?drop_pending_updates=True"
    requests.post(url_delete)
    class H(BaseHTTPRequestHandler):
        def do_GET(self): self.send_response(200); self.end_headers(); self.wfile.write(b"OK")
    threading.Thread(target=lambda: HTTPServer(("0.0.0.0", int(os.environ.get("PORT", 10000))), H).serve_forever(), daemon=True).start()

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    
    # HANDLERS (Asegurando que estén TODOS registrados)
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("config", cmd_config))
    app.add_handler(CommandHandler("models", cmd_models)) # --- FIX: Faltaba esta línea ---
    app.add_handler(CommandHandler("add_project", cmd_add_project))
    app.add_handler(CommandHandler("list_projects", cmd_list_projects))
    app.add_handler(CommandHandler("list_tasks", cmd_list_tasks))
    app.add_handler(CallbackQueryHandler(button_handler)) # --- FIX: Faltaba esta línea ---
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    
    logging.info("🚀 Bozi-bot V3.2.2 Iniciado")
    app.run_polling(drop_pending_updates=True)
