import os
import telebot
from groq import Groq
import threading
import time
import requests
from flask import Flask

# --- CONFIGURACIÓN DE INFRAESTRUCTURA ---
TOKEN = os.environ.get("TELEGRAM_TOKEN")
GROQ_KEY = os.environ.get("GROQ_API_KEY")
TAVILY_KEY = os.environ.get("TAVILY_API_KEY") # Nueva Variable

bot = telebot.TeleBot(TOKEN, threaded=False)
groq_client = Groq(api_key=GROQ_KEY)
server = Flask(__name__)

@server.route('/')
def health():
    return "Bozi-Bot Online - Qwen + Tavily 2026", 200

def run_server():
    port = int(os.environ.get("PORT", 10000))
    server.run(host='0.0.0.0', port=port)

# --- FUNCIÓN DE BÚSQUEDA WEB (TAVILY) ---
def buscar_en_internet(query):
    print(f">>> [WEB SEARCH] Consultando Tavily: {query}")
    try:
        response = requests.post(
            "https://api.tavily.com/search",
            json={
                "api_key": TAVILY_KEY,
                "query": query,
                "search_depth": "advanced",
                "max_results": 3
            }
        )
        data = response.json()
        # Consolidamos los resultados en un string para el modelo
        contexto = "\n".join([f"- {res['content']}" for res in data.get('results', [])])
        return contexto
    except Exception as e:
        print(f"Error en Tavily: {e}")
        return "No se pudo obtener información en tiempo real."

# --- MÓDULO VISUAL ---
def trigger_image(message, prompt_visual):
    bot.send_chat_action(message.chat.id, 'upload_photo')
    seed = int(time.time())
    clean_prompt = prompt_visual.replace(' ', '%20').replace('"', '')
    image_url = f"https://image.pollinations.ai/prompt/{clean_prompt}?width=1024&height=1024&nologo=true&seed={seed}"
    try:
        bot.send_photo(message.chat.id, image_url, caption=f"🎨 *Boceto:* {prompt_visual}", parse_mode="Markdown")
    except:
        bot.reply_to(message, "❌ Error al generar imagen.")

# --- MANEJADOR DE INTENCIÓN Y RESPUESTA ---
@bot.message_handler(func=lambda message: True)
def handle_all_messages(message):
    try:
        # FASE 1: RESPUESTA FINAL CON QWEN
        chat = groq_client.chat.completions.create(
            model="qwen/qwen3-32b",
            messages=[
                {
                    "role": "system", 
                    "content": (
                        "Eres Bozi-bot, experto en Ciberseguridad, redes, infraestrucutura, etc. "
                        "REGLA OBLIGATORIA: Debes realizar todo tu proceso de razonamiento y pensamiento internamente EN ESPAÑOL, y responder siempre en español "
                        f"Contexto actual de internet: {contexto_web}."
                    )
                }, # <--- ASEGURATE DE QUE ESTA COMA ESTÉ AQUÍ
                {"role": "user", "content": message.text}
            ],
            temperature=0.6
        )
        bot.reply_to(message, chat.choices[0].message.content)

    except Exception as e:
        print(f">>> ERROR: {e}")
        bot.reply_to(message, "⚠️ El motor Qwen tuvo un error de procesamiento.")

# --- INICIO LIMPIO (Protocolo Anti-409) ---
if __name__ == "__main__":
    threading.Thread(target=run_server, daemon=True).start()
    
    # Limpieza total para evitar el conflicto de Telegram
    bot.remove_webhook()
    bot.delete_webhook(drop_pending_updates=True)
    time.sleep(3)
    
    print(">>> Bozi-Bot Online con Qwen y Conexión a Internet.")
    bot.infinity_polling(timeout=90)
