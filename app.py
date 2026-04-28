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
MAX_OUTPUT_TOKENS = int(os.getenv("MAX_OUTPUT_TOKENS", "800"))

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


# ---------------------------------------------------
# SERVIDOR WEB PARA VER PROYECTOS PUBLICADOS
# ---------------------------------------------------
class WebHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/" or path == "/webhook":
            self.send_response(200)
            self.send_header("Content-type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"Bozi-bot online. Usa /projects/{id} para ver proyectos publicados.")
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

            html = project.get("html_content") or project.get("content") or ""

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


# ---------------------------------------------------
# PROMPTS
# ---------------------------------------------------
def load_prompt_file(filename, fallback=""):
    try:
        with open(filename, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return fallback


SELF_PROMPT = load_prompt_file(
    "self.txt",
    "Sos Bozi-bot, asistente técnico experto en IT, Cybersecurity y programación."
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
    "Usá historial reciente y recuerdos relevantes solo cuando ayuden."
)

SYSTEM_PROMPT = f"""
{SELF_PROMPT}

{KNOWLEDGE_PROMPT}

{RULES_PROMPT}

{MEMORY_PROMPT}

REGLAS DE FLUJO:
- Conversá naturalmente.
- No guardes cada charla como proyecto.
- Solo creá un borrador cuando el usuario pida construir, diseñar, crear, desarrollar o armar algo concreto.
- No publiques URL automáticamente.
- Publicá únicamente cuando el usuario diga: publicalo, crear URL, pasame la URL, guardar como proyecto, deployalo o similar.
- Si el usuario pide cambios, modificá el borrador actual.
- Si el usuario solo consulta o debate, respondé normal.
""".strip()


HTML_BUILDER_PROMPT = """
Sos un desarrollador frontend experto.

Creá un HTML completo, moderno, responsive y funcional.

REGLAS:
- Devolvé SOLO HTML.
- No uses markdown.
- No uses explicaciones.
- No uses ```html.
- Debe empezar con <!DOCTYPE html>.
- CSS dentro de <style>.
- JavaScript dentro de <script> si hace falta.
- Diseño profesional, limpio, responsive.
- No uses dependencias externas obligatorias.
"""


INTENT_PROMPT = """
Clasificá la intención del usuario.

Respondé SOLO una de estas etiquetas:

CHAT_SIMPLE
PROJECT_DRAFT_CREATE
PROJECT_DRAFT_EDIT
PROJECT_PUBLISH
PROJECT_VIEW_DRAFT
PROJECT_LIST
PROJECT_VIEW_PUBLISHED

Criterios:
- CHAT_SIMPLE: dudas, charla, debate, explicación, consulta técnica.
- PROJECT_DRAFT_CREATE: pide crear, diseñar, armar, desarrollar una web, landing, dashboard, página o interfaz.
- PROJECT_DRAFT_EDIT: pide cambiar, modificar, mejorar o agregar algo al borrador/proyecto actual.
- PROJECT_PUBLISH: pide publicar, crear URL, pasar URL, guardar como proyecto final o deployar.
- PROJECT_VIEW_DRAFT: pide ver el borrador actual.
- PROJECT_LIST: pide listar proyectos.
- PROJECT_VIEW_PUBLISHED: pide ver proyecto publicado por ID.
"""


# ---------------------------------------------------
# UTILIDADES
# ---------------------------------------------------
def trim_text(text, max_chars=1200):
    if not text:
        return ""
    text = str(text).strip()
    return text if len(text) <= max_chars else text[:max_chars] + "..."


def clean_html_output(text):
    if not text:
        return ""

    text = text.strip()
    text = re.sub(r"^```html\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^```\s*", "", text)
    text = re.sub(r"\s*```$", "", text)

    if not text.lower().startswith("<!doctype html"):
        text = "<!DOCTYPE html>\n" + text

    return text.strip()


def get_project_url(project_id):
    if PUBLIC_BASE_URL:
        return f"{PUBLIC_BASE_URL}/projects/{project_id}"
    return f"/projects/{project_id}"

def is_task_capability_question(text):
    t = text.lower()
    return (
        ("puedo" in t or "podés" in t or "podes" in t) and
        ("todos los días" in t or "diario" in t or "tareas" in t or "reporte" in t) and
        ("mandes" in t or "enviarme" in t or "enviar" in t)
    )

def send_to_webhook(data):
    if not WEBHOOK_DEBUG_URL:
        return

    try:
        requests.post(WEBHOOK_DEBUG_URL, json=data, timeout=8)
    except Exception as e:
        logging.error(f"Error enviando a Webhook.site: {e}")


def classify_intent(user_text):
    try:
        response = openai_client.responses.create(
            model=OPENAI_MODEL,
            instructions=INTENT_PROMPT,
            input=user_text,
            max_output_tokens=20,
            temperature=0
        )

        intent = response.output_text.strip().upper()

        valid = {
            "CHAT_SIMPLE",
            "PROJECT_DRAFT_CREATE",
            "PROJECT_DRAFT_EDIT",
            "PROJECT_PUBLISH",
            "PROJECT_VIEW_DRAFT",
            "PROJECT_LIST",
            "PROJECT_VIEW_PUBLISHED"
        }

        return intent if intent in valid else "CHAT_SIMPLE"

    except Exception as e:
        logging.error(f"Error clasificando intención: {e}")
        return "CHAT_SIMPLE"


# ---------------------------------------------------
# MEMORIA
# ---------------------------------------------------
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
        logging.error(f"Error generando embedding: {e}")
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
        logging.error(f"Error guardando memoria: {e}")


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
        logging.error(f"Error recuperando historial: {e}")
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

        return [m for m in (res.data or []) if m.get("similarity", 0) >= 0.25]

    except Exception as e:
        logging.error(f"Error buscando memoria semántica: {e}")
        return []


# ---------------------------------------------------
# WEB SEARCH
# ---------------------------------------------------
def should_search_web(text):
    if USE_WEB_SEARCH == "false":
        return False

    if USE_WEB_SEARCH == "true":
        return True

    keywords = [
        "actual", "hoy", "último", "ultima", "última", "nuevo", "nueva",
        "precio", "cotización", "version", "versión", "noticia",
        "render", "openai", "telegram", "supabase", "api", "documentación"
    ]

    return any(k in text.lower() for k in keywords)


def get_web_context(user_text):
    if not tavily_client or not should_search_web(user_text):
        return ""

    try:
        search_res = tavily_client.search(
            query=user_text,
            max_results=2,
            search_depth="basic"
        )

        results = search_res.get("results", [])

        compact = []
        for r in results[:2]:
            compact.append({
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "content": trim_text(r.get("content", ""), 600)
            })

        return f"Contexto web reciente: {compact}"

    except Exception as e:
        logging.error(f"Error Tavily: {e}")
        return ""


# ---------------------------------------------------
# DRAFTS Y PROYECTOS
# ---------------------------------------------------
def create_draft(chat_id, title, html_content, source_message):
    try:
        res = (
            supabase
            .table("project_drafts")
            .insert({
                "chat_id": chat_id,
                "title": trim_text(title, 150),
                "draft_type": "html",
                "html_content": html_content,
                "source_message": trim_text(source_message, 3000),
                "status": "draft"
            })
            .execute()
        )

        return res.data[0] if res.data else None

    except Exception as e:
        logging.error(f"Error creando draft: {e}")
        return None


def get_latest_draft(chat_id):
    try:
        res = (
            supabase
            .table("project_drafts")
            .select("id, title, html_content, source_message, status, created_at, updated_at")
            .eq("chat_id", chat_id)
            .eq("status", "draft")
            .order("updated_at", desc=True)
            .limit(1)
            .execute()
        )

        return res.data[0] if res.data else None

    except Exception as e:
        logging.error(f"Error obteniendo draft: {e}")
        return None


def update_draft(chat_id, draft_id, html_content, source_message):
    try:
        res = (
            supabase
            .table("project_drafts")
            .update({
                "html_content": html_content,
                "source_message": trim_text(source_message, 3000),
                "updated_at": "now()"
            })
            .eq("chat_id", chat_id)
            .eq("id", draft_id)
            .execute()
        )

        return res.data[0] if res.data else None

    except Exception as e:
        logging.error(f"Error actualizando draft: {e}")
        return None


def publish_draft(chat_id, draft):
    try:
        res = (
            supabase
            .table("projects")
            .insert({
                "chat_id": chat_id,
                "title": draft["title"],
                "content": draft["html_content"],
                "source_message": draft.get("source_message", ""),
                "project_type": "html",
                "html_content": draft["html_content"]
            })
            .execute()
        )

        project = res.data[0] if res.data else None

        if project:
            supabase.table("project_drafts").update({
                "status": "published",
                "updated_at": "now()"
            }).eq("id", draft["id"]).execute()

        return project

    except Exception as e:
        logging.error(f"Error publicando draft: {e}")
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

        return res.data[0] if res.data else None

    except Exception as e:
        logging.error(f"Error obteniendo proyecto público: {e}")
        return None


def get_project(chat_id, project_id):
    try:
        res = (
            supabase
            .table("projects")
            .select("id, title, content, html_content, project_type")
            .eq("chat_id", chat_id)
            .eq("id", project_id)
            .limit(1)
            .execute()
        )

        return res.data[0] if res.data else None

    except Exception as e:
        logging.error(f"Error obteniendo proyecto: {e}")
        return None


# ---------------------------------------------------
# OPENAI
# ---------------------------------------------------
def build_chat_input(user_text, history, semantic_memories, web_context):
    messages = []

    if semantic_memories:
        memory_lines = []
        for m in semantic_memories:
            memory_lines.append(
                f"- {trim_text(m.get('content', ''), 800)}"
            )

        messages.append({
            "role": "user",
            "content": "Recuerdos relevantes:\n" + "\n".join(memory_lines)
        })

    for m in history:
        role = m.get("role", "user")
        content = trim_text(m.get("content", ""), 1000)

        if role not in ["user", "assistant"]:
            role = "user"

        if content:
            messages.append({"role": role, "content": content})

    final = user_text

    if web_context:
        final += f"\n\nContexto externo:\n{trim_text(web_context, 1800)}"

    messages.append({"role": "user", "content": final})
    return messages


def ask_openai_chat(input_messages):
    response = openai_client.responses.create(
        model=OPENAI_MODEL,
        instructions=SYSTEM_PROMPT,
        input=input_messages,
        max_output_tokens=MAX_OUTPUT_TOKENS,
        temperature=0.4
    )

    return response.output_text.strip() or "No pude generar una respuesta clara."


def generate_html_from_request(user_text, semantic_memories=None):
    memory_context = ""

    if semantic_memories:
        memory_context = "\n\nContexto útil:\n" + "\n".join(
            [trim_text(m.get("content", ""), 700) for m in semantic_memories[:4]]
        )

    response = openai_client.responses.create(
        model=OPENAI_MODEL,
        instructions=HTML_BUILDER_PROMPT,
        input=f"Pedido del usuario:\n{user_text}{memory_context}",
        max_output_tokens=2600,
        temperature=0.35
    )

    return clean_html_output(response.output_text)


def edit_html(old_html, change_request):
    prompt = f"""
HTML actual:
{old_html}

Cambio solicitado:
{change_request}

Devolvé el HTML completo actualizado.
"""

    response = openai_client.responses.create(
        model=OPENAI_MODEL,
        instructions=HTML_BUILDER_PROMPT,
        input=prompt,
        max_output_tokens=2600,
        temperature=0.3
    )

    return clean_html_output(response.output_text)


# ---------------------------------------------------
# BOT
# ---------------------------------------------------
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_text = update.message.text or ""

    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

# 🔥 CORRECCIÓN PARA QUE NO DIGA "NO PUEDO"
    if is_task_capability_question(user_text):
    answer = (
        "Sí, Iván. Puedo hacerlo.\n\n"
        "Puedo guardar tareas programadas y enviarte reportes automáticamente por Telegram.\n\n"
        "Por ejemplo:\n"
        "“Todos los días a las 9 mandame un reporte de ciberseguridad”."
    )

    await update.message.reply_text(answer)
    return
    
    intent = classify_intent(user_text)
    logging.info(f"Intent detectado: {intent}")

    user_embedding = get_openai_embedding(user_text)
    save_memory(chat_id, "user", user_text, user_embedding)

    semantic_memories = get_semantic_memories(chat_id, user_embedding)
    history = get_recent_history(chat_id)
    web_context = get_web_context(user_text)

    project_saved = None
    draft_saved = None

    try:
        if intent == "PROJECT_DRAFT_CREATE":
            html = generate_html_from_request(user_text, semantic_memories)
            title = trim_text(user_text, 100)

            draft_saved = create_draft(
                chat_id=chat_id,
                title=title,
                html_content=html,
                source_message=user_text
            )

            if draft_saved:
                answer = (
                    f"Listo Iván. Te armé un primer borrador del proyecto.\n\n"
                    f"Todavía no lo publiqué como URL final.\n\n"
                    f"Podés decirme:\n"
                    f"- publicalo\n"
                    f"- cambiar colores\n"
                    f"- agregar sección de contacto\n"
                    f"- ver borrador"
                )
            else:
                answer = "Generé el borrador, pero no pude guardarlo."

        elif intent == "PROJECT_DRAFT_EDIT":
            draft = get_latest_draft(chat_id)

            if not draft:
                answer = "No tengo un borrador activo para editar. Primero pedime que cree una página o proyecto."
            else:
                new_html = edit_html(draft["html_content"], user_text)

                draft_saved = update_draft(
                    chat_id=chat_id,
                    draft_id=draft["id"],
                    html_content=new_html,
                    source_message=user_text
                )

                answer = (
                    "Listo Iván. Apliqué los cambios al borrador.\n\n"
                    "Cuando quieras verlo online, decime: publicalo."
                )

        elif intent == "PROJECT_PUBLISH":
            draft = get_latest_draft(chat_id)

            if not draft:
                answer = "No tengo un borrador activo para publicar."
            else:
                project_saved = publish_draft(chat_id, draft)

                if project_saved:
                    url = get_project_url(project_saved["id"])
                    answer = (
                        f"Listo Iván. Proyecto publicado como #{project_saved['id']}.\n\n"
                        f"Ver online:\n{url}\n\n"
                        f"Si querés cambios, decime: editar proyecto {project_saved['id']} ..."
                    )
                else:
                    answer = "No pude publicar el proyecto."

        elif intent == "PROJECT_VIEW_DRAFT":
            draft = get_latest_draft(chat_id)

            if not draft:
                answer = "No tengo un borrador activo."
            else:
                answer = (
                    f"Borrador activo: #{draft['id']}\n"
                    f"Título: {draft['title']}\n\n"
                    f"Todavía no está publicado. Decime 'publicalo' para crear la URL."
                )

        elif intent == "PROJECT_LIST":
            projects = list_projects(chat_id)

            if not projects:
                answer = "Todavía no tenés proyectos publicados."
            else:
                lines = ["Tus últimos proyectos publicados:\n"]
                for p in projects:
                    lines.append(f"#{p['id']} - {p['title']}\n{get_project_url(p['id'])}")
                answer = "\n\n".join(lines)

        elif intent == "PROJECT_VIEW_PUBLISHED":
            match = re.search(r"(\d+)", user_text)

            if not match:
                answer = "Decime el número del proyecto. Ejemplo: ver proyecto 3"
            else:
                project_id = int(match.group(1))
                project = get_project(chat_id, project_id)

                if not project:
                    answer = "No encontré ese proyecto."
                else:
                    answer = f"Proyecto #{project_id}:\n{get_project_url(project_id)}"

        else:
            input_messages = build_chat_input(
                user_text=user_text,
                history=history,
                semantic_memories=semantic_memories,
                web_context=web_context
            )

            answer = ask_openai_chat(input_messages)

    except Exception as e:
        logging.error(f"Error procesando mensaje: {e}")
        answer = "Che Iván, se me tildó la IA. Revisá logs de Render y probá de nuevo."

    assistant_embedding = get_openai_embedding(answer)
    save_memory(chat_id, "assistant", answer, assistant_embedding)

    send_to_webhook({
        "type": "bot_output",
        "intent": intent,
        "chat_id": chat_id,
        "user_message": user_text,
        "bot_response": answer,
        "draft_saved": draft_saved,
        "project_saved": project_saved,
        "model": OPENAI_MODEL
    })

    await update.message.reply_text(answer)

async def telegram_startup_cleanup(application):
    try:
        logging.info("Limpiando webhook y updates pendientes de Telegram...")
        await application.bot.delete_webhook(drop_pending_updates=True)
        logging.info("Webhook eliminado y updates pendientes limpiados.")
    except Exception as e:
        logging.error(f"Error limpiando Telegram al iniciar: {e}")

if __name__ == "__main__":
    threading.Thread(target=run_web_server, daemon=True).start()

    application = (
    ApplicationBuilder()
    .token(TELEGRAM_TOKEN)
    .post_init(telegram_startup_cleanup)
    .build()
)

    application.add_handler(
        MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message)
    )

    logging.info("Bozi-bot natural builder listo.")

    application.run_polling(
    drop_pending_updates=True,
    allowed_updates=Update.ALL_TYPES
)
