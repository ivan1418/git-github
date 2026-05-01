# ===================================================
# 🏛️ BOZI-BOT: EL CEREBRO HÍBRIDO ASINCRÓNICO DE ELITE
# Versión: 5.0 (THE FINAL ARCHITECT - FULL PERSISTENCE)
# ===================================================

import os
import logging
import json
import requests
import threading
import time
import asyncio
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler

from telegram import Update, constants
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, CommandHandler, filters
from openai import AsyncOpenAI
from supabase import create_client

# ---------------------------------------------------
# ⚙️ CONFIGURACIÓN Y CLIENTES
# ---------------------------------------------------
logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")

openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# ---------------------------------------------------
# 🛠️ PERSISTENCIA DE CONFIGURACIÓN (DB, NO RAM)
# ---------------------------------------------------

async def get_config(chat_id):
    """Recupera la configuración del usuario de la DB"""
    try:
        res = supabase.table("user_config").select("*").eq("chat_id", int(chat_id)).execute()
        if res.data: return res.data[0]
        # Default si no existe
        return {"model": "gpt-4o", "lang": "Rosario/Voseo"}
    except: return {"model": "gpt-4o", "lang": "Rosario/Voseo"}

async def set_config(chat_id, key, value):
    """Guarda la configuración en la DB"""
    try:
        supabase.table("user_config").upsert({"chat_id": int(chat_id), key: value}).execute()
    except Exception as e: logging.error(f"Error set_config: {e}")

# ---------------------------------------------------
# 🧠 MEMORIA SEMÁNTICA Y APRENDIZAJE
# ---------------------------------------------------

async def save_to_memory(chat_id, user_text, bot_response):
    content = f"Iván: {user_text}\nBozi-bot: {bot_response}"
    try:
        res_emb = await openai_client.embeddings.create(input=content, model="text-embedding-3-small")
        embedding = res_emb.data[0].embedding
        supabase.table("bot_knowledge").insert({
            "chat_id": int(chat_id), "content": content, "embedding": embedding
        }).execute()
    except Exception as e: logging.error(f"Error memoria: {e}")

async def get_semantic_memory(chat_id, query):
    try:
        res_emb = await openai_client.embeddings.create(input=query, model="text-embedding-3-small")
        vector = res_emb.data[0].embedding
        res = supabase.rpc("match_knowledge", {
            "query_embedding": vector, "match_threshold": 0.5, "match_count": 3, "p_chat_id": int(chat_id)
        }).execute()
        return "\n\n💡 [MEMORIA]:\n" + "\n".join([d['content'] for d in res.data]) if res.data else ""
    except: return ""

# ---------------------------------------------------
# 🚀 ORQUESTADOR DE ACCIONES (TAREAS, PROYECTOS, WEB)
# ---------------------------------------------------

async def manage_actions(chat_id, text):
    low_text = text.lower()
    
    # 1. PUBLICACIÓN: De Borrador a URL Real
    if "publicalo" in low_text:
        try:
            # Recuperar el último contexto de la charla para generar el HTML
            last_context = await get_semantic_memory(chat_id, "proyecto")
            res_ia = await openai_client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "system", "content": f"Basado en este borrador: {last_context}, generá un HTML profesional con Tailwind CSS."},
                          {"role": "user", "content": text}]
            )
            html_code = res_ia.choices[0].message.content
            res_db = supabase.table("projects").insert({
                "chat_id": int(chat_id), "content": html_code, "status": "published", "title": "Published Project"
            }).execute()
            p_id = res_db.data[0]['id']
            return f"🚀 **¡Proyecto Publicado!**\nURL: {os.getenv('RENDER_EXTERNAL_URL')}/view/{p_id}"
        except Exception as e: return f"❌ Error en Publicación: {e}"

    # 2. GESTIÓN DE TAREAS (CREATE/UPDATE/DELETE)
    triggers = ["recordame", "agendá", "mañana", "editá tarea", "borrá tarea", "todos los días"]
    if any(w in low_text for w in triggers):
        try:
            res_ia = await openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "system", "content": f"Hoy es {datetime.now()}. Analizá: {{'action': 'create|update|delete', 'desc': '', 'date': 'YYYY-MM-DD HH:MM:SS'}}. Respondé solo JSON."},
                          {"role": "user", "content": text}],
                response_format={"type": "json_object"}
            )
            data = json.loads(res_ia.choices[0].message.content)
            if data['action'] == 'create':
                supabase.table("scheduled_tasks").insert({"chat_id": int(chat_id), "description": data['desc'], "scheduled_at": data['date'], "status": "pending"}).execute()
                return f"✅ Agendado: {data['desc']} para {data['date']}"
            elif data['action'] == 'update':
                # Lógica de edición sobre la última tarea
                last = supabase.table("scheduled_tasks").select("id").eq("chat_id", int(chat_id)).order("created_at", desc=True).limit(1).execute()
                if last.data:
                    supabase.table("scheduled_tasks").update({"description": data['desc'], "scheduled_at": data['date']}).eq("id", last.data[0]['id']).execute()
                    return f"🔄 Tarea editada con éxito."
        except Exception as e: return f"⚠️ Error en Tarea: {e}"
    
    return None

