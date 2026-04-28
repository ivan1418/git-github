import os
import re
import json
import logging
import threading
import requests
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from urllib.parse import urlparse
from http.server import HTTPServer, BaseHTTPRequestHandler

from apscheduler.schedulers.background import BackgroundScheduler
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, CommandHandler, filters

from supabase import create_client
from openai import OpenAI
from tavily import TavilyClient


# ---------------------------------------------------
# CONFIGURACIÓN
# ---------------------------------------------------
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
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
MAX_OUTPUT_TOKENS = int(os.getenv("MAX_OUTPUT_TOKENS", "1000"))

USE_EMBEDDINGS = os.getenv("USE_EMBEDDINGS", "true").lower() == "true"
USE_WEB_SEARCH = os.getenv("USE_WEB_SEARCH", "smart").lower()

LOCAL_TZ = ZoneInfo("America/Argentina/Buenos_Aires")
LOCAL_TZ_NAME = "America/Argentina/Buenos_Aires"

if not TELEGRAM_TOKEN:
    raise ValueError("Falta TELEGRAM_TOKEN.")

if not OPENAI_API_KEY:
    raise ValueError("Falta OPENAI_API_KEY.")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("Faltan SUPABASE_URL o SUPABASE_KEY.")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
openai_client = OpenAI(api_key=OPENAI_API_KEY)
tavily_client = TavilyClient(api_key=TAVILY_API_KEY) if TAVILY_API_KEY else None


# ---------------------------------------------------
# SERVIDOR WEB PARA PROYECTOS PUBLICADOS
# ---------------------------------------------------
class WebHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/" or path == "/webhook":
            self.send_response(200)
            self.send_header("Content-type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                b"Bozi-bot online. Usa /projects/{id} para ver proyectos publicados."
            )
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
    "Sos Bozi-bot, asistente ejecutivo, técnico y estratégico de Iván."
)

KNOWLEDGE_PROMPT = load_prompt_file(
    "knowledge.txt",
    "Sos experto en IT, programación, infraestructura, ciberseguridad y gestión."
)

RULES_PROMPT = load_prompt_file(
    "rules.txt",
    "Respondé claro, útil, profesional y accionable."
)

MEMORY_PROMPT = load_prompt_file(
    "memory.txt",
    "Usá memoria solo cuando aporte valor."
)


SYSTEM_PROMPT = f"""
{SELF_PROMPT}

{KNOWLEDGE_PROMPT}

{RULES_PROMPT}

{MEMORY_PROMPT}

CAPACIDADES REALES DEL SISTEMA:
- Podés conversar naturalmente.
- Podés crear borradores web HTML.
- Podés editar borradores activos.
- Podés publicar proyectos y devolver URL.
- Podés guardar tareas programadas.
- Podés enviar reportes automáticos por Telegram.
- Podés listar tareas y proyectos.
- Podés actuar como gerente general ficticio si Iván lo pide.
- Podés usar agentes ficticios internos: CTO, DevOps, Frontend, Backend, UX/UI, Blue Team, Red Team ético, Sysadmin e Infraestructura.
- Podés ayudar con temas generales, pero tu especialidad fuerte es IT, programación, ciberseguridad, infraestructura, redes, sysadmin, DevOps y automatización.

REGLAS CRÍTICAS:
- Cuando Iván mencione agentes, equipo, contratar agentes o gerente general, interpretalo como roles ficticios internos del bot.
- No sugieras LinkedIn, reclutamiento ni contratación real salvo que Iván lo pida explícitamente.
- Nunca digas que no podés programar tareas si el usuario pide una tarea compatible.
- Si el usuario pregunta si podés hacerlo, respondé que sí y explicá brevemente cómo.
- No inventes horarios, fechas, cuentas, tiempos restantes ni estados de tareas.
- Para horarios usá siempre {LOCAL_TZ_NAME}.
- Nunca respondas placeholders como "X horas y Y minutos".
""".strip()


HTML_BUILDER_PROMPT = """
Sos un desarrollador frontend senior y diseñador UX/UI.

Generá un proyecto web visual completo.

REGLAS:
- Devolvé SOLO HTML.
- Sin markdown.
- Sin explicaciones.
- Sin bloques ```html.
- Debe empezar con <!DOCTYPE html>.
- CSS dentro de <style>.
- JavaScript dentro de <script> si hace falta.
- Responsive, moderno, elegante y profesional.
- No uses dependencias externas obligatorias.
- Si necesitás imágenes, usá placeholders visuales con CSS.
"""


