import os
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters
from supabase import create_client
from sentence_transformers import SentenceTransformer
from groq import Groq
from tavily import TavilyClient

# 1. Configuración de Logs e Infraestructura
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# Inicialización de Clientes (Variables de entorno en Render)
supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))
groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))
tavily_client = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))
model_emb = SentenceTransformer('all-MiniLM-L6-v2') # Modelo liviano de 384 dim

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_text = update.message.text

    # --- PASO 1: MEMORIA Y EMBEDDING ---
    # Generamos el vector para la memoria inteligente
    vector = model_emb.encode(user_text).tolist()
    
    # Guardamos el mensaje del usuario en la nueva tabla bot_memory
    supabase.table("bot_memory").insert({
        "chat_id": chat_id,
        "role": "user",
        "content": user_text,
        "embedding": vector
    }).execute()

    # --- PASO 2: BÚSQUEDA TAVILY (ACTUALIZACIÓN) ---
    # Buscamos en internet para que el bot no esté desactualizado
    try:
        search_result = tavily_client.get_search_context(query=user_text, search_depth="advanced")
        context_data = f"Información actual de internet: {search_result}"
    except Exception as e:
        context_data = "No se pudo obtener datos en tiempo real."
        logging.error(f"Error en Tavily: {e}")

    # --- PASO 3: RECUPERAR HISTORIAL (HILO) ---
    # Traemos los últimos 8 mensajes para mantener el hilo de la charla
    res = supabase.table("bot_memory").select("role, content").eq("chat_id", chat_id).order("created_at", desc=True).limit(8).execute()
    
    # Armamos el array de mensajes para la IA
    messages = [{"role": "system", "content": f"Sos Bozi-bot, un Senior IT Specialist. Usá esta info actual si es necesario: {context_data}"}]
    
    # Invertimos el historial para que sea cronológico
    for m in reversed(res.data):
        messages.append({"role": m["role"], "content": m["content"]})

    # --- PASO 4: LLAMADA A GROQ CON FALLBACK ---
    try:
        # Prioridad 1: Llama 3.3 70B (El más inteligente)
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=messages,
            temperature=0.7
        )
        answer = response.choices[0].message.content
    except Exception as e:
        logging.warning(f"Llama falló, intentando Qwen: {e}")
        # Prioridad 2: Qwen 3 32B (El backup)
        response = groq_client.chat.completions.create(
            model="qwen/qwen3-32b",
            messages=messages,
            temperature=0.7
        )
        answer = response.choices[0].message.content

    # --- PASO 5: GUARDAR RESPUESTA Y ENVIAR ---
    # Guardamos lo que dijo la IA para que el hilo siga en el próximo mensaje
    supabase.table("bot_memory").insert({
        "chat_id": chat_id,
        "role": "assistant",
        "content": answer
    }).execute()

    await context.bot.send_message(chat_id=chat_id, text=answer)

if __name__ == '__main__':
    # El token lo saca de las variables de Render
    application = ApplicationBuilder().token(os.getenv("TELEGRAM_TOKEN")).build()
    
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    
    # Render usa un puerto dinámico, esto es para que no se duerma con cron-job.org
    port = int(os.environ.get('PORT', 10000))
    application.run_polling()
