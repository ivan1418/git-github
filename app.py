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
TAVILY_KEY = os.environ.get("TAVILY_API_KEY")

bot = telebot.TeleBot(TOKEN, threaded=False)
groq_client = Groq(api_key=GROQ_KEY)
server = Flask(__name__)

# Cluster de Modelos (Failover para alta disponibilidad)
MODEL_CLUSTER = ["qwen/qwen3-32b", "llama-3.3-70b-versatile"]
WHISPER_MODEL = "whisper-large-v3-turbo"

@server.route('/')
def health():
    return "Bozi-bot Real-Time Engine Active", 200

# --- HERRAMIENTA DE VERDAD ABSOLUTA (WEB SEARCH) ---
def consultar_web(query):
    print(f">>> [FORCED SEARCH] Extrayendo datos frescos de internet...")
    try:
        response = requests.post(
            "https://api.tavily.com/search",
            json={
                "api_key": TAVILY_KEY,
                "query": query,
                "search_depth": "advanced",
                "max_results": 3
            },
            timeout=12
        )
        data = response.json()
        # Inyectamos los resultados directamente como la única fuente de verdad
        return "\n".join([f"Web: {res['url']}\nContenido: {res['content']}" for res in data.get('results', [])])
    except Exception as e:
        return f"Error de conexión a la red: {str(e)}"

# --- MOTOR DE INFERENCIA CON PENSAMIENTO ---
def get_llm_response(messages, model_id):
    try:
        params = {
            "model": model_id,
            "messages": messages,
            "temperature": 0.3, # Bajamos más la temperatura para evitar alucinaciones
            "max_completion_tokens": 1200,
        }
        if "qwen3" in model_id:
            params["reasoning_effort"] = "default"
        
        completion = groq_client.chat.completions.create(**params)
        return completion.choices[0].message.content
    except Exception as e:
        print(f"Fallo en {model_id}: {e}")
        return None

# --- MANEJADOR DE MENSAJES ---
@bot.message_handler(func=lambda message: True)
def handle_all_messages(message):
    try:
        bot.send_chat_action(message.chat.id, 'typing')
        
        # ELIMINAMOS LA VALIDACIÓN: Ahora buscamos SIEMPRE
        # Solo exceptuamos saludos muy cortos para no quemar tokens de Tavily innecesariamente
        if len(message.text) > 4:
            contexto_fresco = consultar_web(message.text)
        else:
            contexto_fresco = "El usuario solo envió un saludo o texto muy corto."

        # GENERACIÓN DE RESPUESTA BASADA ÚNICAMENTE EN EL CONTEXTO OBTENIDO
        final_msg = [
            {
                "role": "system", 
                "content": (
                    "Eres Bozi-bot, experto en Ciberseguridad e Infraestructura. "
                    "REGLA DE ORO: No uses tu memoria interna para hechos, noticias, datos de tiempo, o datos técnicos de 2024-2026. "
                    "Toda tu respuesta debe basarse en el 'CONTEXTO FRESCO' provisto. "
                    "Si el contexto no contiene la respuesta, admítelo y pide más detalles. "
                    "Debes pensar y responder en español rioplatense técnico. "
                    f"CONTEXTO FRESCO (ACTUALIZADO A ABRIL DE 2026): {contexto_fresco}"
                )
            },
            {"role": "user", "content": message.text}
        ]
        
        # Ejecución con clúster de modelos
        respuesta = None
        for m in MODEL_CLUSTER:
            respuesta = get_llm_response(final_msg, m)
            if respuesta: break
        
        if respuesta:
            # Limpiamos el proceso de pensamiento de Qwen3
            if "</think>" in respuesta:
                respuesta = respuesta.split("</think>")[-1].strip()
            bot.reply_to(message, respuesta)
        else:
            bot.reply_to(message, "⚠️ Cluster saturado. Reintentá en un minuto.")

    except Exception as e:
        bot.reply_to(message, f"❌ Error: {str(e)[:50]}")

# --- MANEJADOR DE AUDIO (WHISPER) ---
@bot.message_handler(content_types=['voice', 'audio'])
def handle_audio(message):
    try:
        bot.send_chat_action(message.chat.id, 'record_voice')
        file_info = bot.get_file(message.voice.file_id if message.voice else message.audio.file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        file_name = f"voice_{message.chat.id}.ogg"
        with open(file_name, 'wb') as f: f.write(downloaded_file)

        with open(file_name, "rb") as af:
            trans = groq_client.audio.transcriptions.create(file=(file_name, af.read()), model=WHISPER_MODEL, language="es")
        
        os.remove(file_name)
        message.text = trans.text
        bot.reply_to(message, f"🎤 *Transcripción:* _{trans.text}_")
        handle_all_messages(message) # Procesamos el texto transcrito con búsqueda forzada
    except Exception:
        bot.reply_to(message, "❌ Error al procesar el audio.")

if __name__ == "__main__":
    threading.Thread(target=lambda: server.run(host='0.0.0.0', port=10000), daemon=True).start()
    bot.remove_webhook()
    bot.delete_webhook(drop_pending_updates=True)
    time.sleep(2)
    print(">>> Bozi-bot Real-Time (Forced Search): ONLINE")
    bot.infinity_polling(timeout=90)