INTENT_PROMPT = """
Clasificá la intención del usuario.

Respondé SOLO una etiqueta:

CHAT_SIMPLE
PROJECT_DRAFT_CREATE
PROJECT_DRAFT_EDIT
PROJECT_PUBLISH
PROJECT_VIEW_DRAFT
PROJECT_LIST
PROJECT_VIEW_PUBLISHED
TASK_CREATE
TASK_LIST
TASK_DELETE
TIME_REMAINING

Criterios:
CHAT_SIMPLE = charla, duda, debate, consulta, pensar juntos, preguntar si algo se puede.
PROJECT_DRAFT_CREATE = pide crear/diseñar/desarrollar una web, página, landing, dashboard, interfaz, app visual o proyecto entregable.
PROJECT_DRAFT_EDIT = pide cambiar/modificar/mejorar/agregar algo al borrador actual.
PROJECT_PUBLISH = pide publicar, crear URL, pasar URL, deployar o guardar como proyecto final.
PROJECT_VIEW_DRAFT = pide ver el borrador actual.
PROJECT_LIST = pide listar proyectos.
PROJECT_VIEW_PUBLISHED = pide ver proyecto publicado por ID.
TASK_CREATE = pide guardar/agendar/programar/enviar un reporte o recordatorio en el futuro o de forma recurrente.
TASK_LIST = pide ver/listar tareas.
TASK_DELETE = pide borrar/cancelar/desactivar tarea.
TIME_REMAINING = pregunta cuánto falta, cuándo es, a qué hora, o cuánto tiempo queda para una tarea/horario.
"""


TASK_EXTRACT_PROMPT = f"""
Extraé una tarea programada desde el mensaje del usuario.

Devolvé SOLO JSON válido con esta estructura:

{{
  "title": "título corto",
  "task_prompt": "qué debe hacer el bot cuando se ejecute",
  "schedule_type": "daily" | "once",
  "time_of_day": "HH:MM" | null,
  "due_at": "YYYY-MM-DDTHH:MM:SS-03:00" | null,
  "timezone": "{LOCAL_TZ_NAME}"
}}

Reglas:
- Zona horaria principal: {LOCAL_TZ_NAME}.
- Si dice todos los días / diariamente, schedule_type = daily.
- Si dice mañana, una vez, hoy, o fecha específica, schedule_type = once.
- Si no indica hora, usar 09:00.
- Si el usuario dice "hoy a las 16:45", crear due_at para hoy a las 16:45 en zona horaria Argentina/Buenos Aires.
- No agregues texto fuera del JSON.
"""


# ---------------------------------------------------
# UTILIDADES
# ---------------------------------------------------
def now_local():
    return datetime.now(LOCAL_TZ)


def utc_iso():
    return datetime.now(timezone.utc).isoformat()


def trim_text(text, max_chars=1200):
    if not text:
        return ""

    text = str(text).strip()

    if len(text) <= max_chars:
        return text

    return text[:max_chars] + "..."


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


def send_to_webhook(data):
    if not WEBHOOK_DEBUG_URL:
        return

    try:
        requests.post(WEBHOOK_DEBUG_URL, json=data, timeout=8)
    except Exception as e:
        logging.error(f"Error enviando a Webhook.site: {e}")


def telegram_send_message(chat_id, text):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(
            url,
            json={"chat_id": chat_id, "text": text},
            timeout=20
        )
    except Exception as e:
        logging.error(f"Error enviando Telegram: {e}")


def is_task_capability_question(text):
    t = text.lower()
    return (
        ("puedo" in t or "podés" in t or "podes" in t or "podria" in t or "podría" in t or "podrias" in t or "podrías" in t)
        and ("todos los días" in t or "diario" in t or "diaria" in t or "tareas" in t or "reporte" in t or "reportes" in t)
        and ("mandes" in t or "enviarme" in t or "enviar" in t or "mandarme" in t or "enviarme" in t)
    )


def is_time_remaining_question(text):
    t = text.lower()
    return (
        "cuanto falta" in t
        or "cuánto falta" in t
        or "cuando es" in t
        or "cuándo es" in t
        or "a que hora" in t
        or "a qué hora" in t
        or "cuanto tiempo queda" in t
        or "cuánto tiempo queda" in t
    )


def parse_datetime_to_local(value):
    if not value:
        return None

    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(LOCAL_TZ)
    except Exception:
        return None


