import os
import logging
import requests
import time
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters
from supabase import create_client
from groq import Groq
from tavily import TavilyClient

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))
groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))
tavily_client = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))

def get_embedding(text):
    model_id = "sentence-transformers/all-MiniLM-L6-v2"
    api_url = f"https://api-inference.huggingface.co/models/{model_id}"
    headers = {"Authorization": f"Bearer {os.getenv('HF_TOKEN', '')}"}
    
    # Reintento simple si la API está fría
    for _ in range(3):
        try:
            response = requests.post(api_url, headers=headers, json={"inputs": text}, timeout=15)
            if response.status_code == 200:
                return response.json()
            time.sleep(2)
        except:
            continue
    return None

SYSTEM_PROMPT = (
    "Actuá como Bozi-bot, experto en IT y Cybersecurity. "
    "Respondé amable, profesional y conciso (máx 3 párrafos). "
    "Usá info de internet para ser coherente con la actualidad. "
    "Español rioplatense."
)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_text = update.message.text

    # 1. Embedding
    vector = get_embedding(user_text)
    supabase.table("bot_memory").insert({
        "chat_id": chat_id, "role": "user", "content": user_text, "embedding": vector
    }).execute()

    # 2. Tavily (Método actualizado)
    try:
        # search() es el método actual recomendado
        search_res = tavily_client.search(query=user_text, max_results=3)
        context_data = f"Contexto internet: {search_res['results']}"
    except:
        context_data = "No hay datos recientes."

    # 3. Historial
    res = supabase.table("bot_memory").select("role, content").eq("chat_id", chat_id).order("created_at", desc=True).limit(8).execute()
    messages = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "system", "content": context_data}]
    for m in reversed(res.data):
        messages.append({"role": m["role"], "content": m["content"]})

    # 4. Groq
    try:
        response = groq_client.chat.completions.create(model="llama-3.3-70b-versatile", messages=messages)
        answer = response.choices[0].message.content
    except:
        response = groq_client.chat.completions.create(model="qwen/qwen3-32b", messages=messages)
        answer = response.choices[0].message.content

    # 5. Respuesta
    supabase.table("bot_memory").insert({"chat_id": chat_id, "role": "assistant", "content": answer}).execute()
    await update.message.reply_text(answer)

if __name__ == '__main__':
    # Usamos drop_pending_updates para evitar el error de Conflict al reiniciar
    application = ApplicationBuilder().token(os.getenv("TELEGRAM_TOKEN")).build()
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    
    logging.info("Bozi-bot online...")
    # Limpia mensajes acumulados para evitar conflictos
    application.run_polling(drop_pending_updates=True)
