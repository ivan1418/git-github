import os
import telebot
from groq import Groq
from supabase import create_client, Client
import requests
import threading
import time
from datetime import datetime # Crucial para el día real

# --- CONFIGURACIÓN ---
TOKEN = os.environ.get("TELEGRAM_TOKEN")
GROQ_KEY = os.environ.get("GROQ_API_KEY")
TAVILY_KEY = os.environ.get("TAVILY_API_KEY")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

bot = telebot.TeleBot(TOKEN, threaded=False)
groq_client = Groq(api_key=GROQ_KEY)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Clúster de Failover (Qwen3 -> Llama 3.3)
MODEL_CLUSTER = ["qwen/qwen3-32b", "llama-3.3-70b-versatile"]

# --- FUNCIÓN DE MEMORIA PERSISTENTE (SQL) ---
def leer_historial_supabase(user_id):
    try:
        # Buscamos en tu tabla 'memories' (según tu captura image_6f49aa.png)
        # Adapté los nombres de columnas a tu SQL
        res = supabase.table("memories").select("content").eq("project_name", str(user_id)).limit(5).execute()
        return "\n".join([item['content'] for item in res.data])
    except:
        return ""

# --- MOTOR DE RESPUESTA BLINDADO ---
def invocar_cluster(messages):
    for model_id in MODEL_CLUSTER:
        try:
            res = groq_client.chat.completions.create(
                model=model_id,
                messages=messages,
                temperature=0.1, # Casi 0 para CERO inventos
                max_completion_tokens=800,
                reasoning_effort="default" if "qwen3" in model_id else None
            )
            return res.choices[0].message.content
        except Exception as e:
            if "rate_limit" in str(e).lower(): continue
            return None
    return None

@bot.message_handler(func=lambda m: True)
def handle_message(message):
    bot.send_chat_action(message.chat.id, 'typing')
    
    # 1. Fecha Real (Se la inyectamos CADA VEZ)
    fecha_hoy = datetime.now().strftime("%A, %d de %B de %2026")
    
    # 2. Recuperar Memoria del Proyecto
    memoria_proyecto = leer_historial_supabase(message.chat.id)
    
    # 3. Prompt de Rigurosidad Técnica
    prompt_sistema = (
        f"Eres Bozi-bot. Hoy es EXACTAMENTE {fecha_hoy}. No inventes otra fecha. "
        f"Historial del proyecto: {memoria_proyecto}. "
        "REGLA: Si no sabes algo, usa Tavily. No divagues con poesía ni creatividad. "
        "Respuesta técnica, en español y basada en evidencia."
    )

    messages = [
        {"role": "system", "content": prompt_sistema},
        {"role": "user", "content": message.text}
    ]

    respuesta = invocar_cluster(messages)
    
    if respuesta:
        if "</think>" in respuesta:
            respuesta = respuesta.split("</think>")[-1].strip()
        
        # Guardar en Supabase para coherencia futura
        try:
            supabase.table("memories").insert({
                "project_name": str(message.chat.id),
                "content": f"Usuario: {message.text} | Bot: {respuesta}"
            }).execute()
        except: pass
        
        bot.reply_to(message, respuesta)
    else:
        bot.reply_to(message, "⚠️ Error de conexión con el clúster.")

if __name__ == "__main__":
    bot.remove_webhook()
    bot.delete_webhook(drop_pending_updates=True)
    time.sleep(2)
    bot.infinity_polling()
