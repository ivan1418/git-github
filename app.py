import os
import telebot
from groq import Groq
import threading
import time
from flask import Flask

TOKEN = os.environ.get("TELEGRAM_TOKEN")
GROQ_KEY = os.environ.get("GROQ_API_KEY")

bot = telebot.TeleBot(TOKEN, threaded=False)
groq_client = Groq(api_key=GROQ_KEY)
server = Flask(__name__)

@server.route('/')
def health():
    return "Bozi-Bot AI Intent Active", 200

def run_server():
    port = int(os.environ.get("PORT", 10000))
    server.run(host='0.0.0.0', port=port)

# --- FUNCIÓN PARA GENERAR IMAGEN ---
def trigger_image(message, prompt_visual):
    bot.send_chat_action(message.chat.id, 'upload_photo')
    seed = int(time.time())
    encoded_prompt = prompt_visual.replace(' ', '%20')
    image_url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1024&height=1024&nologo=true&seed={seed}"
    try:
        bot.send_photo(message.chat.id, image_url, caption=f"🎨 Boceto generado: {prompt_visual}")
    except Exception as e:
        bot.reply_to(message, "❌ Error al generar el boceto.")

# --- MANEJADOR ÚNICO CON CLASIFICACIÓN DE INTENCIÓN ---
@bot.message_handler(func=lambda message: True)
def handle_intent(message):
    print(f">>> Analizando intención de: {message.text}")
    
    try:
        # Le pedimos a Llama que clasifique el mensaje
        classification = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {
                    "role": "system", 
                    "content": "Analiza si el usuario pide una imagen, dibujo, boceto o esquema. Responde SOLO con la palabra 'IMAGEN' seguida de una descripción optimizada en inglés para el generador, o 'TEXTO' si es una charla normal. Ejemplo: 'IMAGEN a high tech server rack'"
                },
                {"role": "user", "content": message.text}
            ]
        )
        
        response_type = classification.choices[0].message.content.strip()

        if response_type.startswith("IMAGEN"):
            # Si Llama dice que es imagen, extraemos la descripción
            visual_prompt = response_type.replace("IMAGEN", "").strip()
            trigger_image(message, visual_prompt)
        else:
            # Si es charla, respondemos como Iván Bozikovich
            chat = groq_client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": "Sos Iván Bozikovich, Senior IT y experto en Ciberseguridad. Respondé técnico."},
                    {"role": "user", "content": message.text}
                ]
            )
            bot.reply_to(message, chat.choices[0].message.content)

    except Exception as e:
        print(f"Error en clasificación: {e}")
        bot.reply_to(message, "Hubo un error al procesar tu solicitud.")

if __name__ == "__main__":
    threading.Thread(target=run_server, daemon=True).start()
    bot.remove_webhook()
    bot.infinity_polling()
