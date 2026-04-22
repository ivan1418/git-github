import os
import telebot
from groq import Groq
import threading
import time
from flask import Flask

# --- CONFIGURACIÓN ---
TOKEN = os.environ.get("TELEGRAM_TOKEN")
GROQ_KEY = os.environ.get("GROQ_API_KEY")

# Usamos non-threaded para evitar colisiones de memoria en el tier gratuito
bot = telebot.TeleBot(TOKEN, threaded=False)
groq_client = Groq(api_key=GROQ_KEY)
server = Flask(__name__)

@server.route('/')
def health():
    return "Bozi-Bot Qwen Engine Active", 200

def run_server():
    port = int(os.environ.get("PORT", 10000))
    server.run(host='0.0.0.0', port=port)

# --- MÓDULO VISUAL ---
def trigger_image(message, prompt_visual):
    bot.send_chat_action(message.chat.id, 'upload_photo')
    seed = int(time.time())
    clean_prompt = prompt_visual.replace(' ', '%20').replace('"', '')
    image_url = f"https://image.pollinations.ai/prompt/{clean_prompt}?width=1024&height=1024&nologo=true&seed={seed}"
    try:
        bot.send_photo(message.chat.id, image_url, caption=f"🎨 *Boceto:* {prompt_visual}", parse_mode="Markdown")
    except Exception:
        bot.reply_to(message, "❌ Error al generar imagen.")

# --- MANEJADOR DE INTENCIÓN Y QWEN ---
@bot.message_handler(func=lambda message: True)
def handle_all_messages(message):
    try:
        # FASE 1: Ruteo rápido con Llama
        classification = groq_client.chat.completions.create(
            model="qwen/qwen3-32b",
            messages=[{"role": "system", "content": "Responde 'IMG: [desc en ingles]' o 'TXT'. Sin hablar."},
                      {"role": "user", "content": message.text}]
        )
        
        intent = classification.choices[0].message.content.strip().upper()

        if intent.startswith("IMG:"):
            trigger_image(message, intent.split("IMG:")[1].strip())
            return 

        # FASE 2: EL CEREBRO QWEN (Pensamiento profundo)
        chat = groq_client.chat.completions.create(
            model="qwen-2.5-32b", # ID OFICIAL EN GROQ
            messages=[
                {"role": "system", "content": "Eres Bozi-bot, experto en Ciberseguridad. Antes de responder, piensa y analiza técnicamente y piensa la solución más eficiente."},
                {"role": "user", "content": message.text}
            ]
        )
        bot.reply_to(message, chat.choices[0].message.content)

    except Exception as e:
        print(f">>> Error: {e}")
        bot.reply_to(message, "⚠️ Error en el motor Qwen.")

# --- EJECUCIÓN CON LIMPIEZA DE CONFLICTOS ---
if __name__ == "__main__":
    threading.Thread(target=run_server, daemon=True).start()
    
    print(">>> Bozi-Bot: Solicitando control exclusivo del Token...")
    
    # MATAMOS CUALQUIER OTRA INSTANCIA (LOCAL O REMOTA)
    bot.delete_webhook(drop_pending_updates=True)
    time.sleep(2) # Espera técnica para que Telegram procese el reset
    
    print(">>> Motor Qwen Online.")
    bot.infinity_polling(timeout=60, long_polling_timeout=30)
