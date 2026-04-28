import os
import re
import logging
import threading
import requests
from urllib.parse import urlparse
from http.server import HTTPServer, BaseHTTPRequestHandler

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters

from supabase import create_client
from openai import OpenAI
from tavily import TavilyClient


# --- CONFIGURACIÓN ---
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
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")

OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_EMBEDDING_MODEL = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")

MAX_HISTORY_MESSAGES = int(os.getenv("MAX_HISTORY_MESSAGES", "4"))
MAX_MEMORY_RESULTS = int(os.getenv("MAX_MEMORY_RESULTS", "6"))
MAX_OUTPUT_TOKENS = int(os.getenv("MAX_OUTPUT_TOKENS", "1800"))

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


# --- SERVIDOR WEB PARA RENDERIZAR PROYECTOS ---
class WebHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/" or path == "/webhook":
            self.send_response(200)
            self.send_header("Content-type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"Bozi-bot online. Usa /projects/{id} para ver proyectos.")
            return

        match = re.match(r"^/projects/(\d+)$", path)

        if match:
            project_id = int(match.group(1))
            project = get_project_by_id(project_id)

            if not project:
                self.send_response(404)
                self.send_header("Content-type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write(b"Proyecto no encontrado.")
                return

            html = project.get("html_content") or ""

            if not html:
                content = project.get("content", "")
                html = f"""
                <!DOCTYPE html>
                <html lang="es">
                <head>
                    <meta charset="UTF-8">
                    <meta name="viewport" content="width=device-width, initial-scale=1.0">
                    <title>{project.get("title", "Proyecto")}</title>
                    <style>
                        body {{
                            font-family: Arial, sans-serif;
                            max-width: 900px;
                            margin: 40px auto;
                            padding: 20px;
                            line-height: 1.6;
                        }}
                        pre {{
                            background: #f4f4f4;
                            padding: 16px;
                            border-radius: 8px;
                            overflow-x: auto;
                        }}
                    </style>
                </head>
                <body>
                    <h1>{project.get("title", "Proyecto")}</h1>
                    <pre>{content}</pre>
                </body>
                </html>
                """

            self.send_response(200)
            self.send_header("Content-type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(html.encode("utf-8"))
            return

        self.send_response(404)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"Ruta no encontrada.")

    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()


def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), WebHandler)
    logging.info(f"Servidor web activo en puerto {port}")
    server.serve_forever()


# --- PROMPTS EXTERNOS ---
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
- Si el usuario pide una página, landing, dashboard, sitio web, visualizador, panel o app simple, NO des instrucciones: construí directamente el proyecto.
- Para proyectos web simples generá HTML completo, funcional y renderizable.
- Usá CSS y JavaScript embebidos dentro del HTML.
- No menciones Supabase salvo que el usuario lo pregunte.
""".strip()


HTML_BUILDER_PROMPT = """
Sos un desarrollador frontend experto.

Tu tarea es crear un proyecto web completo y visible en navegador.

REGLAS:
- Devolvé SOLO HTML completo.
- No uses markdown.
- No uses explicaciones.
- No uses ```html.
- El archivo debe empezar con <!DOCTYPE html>.
- Incluir CSS dentro de <style>.
- Incluir JavaScript dentro de <script> si hace falta.
- Debe ser responsive.
- Debe verse profesional, moderno y prolijo.
- No uses recursos externos obligatorios.
- Si necesitás imágenes, usá placeholders visuales con CSS.
"""


# --- UTILIDADES ---
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
        response = requests.post(WEBHOOK_DEBUG_URL, json=data, timeout=8)
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

    return any(k in text.lower() for k in keywords)


def is_web_project_request(text: str) -> bool:
    t = text.lower()

    keywords = [
        "pagina", "página", "landing", "sitio", "web", "dashboard",
        "panel", "visual", "interfaz", "frontend", "html", "css",
        "javascript", "app visual", "pagina para", "página para"
    ]

    return any(k in t for k in keywords)


def is_project_request(text: str, answer: str = "") -> bool:
    text_lower = text.lower()
    answer_lower = answer.lower()

    trigger_words = [
        "proyecto", "crear", "armar", "generar", "desarrollar", "diseñar",
        "configurar", "automatizar", "script", "codigo", "código",
        "dockerfile", "app.py", "requirements", "bot", "api", "webhook",
        "documentar", "pasame completo", "archivo completo", "landing",
        "pagina", "página", "dashboard"
    ]

    answer_indicators = [
        "```", "dockerfile", "requirements.txt", "app.py",
        "paso 1", "paso 2", "configuración", "script", "<!doctype html"
    ]

    return any(w in text_lower for w in trigger_words) or any(w in answer_lower for w in answer_indicators)


