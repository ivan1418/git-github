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
        # FASE 1: CLASIFICACIÓN Y DETECCIÓN DE ACTUALIDAD (Llama 3.3)
        check = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{
                "role": "system", 
                "content": "Analiza la intención: 1. Si pide imagen, responde 'IMG: [prompt]'. 2. Si pide datos de actualidad/noticias/precios de 2024-2026, responde 'BUSCAR: [query]'. 3. Si es charla técnica, responde 'TXT'."
            }, {"role": "user", "content": message.text}]
        )
        
        intent = check.choices[0].message.content.strip().upper()
        contexto_web = ""

        if intent.startswith("IMG:"):
            trigger_image(message, intent.split("IMG:")[1].strip())
            return
        
        if intent.startswith("BUSCAR:"):
            query_web = intent.split("BUSCAR:")[1].strip()
            bot.send_chat_action(message.chat.id, 'typing')
            contexto_web = buscar_en_internet(query_web)

        # FASE 2: RESPUESTA FINAL CON QWEN (Cerebro Principal)
        chat = groq_client.chat.completions.create(
            model="qwen/qwen3-32b",
            messages=[
                {"role": "system", "content": f"Eres Bozi-bot, experto en Ciberseguridad. Hoy es 22 de abril de 2026. Datos frescos de internet: {contexto_web}. Usa esta info para responder con precisión técnica."},
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
