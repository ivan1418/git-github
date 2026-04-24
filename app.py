import os
import logging
import requests
import time
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters
from supabase import create_client
from groq import Groq
from tavily import TavilyClient

# --- 1. SERVIDOR DE SALUD PARA RENDER ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(b"Bozi-bot is alive")

def run_health_check_server():
    # Usa el puerto 10000 que tenés configurado
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
    logging.info(f"Servidor de salud escuchando en el puerto {port}")
    server.serve_forever()

# --- 2. CONFIGURACIÓN DEL BOT ---
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))
groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))
tavily_client = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))

def get_embedding(text):
    model_id = "sentence-transformers/all-MiniLM-L6-v2"
    api_url = f"https://api-inference.huggingface.co/models/{model_id}"
    headers = {"Authorization": f"Bearer {os.getenv('HF_TOKEN', '')}"}
    for _ in range(3):
        try:
            response = requests.post(api_url, headers=headers, json={"inputs": text}, timeout=15)
            if response.status_code == 200: return response.json()
            time.sleep(2)
        except: continue
    return None

SYSTEM_PROMPT = "Sos Bozi-bot, experto en IT. Respondé corto y conciso en español rioplatense."

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_text = update.message.text
    
    # Memoria
    vector = get_embedding(user_text)
    supabase.table("bot_memory").insert({"chat_id": chat_id, "role": "user", "content": user_text, "embedding": vector}).execute()
    
    # Actualidad
    try:
        search_res = tavily_client.search(query=user_text, max_results=2)
        context_data = f"Info internet: {search_res['results']}"
    except: context_data = "No hay datos nuevos."

    # Historial
    res = supabase.table("bot_memory").select("role, content").eq("chat_id", chat_id).order("created_at", desc=True).limit(6).execute()
    messages = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "system", "content": context_data}]
    for m in reversed(res.data):
        messages.append({"role": m["role"], "content": m["content"]})

    # IA y Respuesta
    try:
        response = groq_client.chat.completions.create(model="llama-3.3-70b-versatile", messages=messages)
        answer = response.choices[0].message.content
    except: answer = "Perdón Iván, falló la conexión con la IA."

    supabase.table("bot_memory").insert({"chat_id": chat_id, "role": "assistant", "content": answer}).execute()
    await update.message.reply_text(answer)

if __name__ == '__main__':
    # Arrancamos el servidor de salud en un hilo aparte para que no bloquee al bot
    threading.Thread(target=run_health_check_server, daemon=True).start()

    # Iniciamos Telegram
    token = os.getenv("TELEGRAM_TOKEN")
    application = ApplicationBuilder().token(token).build()
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    
    logging.info("Bozi-bot online...")
    # Limpiamos actualizaciones pendientes para evitar el error 409 Conflict
    application.run_polling(drop_pending_updates=True)