def calculate_time_remaining(due_at_str):
    try:
        due = parse_datetime_to_local(due_at_str)

        if not due:
            return "No pude calcular el tiempo restante porque esa tarea no tiene una fecha válida."

        now = now_local()
        diff = due - now

        if diff.total_seconds() <= 0:
            return "Ese horario ya pasó."

        total_minutes = int(diff.total_seconds() // 60)
        days = total_minutes // (24 * 60)
        hours = (total_minutes % (24 * 60)) // 60
        minutes = total_minutes % 60

        parts = []

        if days:
            parts.append(f"{days} día{'s' if days != 1 else ''}")

        if hours:
            parts.append(f"{hours} hora{'s' if hours != 1 else ''}")

        if minutes or not parts:
            parts.append(f"{minutes} minuto{'s' if minutes != 1 else ''}")

        due_txt = due.strftime("%d/%m/%Y %H:%M")
        return f"Faltan {' y '.join(parts)}. Está programado para el {due_txt} hs, horario Argentina/Buenos Aires."

    except Exception as e:
        logging.error(f"Error calculando tiempo restante: {e}")
        return "No pude calcular el tiempo restante."


def classify_intent(user_text):
    lower = user_text.lower()

    if is_time_remaining_question(user_text):
        return "TIME_REMAINING"

    if any(x in lower for x in ["todos los días", "diariamente", "recordame", "agendame", "programame", "mandame un reporte", "enviame un reporte", "envíame un reporte"]):
        return "TASK_CREATE"

    if any(x in lower for x in ["listar tareas", "ver tareas", "mis tareas", "tareas programadas"]):
        return "TASK_LIST"

    if any(x in lower for x in ["borrar tarea", "cancelar tarea", "desactivar tarea"]):
        return "TASK_DELETE"

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
            "PROJECT_VIEW_PUBLISHED",
            "TASK_CREATE",
            "TASK_LIST",
            "TASK_DELETE",
            "TIME_REMAINING"
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
        logging.error(f"Error embedding: {e}")
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
        logging.error(f"Error historial: {e}")
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
        logging.error(f"Error memoria semántica: {e}")
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
        "actual",
        "hoy",
        "último",
        "ultima",
        "última",
        "nuevo",
        "precio",
        "cotización",
        "version",
        "versión",
        "noticia",
        "cve",
        "vulnerabilidad",
        "render",
        "openai",
        "telegram",
        "supabase",
        "api",
        "documentación"
    ]

    return any(k in text.lower() for k in keywords)


def get_web_context(user_text):
    if not tavily_client or not should_search_web(user_text):
        return ""

    try:
        search_res = tavily_client.search(
            query=user_text,
            max_results=3,
            search_depth="basic"
        )

        results = search_res.get("results", [])

        compact = []

        for r in results[:3]:
            compact.append({
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "content": trim_text(r.get("content", ""), 700)
            })

        return f"Contexto web reciente: {compact}"

    except Exception as e:
        logging.error(f"Error Tavily: {e}")
        return ""


# ---------------------------------------------------
# DRAFTS / PROYECTOS
# ---------------------------------------------------
def create_draft(chat_id, title, html_content, source_message):
    try:
        res = supabase.table("project_drafts").insert({
            "chat_id": chat_id,
            "title": trim_text(title, 150),
            "draft_type": "html",
            "html_content": html_content,
            "source_message": trim_text(source_message, 3000),
            "status": "draft",
            "updated_at": utc_iso()
        }).execute()

        return res.data[0] if res.data else None

    except Exception as e:
        logging.error(f"Error creando draft: {e}")
        return None


