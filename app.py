# ===================================================
# 🏛️ BOZI-BOT: EL CEREBRO HÍBRIDO ASINCRÓNICO DE ELITE
# Versión: 5.10 (ACTION GUARD + TRIPLE FALLBACK + FULL OPS)
# ===================================================

import os, logging, json, requests, threading, time, asyncio
from datetime import datetime
import pytz 
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update, constants
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, CommandHandler, filters
from openai import AsyncOpenAI
from supabase import create_client

# ---------------------------------------------------
# ⚙️ CONFIGURACIÓN Y CLIENTES
# ---------------------------------------------------
logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")

openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None
openrouter_client = AsyncOpenAI(base_url="https://openrouter.ai/api/v1", api_key=OPENROUTER_API_KEY) if OPENROUTER_API_KEY else None
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
ARG_TZ = pytz.timezone('America/Argentina/Buenos_Aires')

CHAT_HISTORY = {} 
PENDING_ACTIONS = {} # Action Guard: Almacena intenciones que requieren confirmación
DEBUG_MODE = {}

MODEL_HIGH = os.getenv("MODEL_HIGH", "gpt-4o")
MODEL_LOW = "meta-llama/llama-3.1-8b-instruct:free"
MODEL_BACKUP = "google/gemini-flash-1.5-exp"

# ---------------------------------------------------
# 🧠 MEMORIA Y BÚSQUEDA (DEFINICIONES ROBUSTAS)
# ---------------------------------------------------

async def get_semantic_memory(chat_id, query):
    if not openai_client: return ""
    try:
        res_emb = await openai_client.embeddings.create(input=query, model="text-embedding-3-small")
        res = supabase.rpc("match_knowledge", {
            "query_embedding": res_emb.data[0].embedding, "match_threshold": 0.5, "match_count": 2, "p_chat_id": int(chat_id)
        }).execute()
        return "\n\n💡 [MEMORIA]:\n" + "\n".join([d['content'] for d in res.data]) if res.data else ""
    except: return ""

async def search_web_real(query):
    if not TAVILY_API_KEY: return ""
    try:
        res = requests.post("https://api.tavily.com/search", json={"api_key": TAVILY_API_KEY, "query": query, "search_depth": "smart"}, timeout=10).json()
        return "\n\n🌐 [WEB]:\n" + "\n".join([f"- {r['title']}: {r['url']}" for r in res.get("results", [])[:2]])
    except: return ""

async def save_interaction_to_memory(chat_id, user_text, bot_response):
    try:
        content = f"Iván: {user_text}\nBot: {bot_response}"
        if openai_client:
            res_emb = await openai_client.embeddings.create(input=content, model="text-embedding-3-small")
            supabase.table("bot_knowledge").insert({"chat_id": int(chat_id), "content": content, "embedding": res_emb.data[0].embedding}).execute()
    except Exception as e: logging.error(f"Error memoria: {e}")

# ---------------------------------------------------
# 🚀 ROUTER CON RAZONAMIENTO Y ACTION GUARD
# ---------------------------------------------------

async def neural_router(chat_id, user_text, history):
    if not openai_client: return {"intent": "chat", "complexity": "low"}
    hist_str = "\n".join([f"{m['role']}: {m['content']}" for m in history[-3:]])
    prompt = (
        f"Historial: {hist_str}\nUsuario: {user_text}\n"
        "Intents: task_op, project_op, publish, config, web_search, chat, cancel.\n"
        "Complexity: high|low. Needs_confirm: true si la acción es crítica o ambigua.\n"
        "Respondé JSON: {'intent': '...', 'complexity': 'low|high', 'confidence': 0.0, 'needs_confirm': bool, 'params': {}}"
    )
    try:
        res = await openai_client.chat.completions.create(model="gpt-4o-mini", messages=[{"role": "user", "content": prompt}], response_format={"type": "json_object"})
        return json.loads(res.choices[0].message.content)
    except: return {"intent": "chat", "complexity": "low", "confidence": 1.0}

