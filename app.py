# ===================================================
# 🏛️ BOZI-BOT: EL CEREBRO HÍBRIDO ASINCRÓNICO DE ELITE
# Versión: 7.1 (ADAPTIVE INFRASTRUCTURE + DYNAMIC MODELS)
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

openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None
openrouter_client = AsyncOpenAI(base_url="https://openrouter.ai/api/v1", api_key=OPENROUTER_API_KEY) if OPENROUTER_API_KEY else None
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
ARG_TZ = pytz.timezone('America/Argentina/Buenos_Aires')

CHAT_HISTORY, PENDING_ACTIONS, DEBUG_MODE = {}, {}, {}
MODEL_HIGH = os.getenv("MODEL_HIGH", "gpt-4o")

# Cache para modelos dinámicos (Descubrimiento en tiempo real)
DYNAMIC_MODELS = {"primary_free": "meta-llama/llama-3.1-8b-instruct:free", "backup_free": "google/gemini-flash-1.5-exp"}

# ---------------------------------------------------
# 🔍 DESCUBRIMIENTO DINÁMICO DE MODELOS
# ---------------------------------------------------

def update_free_models():
    """Consulta la API de OpenRouter para encontrar los mejores modelos gratis vigentes."""
    global DYNAMIC_MODELS
    try:
        logging.info("Buscando modelos gratuitos en OpenRouter...")
        response = requests.get("https://openrouter.ai/api/v1/models")
        if response.status_code == 200:
            all_models = response.json().get('data', [])
            free_models = [
                m for m in all_models 
                if float(m.get('pricing', {}).get('prompt', 0)) == 0 
                and float(m.get('pricing', {}).get('completion', 0)) == 0
            ]
            # Ordenar por longitud de contexto para priorizar los más capaces
            free_models.sort(key=lambda x: x.get('context_length', 0), reverse=True)
            if len(free_models) >= 2:
                DYNAMIC_MODELS["primary_free"] = free_models[0]['id']
                DYNAMIC_MODELS["backup_free"] = free_models[1]['id']
                logging.info(f"Malla actualizada: {DYNAMIC_MODELS['primary_free']} | {DYNAMIC_MODELS['backup_free']}")
    except Exception as e:
        logging.error(f"Error actualizando modelos: {e}")

def schedule_model_updates():
    while True:
        update_free_models()
        time.sleep(3600) # Cada hora

# ---------------------------------------------------
# 🧠 MEMORIA Y PERSISTENCIA
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
# 💻 CODING ENGINE MEJORADO
# ---------------------------------------------------

async def generate_and_deploy(chat_id, user_request):
    """Genera código con fallback real: OpenAI -> OpenRouter Dinámico."""
    # Intentar primero con OpenAI (Máxima calidad) y luego con el mejor Backup gratis
    clients = [(openai_client, MODEL_HIGH), (openrouter_client, DYNAMIC_MODELS["backup_free"])]
    code = None
    
    for client, model in clients:
        if not client: continue
        try:
            res = await asyncio.wait_for(client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": "Generador de código puro. Solo HTML/Tailwind. Sin explicaciones."},
                    {"role": "user", "content": user_request}
                ]
            ), timeout=30.0)
            raw_code = res.choices[0].message.content.replace("```html", "").replace("```", "").strip()
            if "<html" in raw_code.lower():
                code = raw_code
                break
        except: continue

    if not code: return None

    try:
        res_db = supabase.table("projects").insert({"chat_id": int(chat_id), "content": code, "status": "published"}).execute()
        p_id = res_db.data[0]['id']
        return f"https://git-github-47x8.onrender.com/view/{p_id}"
    except Exception as e:
        logging.error(f"Error DB Deploy: {e}")
        return None

