# ===================================================
# 🏛️ BOZI-BOT: EL CEREBRO HÍBRIDO ASINCRÓNICO DE ELITE
# Versión: 3.9.1 (REAL HTML PUB + PERSISTENCE + SELECTOR)
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
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)
openrouter_client = AsyncOpenAI(base_url="https://openrouter.ai/api/v1", api_key=OPENROUTER_API_KEY)
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# Configuración dinámica de modelo
USER_CONFIG = {"model": "gpt-4o"} 

# ---------------------------------------------------
# 🧠 MEMORIA ACTIVA Y APRENDIZAJE
# ---------------------------------------------------

async def save_interaction_to_memory(chat_id, user_text, bot_response):
    """Guarda la charla y genera embeddings para que el bot 'aprenda'"""
    content = f"Iván: {user_text}\nBozi-bot: {bot_response}"
    try:
        res_emb = await openai_client.embeddings.create(input=content, model="text-embedding-3-small")
        embedding = res_emb.data[0].embedding
        
        supabase.table("bot_knowledge").insert({
            "chat_id": int(chat_id),
            "content": content,
            "embedding": embedding,
            "created_at": datetime.now().isoformat()
        }).execute()
        logging.info(f"🧠 Memoria persistente actualizada para {chat_id}")
    except Exception as e:
        logging.error(f"❌ Error en persistencia de memoria: {e}")

# ---------------------------------------------------
# 🚀 ACCIONES: PUBLICACIÓN REAL (HTML)
# ---------------------------------------------------

async def publish_project_content(chat_id, user_text):
    """Genera y guarda contenido HTML real en la base de datos"""
    if "publicalo" not in user_text.lower():
        return None
    
    try:
        # 1. La IA genera el código HTML basado en la idea previa
        res = await openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": "Generá un archivo HTML5 profesional y autocontenido basado en la idea del usuario. Usá CSS moderno (Tailwind CDN)."},
                      {"role": "user", "content": f"Proyecto para Iván: {user_text}"}]
        )
        html_code = res.choices[0].message.content
        
        # 2. Insertamos en projects con el contenido real
        res_db = supabase.table("projects").insert({
            "chat_id": int(chat_id),
            "content": html_code,
            "status": "published",
            "title": f"Proyecto {datetime.now().strftime('%d/%m')}"
        }).execute()
        
        p_id = res_db.data[0]['id']
        url = f"{SUPABASE_URL}/rest/v1/projects?id=eq.{p_id}&select=content" # Link técnico de visualización
        return f"🚀 **¡Proyecto publicado con contenido real!**\nPodés ver el código generado aquí: {url}\n(Nota: Para ver el renderizado necesitás el frontend del Panel Completo)."
    except Exception as e:
        logging.error(f"❌ Fallo en publicación: {e}")
        return f"⚠️ Error al publicar: {e}"

# ---------------------------------------------------
# 🤖 COMANDOS Y MENSAJES
# ---------------------------------------------------

async def model_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Selector de modelo rápido"""
    if context.args and context.args[0] in ["gpt-4o", "gpt-4o-mini"]:
        USER_CONFIG["model"] = context.args[0]
        await update.message.reply_text(f"✅ Modelo cambiado a: {USER_CONFIG['model']}")
    else:
        await update.message.reply_text("Uso: /model [gpt-4o|gpt-4o-mini]")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_text = update.message.text
    if not user_text: return

    await context.bot.send_chat_action(chat_id=chat_id, action=constants.ChatAction.TYPING)

    # 1. Intentar Publicación Real primero
    pub_res = await publish_project_content(chat_id, user_text)
    if pub_res:
        await update.message.reply_text(pub_res)
        return

    # 2. Búsqueda Semántica (Memoria)
    memoria = ""
    try:
        res_emb = await openai_client.embeddings.create(input=user_text, model="text-embedding-3-small")
        mem_res = supabase.rpc("match_knowledge", {
            "query_embedding": res_emb.data[0].embedding, 
            "match_threshold": 0.5, 
            "match_count": 2, 
            "p_chat_id": int(chat_id)
        }).execute()
        if mem_res.data:
            memoria = "\n\n💡 [MEMORIA ACTIVA]:\n" + "\n".join([d['content'] for d in mem_res.data])
    except Exception as e:
        logging.error(f"Error recuperando memoria: {e}")

    # 3. Generación de Respuesta
    rules = get_file_content("rules.txt")
    self_info = get_file_content("self.txt")
    system_prompt = f"{self_info}\n\nREGLAS:\n{rules}\n{memoria}"

    try:
        res = await openai_client.chat.completions.create(
            model=USER_CONFIG["model"],
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_text}]
        )
        bot_response = res.choices[0].message.content
        await update.message.reply_text(bot_response)
        
        # 4. APRENDIZAJE: Guardar para el futuro
        await save_interaction_to_memory(chat_id, user_text, bot_response)
        
    except Exception as e:
        logging.error(f"Error crítico: {e}")
        await update.message.reply_text(f"❌ Fallo: {e}")

# ---------------------------------------------------
# 🌐 INFRAESTRUCTURA
# ---------------------------------------------------

if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    
    app.add_handler(CommandHandler("model", model_cmd))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    
    # El worker y el dashboard se mantienen de versiones anteriores
    loop = asyncio.get_event_loop()
    loop.create_task(task_worker(app.bot)) 
    
    logging.info(f"🚀 Bozi-bot V3.9.1 Online (Model: {USER_CONFIG['model']})")
    app.run_polling(drop_pending_updates=True)