# ---------------------------------------------------
# 🛠️ ACCIONES (FULL OPS + ACTION GUARD)
# ---------------------------------------------------

async def execute_smart_action(chat_id, intent_data, bot, original_text):
    intent = intent_data.get('intent')
    params = intent_data.get('params', {})
    try:
        if "task" in intent:
            date = params.get('date') or datetime.now(ARG_TZ).strftime('%Y-%m-%d %H:%M:%S')
            supabase.table("scheduled_tasks").insert({"chat_id": int(chat_id), "description": params.get('desc', original_text), "scheduled_at": date, "status": "pending"}).execute()
            await bot.send_message(chat_id, "📌 Tarea anotada en la DB.")
            
        elif "project" in intent:
            res = supabase.table("projects").select("*").eq("chat_id", int(chat_id)).eq("status", "draft").execute()
            new_c = f"\n[{datetime.now(ARG_TZ).strftime('%H:%M')}] {params.get('update', original_text)}"
            if res.data:
                supabase.table("projects").update({"content": res.data[0]['content'] + new_c}).eq("id", res.data[0]['id']).execute()
            else:
                supabase.table("projects").insert({"chat_id": int(chat_id), "content": new_c, "status": "draft"}).execute()
            await bot.send_message(chat_id, "📝 Borrador de proyecto actualizado.")

        elif intent == "publish":
            res_draft = supabase.table("projects").select("*").eq("chat_id", int(chat_id)).eq("status", "draft").execute()
            if res_draft.data:
                res_ia = await openai_client.chat.completions.create(model=MODEL_HIGH, messages=[{"role": "system", "content": "HTML5/Tailwind. SOLO código."}, {"role": "user", "content": res_draft.data[0]['content']}])
                html = res_ia.choices[0].message.content.replace("```html", "").replace("```", "").strip()
                supabase.table("projects").update({"content": html, "status": "published"}).eq("id", res_draft.data[0]['id']).execute()
                await bot.send_message(chat_id, f"🚀 Publicado en: {os.getenv('RENDER_EXTERNAL_URL')}/view/{res_draft.data[0]['id']}")

    except Exception as e: logging.error(f"Error en acción: {e}")

