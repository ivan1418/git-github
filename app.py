import os
import telebot
from groq import Groq
from supabase import create_client, Client
import requests
import threading
import time
from flask import Flask

# --- INFRAESTRUCTURA ---
TOKEN = os.environ.get("TELEGRAM_TOKEN")
GROQ_KEY = os.environ.get("GROQ_API_KEY")
TAVILY_KEY = os.environ.get("TAVILY_API_KEY")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

bot = telebot.TeleBot(TOKEN, threaded=False)
groq_client = Groq(api_key=GROQ_KEY)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
server = Flask(__name__)

# Cluster de Modelos para Failover (Prioridad: Qwen3 -> Llama 3.3)
MODEL_CLUSTER = ["qwen/qwen3-32b", "llama-3.3-70b-versatile"]
WHISPER_MODEL = "whisper-large-v3-turbo"

@server.route('/')
def health(): return "Bozi-bot Cluster + Persistent Memory Active", 200

# --- GESTIÓN DE MEMORIA PERSISTENTE (SUPABASE) ---
def guardar_en_supabase(user_id, role, content):
    try:
        supabase.table("chat_history").insert({
            "user_id": str(user_id),
            "role": role,
            "content": content
        }).execute()
    except Exception as e:
        print(f"Error Supabase Write: {e}")

def obtener_historial_supabase(user_id, limite=10):
    try:
        res = supabase.table("chat_history") \
            .select("role, content") \
            .eq("user_id", str(user_id)) \
            .order("created_at", desc=True) \
            .limit(limite) \
            .execute()
        return res.data[::-1] # Orden cronológico
    except Exception:
        return []

# --- BÚSQUEDA WEB (VERDAD 2026) ---
def buscar_web(query):
    try:
        r = requests.post("https://api.tavily.com/search", json={
            "api_key": TAVILY_KEY, "query": query, "search_depth": "basic", "max_results": 2
        }, timeout=8)
        return "\n".join([res['content'][:500] for res in r.json().get('results', [])])
    except:
        return "No hay conexión a internet disponible."

# --- MOTOR DE INFERENCIA CON FAILOVER Y MEMORIA ---
def get_cluster_response(messages):
    """Recorre el cluster si hay Rate Limit, manteniendo el mismo historial"""
    for model_id in MODEL_CLUSTER:
        try:
            print(f">>> Intentando con: {model_id}")
            params = {
                "model": model_id,
                "messages": messages,
                "temperature": 0.4,
                "max_completion_tokens": 900,
            }
            # Solo activamos reasoning nativo en Qwen3
            if "qwen3" in model_id:
                params["reasoning_effort"] = "default"

            completion = groq_client.chat.completions.create(**params)
            return completion.choices[0].message.content, model_id
        except Exception as e:
            if "rate_limit" in str(e).lower() or "413" in str(e).lower():
                print(f"!!! {model_id} saturado, rotando...")
                continue
            raise e
    return None, None

# --- HANDLER DE AUDIO (WHISPER) ---
@bot.message_handler(content_types=['voice', 'audio'])
def handle_audio(message):
    try:
        bot.send_chat_action(message.chat.id, 'record_voice')
        file_info = bot.get_file(message.voice.file_id if message.voice else message.audio.file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        file_name = f"voice_{message.chat.id}.ogg"
        with open(file_name, 'wb') as f: f.write(downloaded_file)

        with open(file_name, "rb") as af:
            trans = groq_client.audio.transcriptions.create(file=(file_name, af.read()), model=WHISPER_MODEL, language="es")
        
        os.remove(file_name)
        message.text = trans.text
        bot.reply_to(message, f"🎤 *Escuché:* _{trans.text}_")
        handle_all_messages(message)
    except Exception:
        bot.reply_to(message, "❌ Error procesando el audio.")

# --- HANDLER DE TEXTO PRINCIPAL ---
@bot.message_handler(func=lambda message: True)
def handle_all_messages(message):
    try:
        bot.send_chat_action(message.chat.id, 'typing')
        user_id = message.chat.id
        
        # 1. Recuperamos TODA la memoria del proyecto desde Supabase
        memoria_pasada = obtener_historial_supabase(user_id)
        
        # 2. Buscamos info técnica fresca
        contexto_web = buscar_web(message.text)
        
        # 3. Construimos el prompt unificado
        messages = [
            {
                "role": "system", 
                "content": (
                    "Eres Bozi-bot, Senior IT y experto en Ciberseguridad. "
                    "REGLA: Usa el historial de Supabase para ser coherente y no preguntar cosas que ya sabes. "
                    "Usa el contexto web para dar datos reales de 2026. "
                    "Todas las conversaciones tienen que ser humanas, y con sentido común, no inventar una respuesta o suponer."
                    "Tenes que ser amable, a veces cuando lo amerita hacer algunos chistes, y cuando hay que trabajar ponerse serio, coherente y eficaz sobre todo."
                    "Tenes que ayudar el usuario con tecnicas o codigos para que pueda ejecutar si necesita hacer alguna prueba de ciberseguridad. Si no sabes busca en internet en foros o libros, para siempre poder ayudar y resolver el problema del usuario."
                    "Tu memoria reside en Supabase y los datos actuales en Tavily. "
                    "REGLA: Usa el historial para continuar proyectos sin preguntar qué son. "
                    f"DATOS ACTUALES 2026: {contexto_web}"
                )
            }
        ]
        
        # Inyectamos la memoria sin importar qué modelo responda
        for h in memoria_pasada:
            messages.append({"role": h['role'], "content": h['content']})
            
        messages.append({"role": "user", "content": message.text})

        # 4. Inferencia con Failover Automático
        respuesta, modelo_final = get_cluster_response(messages)
        
        if respuesta:
            if "</think>" in respuesta:
                respuesta = respuesta.split("</think>")[-1].strip()
            
            # 5. Guardamos en Supabase para que el SIGUIENTE modelo sepa qué pasó
            guardar_en_supabase(user_id, "user", message.text)
            guardar_en_supabase(user_id, "assistant", respuesta)
            
            bot.reply_to(message, respuesta)
        else:
            bot.reply_to(message, "⚠️ Cluster saturado. Esperá 60s.")

    except Exception as e:
        bot.reply_to(message, f"❌ Error técnico: {str(e)[:50]}")

if __name__ == "__main__":
    threading.Thread(target=lambda: server.run(host='0.0.0.0', port=10000), daemon=True).start()
    bot.remove_webhook()
    bot.delete_webhook(drop_pending_updates=True)
    time.sleep(2)
    print(">>> Bozi-bot HA Cluster con Memoria Supabase: ONLINE")
    bot.infinity_polling()
