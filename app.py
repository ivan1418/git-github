import os
import telebot
from groq import Groq
from supabase import create_client, Client
import requests
import threading
import time
from datetime import datetime
from flask import Flask

# --- CONFIGURACIÓN ---
TOKEN = os.environ.get("TELEGRAM_TOKEN")
GROQ_KEY = os.environ.get("GROQ_API_KEY")
TAVILY_KEY = os.environ.get("TAVILY_API_KEY")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

bot = telebot.TeleBot(TOKEN, threaded=False)
groq_client = Groq(api_key=GROQ_KEY)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
app = Flask(__name__)

# Cluster de Failover
MODEL_CLUSTER = ["qwen/qwen3-32b", "llama-3.3-70b-versatile"]

@app.route('/')
def health():
    return "Bozi-bot Alive", 200

# --- LÓGICA DE MEMORIA Y LLM ---
def leer_historial(user_id):
    try:
        res = supabase.table("memories").select("content").eq("project_name", str(user_id)).order("id", desc=True).limit(5).execute()
        return "\n".join([item['content'] for item in res.data])
    except: return ""

def pensar_y_responder(user_id, text):
    fecha_hoy = datetime.now().strftime("%A, %d de %B de 2026")
    historial = leer_historial(user_id)
    
    # Búsqueda obligatoria para evitar datos viejos
    contexto_web = ""
    try:
        r = requests.post("https://api.tavily.com/search", json={
            "api_key": TAVILY_KEY, "query": text, "max_results": 2
        }, timeout=8)
        contexto_web = "\n".join([res['content'][:500] for res in r.json().get('results', [])])
    except: pass

    prompt = (
        f"Eres Bozi-bot. Hoy es {fecha_hoy}. No inventes fechas. "
        f"Historial: {historial}. Web: {contexto_web}. "
        "Sé técnico, breve y usa los datos web sobre tu memoria interna."
    )

    for model in MODEL_CLUSTER:
        try:
            res = groq_client.chat.completions.create(
                model=model,
                messages=[{"role": "system", "content": prompt}, {"role": "user", "content": text}],
                temperature=0.1
            )
            return res.choices[0].message.content
        except: continue
    return "⚠️ Cluster saturado."

@bot.message_handler(func=lambda m: True)
def main_handler(message):
    bot.send_chat_action(message.chat.id, 'typing')
    ans = pensar_y_responder(message.chat.id, message.text)
    if "</think>" in ans: ans = ans.split("</think>")[-1].strip()
    
    # Guardar en Supabase
    try:
        supabase.table("memories").insert({"project_name": str(message.chat.id), "content": f"U: {message.text} | B: {ans}"}).execute()
    except: pass
    
    bot.reply_to(message, ans)

# --- BOOTSTRAP DE INFRAESTRUCTURA ---
def run_bot():
    print(">>> Reclamando Token de Telegram...")
    bot.remove_webhook()
    bot.delete_webhook(drop_pending_updates=True)
    time.sleep(3) # Tiempo para que Telegram cierre sesiones viejas
    print(">>> Bot escuchando.")
    bot.infinity_polling(timeout=90, long_polling_timeout=30)

if __name__ == "__main__":
    # Iniciamos el bot en un thread separado
    threading.Thread(target=run_bot, daemon=True).start()
    
    # Iniciamos Flask en el puerto que Render requiere (PORT 10000)
    # Esto es CRÍTICO para el error "No open ports detected"
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
