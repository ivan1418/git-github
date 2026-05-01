# ===================================================
# 🏛️ BOZI-BOT: EL CEREBRO HÍBRIDO ASINCRÓNICO DE ELITE
# Versión: 5.1 (PROJECT DRAFTS + TIMEZONE + ERROR FIX)
# ===================================================

import os, logging, json, requests, threading, time, asyncio
from datetime import datetime
import pytz # Para zona horaria Argentina
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
ARG_TZ = pytz.timezone('America/Argentina/Buenos_Aires')

# ---------------------------------------------------
# 🛠️ PERSISTENCIA Y MEMORIA
# ---------------------------------------------------

async def get_config(chat_id):
    try:
        res = supabase.table("user_config").select("*").eq("chat_id", int(chat_id)).execute()
        return res.data[0] if res.data else {"model": "gpt-4o", "lang": "Rosario/Voseo"}
    except Exception as e:
        logging.error(f"Error get_config: {e}")
        return {"model": "gpt-4o", "lang": "Rosario/Voseo"}

async def save_to_memory(chat_id, user_text, bot_response):
    content = f"Iván: {user_text}\nBozi-bot: {bot_response}"
    try:
        res_emb = await openai_client.embeddings.create(input=content, model="text-embedding-3-small")
        embedding = res_emb.data[0].embedding
        supabase.table("bot_knowledge").insert({"chat_id": int(chat_id), "content": content, "embedding": embedding}).execute()
    except Exception as e: logging.error(f"Error memoria: {e}")

# ---------------------------------------------------
# 🚀 GESTIÓN DE PROYECTOS (BORRADOR ACTIVO)
# ---------------------------------------------------

async def update_project_draft(chat_id, update_text):
    """Mantiene un borrador activo del proyecto actual en la DB"""
    try:
        # Buscamos si ya hay un borrador
        res = supabase.table("projects").select("*").eq("chat_id", int(chat_id)).eq("status", "draft").execute()
        new_content = f"Update {datetime.now(ARG_TZ)}: {update_text}"
        if res.data:
            current = res.data[0]['content'] or ""
            supabase.table("projects").update({"content": current + "\n" + new_content}).eq("id", res.data[0]['id']).execute()
        else:
            supabase.table("projects").insert({"chat_id": int(chat_id), "content": new_content, "status": "draft", "title": "Borrador Activo"}).execute()
    except Exception as e: logging.error(f"Error en borrador: {e}")

# ---------------------------------------------------
# 🤖 HANDLERS DE COMANDOS (REGISTRADOS CORRECTAMENTE)
# ---------------------------------------------------

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🏛️ **Bozi-bot V5.1**\n/tasks, /projects, /config, /status, /model [cerebro]")

