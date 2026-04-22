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
    return "Bozi-Bot Qwen Engine Active", 200

def run_server():
    port = int(os.environ.get("PORT", 10000))
    server.run(host='0.0.0.0', port=port)

# --- MÓDULO DE GENERACIÓN VISUAL ---
def trigger_image(message, prompt_visual):
    print(f">>> [ACCION] Generando imagen: {prompt_visual}")
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
        bot.reply_to(message, "❌ No pude procesar el boceto visual.")

# --- MANEJADOR DE INTENCIÓN Y CEREBRO QWEN ---
@bot.message_handler(func=lambda message: True)
def handle_all_messages(message):
    print(f">>> Entrada recibida: {message.text}")
    
    try:
        # FASE 1: CLASIFICACIÓN RÁPIDA (Seguimos con Llama para latencia mínima en ruteo)
        classification = groq_client.chat.completions.create(
            model="qwen/qwen3-32b",
            messages=[
                {
                    "role": "system", 
                    "content": "Eres un motor de ruteo. Si el usuario pide una imagen o boceto responde 'IMG: [descripción en español]'. Si es charla responde 'TXT'. Sin explicaciones."
                },
                {"role": "user", "content": message.text}
            ]
        )
        
        intent_res = classification.choices[0].message.content.strip().upper()

        if intent_res.startswith("IMG:"):
            visual_desc = intent_res.split("IMG:")[1].strip()
            trigger_image(message, visual_desc)
            return 
        
        else:
            # FASE 2: RESPUESTA TÉCNICA CON QWEN
            # Aquí usamos el ID exacto que habilitaste en Groq
            chat = groq_client.chat.completions.create(
                model="qwen/qwen3-32b", # Cambialo por el ID exacto que ves en tu consola de Groq
                messages=[
                    {
                        "role": "system", 
                        "content": (
                            "Eres Bozi"
                            "Responde con profundidad técnica, profesionalismo y precisión. Piensa paso a paso."
                        )
                    },
                    {"role": "user", "content": message.text}
                ]
            )
            
            bot.reply_to(message, chat.choices[0].message.content)

    except Exception as e:
        print(f">>> ERROR: {e}")
        bot.reply_to(message, "⚠️ Error técnico al conectar con el modelo Qwen.")

if __name__ == "__main__":
    threading.Thread(target=run_server, daemon=True).start()
    print(">>> Bozi-Bot desplegado con motor Qwen.")    
    # Limpieza de cola de mensajes para evitar duplicados en el celular
    bot.delete_webhook(drop_pending_updates=True) 
    bot.infinity_polling(timeout=60)