# ---------------------------------------------------
# 🤖 HANDLERS DE COMANDOS
# ---------------------------------------------------

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🏛️ **Bozi-bot V5.0 Online.**\n\n/tasks - Pendientes\n/projects - Publicaciones\n/config - Ajustes\n/status - Sistema")

async def config_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conf = await get_config(update.effective_chat.id)
    await update.message.reply_text(f"⚙️ **Configuración (Persistente):**\n\n🧠 Modelo: {conf['model']}\n🇦🇷 Dialecto: {conf['lang']}")

async def tasks_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    res = supabase.table("scheduled_tasks").select("*").eq("chat_id", update.effective_chat.id).eq("status", "pending").execute()
    msg = "\n".join([f"📌 {t['scheduled_at']}: {t['description']}" for t in res.data]) if res.data else "No hay tareas."
    await update.message.reply_text(f"📝 **Tareas:**\n{msg}")

# ---------------------------------------------------
# 🤖 MENSAJES Y VISIÓN
# ---------------------------------------------------

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_text = update.message.text
    if not user_text: return

    await context.bot.send_chat_action(chat_id=chat_id, action=constants.ChatAction.TYPING)
    
    # 1. Acción (Tareas/Pub)
    action_res = await manage_actions(chat_id, user_text)
    if action_res: return await update.message.reply_text(action_res, parse_mode='Markdown')

    # 2. Cerebro
    conf = await get_config(chat_id)
    memoria = await get_semantic_memory(chat_id, user_text)
    
    # Web Search inteligente (Tavily) si la IA detecta que necesita info fresca
    web_data = ""
    if any(w in user_text.lower() for w in ["actual", "precio", "noticia", "vulnerabilidad", "cyber"]):
        try:
            res_tavily = requests.post("https://api.tavily.com/search", json={"api_key": TAVILY_API_KEY, "query": user_text}).json()
            web_data = "\n\n🌐 [WEB]: " + str(res_tavily.get("results", [])[:2])
        except: pass

    try:
        res = await openai_client.chat.completions.create(
            model=conf['model'],
            messages=[{"role": "system", "content": f"Dialecto: {conf['lang']}.\n{memoria}{web_data}"},
                      {"role": "user", "content": user_text}]
        )
        bot_response = res.choices[0].message.content
        await update.message.reply_text(bot_response)
        asyncio.create_task(save_to_memory(chat_id, user_text, bot_response))
    except Exception as e: await update.message.reply_text(f"❌ Error Crítico: {e}")

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """REINTEGRADA: Visión Técnica"""
    chat_id = update.effective_chat.id
    photo_file = await update.message.photo[-1].get_file()
    await context.bot.send_chat_action(chat_id=chat_id, action=constants.ChatAction.TYPING)
    try:
        res = await openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": [{"type": "text", "text": "Analizá técnicamente esta imagen (Senior IT Rosario)."},
                                                 {"type": "image_url", "image_url": {"url": photo_file.file_path}}]}]
        )
        await update.message.reply_text(f"👁️ **Análisis de Visión**:\n{res.choices[0].message.content}")
    except Exception as e: await update.message.reply_text(f"❌ Error en Visión: {e}")

# ---------------------------------------------------
# 🌐 INFRAESTRUCTURA Y WORKER
# ---------------------------------------------------

class DashboardHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/view/"):
            try:
                p_id = self.path.split("/")[-1]
                res = supabase.table("projects").select("content").eq("id", p_id).execute()
                if res.data:
                    self.send_response(200); self.send_header("Content-type", "text/html"); self.end_headers()
                    self.wfile.write(res.data[0]['content'].encode())
                    return
            except: pass
        self.send_response(200); self.end_headers()
        self.wfile.write(b"Bozi-bot V5.0 Online")

async def task_worker(bot):
    while True:
        try:
            now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            res = supabase.table("scheduled_tasks").select("*").eq("status", "pending").lte("scheduled_at", now).execute()
            for t in res.data:
                await bot.send_message(chat_id=t['chat_id'], text=f"🔔 **RECORDATORIO**: {t['description']}")
                supabase.table("scheduled_tasks").update({"status": "completed"}).eq("id", t['id']).execute()
        except: pass
        await asyncio.sleep(60)

if __name__ == "__main__":
    # 1. Limpieza de Webhooks previos (Estabilidad)
    requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/deleteWebhook?drop_pending_updates=True")
    
    # 2. Servidor Web
    port = int(os.environ.get("PORT", 10000))
    threading.Thread(target=lambda: HTTPServer(("0.0.0.0", port), DashboardHandler).serve_forever(), daemon=True).start()

    # 3. Bot
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("config", config_cmd))
    app.add_handler(CommandHandler("tasks", tasks_cmd))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    
    loop = asyncio.get_event_loop()
    loop.create_task(task_worker(app.bot))
    
    logging.info("🚀 Bozi-bot V5.0 INSUPERABLE Online.")
    app.run_polling()
