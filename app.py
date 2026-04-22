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
    return "Bozi-Bot AI Intent Gateway Active", 200

def run_server():
    port = int(os.environ.get("PORT", 10000))
    server.run(host='0.0.0.0', port=port)

# --- MÓDULO DE GENERACIÓN VISUAL ---
def trigger_image(message, prompt_visual):
    print(f">>> Iniciando generación de imagen: {prompt_visual}")
    bot.send_chat_action(message.chat.id, 'upload_photo')
    
    seed = int(time.time())
    # Limpiamos el prompt para URL
    clean_prompt = prompt_visual.replace(' ', '%20').replace('"', '')
    image_url = f"https://image.pollinations.ai/prompt/{clean_prompt}?width=1024&height=1024&nologo=true&seed={seed}"
    
    try:
        bot.send_photo(
            message.chat.id, 
            image_url, 
            caption=f"🎨 *Boceto:* {prompt_visual}\n\n_Generado por Bozi-Bot AI_",
            parse_mode="Markdown"
        )
        print(">>> Imagen enviada con éxito.")
    except Exception as e:
        print(f">>> ERROR al enviar imagen: {e}")
        bot.reply_to(message, "❌ No pude procesar el boceto. Probá con una descripción más simple.")

# --- MANEJADOR DE INTENCIÓN (BRAIN) ---
@bot.message_handler(func=lambda message: True)
def handle_all_messages(message):
    print(f">>> Procesando entrada: {message.text}")
    
    try:
        # FASE 1: CLASIFICACIÓN ESTRICTA
        classification = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {
                    "role": "system", 
                    "content": (
                        "Eres un clasificador binario. "
                        "Si el usuario pide ver, dibujar, mostrar o generar una imagen/boceto/gráfico, "
                        "responde EXCLUSIVAMENTE con la palabra IMAGEN: seguida del prompt en inglés. "
                        "Si el usuario solo charla o pregunta, responde EXCLUSIVAMENTE con la palabra TEXTO. "
                        "PROHIBIDO dar explicaciones o saludar."
                    )
                },
                {"role": "user", "content": message.text}
            ]
        )
        
        intent_res = classification.choices[0].message.content.strip()
        print(f">>> Intención detectada: {intent_res}")

        if intent_res.upper().startswith("IMAGEN:"):
            # FASE 2A: GENERACIÓN
            visual_desc = intent_res.split("IMAGEN:")[1].strip()
            trigger_image(message, visual_desc)
        
        else:
            # FASE 2B: RESPUESTA TÉCNICA (IVÁN)
            chat = groq_client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {
                        "role": "system", 
                        "content": "Sos Iván"
                    },
                    {"role": "user", "content": message.text}
                ]
            )
            bot.reply_to(message, chat.choices[0].message.content)

    except Exception as e:
        print(f">>> ERROR GENERAL: {e}")
        bot.reply_to(message, "⚠️ El sistema de IA tuvo un hipo técnico. Intentá de nuevo.")

# --- INICIO DE SERVICIOS ---
if __name__ == "__main__":
    # Arrancamos Flask en hilo separado (Daemon para que muera con el main)
    threading.Thread(target=run_server, daemon=True).start()
    
    print(">>> Bozi-Bot desplegado. Salud check OK en puerto 10000.")
    bot.remove_webhook()
    bot.infinity_polling()
