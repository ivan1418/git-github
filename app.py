# ===================================================
# 🏛️ BOZI-BOT: EL CEREBRO HÍBRIDO ASINCRÓNICO DE ELITE
# Versión: 5.15 (COMMAND RESTORATION + PUBLISH FIX)
# ===================================================

import os, logging, json, requests, threading, time, asyncio
from datetime import datetime, timedelta
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
PENDING_ACTIONS = {} 
DEBUG_MODE = {}

MODEL_HIGH = os.getenv("MODEL_HIGH", "gpt-4o")
MODEL_LOW = "meta-llama/llama-3.1-8b-instruct:free"
MODEL_BACKUP = "mistralai/mistral-7b-instruct"

# ---------------------------------------------------
# 🧠 PERSISTENCIA Y MEMORIA
# ---------------------------------------------------

async def get_config(chat_id):
    try:
        res = supabase.table("user_config").select("*").eq("chat_id", int(chat_id)).execute()
        return res.data[0] if res.data else {"model": MODEL_HIGH, "lang": "Rosario/Voseo"}
    except: return {"model": MODEL_HIGH, "lang": "Rosario/Voseo"}

async def save_interaction_to_memory(chat_id, user_text, bot_response):
    try:
        if openai_client:
            res_emb = await openai_client.embeddings.create(input=f"Iván: {user_text}\nBot: {bot_response}", model="text-embedding-3-small")
            supabase.table("bot_knowledge").insert({"chat_id": int(chat_id), "content": f"Iván: {user_text}\nBot: {bot_response}", "embedding": res_emb.data[0].embedding}).execute()
    except: pass

async def get_semantic_memory(chat_id, query):
    if not openai_client: return ""
    try:
        res_emb = await openai_client.embeddings.create(input=query, model="text-embedding-3-small")
        res = supabase.rpc("match_knowledge", {"query_embedding": res_emb.data[0].embedding, "match_threshold": 0.5, "match_count": 2, "p_chat_id": int(chat_id)}).execute()
        return "\n\n💡 [MEMORIA]:\n" + "\n".join([d['content'] for d in res.data]) if res.data else ""
    except: return ""

async def search_web_real(query):
    if not TAVILY_API_KEY: return ""
    try:
        res = requests.post("https://api.tavily.com/search", json={"api_key": TAVILY_API_KEY, "query": query, "search_depth": "smart"}, timeout=10).json()
        return "\n\n🌐 [WEB]:\n" + "\n".join([f"- {r['title']}: {r['url']}" for r in res.get("results", [])[:2]])
    except: return ""

# ---------------------------------------------------
# 🚀 SMART ROUTER
# ---------------------------------------------------

async def smart_neural_router(chat_id, user_text, history):
    if not openai_client: return {"intent": "chat", "complexity": "low"}
    hist_str = "\n".join([f"{m['role']}: {m['content']}" for m in history[-3:]])
    prompt = (
        f"Historial: {hist_str}\nUsuario: {user_text}\n"
        "Categorías: task_op, project_op, publish, chat, web.\n"
        "Respondé SOLO JSON: {'intent': '...', 'complexity': 'low|high', 'confidence': 0.0, 'needs_confirm': bool, 'params': {'desc': '...', 'date': 'YYYY-MM-DD HH:MM:SS', 'update': '...'}}"
    )
    try:
        res = await openai_client.chat.completions.create(model="gpt-4o-mini", messages=[{"role": "user", "content": prompt}], response_format={"type": "json_object"})
        return json.loads(res.choices[0].message.content)
    except: return {"intent": "chat", "complexity": "low"}

# ---------------------------------------------------
# 🤖 ORQUESTADOR Y FALLBACK
# ---------------------------------------------------