async def model_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /model para cambio persistente"""
    if context.args and context.args[0] in ["gpt-4o", "gpt-4o-mini"]:
        new_model = context.args[0]
        try:
            supabase.table("user_config").upsert({"chat_id": update.effective_chat.id, "model": new_model}).execute()
            await update.message.reply_text(f"✅ Modelo actualizado a: `{new_model}`", parse_mode='Markdown')
        except Exception as e: await update.message.reply_text(f"❌ Error DB: {e}")
    else:
        await update.message.reply_text("Uso: `/model gpt-4o` o `/model gpt-4o-mini`", parse_mode='Markdown')

async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now(ARG_TZ).strftime('%H:%M:%S')
    conf = await get_config(update.effective_chat.id)
    await update.message.reply_text(f"🖥️ **Status**: Online\n🧠 **AI**: {conf['model']}\n📍 **Zona**: Rosario ({now})")

async def projects_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    res = supabase.table("projects").select("id, status, title").eq("chat_id", update.effective_chat.id).execute()
    msg = "\n".join([f"🚀 ID {p['id']} [{p['status']}] - {p['title']}" for p in res.data]) if res.data else "Sin proyectos."
    await update.message.reply_text(f"📂 **Tus Proyectos:**\n{msg}")

async def tasks_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    res = supabase.table("scheduled_tasks").select("*").eq("chat_id", update.effective_chat.id).eq("status", "pending").execute()
    msg = "\n".join([f"📌 {t['scheduled_at']}: {t['description']}" for t in res.data]) if res.data else "No hay pendientes."
    await update.message.reply_text(f"📝 **Tareas:**\n{msg}")

# ---------------------------------------------------
# 🤖 ORQUESTADOR DE MENSAJES (ACCIONES + MEMORIA)
# ---------------------------------------------------

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_text = update.message.text
    if not user_text: return
    await context.bot.send_chat_action(chat_id=chat_id, action=constants.ChatAction.TYPING)

    # 1. ¿ES UNA PUBLICACIÓN?
    if "publicalo" in user_text.lower():
        res_draft = supabase.table("projects").select("*").eq("chat_id", int(chat_id)).eq("status", "draft").execute()
        if not res_draft.data:
            return await update.message.reply_text("❌ No hay un borrador activo para publicar.")
        
        res_ia = await openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "system", "content": "Generá HTML5 profesional con Tailwind. Respondé SOLO el código, sin ```html."},
                      {"role": "user", "content": f"Borrador actual: {res_draft.data[0]['content']}\n\nInstrucción final: {user_text}"}]
        )
        html_code = res_ia.choices[0].message.content.replace("```html", "").replace("```", "").strip()
        supabase.table("projects").update({"content": html_code, "status": "published"}).eq("id", res_draft.data[0]['id']).execute()
        url = f"{os.getenv('RENDER_EXTERNAL_URL')}/view/{res_draft.data[0]['id']}"
        await update.message.reply_text(f"🚀 **¡Proyecto Publicado!**\n{url}")
        await save_to_memory(chat_id, user_text, f"Proyecto publicado en {url}")
        return

    # 2. ¿ES TRABAJO DE PROYECTO?
    if any(w in user_text.lower() for w in ["proyecto", "bot", "página", "desarrollá", "agregale"]):
        await update_project_draft(chat_id, user_text)

    # 3. RESPUESTA NORMAL CON MEMORIA Y CONFIG
    conf = await get_config(chat_id)
    memoria = await get_semantic_memory(chat_id, user_text)
    try:
        res = await openai_client.chat.completions.create(
            model=conf['model'],
            messages=[{"role": "system", "content": f"Dialecto: {conf['lang']}. TZ: Rosario.\n{memoria}"},
                      {"role": "user", "content": user_text}]
        )
        bot_response = res.choices[0].message.content
        await update.message.reply_text(bot_response)
        await save_interaction_to_memory(chat_id, user_text, bot_response)
    except Exception as e: await update.message.reply_text(f"❌ Error: {e}")

# ---------------------------------------------------
# 👁️ VISIÓN Y OTROS
# ---------------------------------------------------

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    photo_file = await update.message.photo[-1].get_file()
    res = await openai_client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": [{"type": "text", "text": "Analizá técnicamente (Senior IT Rosario)."},
                                             {"type": "image_url", "image_url": {"url": photo_file.file_path}}]}]
    )
    await update.message.reply_text(f"👁️ **Análisis**: {res.choices[0].message.content}")

# ---------------------------------------------------
# 🌐 SERVER & MAIN
# ---------------------------------------------------

class DashboardHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/view/"):
            p_id = self.path.split("/")[-1]
            try:
                res = supabase.table("projects").select("content").eq("id", p_id).execute()
                if res.data:
                    self.send_response(200); self.send_header("Content-type", "text/html"); self.end_headers()
                    self.wfile.write(res.data[0]['content'].encode())
                    return
            except: pass
        self.send_response(200); self.end_headers(); self.wfile.write(b"Bozi-bot 5.1 Online")

if __name__ == "__main__":
    requests.post(f"[https://api.telegram.org/bot](https://api.telegram.org/bot){TELEGRAM_TOKEN}/deleteWebhook?drop_pending_updates=True")
    threading.Thread(target=lambda: HTTPServer(("0.0.0.0", int(os.environ.get("PORT", 10000))), DashboardHandler).serve_forever(), daemon=True).start()
    
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("model", model_cmd))
    app.add_handler(CommandHandler("config", model_cmd)) # Alias
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("tasks", tasks_cmd))
    app.add_handler(CommandHandler("projects", projects_cmd))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    
    loop = asyncio.get_event_loop()
    # task_worker() debería estar definido arriba con la TZ corregida
    app.run_polling()
