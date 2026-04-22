import os
import telebot
from groq import Groq
import threading
import time
from flask import Flask

# --- CONFIGURACIÓN DE INFRAESTRUCTURA ---
TOKEN = os.environ.get("TELEGRAM_TOKEN")
GROQ_KEY = os.environ.get("GROQ_API_KEY")

bot = telebot.TeleBot(TOKEN, threaded=False)
groq_client = Groq(api_key=GROQ_KEY)
server = Flask(__name__)

@server.route('/')
def health():
    return "Bozi-Bot Qwen Reasoning Active", 200

def run_server():
    port = int(os.environ.get("PORT", 10000))
    server.run(host='0.0.0.0', port=port)

# --- MÓDULO VISUAL ---
def trigger_image(message, prompt_visual):
    print(f">>> [ACCION] Generando imagen: {prompt_visual}")
    bot.send_chat_action(message.chat.id, 'upload_photo')
    seed = int(time.time())
    clean_prompt = prompt_visual.replace(' ', '%20').replace('"', '')
    image_url = f"https://image.pollinations.ai/prompt/{clean_prompt}?width=1024&height=1024&nologo=true&seed={seed}"
    try:
        bot.send_photo(message.chat.id, image_url, caption=f"🎨 *Boceto:* {prompt_visual}", parse_mode="Markdown")
    except Exception as e:
        print(f"Error imagen: {e}")
        bot.reply_to(message, "❌ No pude procesar el boceto visual.")

# --- MANEJADOR DE INTENCIÓN Y QWEN REASONING ---
@bot.message_handler(func=lambda message: True)
def handle_all_messages(message):
    print(f">>> Entrada: {message.text}")
    try:
        # FASE 1: MOTOR QWEN CON RAZONAMIENTO (Basado en el snippet de Groq)
        # Nota: Usamos el ID de modelo qwen-2.5-32b que es el que soporta razonamiento en Groq
        completion = groq_client.chat.completions.create(
            model="qwen/qwen3-32b",
            messages=[
                {"role": "system", "content": "Eres Bozi-bot, experto en Ciberseguridad. Piensa profundamente antes de responder."},
                {"role": "user", "content": message.text}
            ],
            temperature=0.6,
            max_completion_tokens=4096,
            top_p=0.95,
            # reasoning_effort="default", # Habilitar cuando el ID soporte el parámetro nativo
            stream=False # Lo ponemos en False para facilitar el reply en Telegram
        )
        
        response_text = completion.choices[0].message.content
        bot.reply_to(message, response_text)

    except Exception as e:
        print(f">>> ERROR: {e}")
        bot.reply_to(message, "⚠️ El motor Qwen está procesando mucha carga o hay un error de ID.")

# --- EJECUCIÓN CON PROTOCOLO ANTI-CONFLICTO (RESET DE SESIÓN) ---
if __name__ == "__main__":
    # Arrancamos Flask para el Health Check de Cron-job.org
    threading.Thread(target=run_server, daemon=True).start()
    
    print(">>> Bozi-Bot: Iniciando protocolo de limpieza de procesos...")
    
    try:
        # 1. Matamos cualquier Webhook previo
        bot.remove_webhook()
        # 2. Limpiamos la cola de mensajes acumulados (esto evita el lag del celular)
        bot.delete_webhook(drop_pending_updates=True)
        # 3. Espera de seguridad para que Telegram propague el cierre de sesiones viejas
        time.sleep(3)
    except Exception as e:
        print(f"Error en el reset de Telegram: {e}")

    print(">>> Sesión reclamada exitosamente. Motor Qwen Online.")
    
    # Iniciamos el polling con parámetros de resiliencia
    bot.infinity_polling(timeout=60, long_polling_timeout=30)