async def call_ai_with_extreme_fallback(messages, complexity, preferred_model):
    clients_to_try = []
    if complexity == "high" and openai_client: clients_to_try.append((openai_client, preferred_model))
    if openrouter_client:
        clients_to_try.append((openrouter_client, MODEL_LOW))
        clients_to_try.append((openrouter_client, MODEL_BACKUP))
    if not clients_to_try and openai_client: clients_to_try.append((openai_client, MODEL_HIGH))

    for client, model in clients_to_try:
        try:
            res = await client.chat.completions.create(model=model, messages=messages, max_tokens=800)
            content = res.choices[0].message.content
            if content and len(content.strip()) > 2: return content, model
        except: continue
    return "❌ Error en la malla de IA.", "none"

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_text = update.message.text
    if not user_text: return
    if chat_id not in CHAT_HISTORY: CHAT_HISTORY[chat_id] = []
    
    await context.bot.send_chat_action(chat_id=chat_id, action=constants.ChatAction.TYPING)
    intent_data = await smart_neural_router(chat_id, user_text, CHAT_HISTORY[chat_id])
    
    if user_text.lower() in ["no", "cancelá"]:
        if PENDING_ACTIONS.pop(chat_id, None): return await update.message.reply_text("👍 Cancelado.")
    if chat_id in PENDING_ACTIONS and user_text.lower() in ["si", "sí", "dale"]:
        action_obj = PENDING_ACTIONS.pop(chat_id)
        asyncio.create_task(execute_smart_action(chat_id, action_obj['data'], context.bot, user_text))
        return await update.message.reply_text("👌 Procediendo.")

    memoria = await get_semantic_memory(chat_id, user_text)
    web = await search_web_real(user_text) if intent_data['intent'] == "web" else ""
    conf = await get_config(chat_id)
    
    messages = [{"role": "system", "content": f"Socio IT Rosario. {memoria}{web}"}]
    messages.extend(CHAT_HISTORY[chat_id][-8:]); messages.append({"role": "user", "content": user_text})

    bot_response, used_model = await call_ai_with_extreme_fallback(messages, intent_data['complexity'], conf['model'])
    tag = f"\n\n⚡ [{used_model.split('/')[-1]}]" if DEBUG_MODE.get(chat_id) else ""
    await update.message.reply_text(f"{bot_response}{tag}")
    
    CHAT_HISTORY[chat_id].append({"role": "user", "content": user_text}); CHAT_HISTORY[chat_id].append({"role": "assistant", "content": bot_response})
    
    if intent_data['intent'] not in ["chat", "web"]:
        if intent_data.get('needs_confirm') or intent_data.get('confidence', 0) < 0.8:
            PENDING_ACTIONS[chat_id] = {"data": intent_data, "expires": datetime.now() + timedelta(minutes=5)}
            await update.message.reply_text(f"❓ ¿Ejecuto {intent_data['intent']}?")
        else: asyncio.create_task(execute_smart_action(chat_id, intent_data, context.bot, user_text))
            
    asyncio.create_task(save_interaction_to_memory(chat_id, user_text, bot_response))

# ---------------------------------------------------
# 🛠️ ACCIONES Y VISION
# ---------------------------------------------------

