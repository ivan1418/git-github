import os
import telebot
from groq import Groq
import threading
import time
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
    return "Bozi-Bot is Active", 200

def run_server():
    port = int(os.environ.get("PORT", 10000))
    server.run(host='0.0.0.0', port=port)

# --- LÓGICA DEL BOT ---

# 1. COMANDO DE IMAGEN (Sintaxis ultra-robusta con Lambda)
# Esto atrapa el mensaje si empieza EXACTAMENTE con '/img ' o '/img@nombre_de_tu_bot'
@bot.message_handler(func=lambda message: message.text and message.text.startswith(('/img ', '/img@')))
def generate_image(message):
    print(f">>> [DEBUG] Comando /img capturado con éxito: {message.text}")
    
    # Limpiamos el texto del comando
    prompt = message.text.replace("/img ", "").replace(f"/img@{bot.get_me().username} ", "").strip()
    
    if not prompt:
        bot.reply_to(message, "⚠️ Decime qué querés dibujar. Ej: /img servidor en un rack")
        return
    
    # Feedback visual
    bot.send_chat_action(message.chat.id, 'upload_photo')
    
    # Seed dinámico para evitar la caché de Telegram
    seed = int(time.time())
    encoded_prompt = prompt.replace(' ', '%20')
    image_url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1024&height=1024&nologo=true&seed={seed}"
    
    try:
        # Envío de la foto con formato Markdown
        bot.send_photo(
            message.chat.id, 
            image_url, 
            caption=f"🎨 *Boceto generado para:* {prompt}",
            parse_mode="Markdown"
        )
        print(">>> [DEBUG] Imagen enviada correctamente.")
    except Exception as e:
        print(f">>> [DEBUG] Error al enviar imagen: {e}")
        bot.reply_to(message, "❌ No pude generar la imagen en este momento.")

# 2. MANEJADOR DE TEXTO GENERAL (Llama)
# Este bloque SIEMPRE debe ir después de los comandos específicos
@bot.message_handler(func=lambda message: True)
def handle_ia(message):
    print(f">>> [DEBUG] Mensaje de texto procesado por Llama: {message.text}")
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
        print(f">>> [DEBUG] Error Groq: {e}")

# --- EJECUCIÓN DEL SISTEMA ---
if __name__ == "__main__":
    # Arrancamos Flask en paralelo
    threading.Thread(target=run_server, daemon=True).start()
    
    print(">>> Servidor Health Check Online.")
    print(">>> Bozi-Bot escuchando... (Modo Polling)")
    
    bot.remove_webhook()
    bot.infinity_polling()
