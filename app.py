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
        self.wfile.write(b"Bozi-bot online with projects, semantic memory and webhook!")

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
MAX_OUTPUT_TOKENS = int(os.getenv("MAX_OUTPUT_TOKENS", "650"))

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

REGLAS EXTRA:
- Cuando recibas recuerdos antiguos desde Supabase, usalos solo si son relevantes.
- No menciones Supabase salvo que el usuario lo pregunte.
- Si el usuario pide crear, armar, generar, diseñar, configurar o documentar algo, tratá esa respuesta como posible proyecto.
- Si generás código, configuración, guía técnica o arquitectura, hacelo listo para usar.
""".strip()


# --- 4. UTILIDADES GENERALES ---
def trim_text(text, max_chars=1200):
    if not text:
        return ""

    text = str(text).strip()

    if len(text) <= max_chars:
        return text

    return text[:max_chars] + "..."


def send_to_webhook(data):
    if not WEBHOOK_DEBUG_URL:
        logging.info("WEBHOOK_DEBUG_URL no configurada. No se envía a Webhook.site.")
        return

    try:
        logging.info(f"Enviando POST a Webhook.site: {WEBHOOK_DEBUG_URL}")

        response = requests.post(
            WEBHOOK_DEBUG_URL,
            json=data,
            timeout=8
        )

        logging.info(f"Webhook.site respondió HTTP {response.status_code}")

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


def is_project_request(text: str, answer: str = "") -> bool:
    text_lower = text.lower()
    answer_lower = answer.lower()

    trigger_words = [
        "proyecto", "crear", "armar", "generar", "desarrollar", "diseñar",
        "configurar", "automatizar", "script", "codigo", "código",
        "dockerfile", "app.py", "requirements", "bot", "api", "webhook",
        "documentar", "pasame completo", "archivo completo"
    ]

    answer_indicators = [
        "```", "dockerfile", "requirements.txt", "app.py",
        "paso 1", "paso 2", "configuración", "script"
    ]

    return any(w in text_lower for w in trigger_words) or any(w in answer_lower for w in answer_indicators)


def extract_project_title(user_text: str):
    title = trim_text(user_text, 80)

    if not title:
        return "Proyecto generado por Bozi-bot"

    return title


# --- 5. MEMORIA SEMÁNTICA ---
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


# --- 6. PROYECTOS ---
def save_project(chat_id, title, content, source_message):
    try:
        res = (
            supabase
            .table("projects")
            .insert({
                "chat_id": chat_id,
                "title": trim_text(title, 150),
                "content": trim_text(content, 20000),
                "source_message": trim_text(source_message, 3000)
            })
            .execute()
        )

        if res.data and len(res.data) > 0:
            return res.data[0]

        return None

    except Exception as e:
        logging.error(f"Error guardando proyecto en Supabase: {e}")
        return None


def list_projects(chat_id, limit=10):
    try:
        res = (
            supabase
            .table("projects")
            .select("id, title, created_at")
            .eq("chat_id", chat_id)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )

        return res.data or []

    except Exception as e:
        logging.error(f"Error listando proyectos: {e}")
        return []


def get_project(chat_id, project_id):
    try:
        res = (
            supabase
            .table("projects")
            .select("id, title, content, source_message, created_at, updated_at")
            .eq("chat_id", chat_id)
            .eq("id", project_id)
            .limit(1)
            .execute()
        )

        if res.data:
            return res.data[0]

        return None

    except Exception as e:
        logging.error(f"Error obteniendo proyecto: {e}")
        return None


def update_project(chat_id, project_id, new_content):
    try:
        res = (
            supabase
            .table("projects")
            .update({
                "content": trim_text(new_content, 20000)
            })
            .eq("chat_id", chat_id)
            .eq("id", project_id)
            .execute()
        )

        if res.data:
            return res.data[0]

        return None

    except Exception as e:
        logging.error(f"Error actualizando proyecto: {e}")
        return None


# --- 7. BÚSQUEDA WEB ---
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


# --- 8. ARMADO DE INPUT PARA OPENAI ---
def build_openai_input(user_text, history, semantic_memories, web_context, project_context=""):
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

    if project_context:
        messages.append({
            "role": "user",
            "content": project_context
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


def ask_openai(input_messages):
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

    return answer


# --- 9. COMANDOS SIMPLES POR TEXTO ---
async def handle_project_commands(chat_id, user_text, update):
    text = user_text.strip().lower()

    if text in ["/proyectos", "proyectos", "listar proyectos", "mis proyectos"]:
        projects = list_projects(chat_id)

        if not projects:
            await update.message.reply_text("Todavía no tengo proyectos guardados.")
            return True

        lines = ["Tus últimos proyectos guardados:\n"]

        for p in projects:
            lines.append(f"#{p['id']} - {p['title']}")

        lines.append("\nPara ver uno: ver proyecto 12")
        await update.message.reply_text("\n".join(lines))
        return True

    if text.startswith("ver proyecto "):
        try:
            project_id = int(text.replace("ver proyecto ", "").strip())
        except ValueError:
            await update.message.reply_text("Usá el formato: ver proyecto 12")
            return True

        project = get_project(chat_id, project_id)

        if not project:
            await update.message.reply_text("No encontré ese proyecto.")
            return True

        content = project["content"]

        if len(content) > 3500:
            content = content[:3500] + "\n\n...contenido recortado por límite de Telegram."

        await update.message.reply_text(
            f"Proyecto #{project['id']} - {project['title']}\n\n{content}"
        )
        return True

    return False


# --- 10. LÓGICA PRINCIPAL DEL BOT ---
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_text = update.message.text or ""

    await context.bot.send_chat_action(
        chat_id=chat_id,
        action=ChatAction.TYPING
    )

    command_handled = await handle_project_commands(chat_id, user_text, update)

    if command_handled:
        return

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
        answer = ask_openai(input_messages)

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

    project_saved = None

    if is_project_request(user_text, answer):
        project_title = extract_project_title(user_text)

        project_saved = save_project(
            chat_id=chat_id,
            title=project_title,
            content=answer,
            source_message=user_text
        )

        if project_saved:
            answer += f"\n\nProyecto guardado como #{project_saved['id']}."
            answer += "\nPara verlo después: ver proyecto " + str(project_saved["id"])

    webhook_payload = {
        "type": "bot_project_output",
        "chat_id": chat_id,
        "user_message": user_text,
        "bot_response": answer,
        "project_saved": project_saved,
        "semantic_memories_used": semantic_memories,
        "web_context_used": web_context,
        "model": OPENAI_MODEL
    }

    send_to_webhook(webhook_payload)

    await update.message.reply_text(answer)


# --- 11. EJECUCIÓN ---
if __name__ == "__main__":
    threading.Thread(target=run_health_check, daemon=True).start()

    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    application.add_handler(
        MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message)
    )

    logging.info("Bozi-bot con OpenAI + Supabase + Webhook.site + Projects listo.")

    application.run_polling(drop_pending_updates=True)
