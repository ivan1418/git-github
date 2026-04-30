# ===================================================
# 🏛️ BOZI-BOT: EL CEREBRO HÍBRIDO ASINCRÓNICO DE ELITE
# Versión: 3.3 (DASHBOARD WEB + PROJECT EDITOR + TAVILY)
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
OPENROUTER_MODEL_NAME = "mistralai/mistral-7b-instruct:free" 

openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)
openrouter_client = AsyncOpenAI(base_url="https://openrouter.ai/api/v1", api_key=OPENROUTER_API_KEY)
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

TECH_KEYWORDS = ["error", "log", "configurá", "ataque", "hacker", "ip", "script", "codigo", "python", "sql", "vulnerabilidad"]
SEARCH_KEYWORDS = ["noticias", "quien es", "hackeo reciente", "buscá", "investigá", "ultimo", "hoy"]

# ---------------------------------------------------
# 🌐 SERVIDOR WEB (DASHBOARD DINÁMICO)
# ---------------------------------------------------
class DashboardHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/projects" or self.path == "/dashboard":
            try:
                res = supabase.table("projects").select("*").execute()
                projects = res.data
                
                rows = ""
                for p in projects:
                    rows += f"""
                    <div style='border:1px solid #444; padding:15px; margin:10px; border-radius:8px; background:#1e1e1e;'>
                        <h2 style='color:#00ffcc; margin-top:0;'>{p['name']}</h2>
                        <p style='color:#ccc;'>{p.get('description', 'Sin descripción')}</p>
                        <a href='{p['url']}' target='_blank' style='color:#3399ff; text-decoration:none;'>🔗 Abrir Proyecto</a>
                    </div>
                    """
                
                html = f"""
                <html>
                <head><title>Bozi-Bot Project Visualizer</title>
                <meta name="viewport" content="width=device-width, initial-scale=1">
                <style>body{{font-family:sans-serif; background:#121212; color:white; padding:20px; max-width:800px; margin:auto;}}</style>
                </head>
                <body>
                    <h1 style='text-align:center;'>🏛️ Panel de Proyectos - Iván</h1>
                    <hr style='border:0; border-top:1px solid #333;'>
                    {rows if rows else "<p>No hay proyectos cargados aún.</p>"}
                </body>
                </html>
                """
                self.send_response(200)
                self.send_header("Content-type", "text/html")
                self.end_headers()
                self.wfile.write(html.encode())
            except Exception as e:
                self.send_response(500); self.end_headers()
                self.wfile.write(f"Error cargando dashboard: {e}".encode())
        else:
            self.send_response(200); self.end_headers()
            self.wfile.write(b"Bozi-bot Online")

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
        payload = {"api_key": TAVILY_API_KEY, "query": query, "search_depth": "advanced", "max_results": 3}
        response = requests.post(url, json=payload, timeout=10)
        results = response.json().get("results", [])
        return "\n".join([f"- {r['title']}: {r['url']}\n  {r['content'][:200]}..." for r in results])
    except Exception as e:
        logging.error(f"Error en Tavily: {e}"); return ""

# ---------------------------------------------------
# 📁 COMANDOS DE GESTIÓN
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

