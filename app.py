import os
import telebot
from groq import Groq
import threading
from flask import Flask

# --- CONFIGURACIÓN DE VARIABLES ---
TOKEN = os.environ.get("TELEGRAM_TOKEN")
GROQ_KEY = os.environ.get("GROQ_API_KEY")

bot = telebot.TeleBot(TOKEN, threaded=False)
groq_client = Groq(api_key=GROQ_KEY)

# --- SERVIDOR WEB (HEALTH CHECK PARA RENDER) ---
server = Flask(__name__)

@server.route('/')
def health():
    return "Bozi-Bot is Running", 200

def run_server():
    # Render asigna el puerto automáticamente
    port = int(os.environ.get("PORT", 10000))
    server.run(host='0.0.0.0', port=port)

# --- LÓGICA DEL BOT ---
@bot.message_handler(func=lambda message: True)
def handle_ia(message):
    try:
        chat = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": "Sos Iván Bozikovich, experto en ciberseguridad con 20 años de experiencia. Respondé técnico y profesional."},
                {"role": "user", "content": message.text}
            ]
        )
        bot.reply_to(message, chat.choices[0].message.content)
    except Exception as e:
        print(f"Error en IA: {e}")

# --- EJECUCIÓN ---
if __name__ == "__main__":
    # Iniciamos el servidor web en un hilo secundario
    threading.Thread(target=run_server).start()
    
    # Iniciamos el Bot en el hilo principal
    print(">>> Bot Online y Servidor Health Check listo")
    bot.remove_webhook()
    bot.infinity_polling()