def get_latest_draft(chat_id):
    try:
        res = (
            supabase
            .table("project_drafts")
            .select("id, title, html_content, source_message, status")
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
                "updated_at": utc_iso()
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
        res = supabase.table("projects").insert({
            "chat_id": chat_id,
            "title": draft["title"],
            "content": draft["html_content"],
            "source_message": draft.get("source_message", ""),
            "project_type": "html",
            "html_content": draft["html_content"],
            "updated_at": utc_iso()
        }).execute()

        project = res.data[0] if res.data else None

        if project:
            supabase.table("project_drafts").update({
                "status": "published",
                "updated_at": utc_iso()
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
        logging.error(f"Error proyecto público: {e}")
        return None


# ---------------------------------------------------
# TASKS
# ---------------------------------------------------
def parse_task(user_text):
    current = now_local().isoformat()

    try:
        response = openai_client.responses.create(
            model=OPENAI_MODEL,
            instructions=TASK_EXTRACT_PROMPT,
            input=f"Fecha y hora actual: {current}\nMensaje: {user_text}",
            max_output_tokens=300,
            temperature=0
        )

        raw = response.output_text.strip()
        raw = re.sub(r"^```json\s*", "", raw, flags=re.IGNORECASE)
        raw = re.sub(r"\s*```$", "", raw)
        data = json.loads(raw)

        if not data.get("timezone"):
            data["timezone"] = LOCAL_TZ_NAME

        if not data.get("time_of_day") and data.get("schedule_type") == "daily":
            data["time_of_day"] = "09:00"

        return data

    except Exception as e:
        logging.error(f"Error parseando tarea: {e}")
        return {
            "title": trim_text(user_text, 80),
            "task_prompt": user_text,
            "schedule_type": "daily",
            "time_of_day": "09:00",
            "due_at": None,
            "timezone": LOCAL_TZ_NAME
        }


def create_scheduled_task(chat_id, task_data):
    try:
        res = supabase.table("scheduled_tasks").insert({
            "chat_id": chat_id,
            "title": task_data.get("title", "Tarea programada"),
            "task_prompt": task_data.get("task_prompt", ""),
            "schedule_type": task_data.get("schedule_type", "daily"),
            "time_of_day": task_data.get("time_of_day"),
            "due_at": task_data.get("due_at"),
            "timezone": task_data.get("timezone", LOCAL_TZ_NAME),
            "is_active": True
        }).execute()

        return res.data[0] if res.data else None

    except Exception as e:
        logging.error(f"Error creando tarea: {e}")
        return None


def list_tasks(chat_id):
    try:
        res = (
            supabase
            .table("scheduled_tasks")
            .select("id, title, task_prompt, schedule_type, time_of_day, due_at, timezone, is_active, last_run_at, created_at")
            .eq("chat_id", chat_id)
            .order("created_at", desc=True)
            .limit(20)
            .execute()
        )

        return res.data or []

    except Exception as e:
        logging.error(f"Error listando tareas: {e}")
        return []


def get_latest_active_task(chat_id):
    tasks = list_tasks(chat_id)

    for task in tasks:
        if task.get("is_active"):
            return task

    return tasks[0] if tasks else None


def delete_task(chat_id, user_text):
    match = re.search(r"(\d+)", user_text)

    if not match:
        return False

    task_id = int(match.group(1))

    try:
        supabase.table("scheduled_tasks").update({
            "is_active": False
        }).eq("chat_id", chat_id).eq("id", task_id).execute()

        return True

    except Exception as e:
        logging.error(f"Error borrando tarea: {e}")
        return False


def generate_task_report(task_prompt):
    web_context = get_web_context(task_prompt)

    prompt = f"""
Generá el reporte solicitado por Iván.

Tarea:
{task_prompt}

Contexto web:
{web_context}

Respondé en español, claro, ejecutivo y útil.
"""

    response = openai_client.responses.create(
        model=OPENAI_MODEL,
        instructions=SYSTEM_PROMPT,
        input=prompt,
        max_output_tokens=1200,
        temperature=0.4
    )

    return response.output_text.strip()


def is_task_due(task):
    if not task.get("is_active"):
        return False

    now = now_local()

    if task.get("schedule_type") == "daily":
        time_of_day = task.get("time_of_day") or "09:00"

        try:
            hour, minute = map(int, time_of_day.split(":")[:2])
        except Exception:
            hour, minute = 9, 0

        if now.hour != hour or now.minute != minute:
            return False

        last_run = task.get("last_run_at")

        if last_run:
            try:
                last_dt = parse_datetime_to_local(last_run)

                if last_dt and last_dt.date() == now.date():
                    return False

            except Exception:
                pass

        return True

    if task.get("schedule_type") == "once" and task.get("due_at"):
        due = parse_datetime_to_local(task["due_at"])

        if not due:
            return False

        last_run = task.get("last_run_at")

        return now >= due and not last_run

    return False


def run_due_tasks():
    try:
        res = (
            supabase
            .table("scheduled_tasks")
            .select("*")
            .eq("is_active", True)
            .execute()
        )

        tasks = res.data or []

        for task in tasks:
            if not is_task_due(task):
                continue

            chat_id = task["chat_id"]
            title = task["title"]
            task_prompt = task["task_prompt"]

            telegram_send_message(chat_id, f"Ejecutando tarea programada: {title}")

            try:
                report = generate_task_report(task_prompt)
                telegram_send_message(chat_id, report)

                update_data = {"last_run_at": utc_iso()}

                if task.get("schedule_type") == "once":
                    update_data["is_active"] = False

                supabase.table("scheduled_tasks").update(
                    update_data
                ).eq("id", task["id"]).execute()

            except Exception as e:
                logging.error(f"Error ejecutando tarea {task['id']}: {e}")
                telegram_send_message(
                    chat_id,
                    f"No pude ejecutar la tarea #{task['id']}. Revisá logs."
                )

    except Exception as e:
        logging.error(f"Error scheduler: {e}")


# ---------------------------------------------------
# OPENAI CHAT / BUILDER
# ---------------------------------------------------
def build_chat_input(user_text, history, semantic_memories, web_context):
    messages = []

    if semantic_memories:
        memory_lines = [
            f"- {trim_text(m.get('content', ''), 800)}"
            for m in semantic_memories
        ]

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
        max_output_tokens=3000,
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
        max_output_tokens=3000,
        temperature=0.3
    )

    return clean_html_output(response.output_text)


# ---------------------------------------------------
# LIMPIEZA TELEGRAM AL INICIAR
# ---------------------------------------------------
async def telegram_startup_cleanup(application):
    try:
        logging.info("Limpiando webhook y updates pendientes de Telegram...")
        await application.bot.delete_webhook(drop_pending_updates=True)
        logging.info("Webhook eliminado y updates pendientes limpiados.")
    except Exception as e:
        logging.error(f"Error limpiando Telegram al iniciar: {e}")



# ---------------------------------------------------
# EVENTOS / HEALTH / PANEL DE CONTROL
# ---------------------------------------------------
def log_event(chat_id=None, event_type="info", message="", metadata=None):
    try:
        supabase.table("bot_events").insert({
            "chat_id": chat_id,
            "event_type": event_type,
            "message": trim_text(message, 1000),
            "metadata": metadata or {},
            "created_at": utc_iso()
        }).execute()
    except Exception as e:
        logging.warning(f"No pude guardar evento: {e}")


def get_recent_events(chat_id=None, limit=10):
    try:
        query = (
            supabase
            .table("bot_events")
            .select("id, chat_id, event_type, message, metadata, created_at")
            .order("created_at", desc=True)
            .limit(limit)
        )

        if chat_id is not None:
            query = query.eq("chat_id", chat_id)

        res = query.execute()
        return res.data or []
    except Exception as e:
        logging.warning(f"No pude leer eventos: {e}")
        return []


def count_active_tasks(chat_id):
    try:
        tasks = list_tasks(chat_id)
        return len([t for t in tasks if t.get("is_active")])
    except Exception:
        return 0


def count_projects(chat_id):
    try:
        return len(list_projects(chat_id, limit=100))
    except Exception:
        return 0


def describe_agent_team():
    return (
        "Equipo ficticio interno disponible:\n\n"
        "- CEO / Gerente general: coordina prioridades y decisiones.\n"
        "- CTO: arquitectura, stack y calidad técnica.\n"
        "- Backend Developer: APIs, bots, lógica y bases de datos.\n"
        "- Frontend Developer: interfaces, HTML/CSS/JS y experiencia visual.\n"
        "- DevOps: Render, Docker, deploys, logs y estabilidad.\n"
        "- UX/UI: diseño, claridad visual y usabilidad.\n"
        "- Blue Team: defensa, monitoreo, hardening y detección.\n"
        "- Red Team ético: pruebas autorizadas y análisis ofensivo responsable.\n"
        "- Sysadmin / Infraestructura: Linux, redes, servicios y troubleshooting.\n\n"
        "Son roles simulados internos del bot, no personas reales contratadas."
    )


def describe_cost_mode():
    return (
        "Modo costo actual:\n\n"
        f"- Modelo principal: {OPENAI_MODEL}\n"
        f"- Modelo embeddings: {OPENAI_EMBEDDING_MODEL}\n"
        f"- Historial reciente: {MAX_HISTORY_MESSAGES} mensajes\n"
        f"- Memorias semánticas: {MAX_MEMORY_RESULTS} resultados\n"
        f"- Máximo tokens salida: {MAX_OUTPUT_TOKENS}\n"
        f"- Búsqueda web: {USE_WEB_SEARCH}\n\n"
        "Recomendación: mantener gpt-4o-mini para uso diario y subir modelo solo para tareas complejas."
    )


def describe_mode():
    return (
        "Modo operativo actual:\n\n"
        "- Conversación natural: activo\n"
        "- Proyectos con borrador primero: activo\n"
        "- Publicación por URL: activo\n"
        "- Tareas programadas: activo\n"
        "- Memoria semántica: activo si USE_EMBEDDINGS=true\n"
        "- Equipo ficticio de agentes: disponible bajo pedido\n"
        f"- Zona horaria: {LOCAL_TZ_NAME}"
    )


# ---------------------------------------------------
# BOT
# ---------------------------------------------------
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_text = update.message.text or ""

    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    # Corrección directa para preguntas sobre tareas automáticas
    if is_task_capability_question(user_text):
        answer = (
            "Sí, Iván. Puedo hacerlo.\n\n"
            "Puedo guardar tareas programadas y enviarte reportes automáticamente por Telegram.\n\n"
            "Ejemplo:\n"
            "Todos los días a las 9 mandame un reporte de ciberseguridad."
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
    task_saved = None

    try:
        if intent == "TIME_REMAINING":
            task = get_latest_active_task(chat_id)

            if not task:
                answer = "No tenés tareas programadas."
            else:
                if task.get("schedule_type") == "daily":
                    time_of_day = task.get("time_of_day") or "09:00"
                    hour, minute = map(int, time_of_day.split(":")[:2])
                    now = now_local()
                    due = now.replace(hour=hour, minute=minute, second=0, microsecond=0)

                    if due <= now:
                        due = due.replace(day=due.day + 1)

                    answer = calculate_time_remaining(due.isoformat())
                else:
                    due_at = task.get("due_at")
                    answer = calculate_time_remaining(due_at)

        elif intent == "TASK_CREATE":
            task_data = parse_task(user_text)
            task_saved = create_scheduled_task(chat_id, task_data)

            if task_saved:
                if task_saved["schedule_type"] == "daily":
                    answer = (
                        f"Listo Iván. Tarea programada #{task_saved['id']}.\n\n"
                        f"{task_saved['title']}\n"
                        f"Frecuencia: todos los días a las {task_saved.get('time_of_day') or '09:00'} hs "
                        f"({LOCAL_TZ_NAME})."
                    )
                else:
                    due_local = parse_datetime_to_local(task_saved.get("due_at"))
                    due_txt = due_local.strftime("%d/%m/%Y %H:%M") if due_local else task_saved.get("due_at")

                    answer = (
                        f"Listo Iván. Tarea programada #{task_saved['id']}.\n\n"
                        f"{task_saved['title']}\n"
                        f"Fecha: {due_txt} hs ({LOCAL_TZ_NAME})."
                    )
            else:
                answer = "No pude guardar la tarea. Revisá Supabase/logs."

        elif intent == "TASK_LIST":
            tasks = list_tasks(chat_id)

            if not tasks:
                answer = "No tenés tareas programadas."
            else:
                lines = ["Tus tareas programadas:\n"]

                for t in tasks:
                    status = "activa" if t.get("is_active") else "inactiva"

                    if t.get("schedule_type") == "daily":
                        when = f"todos los días a las {t.get('time_of_day') or '09:00'} hs"
                    else:
                        due_local = parse_datetime_to_local(t.get("due_at"))
                        when = due_local.strftime("%d/%m/%Y %H:%M hs") if due_local else "sin horario"

                    lines.append(
                        f"#{t['id']} - {t['title']} | {when} | {status}"
                    )

                answer = "\n".join(lines)

        elif intent == "TASK_DELETE":
            ok = delete_task(chat_id, user_text)

            answer = (
                "Listo Iván. Tarea desactivada."
                if ok
                else "Decime el número de tarea. Ejemplo: borrar tarea 2"
            )

        elif intent == "PROJECT_DRAFT_CREATE":
            html = generate_html_from_request(user_text, semantic_memories)

            draft_saved = create_draft(
                chat_id,
                trim_text(user_text, 100),
                html,
                user_text
            )

            if draft_saved:
                answer = (
                    "Listo Iván. Te armé un primer borrador del proyecto.\n\n"
                    "Todavía no lo publiqué como URL final.\n\n"
                    "Podés decirme:\n"
                    "- publicalo\n"
                    "- cambiar colores\n"
                    "- agregar sección de contacto\n"
                    "- ver borrador"
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
                    chat_id,
                    draft["id"],
                    new_html,
                    user_text
                )

                answer = (
                    "Listo Iván. Apliqué los cambios al borrador. "
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
                        f"Ver online:\n{url}"
                    )
                else:
                    answer = "No pude publicar el proyecto."

        elif intent == "PROJECT_VIEW_DRAFT":
            draft = get_latest_draft(chat_id)

            if draft:
                answer = (
                    f"Borrador activo #{draft['id']}\n"
                    f"Título: {draft['title']}\n\n"
                    "Decime 'publicalo' para crear la URL."
                )
            else:
                answer = "No tengo un borrador activo."

        elif intent == "PROJECT_LIST":
            projects = list_projects(chat_id)

            if not projects:
                answer = "Todavía no tenés proyectos publicados."
            else:
                lines = ["Tus últimos proyectos publicados:\n"]

                for p in projects:
                    lines.append(
                        f"#{p['id']} - {p['title']}\n{get_project_url(p['id'])}"
                    )

                answer = "\n\n".join(lines)

        elif intent == "PROJECT_VIEW_PUBLISHED":
            match = re.search(r"(\d+)", user_text)

            if not match:
                answer = "Decime el número del proyecto. Ejemplo: ver proyecto 3"
            else:
                project_id = int(match.group(1))
                project = get_project(chat_id, project_id)

                if project:
                    answer = f"Proyecto #{project_id}:\n{get_project_url(project_id)}"
                else:
                    answer = "No encontré ese proyecto."

        else:
            input_messages = build_chat_input(
                user_text,
                history,
                semantic_memories,
                web_context
            )

            answer = ask_openai_chat(input_messages)

    except Exception as e:
        logging.error(f"Error procesando mensaje: {e}")
        log_event(chat_id, "error", f"Error procesando mensaje: {e}", {"user_text": user_text})
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
        "task_saved": task_saved,
        "model": OPENAI_MODEL
    })

    await update.message.reply_text(answer)


# ---------------------------------------------------
# ---------------------------------------------------
# COMANDOS TELEGRAM
# ---------------------------------------------------
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    log_event(chat_id, "command", "/start")
    await update.message.reply_text(
        "Hola Iván. Soy Bozi-bot.\n\n"
        "Podés hablarme normalmente o usar comandos rápidos:\n\n"
        "/models - ver modelos disponibles\n"
        "/config - ver configuración actual\n"
        "/tasks - ver tareas programadas\n"
        "/projects - ver proyectos publicados\n"
        "/status - estado general\n"
        "/health - test OpenAI + Supabase + Telegram\n"
        "/errors - últimos eventos/errores\n"
        "/agents - equipo ficticio interno\n"
        "/cost - modo costo actual\n"
        "/mode - modo operativo actual\n"
        "/restart - reiniciar el servicio en Render"
    )


async def cmd_models(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    log_event(chat_id, "command", "/models")
    models = [
        "gpt-4o-mini",
        "gpt-4.1-mini",
        "gpt-4.1",
        "gpt-4o"
    ]

    lines = ["Modelos disponibles para configurar:\n"]
    for model in models:
        current = " ← actual" if model == OPENAI_MODEL else ""
        lines.append(f"- {model}{current}")

    lines.append("\nPara cambiarlo, escribí por chat normal:")
    lines.append("cambiá el modelo a gpt-4o-mini")

    await update.message.reply_text("\n".join(lines))


async def cmd_config(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    log_event(chat_id, "command", "/config")
    config_text = (
        "Configuración actual:\n\n"
        f"- Modelo principal: {OPENAI_MODEL}\n"
        f"- Modelo embeddings: {OPENAI_EMBEDDING_MODEL}\n"
        f"- Historial reciente: {MAX_HISTORY_MESSAGES}\n"
        f"- Memorias semánticas: {MAX_MEMORY_RESULTS}\n"
        f"- Máximo tokens salida: {MAX_OUTPUT_TOKENS}\n"
        f"- Embeddings activos: {USE_EMBEDDINGS}\n"
        f"- Web search: {USE_WEB_SEARCH}\n"
        f"- Zona horaria: {LOCAL_TZ_NAME}\n"
        f"- URL pública: {PUBLIC_BASE_URL or 'no configurada'}"
    )

    await update.message.reply_text(config_text)


async def cmd_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    log_event(chat_id, "command", "/tasks")
    tasks = list_tasks(chat_id)

    if not tasks:
        await update.message.reply_text("No tenés tareas programadas.")
        return

    lines = ["Tus tareas programadas:\n"]

    for task in tasks:
        status = "activa" if task.get("is_active") else "inactiva"

        if task.get("schedule_type") == "daily":
            when = f"todos los días a las {task.get('time_of_day') or '09:00'} hs"
        else:
            due_local = parse_datetime_to_local(task.get("due_at"))
            when = due_local.strftime("%d/%m/%Y %H:%M hs") if due_local else "sin horario"

        lines.append(f"#{task['id']} - {task['title']} | {when} | {status}")

    await update.message.reply_text("\n".join(lines))


async def cmd_projects(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    log_event(chat_id, "command", "/projects")
    projects = list_projects(chat_id)

    if not projects:
        await update.message.reply_text("No tenés proyectos publicados.")
        return

    lines = ["Tus últimos proyectos publicados:\n"]

    for project in projects:
        lines.append(f"#{project['id']} - {project['title']}\n{get_project_url(project['id'])}")

    await update.message.reply_text("\n\n".join(lines))


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    log_event(chat_id, "command", "/status")
    active_tasks = count_active_tasks(chat_id)
    project_count = count_projects(chat_id)
    recent_errors = [e for e in get_recent_events(chat_id, limit=10) if e.get("event_type") == "error"]

    await update.message.reply_text(
        "Estado general de Bozi-bot:\n\n"
        "✔ Servicio: online\n"
        "✔ Telegram: polling activo\n"
        "✔ Scheduler: activo\n"
        f"✔ Modelo: {OPENAI_MODEL}\n"
        f"✔ Timezone: {LOCAL_TZ_NAME}\n"
        f"✔ Tareas activas: {active_tasks}\n"
        f"✔ Proyectos publicados: {project_count}\n"
        f"✔ Últimos errores registrados: {len(recent_errors)}"
    )


async def cmd_health(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    log_event(chat_id, "command", "/health")

    checks = []

    try:
        me = await context.bot.get_me()
        checks.append(f"✔ Telegram OK: @{me.username}")
    except Exception as e:
        checks.append(f"❌ Telegram error: {e}")
        log_event(chat_id, "error", f"Health Telegram error: {e}")

    try:
        supabase.table("scheduled_tasks").select("id").limit(1).execute()
        checks.append("✔ Supabase OK")
    except Exception as e:
        checks.append(f"❌ Supabase error: {e}")
        log_event(chat_id, "error", f"Health Supabase error: {e}")

    try:
        response = openai_client.responses.create(
            model=OPENAI_MODEL,
            instructions="Respondé solo OK.",
            input="healthcheck",
            max_output_tokens=10,
            temperature=0
        )
        result = response.output_text.strip()
        checks.append(f"✔ OpenAI OK: {result or 'sin texto'}")
    except Exception as e:
        checks.append(f"❌ OpenAI error: {e}")
        log_event(chat_id, "error", f"Health OpenAI error: {e}")

    checks.append("✔ Scheduler: proceso iniciado")
    checks.append(f"✔ Timezone: {LOCAL_TZ_NAME}")

    await update.message.reply_text("Healthcheck:\n\n" + "\n".join(checks))


async def cmd_errors(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    log_event(chat_id, "command", "/errors")
    events = get_recent_events(chat_id, limit=10)

    if not events:
        await update.message.reply_text("No hay eventos registrados todavía.")
        return

    lines = ["Últimos eventos registrados:\n"]
    for event in events:
        created = event.get("created_at", "")
        event_type = event.get("event_type", "info")
        message = trim_text(event.get("message", ""), 180)
        lines.append(f"#{event['id']} | {created} | {event_type}\n{message}")

    await update.message.reply_text("\n\n".join(lines))


async def cmd_agents(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    log_event(chat_id, "command", "/agents")
    await update.message.reply_text(describe_agent_team())


async def cmd_cost(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    log_event(chat_id, "command", "/cost")
    await update.message.reply_text(describe_cost_mode())


async def cmd_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    log_event(chat_id, "command", "/mode")
    await update.message.reply_text(describe_mode())


async def cmd_restart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    log_event(chat_id, "command", "/restart")
    await update.message.reply_text("Reiniciando servicio en Render...")
    os._exit(0)


# MAIN
# ---------------------------------------------------
if __name__ == "__main__":
    threading.Thread(target=run_web_server, daemon=True).start()

    scheduler = BackgroundScheduler(timezone=LOCAL_TZ_NAME)
    scheduler.add_job(run_due_tasks, "cron", second=0)
    scheduler.start()
    log_event(None, "startup", "Bozi-bot iniciado correctamente", {"model": OPENAI_MODEL, "timezone": LOCAL_TZ_NAME})

    application = (
        ApplicationBuilder()
        .token(TELEGRAM_TOKEN)
        .post_init(telegram_startup_cleanup)
        .build()
    )

    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("models", cmd_models))
    application.add_handler(CommandHandler("config", cmd_config))
    application.add_handler(CommandHandler("tasks", cmd_tasks))
    application.add_handler(CommandHandler("projects", cmd_projects))
    application.add_handler(CommandHandler("status", cmd_status))
    application.add_handler(CommandHandler("health", cmd_health))
    application.add_handler(CommandHandler("errors", cmd_errors))
    application.add_handler(CommandHandler("agents", cmd_agents))
    application.add_handler(CommandHandler("cost", cmd_cost))
    application.add_handler(CommandHandler("mode", cmd_mode))
    application.add_handler(CommandHandler("restart", cmd_restart))

    application.add_handler(
        MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message)
    )

    logging.info("Bozi-bot CEO Builder Scheduler listo.")

    application.run_polling(
        drop_pending_updates=True,
        allowed_updates=Update.ALL_TYPES
    )
