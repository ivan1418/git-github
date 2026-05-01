# ===================================================
# 🏛️ BOZI-BOT: EL CEREBRO HÍBRIDO ASINCRÓNICO DE ELITE
# Versión: 5.20 (DYNAMIC DISCOVERY + ADAPTIVE FALLBACK)
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

# Cache para modelos dinámicos
DYNAMIC_MODELS = {"primary": "meta-llama/llama-3.1-8b-instruct:free", "backup": "google/gemini-flash-1.5-exp"}

# ---------------------------------------------------
# 🔍 DESCUBRIMIENTO DINÁMICO DE MODELOS GRATIS
# ---------------------------------------------------

def update_free_models():
    """Consulta la API de OpenRouter para encontrar los mejores modelos gratis."""
    global DYNAMIC_MODELS
    try:
        logging.info("Buscando mejores modelos gratuitos en OpenRouter...")
        response = requests.get("https://openrouter.ai/api/v1/models")
        if response.status_code == 200:
            all_models = response.json().get('data', [])
            # Filtrar solo los que son GRATIS (pricing 0)
            free_models = [
                m for m in all_models 
                if float(m.get('pricing', {}).get('prompt', 0)) == 0 
                and float(m.get('pricing', {}).get('completion', 0)) == 0
            ]
            
            # Ordenar por longitud de contexto (como proxy de 'mejor') o popularidad
            free_models.sort(key=lambda x: x.get('context_length', 0), reverse=True)

            if len(free_models) >= 2:
                DYNAMIC_MODELS["primary"] = free_models[0]['id']
                DYNAMIC_MODELS["backup"] = free_models[1]['id']
                logging.info(f"Modelos actualizados: P={DYNAMIC_MODELS['primary']} | B={DYNAMIC_MODELS['backup']}")
    except Exception as e:
        logging.error(f"Error actualizando modelos: {e}")

# Ejecutar actualización al inicio y cada 1 hora
def schedule_model_updates():
    while True:
        update_free_models()
        time.sleep(3600)

# ---------------------------------------------------
# 🤖 MALLA DE IA ADAPTATIVA
# ---------------------------------------------------

async def call_ai_logic(messages, complexity, preferred_model):
    """Malla Adaptativa: Usa la cache dinámica de modelos gratuitos."""
    queue = []
    p_free = DYNAMIC_MODELS["primary"]
    b_free = DYNAMIC_MODELS["backup"]

    if complexity == "high":
        if openai_client: queue.append((openai_client, preferred_model, "OpenAI-Primary"))
        if openrouter_client: queue.append((openrouter_client, p_free, "OpenRouter-Dynamic-Low"))
    else:
        if openrouter_client: queue.append((openrouter_client, p_free, "OpenRouter-Dynamic-Primary"))
        if openai_client: queue.append((openai_client, preferred_model, "OpenAI-Fallback"))
    
    # Backup terciario dinámico siempre al final
    if openrouter_client: queue.append((openrouter_client, b_free, "Backup-Terciario-Dynamic"))

    for client, model, label in queue:
        try:
            logging.info(f"Turno de {label} usando {model}...")
            res = await asyncio.wait_for(
                client.chat.completions.create(model=model, messages=messages, max_tokens=800),
                timeout=12.0
            )
            content = res.choices[0].message.content
            if content and len(content.strip()) > 1:
                prefix = "⚠️ [Modo Backup Dinámico]: " if "Backup" in label else ""
                return f"{prefix}{content}", model
        except Exception as e:
            logging.error(f"Falla en {label} ({model}): {e}")
            continue
    
    return "❌ Los servicios están saturados. Incluso el descubrimiento dinámico falló.", "none"

# ---------------------------------------------------
# 🚀 ORQUESTADOR
# ---------------------------------------------------

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_text = update.message.text
    if not user_text: return
    if chat_id not in CHAT_HISTORY: CHAT_HISTORY[chat_id] = []
    
    await context.bot.send_chat_action(chat_id=chat_id, action=constants.ChatAction.TYPING)

    # Detección local de complejidad
    complexity = "low"
    tech_keywords = ["program", "code", "cyber", "seguridad", "api", "fix", "error", "script", "hacker", "infra", "deploy"]
    if any(k in user_text.lower() for k in tech_keywords):
        complexity = "high"

    messages = [{"role": "system", "content": "Socio IT Rosario. Natural y directo."}]
    messages.extend(CHAT_HISTORY[chat_id][-6:])
    messages.append({"role": "user", "content": user_text})

    bot_response, used_model = await call_ai_logic(messages, complexity, MODEL_HIGH)
    
    tag = f"\n\n⚡ [{used_model.split('/')[-1]}]" if DEBUG_MODE.get(chat_id) else ""
    await update.message.reply_text(f"{bot_response}{tag}")
    
    CHAT_HISTORY[chat_id].append({"role": "user", "content": user_text})
    CHAT_HISTORY[chat_id].append({"role": "assistant", "content": bot_response})
    if len(CHAT_HISTORY[chat_id]) > 10: CHAT_HISTORY[chat_id] = CHAT_HISTORY[chat_id][-10:]

# --- [ Handlers y Comandos ] ---
async def start_cmd(update, context): await update.message.reply_text("🏛️ Bozi-bot V5.20: Adaptive Hunter Online.")
async def status_cmd(update, context): 
    await update.message.reply_text(f"🖥️ Online\n🧠 Primario Gratis: {DYNAMIC_MODELS['primary']}\n🛡️ Backup Gratis: {DYNAMIC_MODELS['backup']}")

async def debug_cmd(update, context):
    DEBUG_MODE[update.effective_chat.id] = not DEBUG_MODE.get(update.effective_chat.id, False)
    await update.message.reply_text(f"🛠️ Debug: {'ON' if DEBUG_MODE[update.effective_chat.id] else 'OFF'}")

class DashboardHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers(); self.wfile.write(b"Bozi-bot V5.20 Adaptive Live")

if __name__ == "__main__":
    requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/deleteWebhook?drop_pending_updates=True")
    
    # Iniciar hilo de actualización dinámica de modelos
    threading.Thread(target=schedule_model_updates, daemon=True).start()
    
    threading.Thread(target=lambda: HTTPServer(("0.0.0.0", int(os.environ.get("PORT", 10000))), DashboardHandler).serve_forever(), daemon=True).start()
    
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("debug", debug_cmd))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    
    logging.info("Bot en marcha con descubrimiento dinámico...")
    app.run_polling()