# ---------------------------------------------------
# 🤖 ORQUESTADOR (TRIPLE FALLBACK + ACTION GUARD)
# ---------------------------------------------------

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_text = update.message.text
    if not user_text: return
    if chat_id not in CHAT_HISTORY: CHAT_HISTORY[chat_id] = []
    
    await context.bot.send_chat_action(chat_id=chat_id, action=constants.ChatAction.TYPING)
    intent_data = await neural_router(chat_id, user_text, CHAT_HISTORY[chat_id])
    
    # 1. Manejo de Negativa o Cancelación
    if intent_data['intent'] == "cancel" or user_text.lower() in ["no", "cancelá", "pará"]:
        PENDING_ACTIONS.pop(chat_id, None)
        return await update.message.reply_text("👍 Listo Iván, cancelado.")

    # 2. Confirmación de Acción Pendiente
    if chat_id in PENDING_ACTIONS and user_text.lower() in ["si", "sí", "dale", "metele"]:
        stored_intent = PENDING_ACTIONS.pop(chat_id)
        asyncio.create_task(execute_smart_action(chat_id, stored_intent, context.bot, user_text))
        return await update.message.reply_text("👌 Procediendo...")

    # 3. Triple Fallback Simétrico
    memoria = await get_semantic_memory(chat_id, user_text)
    web = await search_web_real(user_text) if intent_data['intent'] == "web_search" else ""
    conf_user = await get_config(chat_id)
    
    messages = [{"role": "system", "content": f"Socio IT Rosario. Natural. {memoria}{web}"}]
    messages.extend(CHAT_HISTORY[chat_id][-8:])
    messages.append({"role": "user", "content": user_text})

    bot_response, used_model = "❌ Sin respuesta IA", "none"
    try:
        client = openai_client if (intent_data['complexity'] == "high" and openai_client) else openrouter_client
        model = MODEL_HIGH if (intent_data['complexity'] == "high" and openai_client) else MODEL_LOW
        res = await client.chat.completions.create(model=model, messages=messages, max_tokens=800)
        bot_response, used_model = res.choices[0].message.content, model
    except:
        try: # Fallback a OpenRouter Backup
            res = await openrouter_client.chat.completions.create(model=MODEL_BACKUP, messages=messages)
            bot_response, used_model = res.choices[0].message.content, MODEL_BACKUP
        except: pass

    debug_tag = f"\n\n⚡ [{used_model.split('/')[-1]}]" if DEBUG_MODE.get(chat_id) else ""
    await update.message.reply_text(f"{bot_response}{debug_tag}")
    
    # 4. Actualización de Contexto y Gestión de Acción
    CHAT_HISTORY[chat_id].append({"role": "user", "content": user_text})
    CHAT_HISTORY[chat_id].append({"role": "assistant", "content": bot_response})
    if len(CHAT_HISTORY[chat_id]) > 16: CHAT_HISTORY[chat_id] = CHAT_HISTORY[chat_id][-16:]
    
    if intent_data['intent'] not in ["chat", "cancel"]:
        if intent_data.get('needs_confirm') or intent_data.get('confidence', 0) < 0.8:
            PENDING_ACTIONS[chat_id] = intent_data
            await update.message.reply_text(f"❓ Iván, ¿querés que ejecute '{intent_data['intent']}'? (si/no)")
        else:
            asyncio.create_task(execute_smart_action(chat_id, intent_data, context.bot, user_text))
            
    asyncio.create_task(save_interaction_to_memory(chat_id, user_text, bot_response))

# ---------------------------------------------------
# 🌐 HANDLERS Y SERVER (FULL DEPLOYABLE)
# ---------------------------------------------------

async def debug_cmd(update, context):
    DEBUG_MODE[update.effective_chat.id] = not DEBUG_MODE.get(update.effective_chat.id, False)
    await update.message.reply_text(f"🛠️ Debug: {'ON' if DEBUG_MODE[update.effective_chat.id] else 'OFF'}")

async def start_cmd(update, context): await update.message.reply_text("🏛️ Bozi-bot V5.10: Neural Guard Active.")
async def status_cmd(update, context): await update.message.reply_text(f"🖥️ Online | {datetime.now(ARG_TZ).strftime('%H:%M:%S')}")

async def task_worker(bot):
    while True:
        try:
            now = datetime.now(ARG_TZ).strftime('%Y-%m-%d %H:%M:%S')
            res = supabase.table("scheduled_tasks").select("*").eq("status", "pending").lte("scheduled_at", now).execute()
            for t in res.data:
                await bot.send_message(chat_id=t['chat_id'], text=f"🔔 RECORDATORIO: {t['description']}")
                supabase.table("scheduled_tasks").update({"status": "completed"}).eq("id", t['id']).execute()
        except: pass
        await asyncio.sleep(60)

class DashboardHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/view/"):
            p_id = self.path.split("/")[-1]
            res = supabase.table("projects").select("content").eq("id", p_id).execute()
            if res.data:
                self.send_response(200); self.send_header("Content-type", "text/html"); self.end_headers()
                self.wfile.write(res.data[0]['content'].encode()); return
        self.send_response(200); self.end_headers(); self.wfile.write(b"Bozi-bot V5.10 Live")

if __name__ == "__main__":
    requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/deleteWebhook?drop_pending_updates=True")
    threading.Thread(target=lambda: HTTPServer(("0.0.0.0", int(os.environ.get("PORT", 10000))), DashboardHandler).serve_forever(), daemon=True).start()
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start_cmd)); app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("debug", debug_cmd))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    loop = asyncio.get_event_loop(); loop.create_task(task_worker(app.bot)); app.run_polling()
