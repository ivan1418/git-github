import os
import logging
import threading
import requests
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
        self.wfile.write(b"Bozi-bot is online with semantic memory and webhook output!")

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
WEBHOOK_DEBUG_URL = os.getenv("WEBHOOK_DEBUG_URL")

OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_EMBEDDING_MODEL = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")

MAX_HISTORY_MESSAGES = int(os.getenv("MAX_HISTORY_MESSAGES", "4"))
MAX_MEMORY_RESULTS = int(os.getenv("MAX_MEMORY_RESULTS", "6"))
MAX_OUTPUT_TOKENS = int(os.getenv("MAX_OUTPUT_TOKENS", "450"))

USE_EMBEDDINGS = os.getenv("USE_EMBEDDINGS", "true").lower() == "true"
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


# --- 3. PROMPTS EXTERNOS ---
def load_prompt_file(filename, fallback=""):
    try:
        with open(filename, "r", encoding="utf-8") as f:
            return f.read().strip()
    except FileNotFoundError:
        logging.warning(f"No se encontró {filename}. Usando fallback.")
        return fallback
    except Exception as e:
        logging.error(f"Error leyendo {filename}: {e}")
        return fallback


SELF_PROMPT = load_prompt_file(
    "self.txt",
    "Sos Bozi-bot, un asistente técnico especializado en IT, Cybersecurity y programación."
)

KNOWLEDGE_PROMPT = load_prompt_file(
    "knowledge.txt",
    "Tenés conocimientos avanzados en redes, sistemas, ciberseguridad, infraestructura y programación."
)

RULES_PROMPT = load_prompt_file(
    "rules.txt",
    "Respondé claro, corto, directo y sin inventar datos."
)

MEMORY_PROMPT = load_prompt_file(
    "memory.txt",
    "Usá el historial reciente y recuerdos relevantes de largo plazo cuando sirvan."
)

SYSTEM_PROMPT = f"""
{SELF_PROMPT}

{KNOWLEDGE_PROMPT}

{RULES_PROMPT}

{MEMORY_PROMPT}

REGLA EXTRA:
Cuando recibas recuerdos antiguos desde Supabase, usalos solo si son relevantes para la consulta actual.
No menciones que usás Supabase salvo que el usuario lo pregunte.
""".strip()


# --- 4. UTILIDADES ---
def trim_text(text, max_chars=1200):
    if not text:
        return ""

    text = str(text).strip()

    if len(text) <= max_chars:
        return text

    return text[:max_chars] + "..."


def send_to_webhook(data):
    if not WEBHOOK_DEBUG_URL:
        return

    try:
        requests.post(
            WEBHOOK_DEBUG_URL,
            json=data,
            timeout=5
        )
    except Exception as e:
        logging.error(f"Error enviando a Webhook.site: {e}")


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


def get_openai_embedding(text):
    if not USE_EMBEDDINGS:
        return None

    try:
        response = openai_client.embeddings.create(
            model=OPENAI_EMBEDDING_MODEL,
            input=trim_text(text, 6000)
        )

        return response.data[0].embedding

    except Exception as e:
        logging.error(f"Error generando embedding con OpenAI: {e}")
        return None


def save_memory(chat_id, role, content, embedding=None):
    try:
        data = {
            "chat_id": chat_id,
            "role": role,
            "content": trim_text(content, 5000)
        }

        if embedding is not None:
            data["embedding"] = embedding

        supabase.table("bot_memory").insert(data).execute()

    except Exception as e:
        logging.error(f"Error guardando memoria en Supabase: {e}")


def get_recent_history(chat_id):
    try:
        res = (
            supabase
            .table("bot_memory")
            .select("role, content, created_at")
            .eq("chat_id", chat_id)
            .order("created_at", desc=True)
            .limit(MAX_HISTORY_MESSAGES)
            .execute()
        )

        return list(reversed(res.data or []))

    except Exception as e:
        logging.error(f"Error recuperando historial reciente: {e}")
        return []


def get_semantic_memories(chat_id, query_embedding):
    if not USE_EMBEDDINGS or query_embedding is None:
        return []

    try:
        res = supabase.rpc(
            "match_bot_memory",
            {
                "query_embedding": query_embedding,
                "match_chat_id": chat_id,
                "match_count": MAX_MEMORY_RESULTS
            }
        ).execute()

        memories = res.data or []

        filtered = []
        for item in memories:
            similarity = item.get("similarity", 0)

            if similarity >= 0.25:
                filtered.append(item)

        return filtered

    except Exception as e:
        logging.error(f"Error buscando memoria semántica: {e}")
        return []


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


def build_openai_input(user_text, history, semantic_memories, web_context):
    messages = []

    if semantic_memories:
        memory_lines = []

        for m in semantic_memories:
            role = m.get("role", "unknown")
            content = trim_text(m.get("content", ""), 900)
            created_at = m.get("created_at", "")
            similarity = round(float(m.get("similarity", 0)), 3)

            memory_lines.append(
                f"- Fecha: {created_at} | Rol: {role} | Similitud: {similarity} | Contenido: {content}"
            )

        messages.append({
            "role": "user",
            "content": "Recuerdos relevantes de conversaciones anteriores:\n" + "\n".join(memory_lines)
        })

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

    final_user_message = user_text

    if web_context:
        final_user_message += f"\n\nContexto externo disponible:\n{trim_text(web_context, 1800)}"

    messages.append({
        "role": "user",
        "content": final_user_message
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

    user_embedding = get_openai_embedding(user_text)

    save_memory(
        chat_id=chat_id,
        role="user",
        content=user_text,
        embedding=user_embedding
    )

    history = get_recent_history(chat_id)
    semantic_memories = get_semantic_memories(chat_id, user_embedding)
    web_context = get_web_context(user_text)

    input_messages = build_openai_input(
        user_text=user_text,
        history=history,
        semantic_memories=semantic_memories,
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

    assistant_embedding = get_openai_embedding(answer)

    save_memory(
        chat_id=chat_id,
        role="assistant",
        content=answer,
        embedding=assistant_embedding
    )

    send_to_webhook({
        "type": "bot_project_output",
        "chat_id": chat_id,
        "user_message": user_text,
        "bot_response": answer,
        "semantic_memories_used": semantic_memories,
        "web_context_used": web_context,
        "model": OPENAI_MODEL
    })

    await update.message.reply_text(answer)


# --- 6. EJECUCIÓN ---
if __name__ == "__main__":
    threading.Thread(target=run_health_check, daemon=True).start()

    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    application.add_handler(
        MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message)
    )

    logging.info("Bozi-bot con OpenAI + Supabase + Webhook.site listo.")

    application.run_polling(drop_pending_updates=True)
