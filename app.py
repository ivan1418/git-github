import os
import logging
import requests
import time
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters

from supabase import create_client
from openai import OpenAI
from tavily import TavilyClient


# --- 1. HEALTH CHECK PARA RENDER ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Bozi-bot is online and optimized!")

    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()


def run_health_check():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    logging.info(f"Health check activo en puerto {port}")
    server.serve_forever()


# --- 2. CONFIGURACIÓN ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")

OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
MAX_HISTORY_MESSAGES = int(os.getenv("MAX_HISTORY_MESSAGES", "4"))
MAX_OUTPUT_TOKENS = int(os.getenv("MAX_OUTPUT_TOKENS", "450"))
USE_EMBEDDINGS = os.getenv("USE_EMBEDDINGS", "false").lower() == "true"
USE_WEB_SEARCH = os.getenv("USE_WEB_SEARCH", "smart").lower()

if not TELEGRAM_TOKEN:
    raise ValueError("Falta TELEGRAM_TOKEN en Render.")

if not OPENAI_API_KEY:
    raise ValueError("Falta OPENAI_API_KEY en Render.")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("Faltan SUPABASE_URL o SUPABASE_KEY en Render.")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
openai_client = OpenAI(api_key=OPENAI_API_KEY)
tavily_client = TavilyClient(api_key=TAVILY_API_KEY) if TAVILY_API_KEY else None


# --- 3. PROMPT BARATO Y DIRECTO ---
SYSTEM_PROMPT = """
Sos Bozi-bot, asistente experto en IT Infrastructure, Cybersecurity, Linux, redes, scripting y soporte técnico.

Respondé en español rioplatense, claro, profesional y directo.
No hagas introducciones largas.
Dá pasos concretos cuando sea técnico.
No inventes datos.
Si falta información, hacé una suposición razonable y aclarala brevemente.
Máximo 3 párrafos salvo que el usuario pida código o una guía completa.
"""


# --- 4. UTILIDADES DE COSTO ---
def should_search_web(text: str) -> bool:
    if USE_WEB_SEARCH == "false":
        return False

    if USE_WEB_SEARCH == "true":
        return True

    keywords = [
        "actual", "hoy", "último", "ultima", "última", "nuevo", "nueva",
        "precio", "cotización", "cotizacion", "versión", "version",
        "noticia", "2026", "render", "openai", "telegram", "supabase",
        "error", "api", "documentación", "documentacion"
    ]

    text_lower = text.lower()
    return any(k in text_lower for k in keywords)


def get_embedding(text):
    if not USE_EMBEDDINGS:
        return None

    model_id = "sentence-transformers/all-MiniLM-L6-v2"
    api_url = f"https://api-inference.huggingface.co/models/{model_id}"
    headers = {"Authorization": f"Bearer {os.getenv('HF_TOKEN', '')}"}

    for _ in range(2):
        try:
            response = requests.post(
                api_url,
                headers=headers,
                json={"inputs": text[:1000]},
                timeout=10
            )

            if response.status_code == 200:
                return response.json()

            time.sleep(1)

        except Exception as e:
            logging.error(f"Error generando embedding: {e}")
            time.sleep(1)

    return None


def trim_text(text, max_chars=1200):
    if not text:
        return ""

    text = str(text).strip()

    if len(text) <= max_chars:
        return text

    return text[:max_chars] + "..."


def get_recent_history(chat_id):
    try:
        res = (
            supabase
            .table("bot_memory")
            .select("role, content")
            .eq("chat_id", chat_id)
            .order("created_at", desc=True)
            .limit(MAX_HISTORY_MESSAGES)
            .execute()
        )

        return list(reversed(res.data or []))

    except Exception as e:
        logging.error(f"Error recuperando historial: {e}")
        return []


def save_memory(chat_id, role, content, embedding=None):
    try:
        data = {
            "chat_id": chat_id,
            "role": role,
            "content": trim_text(content, 3000)
        }

        if embedding is not None:
            data["embedding"] = embedding

        supabase.table("bot_memory").insert(data).execute()

    except Exception as e:
        logging.error(f"Error guardando memoria en Supabase: {e}")


def get_web_context(user_text):
    if not tavily_client:
        return ""

    if not should_search_web(user_text):
        return ""

    try:
        search_res = tavily_client.search(
            query=user_text,
            max_results=2,
            search_depth="basic"
        )

        results = search_res.get("results", [])

        compact_results = []
        for r in results[:2]:
            compact_results.append({
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "content": trim_text(r.get("content", ""), 600)
            })

        return f"Contexto web reciente: {compact_results}"

    except Exception as e:
        logging.error(f"Error en Tavily: {e}")
        return ""


def build_openai_input(user_text, history, web_context):
    messages = []

    for m in history:
        role = m.get("role", "user")
        content = trim_text(m.get("content", ""), 1000)

        if role not in ["user", "assistant"]:
            role = "user"

        if content:
            messages.append({
                "role": role,
                "content": content
            })

    extra_context = ""

    if web_context:
        extra_context = f"\n\nContexto externo disponible:\n{trim_text(web_context, 1800)}"

    messages.append({
        "role": "user",
        "content": f"{user_text}{extra_context}"
    })

    return messages


# --- 5. LÓGICA DEL BOT ---
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_text = update.message.text or ""

    await context.bot.send_chat_action(
        chat_id=chat_id,
        action=ChatAction.TYPING
    )

    vector = get_embedding(user_text)
    save_memory(chat_id, "user", user_text, vector)

    history = get_recent_history(chat_id)
    web_context = get_web_context(user_text)

    input_messages = build_openai_input(
        user_text=user_text,
        history=history,
        web_context=web_context
    )

    try:
        response = openai_client.responses.create(
            model=OPENAI_MODEL,
            instructions=SYSTEM_PROMPT,
            input=input_messages,
            max_output_tokens=MAX_OUTPUT_TOKENS,
            temperature=0.4
        )

        answer = response.output_text.strip()

        if not answer:
            answer = "No pude generar una respuesta clara. Probá reformulando la consulta."

    except Exception as e:
        logging.error(f"Error en OpenAI: {e}")
        answer = "Che Iván, se me tildó la IA. Revisá logs de Render y probá de nuevo."

    save_memory(chat_id, "assistant", answer)

    await update.message.reply_text(answer)


# --- 6. EJECUCIÓN ---
if __name__ == "__main__":
    threading.Thread(target=run_health_check, daemon=True).start()

    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    application.add_handler(
        MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message)
    )

    logging.info("Bozi-bot optimizado con OpenAI listo.")

    application.run_polling(drop_pending_updates=True)
