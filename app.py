import os
import telebot
from groq import Groq
import threading
import time
from flask import Flask

# --- CONFIGURACIÓN DE VARIABLES ---
# Cargadas desde Render -> Dashboard -> Settings -> Environment
TOKEN = os.environ.get("TELEGRAM_TOKEN")
GROQ_KEY = os.environ.get("GROQ_API_KEY")

bot = telebot.TeleBot(TOKEN, threaded=False)
groq_client = Groq(api_key=GROQ_KEY)

# --- SERVIDOR WEB (HEALTH CHECK PARA RENDER) ---
# Este servidor responde a Cron-job.org para mantener el bot despierto
server = Flask(__name__)

@server.route('/')
def health():
    return "Bozi-Bot is Online & Active", 200

def run_server():
    port = int(os.environ.get("PORT", 10000))
    server.run(host='0.0.0.0', port=port)

# --- LÓGICA DEL BOT: COMANDOS ---

@bot.message_handler(commands=['img'])
def generate_image(message):
    prompt = message.text.replace("/img ", "").strip()
    
    if not prompt or prompt == "/img":
        bot.reply_to(message, "⚠️ Decime qué querés dibujar. Ej: /img topologia de red segura")
        return
    
    bot.send_chat_action(message.chat.id, 'upload_photo')
    
    # Seed dinámico para evitar la caché de Telegram
    seed = int(time.time())
    encoded_prompt = prompt.replace(' ', '%20')
    image_url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1024&height=1024&nologo=true&seed={seed}"
    
    try:
        bot.send_photo(
            message.chat.id, 
            image_url, 
            caption=f"🎨 *Boceto para:* {prompt}",
            parse_mode="Markdown"
        )
    except Exception as e:
        print(f"Error en imagen: {e}")
        bot.reply_to(message, "❌ No pude generar la imagen en este momento.")

# --- LÓGICA DEL BOT: TEXTO (LLAMA 3.3) ---

@bot.message_handler(func=lambda message: True)
def handle_ia(message):
    try:
        chat = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": "Sos Iván Bozikovich, Senior IT Infrastructure y Cybersecurity Specialist. Respondé de forma técnica y profesional."},
                {"role": "user", "content": message.text}
            ]
        )
        bot.reply_to(message, chat.choices[0].message.content)
    except Exception as e:
        print(f"Error en IA: {e}")

# --- EJECUCIÓN DEL SISTEMA ---
if __name__ == "__main__":
    # Arrancamos el servidor Flask para que Cron-job.org tenga a quién hablarle
    threading.Thread(target=run_server, daemon=True).start()
    
    print(">>> Bozi-Bot desplegado exitosamente.")
    print(">>> Esperando pings de Cron-job.org para mantener persistencia.")
    
    bot.remove_webhook()
    bot.infinity_polling()
