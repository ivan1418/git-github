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
    # Avisamos en Telegram que estamos cargando la foto
    bot.send_chat_action(message.chat.id, 'upload_photo')
    seed = int(time.time())
    clean_prompt = prompt_visual.replace(' ', '%20').replace('"', '')
    image_url = f"https://image.pollinations.ai/prompt/{clean_prompt}?width=1024&height=1024&nologo=true&seed={seed}"
    
    try:
        # Enviamos SOLO la foto con su epígrafe
        bot.send_photo(
            message.chat.id, 
            image_url, 
            caption=f"🎨 *Boceto:* {prompt_visual}",
            parse_mode="Markdown"
        )
        print(">>> Imagen enviada correctamente.")
    except Exception as e:
        print(f">>> Error enviando imagen: {e}")
        bot.reply_to(message, "❌ No pude procesar el boceto.")

# --- MANEJADOR DE INTENCIÓN (EL CEREBRO) ---
@bot.message_handler(func=lambda message: True)
def handle_all_messages(message):
    print(f">>> Mensaje entrante: {message.text}")
    
    try:
        # FASE 1: CLASIFICACIÓN ULTRA-ESTRICTA
        # Este prompt es el Firewall. Le prohíbe charlar si detecta imagen.
        classification = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {
                    "role": "system", 
                    "content": (
                        "Eres un motor de ruteo técnico. Analiza la intención del usuario.\n"
                        "Regla 1: Si el usuario quiere ver, dibujar, mostrar o generar una imagen/boceto/gráfico, responde EXCLUSIVAMENTE con 'IMG: [descripción en español]'.\n"
                        "Regla 2: Si es charla o consulta técnica normal, responde 'TXT'.\n"
                        "Regla 3: Si hace falta dar explicaciones ponelas, saluda y pedí disculpas si es necesario. Pero solo responde el código IMG o TXT cuando estamos haciendo un trabajo."
                    )
                },
                {"role": "user", "content": message.text}
            ]
        )
        
        # Obtenemos la respuesta y la forzamos a mayúsculas para evitar fallas
        intent_res = classification.choices[0].message.content.strip()
        print(f">>> Clasificación: {intent_res}")

        if intent_res.upper().startswith("IMG:"):
            # FASE 2A: DISPARAR IMAGEN Y *CORTAR LA EJECUCIÓN* AQUÍ
            visual_desc = intent_res.split("IMG:")[1].strip()
            trigger_image(message, visual_desc)
            # El return asegura que no se ejecute nada más abajo
            return 
        
        else:
            # FASE 2B: RESPUESTA TÉCNICA (Bozi)
            # Solo se ejecuta si la clasificación fue 'TXT'
            chat = groq_client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {
                        "role": "system", 
                        "content": "Eres Bozi. Responde de forma técnica, profesional y al grano."
                    },
                    {"role": "user", "content": message.text}
                ]
            )
            bot.reply_to(message, chat.choices[0].message.content)

    except Exception as e:
        print(f">>> Error en el proceso: {e}")
        bot.reply_to(message, "⚠️ El sistema de IA tuvo un hipo técnico. Intentá de nuevo.")

if __name__ == "__main__":
    threading.Thread(target=run_server, daemon=True).start()
    print(">>> Bozi-Bot desplegado exitosamente. Salud check OK en puerto 10000.")    
    # Aseguramos que el bot empiece limpio sin webhooks viejos
    bot.remove_webhook()
    bot.infinity_polling()