async def cmd_edit_project(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = " ".join(context.args)
    if not text or "|" not in text:
        await update.message.reply_text("Uso: /edit_project NombreActual | NuevoNombre | NuevaURL")
        return
    parts = [p.strip() for p in text.split("|")]
    try:
        supabase.table("projects").update({"name": parts[1], "url": parts[2]}).eq("name", parts[0]).execute()
        await update.message.reply_text(f"✅ Proyecto '{parts[0]}' actualizado.")
    except Exception as e: await update.message.reply_text(f"❌ Error: {e}")

async def cmd_list_projects(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        res = supabase.table("projects").select("*").eq("chat_id", update.effective_chat.id).execute()
        if not res.data: await update.message.reply_text("No hay proyectos."); return
        msg = "📂 **Tus Proyectos:**\n\n"
        for p in res.data: msg += f"🔹 **{p['name']}**\n🔗 [Ver Dashboard](https://git-github-47x8.onrender.com/projects)\n🔗 [URL Directa]({p['url']})\n\n"
        await update.message.reply_text(msg, parse_mode="Markdown")
    except Exception as e: await update.message.reply_text(f"❌ Error: {e}")

# ---------------------------------------------------
# 🧠 LÓGICA DE MENSAJES E IMÁGENES
# ---------------------------------------------------
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await context.bot.send_chat_action(chat_id=chat_id, action=constants.ChatAction.TYPING)
    status = await update.message.reply_text("🧐 Analizando imagen con Visión GPT-4o-mini...")
    try:
        file = await update.message.photo[-1].get_file(); bytes_img = await file.download_as_bytearray()
        img64 = base64.b64encode(bytes_img).decode('utf-8')
        prompt = update.message.caption or "Analizá esta imagen como experto en seguridad."
        res = await openai_client.chat.completions.create(model=OPENAI_MODEL_NAME, messages=[{"role": "user", "content": [{"type": "text", "text": prompt}, {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img64}"}}]}], max_tokens=500)
        ans = res.choices[0].message.content
        await context.bot.edit_message_text(chat_id=chat_id, message_id=status.message_id, text=ans)
        await safe_save(chat_id, "user", f"[IMAGEN]: {prompt}"); await safe_save(chat_id, "assistant", ans)
    except Exception as e: await context.bot.edit_message_text(chat_id=chat_id, message_id=status.message_id, text=f"Error: {e}")

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
        pref = config.get("selected_model", "hybrid")
        
        if pref == "openai" or is_technical:
            client = openai_client; model = OPENAI_MODEL_NAME
        else:
            client = openrouter_client; model = OPENROUTER_MODEL_NAME
        
        system = "Sos Bozi-bot, asistente experto de Iván."
        if web_context: system += f"\nInformación web reciente: {web_context}"
        
        messages = [{"role": "system", "content": system}]
        for h in history: messages.append({"role": h["role"], "content": h["content"]})
        messages.append({"role": "user", "content": user_text})

        res = await client.chat.completions.create(model=model, messages=messages, temperature=0.7)
        ans = res.choices[0].message.content
        await context.bot.edit_message_text(chat_id=chat_id, message_id=status.message_id, text=ans)
        await safe_save(chat_id, "user", user_text); await safe_save(chat_id, "assistant", ans)
    except Exception as e: await context.bot.edit_message_text(chat_id=chat_id, message_id=status.message_id, text=f"Error: {str(e)[:50]}")

# ---------------------------------------------------
# 🚀 BOOT
# ---------------------------------------------------
async def cmd_config(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (f"⚙️ **Estado Real de Bozi-bot V3.3**\n\n👤 **Usuario:** Iván\n🧠 **Cerebro Superior:** OpenAI GPT-4o-mini\n🧠 **Cerebro Chat:** Mistral 7B (Free)\n\n"
           f"🔗 [Abrir Panel de Proyectos](https://git-github-47x8.onrender.com/projects)")
    await update.message.reply_text(msg, parse_mode="Markdown")

if __name__ == "__main__":
    requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/deleteWebhook?drop_pending_updates=True")
    
    threading.Thread(target=lambda: HTTPServer(("0.0.0.0", int(os.environ.get("PORT", 10000))), DashboardHandler).serve_forever(), daemon=True).start()

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    
    app.add_handler(CommandHandler("start", lambda u, c: u.message.reply_text("🏛️ Bozi-bot V3.3 Online.\nDashboard en /projects.")))
    app.add_handler(CommandHandler("config", cmd_config))
    app.add_handler(CommandHandler("add_project", cmd_add_project))
    app.add_handler(CommandHandler("edit_project", cmd_edit_project))
    app.add_handler(CommandHandler("list_projects", cmd_list_projects))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    
    logging.info("🚀 Bozi-bot V3.3 (Dashboard Activo) Iniciado")
    app.run_polling(drop_pending_updates=True)
