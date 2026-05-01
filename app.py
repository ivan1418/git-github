# ===================================================
# 🏛️ BOZI-BOT: EL CEREBRO HÍBRIDO ASINCRÓNICO DE ELITE
# Versión: 5.19 (ATOMIC RESILIENCE + FORCED FALLBACK)
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
# 🤖 MALLA DE IA ULTRA RESILIENTE (FIXED)
# ---------------------------------------------------

async def call_ai_logic(messages, complexity, preferred_model):
    """Malla Triple: Intenta según complejidad con timeouts estrictos."""
    queue = []
    if complexity == "high":
        if openai_client: queue.append((openai_client, preferred_model, "OpenAI-Primary"))
        if openrouter_client: queue.append((openrouter_client, MODEL_LOW, "OpenRouter-Low"))
    else:
        if openrouter_client: queue.append((openrouter_client, MODEL_LOW, "OpenRouter-Primary"))
        if openai_client: queue.append((openai_client, preferred_model, "OpenAI-High"))
    
    # Backup terciario siempre al final
    if openrouter_client: queue.append((openrouter_client, MODEL_BACKUP, "Backup-Terciario"))

    for client, model, label in queue:
        try:
            logging.info(f"Intentando con {label} ({model})...")
            res = await asyncio.wait_for(
                client.chat.completions.create(model=model, messages=messages, max_tokens=800),
                timeout=12.0 # Timeout de 12 segundos para no colgar el bot
            )
            content = res.choices[0].message.content
            if content and len(content.strip()) > 1:
                prefix = "⚠️ [Modo Backup]: " if "Backup" in label else ""
                return f"{prefix}{content}", model
        except Exception as e:
            logging.error(f"Falla en {label}: {e}")
            continue
    
    return "❌ Lo siento Iván, los servicios de IA están saturados. Reintentá en un momento.", "none"

# ---------------------------------------------------
# 🚀 ORQUESTADOR Y HANDLERS
# ---------------------------------------------------

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_text = update.message.text
    if not user_text: return
    if chat_id not in CHAT_HISTORY: CHAT_HISTORY[chat_id] = []
    
    await context.bot.send_chat_action(chat_id=chat_id, action=constants.ChatAction.TYPING)

    # Determinación de complejidad rápida (basada en keywords para no bloquear)
    complexity = "low"
    tech_keywords = ["program", "code", "cyber", "seguridad", "api", "fix", "error", "script", "hacker"]
    if any(k in user_text.lower() for k in tech_keywords):
        complexity = "high"

    # Preparar mensajes
    messages = [{"role": "system", "content": "Socio IT Rosario. Natural y directo."}]
    messages.extend(CHAT_HISTORY[chat_id][-6:])
    messages.append({"role": "user", "content": user_text})

    # Llamada a la IA con la malla de fallback
    bot_response, used_model = await call_ai_logic(messages, complexity, MODEL_HIGH)
    
    # Enviar respuesta
    tag = f"\n\n⚡ [{used_model.split('/')[-1]}]" if DEBUG_MODE.get(chat_id) else ""
    await update.message.reply_text(f"{bot_response}{tag}")
    
    # Actualizar historial
    CHAT_HISTORY[chat_id].append({"role": "user", "content": user_text})
    CHAT_HISTORY[chat_id].append({"role": "assistant", "content": bot_response})
    if len(CHAT_HISTORY[chat_id]) > 10: CHAT_HISTORY[chat_id] = CHAT_HISTORY[chat_id][-10:]

async def start_cmd(update, context): await update.message.reply_text("🏛️ Bozi-bot V5.19 Operativo.")
async def status_cmd(update, context): await update.message.reply_text(f"🖥️ Online | {datetime.now(ARG_TZ).strftime('%H:%M:%S')}")
async def debug_cmd(update, context):
    DEBUG_MODE[update.effective_chat.id] = not DEBUG_MODE.get(update.effective_chat.id, False)
    await update.message.reply_text(f"🛠️ Debug: {'ON' if DEBUG_MODE[update.effective_chat.id] else 'OFF'}")

class DashboardHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers(); self.wfile.write(b"Bozi-bot V5.19 Live")

if __name__ == "__main__":
    # Limpiar Webhook
    requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/deleteWebhook?drop_pending_updates=True")
    
    # Server para Render
    threading.Thread(target=lambda: HTTPServer(("0.0.0.0", int(os.environ.get("PORT", 10000))), DashboardHandler).serve_forever(), daemon=True).start()
    
    # App
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("debug", debug_cmd))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    
    logging.info("Bot en marcha...")
    app.run_polling()
