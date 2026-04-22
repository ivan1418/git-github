import os
import telebot
from groq import Groq
import threading
import time
import requests
from flask import Flask

# --- INFRAESTRUCTURA ---
TOKEN = os.environ.get("TELEGRAM_TOKEN")
GROQ_KEY = os.environ.get("GROQ_API_KEY")
TAVILY_KEY = os.environ.get("TAVILY_API_KEY")

bot = telebot.TeleBot(TOKEN, threaded=False)
groq_client = Groq(api_key=GROQ_KEY)
server = Flask(__name__)

# Cluster de Modelos (Failover Strategy)
MODEL_CLUSTER = ["qwen/qwen3-32b", "llama-3.3-70b-versatile"]
WHISPER_MODEL = "whisper-large-v3-turbo"

@server.route('/')
def health():
    return "Bozi-bot HA Engine 2026 Active", 200

# --- HERRAMIENTA DE BÚSQUEDA WEB ---
def consultar_web(query):
    try:
        response = requests.post(
            "https://api.tavily.com/search",
            json={"api_key": TAVILY_KEY, "query": query, "search_depth": "basic", "max_results": 2},
            timeout=8
        )
        data = response.json()
        return "\n".join([f"- {res['content'][:600]}" for res in data.get('results', [])])
    except:
        return "Conexión a internet no disponible en este momento."

# --- MOTOR DE INFERENCIA CON PENSAMIENTO FORZADO ---
def get_llm_response(messages, model_id):
    try:
        params = {
            "model": model_id,
            "messages": messages,
            "temperature": 0.5, # Bajamos temperatura para más precisión técnica
            "max_completion_tokens": 1024,
        }
        
        # Si es Qwen3, usamos el parámetro nativo de pensamiento
        if "qwen3" in model_id:
            params["reasoning_effort"] = "default"

        completion = groq_client.chat.completions.create(**params)
        return completion.choices[0].message.content
    except Exception as e:
        print(f"FALLO en {model_id}: {e}")
        return None

# --- HANDLER PRINCIPAL ---
@bot.message_handler(func=lambda message: True)
def handle_all_messages(message):
    try:
        bot.send_chat_action(message.chat.id, 'typing')
        
        # 1. ¿Necesitamos Internet? (Decisión rápida)
        intent_msg = [{"role": "system", "content": "Responde solo BUSCAR o SABER."},
                      {"role": "user", "content": message.text}]
        
        # Intentamos obtener la intención (con failover)
        intent_res = None
        for m in MODEL_CLUSTER:
            intent_res = get_llm_response(intent_msg, m)
            if intent_res: break

        contexto = ""
        if intent_res and "BUSCAR" in intent_res.upper():
            bot.send_chat_action(message.chat.id, 'typing')
            contexto = consultar_web(message.text)

        # 2. Respuesta final con Protocolo de Pensamiento en Español
        final_msg = [
            {
                "role": "system", 
                "content": (
                    "Eres Bozi-bot. "
                    "REGLA DE ORO: Antes de responder, analiza los datos. "
                    "Debes pensar y responder íntegramente en ESPAÑOL. "
                    f"DATOS DE INTERNET (2026): {contexto}. "
                    "Si no hay datos, advierte que usas tu base estática."
                )
            },
            {"role": "user", "content": message.text}
        ]
        
        # Intentamos la respuesta final recorriendo el clúster
        respuesta = None
        for m in MODEL_CLUSTER:
            respuesta = get_llm_response(final_msg, m)
            if respuesta: break
        
        if respuesta:
            # Limpiamos tags de pensamiento
            if "</think>" in respuesta:
                respuesta = respuesta.split("</think>")[-1].strip()
            bot.reply_to(message, respuesta)
        else:
            bot.reply_to(message, "⚠️ Error crítico: Cluster de modelos fuera de línea.")

    except Exception as e:
        bot.reply_to(message, f"❌ Error en Bozi-bot: {str(e)}")

# (Se incluye el manejador de audio de Whisper del mensaje anterior aquí)
@bot.message_handler(content_types=['voice', 'audio'])
def handle_audio(message):
    # ... (mismo código de Whisper anterior) ...
    pass

if __name__ == "__main__":
    threading.Thread(target=lambda: server.run(host='0.0.0.0', port=10000), daemon=True).start()
    bot.remove_webhook()
    bot.delete_webhook(drop_pending_updates=True)
    time.sleep(2)
    bot.infinity_polling(timeout=90)