async def execute_smart_action(chat_id, intent_data, bot, original_text):
    intent = intent_data.get('intent')
    params = intent_data.get('params', {})
    try:
        if "task" in intent:
            date = params.get('date') or datetime.now(ARG_TZ).strftime('%Y-%m-%d %H:%M:%S')
            supabase.table("scheduled_tasks").insert({"chat_id": int(chat_id), "description": params.get('desc', original_text), "scheduled_at": date, "status": "pending"}).execute()
            await bot.send_message(chat_id, "📌 Tarea anotada.")
        elif "project" in intent:
            res = supabase.table("projects").select("*").eq("chat_id", int(chat_id)).eq("status", "draft").execute()
            new_c = f"\n[{datetime.now(ARG_TZ).strftime('%H:%M')}] {params.get('update', original_text)}"
            if res.data:
                supabase.table("projects").update({"content": res.data[0]['content'] + new_c}).eq("id", res.data[0]['id']).execute()
            else:
                supabase.table("projects").insert({"chat_id": int(chat_id), "content": new_c, "status": "draft"}).execute()
            await bot.send_message(chat_id, "📝 Borrador actualizado.")
        elif intent == "publish":
            res_draft = supabase.table("projects").select("*").eq("chat_id", int(chat_id)).eq("status", "draft").execute()
            if res_draft.data:
                res_ia = await openai_client.chat.completions.create(model=MODEL_HIGH, messages=[{"role": "system", "content": "HTML5/Tailwind. SOLO código."}, {"role": "user", "content": res_draft.data[0]['content']}])
                # FIX SINTAXIS: Reemplazo en una sola línea para evitar errores de despliegue
                html = res_ia.choices[0].message.content.replace("```html", "").replace("```", "").strip()
                supabase.table("projects").update({"content": html, "status": "published"}).eq("id", res_draft.data[0]['id']).execute()
                await bot.send_message(chat_id, f"🚀 Publicado en: {os.getenv('RENDER_EXTERNAL_URL')}/view/{res_draft.data[0]['id']}")
    except Exception as e: logging.error(f"Error Action: {e}")

async def handle_photo(update, context):
    photo = await update.message.photo[-1].get_file()
    try:
        res = await openai_client.chat.completions.create(model=MODEL_HIGH, messages=[{"role": "user", "content": [{"type": "text", "text": "Analizá técnicamente."}, {"type": "image_url", "image_url": {"url": photo.file_path}}]}] )
        await update.message.reply_text(f"👁️ Análisis:\n\n{res.choices[0].message.content}")
    except: await update.message.reply_text("❌ Error visión.")

# ---------------------------------------------------
# 🌐 HANDLERS Y SERVER (FULL)
# ---------------------------------------------------

async def start_cmd(update, context): await update.message.reply_text("🏛️ Bozi-bot V5.15 Online.")
async def status_cmd(update, context): await update.message.reply_text(f"🖥️ Online | {datetime.now(ARG_TZ).strftime('%H:%M:%S')}")
async def debug_cmd(update, context):
    DEBUG_MODE[update.effective_chat.id] = not DEBUG_MODE.get(update.effective_chat.id, False)
    await update.message.reply_text(f"🛠️ Debug: {'ON' if DEBUG_MODE[update.effective_chat.id] else 'OFF'}")

async def tasks_cmd(update, context):
    res = supabase.table("scheduled_tasks").select("*").eq("chat_id", update.effective_chat.id).eq("status", "pending").execute()
    msg = "\n".join([f"📌 {t['scheduled_at']}: {t['description']}" for t in res.data]) if res.data else "Limpio."
    await update.message.reply_text(f"📝 Pendientes:\n{msg}")

async def config_cmd(update, context):
    c = await get_config(update.effective_chat.id)
    await update.message.reply_text(f"⚙️ Config: {c['model']}")

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
            try:
                p_id = self.path.split("/")[-1]
                res = supabase.table("projects").select("content").eq("id", p_id).execute()
                if res.data:
                    self.send_response(200); self.send_header("Content-type", "text/html"); self.end_headers()
                    self.wfile.write(res.data[0]['content'].encode()); return
            except: pass
        self.send_response(200); self.end_headers(); self.wfile.write(b"Bozi-bot V5.15 Live")

if __name__ == "__main__":
    requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/deleteWebhook?drop_pending_updates=True")
    threading.Thread(target=lambda: HTTPServer(("0.0.0.0", int(os.environ.get("PORT", 10000))), DashboardHandler).serve_forever(), daemon=True).start()
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start_cmd)); app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("debug", debug_cmd)); app.add_handler(CommandHandler("tasks", tasks_cmd))
    app.add_handler(CommandHandler("config", config_cmd))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    loop = asyncio.get_event_loop(); loop.create_task(task_worker(app.bot)); app.run_polling()
