import os
import logging
import requests
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters
from supabase import create_client
from groq import Groq
from tavily import TavilyClient

# 1. Configuración de Logs e Infraestructura
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# Inicialización de Clientes (Variables de entorno en Render)
supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))
groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))
tavily_client = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))

# Función para generar embeddings vía API (Evita el error de memoria RAM en Render)
def get_embedding(text):
    model_id = "sentence-transformers/all-MiniLM-L6-v2"
    api_url = f"https://api-inference.huggingface.co/models/{model_id}"
    # Usamos el token de Hugging Face si existe, sino va sin auth (con límites)
    headers = {"Authorization": f"Bearer {os.getenv('HF_TOKEN', '')}"}
    try:
        response = requests.post(api_url, headers=headers, json={"inputs": text}, timeout=10)
        return response.json()
    except Exception as e:
        logging.error(f"Error al obtener embedding: {e}")
        return None

# --- SYSTEM PROMPT DE BOZI-BOT ---
SYSTEM_PROMPT = (
    "Actuá como Bozi-bot, un asistente experto en IT Infrastructure y Cybersecurity. "
    "Tu tono debe ser profesional, amable y extremadamente eficiente. "
    "REGLAS CRÍTICAS: "
    "1. COHERENCIA: Usá el historial y datos de internet para ser preciso. "
    "2. CONCISIÓN: Sin intros largas. Directo al grano. "
    "3. RAZONAMIENTO: Analizá si la info sigue las mejores prácticas de seguridad. "
    "4. BREVEDAD: Máximo 3 párrafos. "
    "5. IDIOMA: Español rioplatense con términos técnicos en inglés. "
    "Si no sabés algo, admitilo."
)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_text = update.message.text

    # --- PASO 1: MEMORIA INTELIGENTE (EMBEDDING) ---
    vector = get_embedding(user_text)
    
    # Guardamos el mensaje del usuario en Supabase
    supabase.table("bot_memory").insert({
        "chat_id": chat_id,
        "role": "user",
        "content": user_text,
        "embedding": vector
    }).execute()

    # --- PASO 2: ACTUALIZACIÓN (TAVILY) ---
    try:
        search_result = tavily_client.get_search_context(query=user_text, search_depth="advanced")
        context_data = f"Información actual de internet (2026): {search_result}"
    except Exception as e:
        context_data = "No se pudo obtener datos en tiempo real."
        logging.error(f"Error en Tavily: {e}")

    # --- PASO 3: HISTORIAL DE CONVERSACIÓN ---
    # Traemos los últimos 8 mensajes para mantener el hilo
    res = supabase.table("bot_memory").select("role, content").eq("chat_id", chat_id).order("created_at", desc=True).limit(8).execute()
    
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "system", "content": context_data}
    ]
    
    for m in reversed(res.data):
        messages.append({"role": m["role"], "content": m["content"]})

    # --- PASO 4: LLAMADA A GROQ CON FALLBACK ---
    answer = ""
    try:
        # Prioridad: Llama 3.3 70B
        response = groq_client.chat.completions.create(model="llama-3.3-70b-versatile", messages=messages)
        answer = response.choices[0].message.content
    except Exception:
        # Backup: Qwen 3 32B
        try:
            response = groq_client.chat.completions.create(model="qwen/qwen3-32b", messages=messages)
            answer = response.choices[0].message.content
        except Exception:
            answer = "Iván, tengo un problema de conexión con mis modelos de IA. Probá en un ratito."

    # --- PASO 5: PERSISTENCIA Y RESPUESTA ---
    if answer:
        supabase.table("bot_memory").insert({
            "chat_id": chat_id,
            "role": "assistant",
            "content": answer
        }).execute()

        await update.message.reply_text(answer)

if __name__ == '__main__':
    token = os.getenv("TELEGRAM_TOKEN")
    application = ApplicationBuilder().token(token).build()
    
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    
    logging.info("Bozi-bot online...")
    application.run_polling()
