# ===================================================
# 🏛️ BOZI-BOT: EL CEREBRO HÍBRIDO ASINCRÓNICO DE ELITE
# Versión: 4.2 (THE FORTRESS: FULL PERSISTENCE + WEB + PUB)
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
# 🧠 MEMORIA SEMÁNTICA Y APRENDIZAJE (EL CABLE QUE FALTABA)
# ---------------------------------------------------

async def save_to_memory(chat_id, user_text, bot_response):
    """Genera embeddings y guarda en bot_knowledge para aprender de la charla"""
    content = f"Iván: {user_text}\nBozi-bot: {bot_response}"
    try:
        res_emb = await openai_client.embeddings.create(input=content, model="text-embedding-3-small")
        embedding = res_emb.data[0].embedding
        supabase.table("bot_knowledge").insert({
            "chat_id": int(chat_id), "content": content, "embedding": embedding
        }).execute()
        logging.info(f"🧠 Memoria semántica actualizada para {chat_id}")
    except Exception as e:
        logging.error(f"❌ Error guardando memoria: {e}")

async def get_semantic_memory(chat_id, query):
    """Busca contexto relevante en charlas pasadas"""
    try:
        res_emb = await openai_client.embeddings.create(input=query, model="text-embedding-3-small")
        vector = res_emb.data[0].embedding
        res = supabase.rpc("match_knowledge", {
            "query_embedding": vector, "match_threshold": 0.5, "match_count": 3, "p_chat_id": int(chat_id)
        }).execute()
        return "\n\n💡 [MEMORIA PASADA]:\n" + "\n".join([d['content'] for d in res.data]) if res.data else ""
    except: return ""

# ---------------------------------------------------
# 🌐 WEB SEARCH (TAVILY INTEGRATION)
# ---------------------------------------------------

def web_search(query):
    if not TAVILY_API_KEY: return ""
    try:
        url = "https://api.tavily.com/search"
        payload = {"api_key": TAVILY_API_KEY, "query": query, "search_depth": "smart"}
        res = requests.post(url, json=payload, timeout=10).json()
        results = [f"- {r['title']}: {r['content']} ({r['url']})" for r in res.get("results", [])]
        return "\n\n🌐 [WEB SEARCH]:\n" + "\n".join(results)
    except: return ""

# ---------------------------------------------------
# 🚀 ACCIONES CRUD Y PUBLICACIÓN REAL
# ---------------------------------------------------

async def manage_actions(chat_id, text):
    """Orquestador de Tareas y Proyectos"""
    low_text = text.lower()
    
    # PUBLICAR PROYECTO REAL (Guarda HTML en DB)
    if "publicalo" in low_text or "generar url" in low_text:
        try:
            res_ia = await openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "system", "content": "Generá un HTML5 profesional (Tailwind CSS) basado en el pedido del usuario."},
                          {"role": "user", "content": text}]
            )
            html_code = res_ia.choices[0].message.content
            res_db = supabase.table("projects").insert({
                "chat_id": int(chat_id), "content": html_code, "status": "published", "title": "Auto-Gen Project"
            }).execute()
            p_id = res_db.data[0]['id']
            # Esta URL ahora es funcional gracias al DashboardHandler de abajo
            url = f"{os.getenv('RENDER_EXTERNAL_URL')}/view/{p_id}"
            return f"🚀 **¡Proyecto publicado!**\nIván, podés verlo acá: {url}"
        except Exception as e: return f"❌ Error publicando: {e}"

    # CREAR TAREA (Lenguaje Natural)
    if any(w in low_text for w in ["recordame", "agendá", "mañana", "a las"]):
        try:
            res_ia = await openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "system", "content": f"Hoy es {datetime.now()}. Respondé solo JSON: {{'desc': '', 'date': 'YYYY-MM-DD HH:MM:SS'}}"},
                          {"role": "user", "content": text}],
                response_format={"type": "json_object"}
            )
            data = json.loads(res_ia.choices[0].message.content)
            supabase.table("scheduled_tasks").insert({
                "chat_id": int(chat_id), "description": data['desc'], "scheduled_at": data['date'], "status": "pending"
            }).execute()
            return f"✅ Tarea agendada para {data['date']}: {data['desc']}"
        except: pass
    return None

# ---------------------------------------------------
# 🤖 ORQUESTADOR Y HANDLERS
# ---------------------------------------------------

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_text = update.message.text
    if not user_text: return

    await context.bot.send_chat_action(chat_id=chat_id, action=constants.ChatAction.TYPING)

    # 1. Intentar acción primero
    action_res = await manage_actions(chat_id, user_text)
    if action_res:
        return await update.message.reply_text(action_res, parse_mode='Markdown')

    # 2. Obtener Contexto: Reglas + Memoria + Web
    rules = get_file_content("rules.txt")
    self_info = get_file_content("self.txt")
    memoria = await get_semantic_memory(chat_id, user_text)
    web_info = web_search(user_text) if any(w in user_text.lower() for w in ["noticia", "actual", "vulnerabilidad"]) else ""

    system_prompt = f"{self_info}\n\n{rules}\n{memoria}{web_info}"

    try:
        res = await openai_client.chat.completions.create(
            model="gpt-4o", 
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_text}]
        )
        bot_response = res.choices[0].message.content
        await update.message.reply_text(bot_response)
        
        # 3. APRENDIZAJE: Guardar de forma asíncrona
        asyncio.create_task(save_to_memory(chat_id, user_text, bot_response))
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")

# ---------------------------------------------------
# 🌐 DASHBOARD: RENDERIZADO DE PROYECTOS (EL CABLE FINAL)
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
        self.send_response(200); self.send_header("Content-type", "text/html"); self.end_headers()
        self.wfile.write(b"<h1>Bozi-bot V4.2 Online</h1>")

# ---------------------------------------------------
# 🚀 INICIO (IDEM V4.1 PERO CON TODO CONECTADO)
# ---------------------------------------------------
# [Mantener el bloque __main__ de la V4.1 con todos los CommandHandlers]