def extract_project_title(user_text: str):
    return trim_text(user_text, 100) or "Proyecto generado por Bozi-bot"


def get_project_url(project_id):
    if PUBLIC_BASE_URL:
        return f"{PUBLIC_BASE_URL}/projects/{project_id}"

    return f"/projects/{project_id}"


def clean_html_output(text):
    if not text:
        return ""

    text = text.strip()

    text = re.sub(r"^```html\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^```\s*", "", text)
    text = re.sub(r"\s*```$", "", text)

    return text.strip()


# --- MEMORIA SEMÁNTICA ---
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
        return [m for m in memories if m.get("similarity", 0) >= 0.25]

    except Exception as e:
        logging.error(f"Error buscando memoria semántica: {e}")
        return []


# --- PROYECTOS ---
def save_project(chat_id, title, content, source_message, project_type="text", html_content=None):
    try:
        res = (
            supabase
            .table("projects")
            .insert({
                "chat_id": chat_id,
                "title": trim_text(title, 150),
                "content": trim_text(content, 25000),
                "source_message": trim_text(source_message, 3000),
                "project_type": project_type,
                "html_content": html_content
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
            .select("id, title, project_type, created_at")
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
            .select("id, title, content, html_content, project_type, source_message, created_at, updated_at")
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


def get_project_by_id(project_id):
    try:
        res = (
            supabase
            .table("projects")
            .select("id, title, content, html_content, project_type")
            .eq("id", project_id)
            .limit(1)
            .execute()
        )

        if res.data:
            return res.data[0]

        return None

    except Exception as e:
        logging.error(f"Error obteniendo proyecto público: {e}")
        return None


def update_project_html(chat_id, project_id, html_content, source_message):
    try:
        res = (
            supabase
            .table("projects")
            .update({
                "content": trim_text(html_content, 25000),
                "html_content": html_content,
                "project_type": "html",
                "source_message": trim_text(source_message, 3000)
            })
            .eq("chat_id", chat_id)
            .eq("id", project_id)
            .execute()
        )

        if res.data:
            return res.data[0]

        return None

    except Exception as e:
        logging.error(f"Error actualizando proyecto HTML: {e}")
        return None


# --- WEB SEARCH ---
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


# --- OPENAI ---
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


def generate_html_project(user_text, semantic_memories=None):
    memory_context = ""

    if semantic_memories:
        lines = []
        for m in semantic_memories[:4]:
            lines.append(trim_text(m.get("content", ""), 700))
        memory_context = "\n\nContexto útil de memoria:\n" + "\n".join(lines)

    response = openai_client.responses.create(
        model=OPENAI_MODEL,
        instructions=HTML_BUILDER_PROMPT,
        input=f"Pedido del usuario:\n{user_text}{memory_context}",
        max_output_tokens=2600,
        temperature=0.35
    )

    html = clean_html_output(response.output_text)

    if not html.lower().startswith("<!doctype html"):
        html = "<!DOCTYPE html>\n" + html

    return html


# --- COMANDOS ---
async def handle_project_commands(chat_id, user_text, update):
    text = user_text.strip().lower()

    if text in ["/proyectos", "proyectos", "listar proyectos", "mis proyectos"]:
        projects = list_projects(chat_id)

        if not projects:
            await update.message.reply_text("Todavía no tengo proyectos guardados.")
            return True

        lines = ["Tus últimos proyectos guardados:\n"]

        for p in projects:
            url = get_project_url(p["id"]) if p.get("project_type") == "html" else ""
            line = f"#{p['id']} - {p['title']} [{p.get('project_type', 'text')}]"
            if url:
                line += f"\n{url}"
            lines.append(line)

        lines.append("\nPara ver uno: ver proyecto 12")
        await update.message.reply_text("\n\n".join(lines))
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

        if project.get("project_type") == "html":
            await update.message.reply_text(
                f"Proyecto #{project['id']} - {project['title']}\n\nVer online:\n{get_project_url(project['id'])}"
            )
            return True

        content = project["content"]

        if len(content) > 3500:
            content = content[:3500] + "\n\n...contenido recortado por límite de Telegram."

        await update.message.reply_text(
            f"Proyecto #{project['id']} - {project['title']}\n\n{content}"
        )
        return True

    edit_match = re.match(r"^(editar|modificar|cambiar) proyecto (\d+)\s*(.*)$", user_text.strip(), re.IGNORECASE)

    if edit_match:
        project_id = int(edit_match.group(2))
        change_request = edit_match.group(3).strip()

        if not change_request:
            await update.message.reply_text(
                f"Decime qué cambio querés hacer. Ejemplo:\neditar proyecto {project_id} cambiar el color principal a azul oscuro"
            )
            return True

        project = get_project(chat_id, project_id)

        if not project:
            await update.message.reply_text("No encontré ese proyecto.")
            return True

        if project.get("project_type") != "html":
            await update.message.reply_text("Por ahora solo puedo editar proyectos web HTML publicados.")
            return True

        old_html = project.get("html_content") or ""

        edit_prompt = f"""
HTML actual:
{old_html}

Cambio solicitado:
{change_request}

Devolvé el HTML completo actualizado.
"""

        try:
            response = openai_client.responses.create(
                model=OPENAI_MODEL,
                instructions=HTML_BUILDER_PROMPT,
                input=edit_prompt,
                max_output_tokens=2600,
                temperature=0.3
            )

            new_html = clean_html_output(response.output_text)

            updated = update_project_html(
                chat_id=chat_id,
                project_id=project_id,
                html_content=new_html,
                source_message=change_request
            )

            if updated:
                await update.message.reply_text(
                    f"Listo Iván. Proyecto #{project_id} actualizado.\n\nVer online:\n{get_project_url(project_id)}"
                )
            else:
                await update.message.reply_text("No pude actualizar el proyecto.")

            return True

        except Exception as e:
            logging.error(f"Error editando proyecto: {e}")
            await update.message.reply_text("Se me complicó editar el proyecto. Revisá logs de Render.")
            return True

    return False


# --- BOT ---
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_text = update.message.text or ""

    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    command_handled = await handle_project_commands(chat_id, user_text, update)
    if command_handled:
        return

    user_embedding = get_openai_embedding(user_text)

    save_memory(chat_id, "user", user_text, user_embedding)

    history = get_recent_history(chat_id)
    semantic_memories = get_semantic_memories(chat_id, user_embedding)
    web_context = get_web_context(user_text)

    try:
        if is_web_project_request(user_text):
            html = generate_html_project(user_text, semantic_memories)
            title = extract_project_title(user_text)

            project_saved = save_project(
                chat_id=chat_id,
                title=title,
                content=html,
                source_message=user_text,
                project_type="html",
                html_content=html
            )

            if project_saved:
                project_id = project_saved["id"]
                project_url = get_project_url(project_id)

                answer = (
                    f"Listo Iván. Proyecto web creado como #{project_id}.\n\n"
                    f"Ver online:\n{project_url}\n\n"
                    f"Para editarlo:\neditar proyecto {project_id} cambiar ..."
                )
            else:
                answer = "Generé el HTML, pero no pude guardarlo en Supabase."

        else:
            input_messages = build_openai_input(
                user_text=user_text,
                history=history,
                semantic_memories=semantic_memories,
                web_context=web_context
            )

            answer = ask_openai(input_messages)

            project_saved = None

            if is_project_request(user_text, answer):
                title = extract_project_title(user_text)

                project_saved = save_project(
                    chat_id=chat_id,
                    title=title,
                    content=answer,
                    source_message=user_text,
                    project_type="text"
                )

                if project_saved:
                    answer += f"\n\nProyecto guardado como #{project_saved['id']}."
                    answer += f"\nPara verlo después: ver proyecto {project_saved['id']}"

    except Exception as e:
        logging.error(f"Error en OpenAI/proyecto: {e}")
        answer = "Che Iván, se me tildó la IA. Revisá logs de Render y probá de nuevo."
        project_saved = None

    assistant_embedding = get_openai_embedding(answer)
    save_memory(chat_id, "assistant", answer, assistant_embedding)

    send_to_webhook({
        "type": "bot_project_output",
        "chat_id": chat_id,
        "user_message": user_text,
        "bot_response": answer,
        "project_saved": project_saved,
        "semantic_memories_used": semantic_memories,
        "web_context_used": web_context,
        "model": OPENAI_MODEL
    })

    await update.message.reply_text(answer)


# --- EJECUCIÓN ---
if __name__ == "__main__":
    threading.Thread(target=run_web_server, daemon=True).start()

    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    application.add_handler(
        MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message)
    )

    logging.info("Bozi-bot Builder listo: Telegram + OpenAI + Supabase + URLs.")

    application.run_polling(drop_pending_updates=True)
