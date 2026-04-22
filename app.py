import os
import telebot
from groq import Groq
import threading
import time
import requests
from flask import Flask

# --- INFRAESTRUCTURA Y VARIABLES DE ENTORNO ---
TOKEN = os.environ.get("TELEGRAM_TOKEN")
GROQ_KEY = os.environ.get("GROQ_API_KEY")
TAVILY_KEY = os.environ.get("TAVILY_API_KEY")

# Inicialización de clientes
bot = telebot.TeleBot(TOKEN, threaded=False)
groq_client = Groq(api_key=GROQ_KEY)
server = Flask(__name__)

@server.route('/')
def health():
    return "Bozi-bot Qwen3 Engine Active", 200

def run_server():
    port = int(os.environ.get("PORT", 10000))
    server.run(host='0.0.0.0', port=port)

# --- WEB SEARCH TOOL (TAVILY) ---
def consultar_web(query):
    print(f">>> [WEB SEARCH] Bozi-bot buscando: {query}")
    try:
        response = requests.post(
            "https://api.tavily.com/search",
            json={
                "api_key": TAVILY_KEY,
                "query": query,
                "search_depth": "advanced",
                "max_results": 4
            },
            timeout=10
        )
        data = response.json()
        return "\n".join([f"- {res['content']}" for res in data.get('results', [])])
    except Exception as e:
        print(f"Error en Tavily: {e}")
        return "No hay datos recientes disponibles."

# --- MANEJADOR DE INTENCIÓN Y RESPUESTA ---
@bot.message_handler(func=lambda message: True)
def handle_all_messages(message):
    try:
        # feedback visual: "Escribiendo..."
        bot.send_chat_action(message.chat.id, 'typing')
        
        # Paso 1: Clasificación de intención (¿Necesita buscar?)
        # Usamos Qwen 3 pero con un prompt corto para velocidad
        analisis = groq_client.chat.completions.create(
            model="qwen/qwen3-32b",
            messages=[
                {"role": "system", "content": "Si la pregunta requiere datos actuales (noticias, precios, ciberseguridad hoy), responde 'BUSCAR'. Si no, responde 'SABER'."},
                {"role": "user", "content": message.text}
            ],
            temperature=0.1
        )
        
        decision = analisis.choices[0].message.content.strip().upper()
        contexto_web = ""

        if "BUSCAR" in decision:
            # Refrescamos el "Escribiendo..." porque la búsqueda web toma tiempo
            bot.send_chat_action(message.chat.id, 'typing')
            contexto_web = consultar_web(message.text)

        # Paso 2: Respuesta final con Razonamiento de Qwen 3
        # Inyectamos el contexto de internet directamente en el sistema
        bot.send_chat_action(message.chat.id, 'typing')
        
        completion = groq_client.chat.completions.create(
            model="qwen/qwen3-32b",
            messages=[
                {
                    "role": "system", 
                    "content": (
                        "Eres Bozi-bot, experto en IT"
                        "DEBES PENSAR Y RESPONDER SIEMPRE EN ESPAÑOL. "
                        f"CONTEXTO ACTUAL (2026): {contexto_web}. "
                        "Usa este contexto para dar respuestas precisas y actualizadas."
                    )
                },
                {"role": "user", "content": message.text}
            ],
            temperature=0.6,
            max_completion_tokens=4096,
            top_p=0.95,
            reasoning_effort="default" # Forzamos el pensamiento profundo
        )
        
        # Extraemos la respuesta final (limpiando tags si los hubiera)
        res_final = completion.choices[0].message.content
        if "</think>" in res_final:
            res_final = res_final.split("</think>")[-1].strip()
            
        bot.reply_to(message, res_final)

    except Exception as e:
        print(f">>> ERROR CRÍTICO: {e}")
        bot.reply_to(message, f"⚠️ Error en Bozi-bot: {str(e)}")

# --- PROTOCOLO DE ARRANQUE (ANTI-CONFLICTO 409) ---
if __name__ == "__main__":
    # Servidor Flask en segundo plano para el health check
    threading.Thread(target=run_server, daemon=True).start()
    
    print(">>> Bozi-bot: Reclamando control de sesión...")
    
    # Limpiamos conexiones previas para evitar error 409
    bot.remove_webhook()
    bot.delete_webhook(drop_pending_updates=True)
    time.sleep(2) # Pausa técnica
    
    print(">>> Motor Qwen 3 Online. Bozi-bot escuchando...")
    bot.infinity_polling(timeout=90, long_polling_timeout=40)