# ---------------------------------------------------
# 🚀 ORQUESTADOR INTEGRAL
# ---------------------------------------------------

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_text = update.message.text
    if not user_text: return
    if chat_id not in CHAT_HISTORY: CHAT_HISTORY[chat_id] = []
    
    await context.bot.send_chat_action(chat_id=chat_id, action=constants.ChatAction.TYPING)

    # 1. Ruteo Inteligente de Programación
    coding_triggers = ["haceme", "programá", "creá la web", "desplegá", "hacerla vos", "sitio"]
    if any(t in user_text.lower() for t in coding_triggers):
        await update.message.reply_text("🚀 Iniciando motor de arquitectura y despliegue...")
        url = await generate_and_deploy(chat_id, user_text)
        if url: return await update.message.reply_text(f"✅ ¡Online Iván!\n{url}")
        else: return await update.message.reply_text("❌ Falló el compilador o la DB.")

    # 2. Conversación Adaptativa (Fallback a OpenRouter si falla OpenAI)
    memoria = await get_semantic_memory(chat_id, user_text)
    messages = [{"role": "system", "content": f"Socio IT Rosario. Natural. {memoria}"}]
    messages.extend(CHAT_HISTORY[chat_id][-8:]); messages.append({"role": "user", "content": user_text})

    bot_response, used_model = "❌ No hay respuesta.", "none"
    # Malla: OpenAI -> OpenRouter Gratis Primario
    for client, model in [(openai_client, MODEL_HIGH), (openrouter_client, DYNAMIC_MODELS["primary_free"])]:
        if not client: continue
        try:
            res = await asyncio.wait_for(client.chat.completions.create(model=model, messages=messages), timeout=15.0)
            bot_response, used_model = res.choices[0].message.content, model
            break
        except: continue

    tag = f"\n\n⚡ [{used_model.split('/')[-1]}]" if DEBUG_MODE.get(chat_id) else ""
    await update.message.reply_text(f"{bot_response}{tag}")
    
    CHAT_HISTORY[chat_id].append({"role": "user", "content": user_text})
    CHAT_HISTORY[chat_id].append({"role": "assistant", "content": bot_response})
    if len(CHAT_HISTORY[chat_id]) > 12: CHAT_HISTORY[chat_id] = CHAT_HISTORY[chat_id][-12:]
    asyncio.create_task(save_interaction_to_memory(chat_id, user_text, bot_response))

# ---------------------------------------------------
# 🛠️ HANDLERS Y COMANDOS
# ---------------------------------------------------

async def handle_photo(update, context):
    photo = await update.message.photo[-1].get_file()
    try:
        res = await openai_client.chat.completions.create(model=MODEL_HIGH, messages=[{"role": "user", "content": [{"type": "text", "text": "Analizá técnicamente."}, {"type": "image_url", "image_url": {"url": photo.file_path}}]}] )
        await update.message.reply_text(f"👁️ Análisis:\n\n{res.choices[0].message.content}")
    except: await update.message.reply_text("❌ Error analizando visión.")

async def start_cmd(update, context): await update.message.reply_text("🏛️ Bozi-bot V7.1: Adaptive Sentinel Online.")
async def debug_cmd(update, context):
    DEBUG_MODE[update.effective_chat.id] = not DEBUG_MODE.get(update.effective_chat.id, False)
    await update.message.reply_text(f"🛠️ Debug: {'ON' if DEBUG_MODE[update.effective_chat.id] else 'OFF'}")

async def status_cmd(update, context):
    await update.message.reply_text(f"🖥️ Online\n🧠 Modelo Free: {DYNAMIC_MODELS['primary_free']}\n🇦🇷 Rosario: {datetime.now(ARG_TZ).strftime('%H:%M:%S')}")

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

# ---------------------------------------------------
# 🌐 DASHBOARD & MAIN
# ---------------------------------------------------

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
        self.send_response(200); self.end_headers(); self.wfile.write(b"Bozi-bot V7.1 Live")

if __name__ == "__main__":
    requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/deleteWebhook?drop_pending_updates=True")
    
    # Hilos de Background
    threading.Thread(target=schedule_model_updates, daemon=True).start()
    threading.Thread(target=lambda: HTTPServer(("0.0.0.0", int(os.environ.get("PORT", 10000))), DashboardHandler).serve_forever(), daemon=True).start()
    
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("debug", debug_cmd))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    
    loop = asyncio.get_event_loop(); loop.create_task(task_worker(app.bot))
    app.run_polling()
