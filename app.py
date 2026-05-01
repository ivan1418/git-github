# ===================================================
# 🏛️ BOZI-BOT: EL CEREBRO HÍBRIDO ASINCRÓNICO DE ELITE
# Versión: 5.18 (SYNTAX FIX + ROBUST MESH IA)
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

CHAT_HISTORY, PENDING_ACTIONS, DEBUG_MODE = {}, {}, {}

MODEL_HIGH = os.getenv("MODEL_HIGH", "gpt-4o")
MODEL_LOW = "meta-llama/llama-3.1-8b-instruct:free"
MODEL_BACKUP = "google/gemini-flash-1.5-exp"

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

# ---------------------------------------------------
# 🤖 MALLA DE IA CON TRIPLE REINTENTO (FIXED)
# ---------------------------------------------------

async def call_ai_with_extreme_fallback(messages, complexity, preferred_model):
    queue = []
    if complexity == "high":
        if openai_client: queue.append((openai_client, preferred_model, False))
        if openrouter_client: queue.append((openrouter_client, MODEL_LOW, False))
    else:
        if openrouter_client: queue.append((openrouter_client, MODEL_LOW, False))
        if openai_client: queue.append((openai_client, preferred_model, False))
    
    if openrouter_client: queue.append((openrouter_client, MODEL_BACKUP, True))

    for client, model, is_backup in queue:
        try:
            res = await client.chat.completions.create(model=model, messages=messages, max_tokens=800, timeout=15)
            content = res.choices[0].message.content
            if content and len(content.strip()) > 2:
                prefix = "⚠️ [Modo Backup Activo]: " if is_backup else ""
                return f"{prefix}{content}", model
        except: continue
    return "❌ Error crítico en la malla de IA.", "none"

# ---------------------------------------------------
# 🚀 ROUTER Y HANDLERS
# ---------------------------------------------------

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_text = update.message.text
    if not user_text: return
    if chat_id not in CHAT_HISTORY: CHAT_HISTORY[chat_id] = []
    await context.bot.send_chat_action(chat_id=chat_id, action=constants.ChatAction.TYPING)

    # Router Rápido
    try:
        res_r = await openai_client.chat.completions.create(model="gpt-4o-mini", messages=[{"role": "user", "content": f"Usuario: {user_text}. JSON: {{'intent': 'task|project|publish|chat', 'complexity': 'high|low'}}"}], response_format={"type": "json_object"})
        intent_data = json.loads(res_r.choices[0].message.content)
    except: intent_data = {"intent": "chat", "complexity": "low"}

    memoria = await get_semantic_memory(chat_id, user_text)
    conf = await get_config(chat_id)
    messages = [{"role": "system", "content": f"Socio IT Rosario. {memoria}"}]
    messages.extend(CHAT_HISTORY[chat_id][-8:]); messages.append({"role": "user", "content": user_text})

    bot_response, used_model = await call_ai_with_extreme_fallback(messages, intent_data['complexity'], conf['model'])
    tag = f"\n\n⚡ [{used_model.split('/')[-1]}]" if DEBUG_MODE.get(chat_id) else ""
    await update.message.reply_text(f"{bot_response}{tag}")
    
    CHAT_HISTORY[chat_id].append({"role": "user", "content": user_text}); CHAT_HISTORY[chat_id].append({"role": "assistant", "content": bot_response})
    if intent_data['intent'] != "chat": asyncio.create_task(execute_smart_action(chat_id, intent_data, context.bot, user_text))
    asyncio.create_task(save_interaction_to_memory(chat_id, user_text, bot_response))

async def execute_smart_action(chat_id, intent_data, bot, original_text):
    intent = intent_data.get('intent')
    try:
        if intent == "publish":
            res_draft = supabase.table("projects").select("*").eq("chat_id", int(chat_id)).eq("status", "draft").execute()
            if res_draft.data:
                res_ia = await openai_client.chat.completions.create(model=MODEL_HIGH, messages=[{"role": "system", "content": "HTML5. SOLO código."}, {"role": "user", "content": res_draft.data[0]['content']}])
                # LÍNEA 191 CORREGIDA: Sin saltos de línea ni caracteres ocultos
                html = res_ia.choices[0].message.content.replace("```html", "").replace("```", "").strip()
                supabase.table("projects").update({"content": html, "status": "published"}).eq("id", res_draft.data[0]['id']).execute()
                await bot.send_message(chat_id, f"🚀 Publicado en: {os.getenv('RENDER_EXTERNAL_URL')}/view/{res_draft.data[0]['id']}")
    except: pass

async def handle_photo(update, context):
    photo = await update.message.photo[-1].get_file()
    res = await openai_client.chat.completions.create(model=MODEL_HIGH, messages=[{"role": "user", "content": [{"type": "text", "text": "Analizá técnicamente."}, {"type": "image_url", "image_url": {"url": photo.file_path}}]}] )
    await update.message.reply_text(f"👁️ Análisis:\n\n{res.choices[0].message.content}")

async def start_cmd(update, context): await update.message.reply_text("🏛️ Bozi-bot V5.18 Online.")
async def status_cmd(update, context): await update.message.reply_text(f"🖥️ Online | Rosario: {datetime.now(ARG_TZ).strftime('%H:%M:%S')}")

class DashboardHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/view/"):
            p_id = self.path.split("/")[-1]
            res = supabase.table("projects").select("content").eq("id", p_id).execute()
            if res.data:
                self.send_response(200); self.send_header("Content-type", "text/html"); self.end_headers()
                self.wfile.write(res.data[0]['content'].encode()); return
        self.send_response(200); self.end_headers(); self.wfile.write(b"Bozi-bot V5.18 Live")

if __name__ == "__main__":
    requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/deleteWebhook?drop_pending_updates=True")
    threading.Thread(target=lambda: HTTPServer(("0.0.0.0", int(os.environ.get("PORT", 10000))), DashboardHandler).serve_forever(), daemon=True).start()
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start_cmd)); app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo)); app.run_polling()
