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

# --- 1. SERVIDOR DE SALUD (Fix para Render Timed Out) ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(b"Bozi-bot is online and kicking!")

def run_health_check():
    # Usa el puerto 10000 configurado en tus variables de Render
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
    logging.info(f"Health check server activo en puerto {port}")
    server.serve_forever()

# --- 2. CONFIGURACIÓN INICIAL ---
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# Clientes de API
supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))
groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))
tavily_client = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))

# Función de Embeddings (Usa Hugging Face para no agotar la RAM de Render)
def get_embedding(text):
    model_id = "sentence-transformers/all-MiniLM-L6-v2"
    api_url = f"https://api-inference.huggingface.co/models/{model_id}"
    headers = {"Authorization": f"Bearer {os.getenv('HF_TOKEN', '')}"}
    for _ in range(3):
        try:
            response = requests.post(api_url, headers=headers, json={"inputs": text}, timeout=15)
            if response.status_code == 200:
                return response.json()
            time.sleep(2)
        except:
            continue
    return None

# --- 3. SYSTEM PROMPT PERSONALIZADO ---
SYSTEM_PROMPT = (
    "Actuá como Bozi-bot, un asistente experto en IT Infrastructure y Cybersecurity. "
    "Tu tono debe ser profesional, amable, divertido y extremadamente eficiente. "
    "REGLAS CRÍTICAS DE RESPUESTA: "
    "1. COHERENCIA: Usarás el historial de conversación y datos de internet para ser preciso. "
    "2. CONCISIÓN: No des introducciones innecesarias. Ve directo al grano. "
    "3. RAZONAMIENTO: Analizá si la información sigue las mejores prácticas de ciberseguridad. "
    "4. BREVEDAD: Respondé corto y conciso (máximo 3-4 párrafos). "
    "5. IDIOMA: Respondé en español rioplatense con términos técnicos en inglés. "
    "Si no sabés algo, admitilo."
)

# --- 4. LÓGICA DE MENSAJES ---
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_text = update.message.text
    
    # Generar vector y guardar en Supabase
    vector = get_embedding(user_text)
    supabase.table("bot_memory").insert({
        "chat_id": chat_id, "role": "user", "content": user_text, "embedding": vector
    }).execute()
    
    # Buscar contexto actual en internet con Tavily
    try:
        search_res = tavily_client.search(query=user_text, max_results=2)
        context_data = f"Contexto internet actual (2026): {search_res['results']}"
    except:
        context_data = "No se pudo obtener información reciente de internet."

    # Recuperar historial de Supabase (últimos 6 mensajes)
    res = supabase.table("bot_memory").select("role, content").eq("chat_id", chat_id).order("created_at", desc=True).limit(6).execute()
    
    # Armar lista de mensajes para Groq
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "system", "content": context_data}
    ]
    for m in reversed(res.data):
        messages.append({"role": m["role"], "content": m["content"]})

    # Inferencia con IA (Llama 3.3 en Groq)
    try:
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=messages,
            temperature=0.6
        )
        answer = response.choices[0].message.content
    except Exception as e:
        logging.error(f"Error en Groq: {e}")
        answer = "Che Iván, se me tildó el rack de la IA. Bancame un toque y volvé a probar."

    # Guardar respuesta y enviar a Telegram
    supabase.table("bot_memory").insert({
        "chat_id": chat_id, "role": "assistant", "content": answer
    }).execute()
    
    await update.message.reply_text(answer)

# --- 5. EJECUCIÓN ---
if __name__ == '__main__':
    # Lanzar el servidor de salud en un hilo separado
    threading.Thread(target=run_health_check, daemon=True).start()

    # Configurar el Bot de Telegram
    token = os.getenv("TELEGRAM_TOKEN")
    application = ApplicationBuilder().token(token).build()
    
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    
    logging.info("Bozi-bot listo para la acción...")
    
    # drop_pending_updates=True mata el error 409 Conflict al reiniciar
    application.run_polling(drop_pending_updates=True)
