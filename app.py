import os
import telebot
from groq import Groq
import threading
import time
from flask import Flask

# --- CONFIGURACIÓN ---
TOKEN = os.environ.get("TELEGRAM_TOKEN")
GROQ_KEY = os.environ.get("GROQ_API_KEY")

bot = telebot.TeleBot(TOKEN, threaded=False)
groq_client = Groq(api_key=GROQ_KEY)
server = Flask(__name__)

@server.route('/')
def health():
    return "Bozi-Bot AI Intent Gateway Active", 200

def run_server():
    port = int(os.environ.get("PORT", 10000))
    server.run(host='0.0.0.0', port=port)

# --- MÓDULO VISUAL ---
def trigger_image(message, prompt_visual):
    print(f">>> [ACCION] Generando imagen para: {prompt_visual}")
    bot.send_chat_action(message.chat.id, 'upload_photo')
    seed = int(time.time())
    clean_prompt = prompt_visual.replace(' ', '%20').replace('"', '')
    image_url = f"https://image.pollinations.ai/prompt/{clean_prompt}?width=1024&height=1024&nologo=true&seed={seed}"
    
    try:
        bot.send_photo(
            message.chat.id, 
            image_url, 
            caption=f"🎨 *Boceto:* {prompt_visual}",
            parse_mode="Markdown"
        )
    except Exception as e:
        print(f">>> Error enviando imagen: {e}")
        bot.reply_to(message, "❌ No pude procesar el boceto.")

# --- MANEJADOR DE INTENCIÓN (EL CEREBRO) ---
@bot.message_handler(func=lambda message: True)
def handle_all_messages(message):
    print(f">>> Mensaje entrante: {message.text}")
    
    try:
        # FASE 1: CLASIFICACIÓN ULTRA-ESTRICTA
        # Le pedimos que actúe como una API, no como un chat.
        classification = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {
                    "role": "system", 
                    "content": (
                        "Eres un motor de clasificación técnica. Tu salida debe ser estrictamente una de estas dos opciones:\n"
                        "1. Si el usuario quiere una imagen/boceto/dibujo/esquema: responde 'IMG: [descripción en español]'\n"
                        "2. Si es charla o consulta técnica: responde 'TXT'\n"                        
                    )
                },
                {"role": "user", "content": message.text}
            ]
        )
        
        intent_res = classification.choices[0].message.content.strip()
        print(f">>> Clasificación: {intent_res}")

        if intent_res.upper().startswith("IMG:"):
            # FASE 2A: DISPARAR IMAGEN
            visual_desc = intent_res.split("IMG:")[1].strip()
            trigger_image(message, visual_desc)
        
        else:
            # FASE 2B: RESPUESTA TÉCNICA (Bozi)
            chat = groq_client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {
                        "role": "system", 
                        "content": "Eres Bozi"
                    },
                    {"role": "user", "content": message.text}
                ]
            )
            bot.reply_to(message, chat.choices[0].message.content)

    except Exception as e:
        print(f">>> Error en el proceso: {e}")
        bot.reply_to(message, "⚠️ Error técnico en el procesamiento.")

if __name__ == "__main__":
    threading.Thread(target=run_server, daemon=True).start()
    print(">>> Bozi-Bot desplegado. Salud check OK.")
    bot.remove_webhook()
    bot.infinity_polling()
