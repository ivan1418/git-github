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

# Inicialización de Clientes usando los nombres exactos de tu captura de Render
# SUPABASE_KEY debe ser la "service_role key" para poder escribir en la DB
supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))
groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))
tavily_client = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))

# Función de Embeddings vía API (Para no exceder los 512MB de RAM de Render)
def get_embedding(text):
    model_id = "sentence-transformers/all-MiniLM-L6-v2"
    api_url = f"https://api-inference.huggingface.co/models/{model_id}"
    # Si tenés un token de Hugging Face podés agregarlo, si no, funciona con límites
    headers = {"Authorization": f"Bearer {os.getenv('HF_TOKEN', '')}"}
    try:
        response = requests.post(api_url, headers=headers, json={"inputs": text}, timeout=10)
        return response.json()
    except Exception as e:
        logging.error(f"Error en embedding: {e}")
        return None

SYSTEM_PROMPT = (
    "Actuá como Bozi-bot, un asistente experto en IT Infrastructure y Cybersecurity. "
    "Tu tono debe ser profesional, amable y extremadamente eficiente. "
    "REGLAS: "
    "1. COHERENCIA: Usá historial y datos de internet. "
    "2. CONCISIÓN: Directo al grano. "
    "3. RAZONAMIENTO: Seguí mejores prácticas de seguridad. "
    "4. BREVEDAD: Máximo 3 párrafos. "
    "5. IDIOMA: Español rioplatense."
)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_text = update.message.text

    # 1. Memoria Inteligente
    vector = get_embedding(user_text)
    supabase.table("bot_memory").insert({
        "chat_id": chat_id, "role": "user", "content": user_text, "embedding": vector
    }).execute()

    # 2. Actualización vía Tavily
    try:
        search_result = tavily_client.get_search_context(query=user_text, search_depth="advanced")
        context_data = f"Información de internet (2026): {search_result}"
    except:
        context_data = "No hay datos recientes disponibles."

    # 3. Historial (Hilo de la charla)
    res = supabase.table("bot_memory").select("role, content").eq("chat_id", chat_id).order("created_at", desc=True).limit(8).execute()
    messages = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "system", "content": context_data}]
    for m in reversed(res.data):
        messages.append({"role": m["role"], "content": m["content"]})

    # 4. Lógica de Groq (Fallback)
    try:
        response = groq_client.chat.completions.create(model="llama-3.3-70b-versatile", messages=messages)
        answer = response.choices[0].message.content
    except:
        response = groq_client.chat.completions.create(model="qwen/qwen3-32b", messages=messages)
        answer = response.choices[0].message.content

    # 5. Persistencia y Envío
    supabase.table("bot_memory").insert({"chat_id": chat_id, "role": "assistant", "content": answer}).execute()
    await update.message.reply_text(answer)

if __name__ == '__main__':
    application = ApplicationBuilder().token(os.getenv("TELEGRAM_TOKEN")).build()
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    logging.info("Bozi-bot online en Render...")
    application.run_polling()
