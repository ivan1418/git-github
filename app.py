import os
import telebot
from groq import Groq
from supabase import create_client, Client
import requests
import threading
import time
from flask import Flask

# --- INFRAESTRUCTURA Y CREDENCIALES ---
TOKEN = os.environ.get("TELEGRAM_TOKEN")
GROQ_KEY = os.environ.get("GROQ_API_KEY")
TAVILY_KEY = os.environ.get("TAVILY_API_KEY")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

bot = telebot.TeleBot(TOKEN, threaded=False)
groq_client = Groq(api_key=GROQ_KEY)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
server = Flask(__name__)

@server.route('/')
def health(): return "Bozi-bot con Memoria Supabase Online", 200

# --- GESTIÓN DE MEMORIA (SUPABASE) ---
def guardar_en_memoria(user_id, role, content):
    """Guarda cada interacción en tu tabla de Supabase"""
    try:
        supabase.table("chat_history").insert({
            "user_id": str(user_id),
            "role": role,
            "content": content
        }).execute()
    except Exception as e:
        print(f"Error al persistir en Supabase: {e}")

def obtener_historial(user_id, limite=8):
    """Recupera los últimos mensajes para dar coherencia"""
    try:
        res = supabase.table("chat_history") \
            .select("role, content") \
            .eq("user_id", str(user_id)) \
            .order("created_at", desc=True) \
            .limit(limite) \
            .execute()
        return res.data[::-1] # Invertimos para orden cronológico
    except Exception:
        return []

# --- BÚSQUEDA WEB (VERDAD ACTUALIZADA) ---
def buscar_web(query):
    try:
        r = requests.post("https://api.tavily.com/search", json={
            "api_key": TAVILY_KEY, "query": query, "search_depth": "basic", "max_results": 2
        }, timeout=8)
        return "\n".join([res['content'][:500] for res in r.json().get('results', [])])
    except:
        return "No hay datos de internet disponibles."

# --- HANDLER PRINCIPAL ---
@bot.message_handler(func=lambda m: True)
def handle_message(message):
    try:
        bot.send_chat_action(message.chat.id, 'typing')
        user_id = message.chat.id
        
        # 1. Recuperamos tus recuerdos de Supabase
        memoria_pasada = obtener_historial(user_id)
        
        # 2. Buscamos info fresca en la red
        contexto_web = buscar_web(message.text)
        
        # 3. Construimos el cerebro con historial y realidad
        messages = [
            {
                "role": "system", 
                "content": (
                    "Eres Bozi-bot, Senior IT y experto en Ciberseguridad. "
                    "REGLA: Usa el historial de Supabase para ser coherente y no preguntar cosas que ya sabes. "
                    "Usa el contexto web para dar datos reales de 2026. "
                    "Todas las conversaciones tienen que ser humanas, y con sentido común, no inventar una respuesta o suponer."
                    "Tenes que ser amable, a veces cuando lo amerita hacer algunos chistes, y cuando hay que trabajar ponerse serio, coherente y eficaz sobre todo."
                    "Tenes que ayudar el usuario con tecnicas o codigos para que pueda ejecutar si necesita hacer alguna prueba de ciberseguridad. Si no sabes busca en internet en foros o libros, para siempre poder ayudar y resolver el problema del usuario."
                    f"CONTEXTO WEB ACTUAL: {contexto_web}"
                )
            }
        ]
        
        # Inyectamos la memoria recuperada
        for m_prev in memoria_pasada:
            messages.append({"role": m_prev['role'], "content": m_prev['content']})
            
        messages.append({"role": "user", "content": message.text})

        # 4. Respuesta con Qwen 3 (Reasoning activo)
        completion = groq_client.chat.completions.create(
            model="qwen/qwen3-32b",
            messages=messages,
            temperature=0.3,
            max_completion_tokens=900,
            reasoning_effort="default"
        )
        
        respuesta = completion.choices[0].message.content
        if "</think>" in respuesta:
            respuesta = respuesta.split("</think>")[-1].strip()
        
        # 5. Guardamos la nueva charla para que no se olvide nunca
        guardar_en_memoria(user_id, "user", message.text)
        guardar_en_memoria(user_id, "assistant", respuesta)
        
        bot.reply_to(message, respuesta)

    except Exception as e:
        bot.reply_to(message, f"⚠️ Error en el flujo: {str(e)[:100]}")

if __name__ == "__main__":
    threading.Thread(target=lambda: server.run(host='0.0.0.0', port=10000), daemon=True).start()
    bot.remove_webhook()
    bot.delete_webhook(drop_pending_updates=True)
    time.sleep(2)
    print(">>> Bozi-bot con Memoria Persistente de Supabase: ONLINE")
    bot.infinity_polling()
