# ===================================================
# 🏛️ BOZI-BOT: EL CEREBRO HÍBRIDO ASINCRÓNICO DE ELITE
# Versión: 3.4 (SEMANTIC MEMORY + STABLE ROUTING)
# ===================================================

import os
import logging
import base64
import requests
import threading
import time
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
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")

# Modelo estable para evitar el 404
OPENROUTER_MODEL_NAME = "mistralai/mistral-7b-instruct-v0.1"
OPENAI_MODEL_NAME = "gpt-4o-mini"

openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)
openrouter_client = AsyncOpenAI(base_url="https://openrouter.ai/api/v1", api_key=OPENROUTER_API_KEY)
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

TECH_KEYWORDS = ["error", "log", "configurá", "ataque", "hacker", "ip", "script", "python", "vulnerabilidad", "maestría", "ceupe"]

# ---------------------------------------------------
# 🧠 CEREBRO SEMÁNTICO (RAG)
# ---------------------------------------------------

async def get_embedding(text):
    """Genera el vector para guardar en la memoria semántica"""
    try:
        res = await openai_client.embeddings.create(input=text, model="text-embedding-3-small")
        return res.data[0].embedding
    except: return None

async def search_memory(chat_id, query_text):
    """Busca en la tabla bot_knowledge que creaste en Supabase"""
    vector = await get_embedding(query_text)
    if not vector: return ""
    try:
        res = supabase.rpc("match_knowledge", {
            "query_embedding": vector,
            "match_threshold": 0.5,
            "match_count": 3,
            "p_chat_id": chat_id
        }).execute()
        if res.data:
            return "\n\n💡 [MEMORIA DEL SISTEMA]:\n" + "\n".join([d['content'] for d in res.data])
        return ""
    except: return ""

async def save_to_memory(chat_id, text):
    """Guarda info técnica importante automáticamente"""
    vector = await get_embedding(text)
    if vector:
        try:
            supabase.table("bot_knowledge").insert({
                "chat_id": chat_id, "content": text, "embedding": vector
            }).execute()
        except: pass

# ---------------------------------------------------
# 🌐 DASHBOARD Y HANDLERS (Igual a V3.3.2)
# ---------------------------------------------------
class DashboardHandler(BaseHTTPRequestHandler):
    def do_HEAD(self): self.send_response(200); self.end_headers()
    def do_GET(self):
        if self.path in ["/projects", "/dashboard"]:
            try:
                res = supabase.table("projects").select("*").execute()
                rows = "".join([f"<div style='border:1px solid #444; padding:15px; margin:10px; border-radius:8px; background:#1e1e1e;'><h2 style='color:#00ffcc; margin-top:0;'>{p['name']}</h2><p style='color:#ccc;'>{p['url']}</p></div>" for p in res.data])
                html = f"<html><body style='background:#121212; color:white; font-family:sans-serif; padding:20px;'><h1>🏛️ Panel de Iván</h1>{rows}</body></html>"
                self.send_response(200); self.send_header("Content-type", "text/html"); self.end_headers(); self.wfile.write(html.encode())
            except: self.send_response(500); self.end_headers()
        else: self.send_response(200); self.end_headers(); self.wfile.write(b"Online")

# ---------------------------------------------------
# 🤖 LÓGICA DE MENSAJES
# ---------------------------------------------------
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_text = update.message.text
    await context.bot.send_chat_action(chat_id=chat_id, action=constants.ChatAction.TYPING)
    
    # 1. Buscar en la memoria semántica
    memoria = await search_memory(chat_id, user_text)
    
    # 2. Decidir modelo (Híbrido)
    is_tech = any(w in user_text.lower() for w in TECH_KEYWORDS)
    client = openai_client if is_tech else openrouter_client
    model = OPENAI_MODEL_NAME if is_tech else OPENROUTER_MODEL_NAME
    
    try:
        messages = [{"role": "system", "content": f"Sos Bozi-bot. {memoria}"}, {"role": "user", "content": user_text}]
        res = await client.chat.completions.create(model=model, messages=messages)
        ans = res.choices[0].message.content
        await update.message.reply_text(ans)
        
        # 3. Si es técnico, guardar en la memoria semántica para el futuro
        if is_tech:
            await save_to_memory(chat_id, f"Iván preguntó: {user_text}. Respuesta: {ans}")
            
    except Exception as e:
        await update.message.reply_text(f"Error: {str(e)[:50]}")

# ---------------------------------------------------
# 🚀 INICIO
# ---------------------------------------------------
if __name__ == "__main__":
    for i in range(2): requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/deleteWebhook?drop_pending_updates=True")
    
    threading.Thread(target=lambda: HTTPServer(("0.0.0.0", int(os.environ.get("PORT", 10000))), DashboardHandler).serve_forever(), daemon=True).start()

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    
    logging.info("🚀 Bozi-bot V3.4 (Semantic Memory) Iniciado")
    time.sleep(10)
    app.run_polling(drop_pending_updates=True)
