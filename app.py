import os
import telebot
from groq import Groq
from supabase import create_client, Client
import requests
import threading
import time
from datetime import datetime
from flask import Flask

# --- CONFIGURACIÓN DE INFRAESTRUCTURA ---
TOKEN = os.environ.get("TELEGRAM_TOKEN")
GROQ_KEY = os.environ.get("GROQ_API_KEY")
TAVILY_KEY = os.environ.get("TAVILY_API_KEY")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

bot = telebot.TeleBot(TOKEN, threaded=False)
groq_client = Groq(api_key=GROQ_KEY)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
app = Flask(__name__)

@app.route('/')
def health(): return "Bozi-bot Engine Online", 200

# --- HERRAMIENTA DE BÚSQUEDA (EL SENSOR EXTERNO) ---
def buscar_en_internet(query):
    print(f">>> [WEB] Buscando datos reales para: {query}")
    try:
        r = requests.post("https://api.tavily.com/search", json={
            "api_key": TAVILY_KEY, 
            "query": query, 
            "search_depth": "advanced",
            "max_results": 3
        }, timeout=10)
        resultados = r.json().get('results', [])
        if not resultados: return "No se hallaron resultados recientes en la web."
        return "\n".join([f"- {res['content']}" for res in resultados])
    except Exception as e:
        return f"Error de conexión con Tavily: {str(e)}"

# --- LÓGICA DE RAZONAMIENTO Y DECISIÓN ---
def procesar_respuesta_inteligente(user_id, texto_usuario):
    fecha_actual = datetime.now().strftime("%A %d de %B de %Y")
    
    # PASO 1: Análisis de Necesidad de Datos (Módulo de Decisión)
    # Aquí Qwen3 decide si necesita internet. Le prohibimos decir "no tengo internet".
    decision_prompt = [
        {"role": "system", "content": "Eres un auditor de actualidad. Tu única función es responder 'BUSCAR' si la pregunta requiere datos de 2024-2026, clima, noticias o hechos fácticos. Responde 'MEMORIA' solo si es una charla casual o lógica pura. NO des explicaciones."},
        {"role": "user", "content": texto_usuario}
    ]
    
    decision = groq_client.chat.completions.create(
        model="qwen/qwen3-32b",
        messages=decision_prompt,
        temperature=0.1
    ).choices[0].message.content.strip().upper()

    contexto_web = ""
    if "BUSCAR" in decision:
        contexto_web = buscar_en_internet(texto_usuario)

    # PASO 2: Recuperar Memoria de Supabase
    try:
        res_mem = supabase.table("memories").select("content").eq("project_name", str(user_id)).order("id", desc=True).limit(5).execute()
        historial = "\n".join([m['content'] for m in res_mem.data])
    except: historial = ""

    # PASO 3: Respuesta Final Basada en Evidencia
    prompt_final = [
        {
            "role": "system", 
            "content": (
                f"Eres Bozi-bot, Senior IT Specialist. Hoy es {fecha_actual}. "
                "INSTRUCCIÓN: Tienes acceso total a Internet a través de Tavily. "
                f"DATOS DE INTERNET OBTENIDOS: {contexto_web}. "
                f"HISTORIAL DE PROYECTO: {historial}. "
                "REGLA: Si recibiste datos de internet, USALOS. No digas que no puedes conectar. "
                "Si la información web contradice tu memoria interna, la web es la VERDAD."
            )
        },
        {"role": "user", "content": texto_usuario}
    ]

    # Usamos Llama 3.3 como failover o para ejecución final si Qwen satura tokens
    try:
        res = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=prompt_final,
            temperature=0.3
        )
        return res.choices[0].message.content
    except:
        return "⚠️ Error: Los modelos están saturados. Reintenta en 10 segundos."

@bot.message_handler(func=lambda m: True)
def handle_text(message):
    bot.send_chat_action(message.chat.id, 'typing')
    
    respuesta = procesar_respuesta_inteligente(message.chat.id, message.text)
    
    # Limpieza de tags de razonamiento si aparecen
    if "</think>" in respuesta:
        respuesta = respuesta.split("</think>")[-1].strip()

    # Persistencia en Supabase
    try:
        supabase.table("memories").insert({
            "project_name": str(message.chat.id),
            "content": f"U: {message.text} | B: {respuesta}"
        }).execute()
    except: pass

    bot.reply_to(message, respuesta)

# --- BOOTSTRAP ANTI-409 ---
def run_telebot():
    bot.remove_webhook()
    bot.delete_webhook(drop_pending_updates=True)
    time.sleep(3)
    print(">>> Bozi-bot reclamó el control del token.")
    bot.infinity_polling(timeout=90)

if __name__ == "__main__":
    threading.Thread(target=run_telebot, daemon=True).start()
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
