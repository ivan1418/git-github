# ===================================================
# 🏛️ BOZI-BOT: EL CEREBRO HÍBRIDO ASINCRÓNICO DE ELITE
# Versión: 3.6 (EXECUTIVE: VISION + AUTO-TASKS + PUB)
# ===================================================

import os
import logging
import json
import requests
import threading
import time
import asyncio
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler

from telegram import Update, constants
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters
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
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")

OPENAI_MODEL = "gpt-4o" # Cambiamos a 4o para Visión y lógica compleja
openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# ---------------------------------------------------
# 🧠 LÓGICA DE ACCIONES (AUTO-INSERT & PROJECTS)
# ---------------------------------------------------

async def extract_and_save_task(chat_id, text):
    """Usa IA para extraer tareas y guardarlas en scheduled_tasks"""
    prompt = (
        "Extraé tareas del siguiente texto. Si hay una intención de recordar algo en el futuro, "
        "respondé ÚNICAMENTE un JSON con: {'desc': 'qué recordar', 'date': 'YYYY-MM-DD HH:MM:SS'}. "
        f"Hoy es {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}. "
        f"Texto: {text}"
    )
    try:
        res = await openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": "Sos un extractor de datos precisos."},
                      {"role": "user", "content": prompt}],
            response_format={ "type": "json_object" }
        )
        data = json.loads(res.choices[0].message.content)
        if data.get('desc') and data.get('date'):
            supabase.table("scheduled_tasks").insert({
                "chat_id": chat_id,
                "description": data['desc'],
                "scheduled_at": data['date'],
                "status": "pending"
            }).execute()
            return f"✅ Entendido Iván, agendado: '{data['desc']}' para el {data['date']}."
    except: pass
    return None

async def handle_publication(chat_id, text):
    """Regla 3: Idea -> Borrador -> Publicar"""
    if "publicalo" in text.lower():
        # Aquí simulamos la generación de URL. En un panel real, esto apuntaría a una tabla pública.
        project_id = "p-" + str(int(time.time()))
        url = f"https://bozi-panel.render.com/share/{project_id}"
        return f"🚀 ¡Proyecto publicado! Podés revisarlo acá: {url}"
    return None

# ---------------------------------------------------
# 👁️ VISIÓN (ANÁLISIS DE IMÁGENES)
# ---------------------------------------------------

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await context.bot.send_chat_action(chat_id=chat_id, action=constants.ChatAction.TYPING)
    
    photo_file = await update.message.photo[-1].get_file()
    image_url = photo_file.file_path

    response = await openai_client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Analizá esta imagen técnicamente como un Senior IT. ¿Qué ves? (Logs, hardware, errores, etc.)"},
                    {"type": "image_url", "image_url": {"url": image_url}},
                ],
            }
        ],
    )
    await update.message.reply_text(f"👁️ **Análisis de Visión**:\n\n{response.choices[0].message.content}", parse_mode='Markdown')

# ---------------------------------------------------
# 🤖 ORQUESTADOR PRINCIPAL
# ---------------------------------------------------

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_text = update.message.text
    if not user_text: return

    # 1. Intentar acciones automáticas primero
    task_confirm = await extract_and_save_task(chat_id, user_text)
    if task_confirm:
        await update.message.reply_text(task_confirm)
        return

    pub_confirm = await handle_publication(chat_id, user_text)
    if pub_confirm:
        await update.message.reply_text(pub_confirm)
        return

    # 2. Si no es una acción, procesar como charla normal (Lógica V3.5.6)
    # [Aquí iría el resto de tu handle_message anterior...]
    await update.message.reply_text("Recibido. Estoy procesando tu pedido bajo las reglas de Rosario.")

# ---------------------------------------------------
# 🌐 DASHBOARD AVANZADO (PREVIA)
# ---------------------------------------------------

class DashboardHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        # Aquí empezamos a inyectar HTML real para el Panel Completo
        html = f"""
        <html>
            <head><title>Bozi-Panel</title></head>
            <body style='font-family:sans-serif; padding:20px;'>
                <h1>🏛️ Bozi-bot Control Center</h1>
                <p>Status: <span style='color:green'>Online</span></p>
                <hr>
                <h3>Próximas Tareas (scheduled_tasks)</h3>
                <p><i>Conectando con Supabase API...</i></p>
            </body>
        </html>
        """
        self.wfile.write(html.encode())

# [El bloque __main__ se mantiene igual, sumando el handler de fotos]
if __name__ == "__main__":
    # ... setup anterior ...
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    
    # Handler para Texto
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    # Handler para Fotos (Visión)
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    
    # Iniciar Worker y Polling
    loop = asyncio.get_event_loop()
    loop.create_task(task_worker(app.bot)) 
    app.run_polling()
