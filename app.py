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

# Modelo de embeddings de 384 dimensiones (liviano para la RAM de Render)
model_emb = SentenceTransformer('paraphrase-albert-small-v2') 

# --- DEFINICIÓN DEL SYSTEM PROMPT ---
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

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_text = update.message.text

    # --- PASO 1: MEMORIA INTELIGENTE (EMBEDDING) ---
    vector = model_emb.encode(user_text).tolist()
    
    # Guardamos el mensaje del usuario
    supabase.table("bot_memory").insert({
        "chat_id": chat_id,
        "role": "user",
        "content": user_text,
        "embedding": vector
    }).execute()

    # --- PASO 2: ACTUALIZACIÓN (TAVILY SEARCH) ---
    try:
        # Buscamos en internet para tener datos frescos de 2026
        search_result = tavily_client.get_search_context(query=user_text, search_depth="advanced")
        context_data = f"Información actual de internet (contexto): {search_result}"
    except Exception as e:
        context_data = "No se pudo obtener datos en tiempo real de internet."
        logging.error(f"Error en Tavily: {e}")

    # --- PASO 3: CONSTRUIR MENSAJES PARA LA IA ---
    # Recuperamos los últimos 8 mensajes de Supabase para el hilo
    res = supabase.table("bot_memory").select("role, content").eq("chat_id", chat_id).order("created_at", desc=True).limit(8).execute()
    
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "system", "content": context_data}
    ]
    
    # Invertimos el historial para que sea cronológico
    for m in reversed(res.data):
        messages.append({"role": m["role"], "content": m["content"]})

    # --- PASO 4: EJECUCIÓN CON FALLBACK (LLAMA -> QWEN) ---
    answer = ""
    try:
        # Prioridad: Llama 3.3 70B
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=messages,
            temperature=0.6 # Un poco más bajo para mayor coherencia
        )
        answer = response.choices[0].message.content
    except Exception as e:
        logging.warning(f"Llama falló o límite excedido, intentando Qwen: {e}")
        try:
            # Backup: Qwen 3 32B
            response = groq_client.chat.completions.create(
                model="qwen/qwen3-32b",
                messages=messages,
                temperature=0.6
            )
            answer = response.choices[0].message.content
        except Exception as e2:
            answer = "Perdón Iván, tuve un problema técnico con los modelos de IA. Intentá de nuevo en un minuto."
            logging.error(f"Ambos modelos fallaron: {e2}")

    # --- PASO 5: PERSISTENCIA Y RESPUESTA ---
    if answer:
        # Guardamos la respuesta del asistente para la próxima vuelta
        supabase.table("bot_memory").insert({
            "chat_id": chat_id,
            "role": "assistant",
            "content": answer
        }).execute()

        await context.bot.send_message(chat_id=chat_id, text=answer)

if __name__ == '__main__':
    # Asegurate de tener TELEGRAM_TOKEN en Render
    token = os.getenv("TELEGRAM_TOKEN")
    if not token:
        raise ValueError("No se encontró TELEGRAM_TOKEN en las variables de entorno.")

    application = ApplicationBuilder().token(token).build()
    
    # Handler para mensajes de texto
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    
    # Render asigna un puerto automáticamente en la variable PORT
    logging.info("Bozi-bot online en la nube...")
    application.run_polling()
