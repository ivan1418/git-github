import os
import telebot
from groq import Groq
import threading
import time
import requests
from flask import Flask

# --- INFRAESTRUCTURA CORE ---
TOKEN = os.environ.get("TELEGRAM_TOKEN")
GROQ_KEY = os.environ.get("GROQ_API_KEY")
TAVILY_KEY = os.environ.get("TAVILY_API_KEY")

bot = telebot.TeleBot(TOKEN, threaded=False)
groq_client = Groq(api_key=GROQ_KEY)
server = Flask(__name__)

@server.route('/')
def health():
    return "Bozi-bot Qwen3 Engine Active", 200

# --- HERRAMIENTA DE CONEXIÓN A INTERNET ---
def consultar_web(query):
    print(f">>> [AGENTE] Qwen solicitando datos de internet para: {query}")
    try:
        response = requests.post(
            "https://api.tavily.com/search",
            json={
                "api_key": TAVILY_KEY,
                "query": query,
                "search_depth": "advanced",
                "max_results": 5
            }
        )
        data = response.json()
        return "\n".join([f"Fuente: {res['url']}\nContenido: {res['content']}" for res in data.get('results', [])])
    except Exception as e:
        return f"Error de conexión: {str(e)}"

# --- LÓGICA DE PENSAMIENTO Y RESPUESTA ---
@bot.message_handler(func=lambda message: True)
def handle_all_messages(message):
    try:
        bot.send_chat_action(message.chat.id, 'typing')
        
        # 1. PASO DE PENSAMIENTO: ¿Necesito internet?
        # Usamos el modelo Qwen que viste en tu Playground
        analisis_previo = groq_client.chat.completions.create(
            model="qwen/qwen3-32b",
            messages=[
                {"role": "system", "content": "Eres el módulo de análisis de Bozi-bot. Responde únicamente 'BUSCAR' si necesitas internet para responder con actualidad o 'SABER' si puedes responder con tu conocimiento."},
                {"role": "user", "content": message.text}
            ],
            reasoning_effort="low" # Pensamiento rápido para la decisión
        )
        
        decision = analisis_previo.choices[0].message.content.strip().upper()
        contexto_web = ""
        
        if "BUSCAR" in decision:
            contexto_web = consultar_web(message.text)

        # 2. RESPUESTA FINAL CON RAZONAMIENTO PROFUNDO
        # Implementamos los parámetros que viste en la captura de Groq
        completion = groq_client.chat.completions.create(
            model="qwen/qwen3-32b",
            messages=[
                {
                    "role": "system", 
                    "content": (
                        "Eres Bozi-bot, experto en Ciberseguridad e Infraestructura IT. "
                        "DEBES PENSAR Y RESPONDER SIEMPRE EN ESPAÑOL. "
                        f"CONTEXTO DE INTERNET OBTENIDO: {contexto_web}. "
                        "Si tienes contexto, úsalo para dar datos reales de hoy. Si no, usa tu lógica técnica."
                    )
                },
                {"role": "user", "content": message.text}
            ],
            temperature=0.6,
            max_completion_tokens=4096,
            top_p=0.95,
            reasoning_effort="default", # Forzamos el pensamiento profundo
            stream=False 
        )
        
        # Limpieza de tags <think> para que no ensucien el chat de Telegram
        res_final = completion.choices[0].message.content
        if "</think>" in res_final:
            res_final = res_final.split("</think>")[-1].strip()
            
        bot.reply_to(message, res_final)

    except Exception as e:
        print(f">>> CRITICAL ERROR: {e}")
        bot.reply_to(message, f"⚠️ Error en el motor Qwen3: {str(e)}")

# --- PROTOCOLO DE ARRANQUE SEGURO (ANTI-409) ---
if __name__ == "__main__":
    threading.Thread(target=lambda: server.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000))), daemon=True).start()
    
    # Reset de sesión de Telegram
    bot.remove_webhook()
    bot.delete_webhook(drop_pending_updates=True)
    time.sleep(2)
    
    print(">>> Bozi-bot operando con Qwen3 y razonando en español.")
    bot.infinity_polling(timeout=90)
