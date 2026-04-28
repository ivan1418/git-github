import os
import re
import json
import logging
import threading
import requests
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from urllib.parse import urlparse
from http.server import HTTPServer, BaseHTTPRequestHandler

from apscheduler.schedulers.background import BackgroundScheduler
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters
from supabase import create_client
from openai import OpenAI
from tavily import TavilyClient

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)

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
LOCAL_TZ_NAME = "America/Argentina/Buenos_Aires"
LOCAL_TZ = ZoneInfo(LOCAL_TZ_NAME)
ALLOWED_MODELS = {"gpt-4o-mini", "gpt-4.1-mini", "gpt-4.1", "gpt-4o"}

DEFAULT_BOT_CONFIG = {
    "mode": "asistente_general_tecnico",
    "response_style": "natural_profesional",
    "detail_level": "medio",
    "technical_depth": "alto",
    "project_behavior": "draft_first",
    "agent_team": "enabled",
    "auto_publish_projects": "false",
    "web_search": USE_WEB_SEARCH,
    "model": OPENAI_MODEL,
    "max_output_tokens": str(MAX_OUTPUT_TOKENS),
}

if not TELEGRAM_TOKEN:
    raise ValueError("Falta TELEGRAM_TOKEN.")
if not OPENAI_API_KEY:
    raise ValueError("Falta OPENAI_API_KEY.")
if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("Faltan SUPABASE_URL o SUPABASE_KEY.")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
openai_client = OpenAI(api_key=OPENAI_API_KEY)
tavily_client = TavilyClient(api_key=TAVILY_API_KEY) if TAVILY_API_KEY else None


def now_local():
    return datetime.now(LOCAL_TZ)


def utc_iso():
    return datetime.now(timezone.utc).isoformat()


def trim_text(text, max_chars=1200):
    text = str(text or "").strip()
    return text if len(text) <= max_chars else text[:max_chars] + "..."


def load_prompt_file(filename, fallback=""):
    try:
        with open(filename, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return fallback


SELF_PROMPT = load_prompt_file("self.txt", "Sos Bozi-bot, asistente ejecutivo, técnico y estratégico de Iván.")
KNOWLEDGE_PROMPT = load_prompt_file("knowledge.txt", "Sos experto en IT, programación, infraestructura, ciberseguridad y gestión.")
RULES_PROMPT = load_prompt_file("rules.txt", "Respondé claro, útil, profesional y accionable.")
MEMORY_PROMPT = load_prompt_file("memory.txt", "Usá memoria solo cuando aporte valor.")

BASE_SYSTEM_PROMPT = f"""
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
- Podés cambiar tu configuración dinámica guardada en Supabase sin redeploy.
- Podés actuar como gerente general ficticio si Iván lo pide.
- Podés usar agentes ficticios internos: CTO, DevOps, Frontend, Backend, UX/UI, Blue Team, Red Team ético, Sysadmin e Infraestructura.
- Podés ayudar con temas generales, con especialidad fuerte en IT, programación, ciberseguridad, infraestructura, redes, sysadmin, DevOps y automatización.

REGLAS CRÍTICAS:
- Cuando Iván mencione agentes, equipo, contratar agentes o gerente general, interpretalo como roles ficticios internos del bot.
- No sugieras LinkedIn, reclutamiento ni contratación real salvo que Iván lo pida explícitamente.
- Nunca digas que no podés programar tareas si el usuario pide una tarea compatible.
- No inventes horarios, fechas, cuentas, tiempos restantes ni estados de tareas.
- Para horarios usá siempre {LOCAL_TZ_NAME}.
- Nunca respondas placeholders como "X horas y Y minutos".
""".strip()

HTML_BUILDER_PROMPT = """
Sos un desarrollador frontend senior y diseñador UX/UI.
Generá un proyecto web visual completo.
REGLAS:
- Devolvé SOLO HTML.
- Sin markdown ni explicaciones.
- Debe empezar con <!DOCTYPE html>.
- CSS dentro de <style>.
- JavaScript dentro de <script> si hace falta.
- Responsive, moderno, elegante y profesional.
- No uses dependencias externas obligatorias.
"""

INTENT_PROMPT = """
Clasificá la intención del usuario. Respondé SOLO una etiqueta:
CHAT_SIMPLE
CONFIG_UPDATE
CONFIG_VIEW
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
CONFIG_UPDATE = pide cambiar modo, personalidad, tono, modelo, detalle, comportamiento, activar modo gerente o modificar configuración del bot.
CONFIG_VIEW = pide ver configuración actual del bot.
PROJECT_DRAFT_CREATE = pide crear/diseñar/desarrollar una web, página, landing, dashboard, interfaz o app visual.
PROJECT_DRAFT_EDIT = pide cambiar/modificar/mejorar/agregar algo al borrador actual.
PROJECT_PUBLISH = pide publicar, crear URL, pasar URL, deployar o guardar como proyecto final.
PROJECT_VIEW_DRAFT = pide ver el borrador actual.
PROJECT_LIST = pide listar proyectos.
PROJECT_VIEW_PUBLISHED = pide ver proyecto publicado por ID.
TASK_CREATE = pide guardar/agendar/programar/enviar reporte o recordatorio futuro/recurrente.
TASK_LIST = pide ver/listar tareas.
TASK_DELETE = pide borrar/cancelar/desactivar tarea.
TIME_REMAINING = pregunta cuánto falta, cuándo es o cuánto tiempo queda.
"""

TASK_EXTRACT_PROMPT = f"""
Extraé una tarea programada desde el mensaje del usuario. Devolvé SOLO JSON válido:
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
- Si dice hoy a las HH:MM, due_at para hoy a esa hora en Argentina/Buenos_Aires.
"""

CONFIG_EXTRACT_PROMPT = """
Extraé cambios de configuración pedidos por el usuario. Devolvé SOLO JSON válido.
Campos posibles:
{
  "mode": "asistente_general_tecnico | gerente_general | cto | devops | cybersec | sysadmin | diseñador_ux | minimalista",
  "response_style": "natural_profesional | ejecutivo | tecnico | cercano | directo | didactico",
  "detail_level": "bajo | medio | alto",
  "technical_depth": "bajo | medio | alto",
  "project_behavior": "draft_first | auto_draft | ask_before_project",
  "agent_team": "enabled | disabled",
  "auto_publish_projects": "true | false",
  "web_search": "smart | true | false",
  "model": "gpt-4o-mini | gpt-4.1-mini | gpt-4.1 | gpt-4o",
  "max_output_tokens": "500 | 800 | 1000 | 1500 | 2000"
}
Reglas:
- Solo incluí campos pedidos.
- Si pide modo gerente, mode = gerente_general y agent_team = enabled.
- Si pide respuestas más cortas, detail_level = bajo y max_output_tokens = 500.
- Si pide respuestas más completas, detail_level = alto y max_output_tokens = 1500.
- Si pide tono ejecutivo, response_style = ejecutivo.
- Si pide modo técnico, response_style = tecnico y technical_depth = alto.
"""


class WebHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/" or path == "/webhook":
            self.send_response(200)
            self.send_header("Content-type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"Bozi-bot online. Usa /projects/{id} para ver proyectos publicados.")
            return
        match = re.match(r"^/projects/(\d+)$", path)
        if match:
            project = get_project_by_id(int(match.group(1)))
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


def parse_json_output(raw):
    raw = str(raw).strip()
    raw = re.sub(r"^```json\s*", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"\s*```$", "", raw)
    return json.loads(raw)


def clean_html_output(text):
    text = str(text or "").strip()
    text = re.sub(r"^```html\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^```\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text if text.lower().startswith("<!doctype html") else "<!DOCTYPE html>\n" + text


def send_to_webhook(data):
    if WEBHOOK_DEBUG_URL:
        try:
            requests.post(WEBHOOK_DEBUG_URL, json=data, timeout=8)
        except Exception as e:
            logging.error(f"Error enviando a Webhook.site: {e}")


def telegram_send_message(chat_id, text):
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={"chat_id": chat_id, "text": text}, timeout=20)
    except Exception as e:
        logging.error(f"Error enviando Telegram: {e}")


def get_project_url(project_id):
    return f"{PUBLIC_BASE_URL}/projects/{project_id}" if PUBLIC_BASE_URL else f"/projects/{project_id}"


def is_task_capability_question(text):
    t = text.lower()
    return (("puedo" in t or "podés" in t or "podes" in t or "podría" in t or "podrias" in t)
            and ("todos los días" in t or "diario" in t or "tareas" in t or "reporte" in t)
            and ("mandes" in t or "enviarme" in t or "enviar" in t or "mandarme" in t))


def is_time_remaining_question(text):
    t = text.lower()
    return any(x in t for x in ["cuanto falta", "cuánto falta", "cuando es", "cuándo es", "a que hora", "a qué hora", "cuanto tiempo queda", "cuánto tiempo queda"])


def is_config_view_question(text):
    t = text.lower()
    return any(x in t for x in ["ver configuración", "ver configuracion", "mi configuración", "mi configuracion", "tu configuración", "tu configuracion", "cómo estás configurado", "como estas configurado"])


def is_config_update_question(text):
    t = text.lower()
    triggers = ["cambiá tu", "cambia tu", "configurate", "activá modo", "activa modo", "modo gerente", "modo cto", "modo devops", "modo cyber", "respondé más corto", "responde más corto", "respondé mas corto", "responde mas corto", "respondé más completo", "responde más completo", "tono ejecutivo", "tono técnico", "tono tecnico", "cambia el modelo", "cambiá el modelo", "usa el modelo", "usá el modelo", "desactivá web search", "desactiva web search"]
    return any(x in t for x in triggers)


def parse_datetime_to_local(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(LOCAL_TZ)
    except Exception:
        return None


def calculate_time_remaining(due_at_str):
    due = parse_datetime_to_local(due_at_str)
    if not due:
        return "No pude calcular el tiempo restante porque esa tarea no tiene una fecha válida."
    diff = due - now_local()
    if diff.total_seconds() <= 0:
        return "Ese horario ya pasó."
    total_minutes = int(diff.total_seconds() // 60)
    days = total_minutes // 1440
    hours = (total_minutes % 1440) // 60
    minutes = total_minutes % 60
    parts = []
    if days:
        parts.append(f"{days} día{'s' if days != 1 else ''}")
    if hours:
        parts.append(f"{hours} hora{'s' if hours != 1 else ''}")
    if minutes or not parts:
        parts.append(f"{minutes} minuto{'s' if minutes != 1 else ''}")
    return f"Faltan {' y '.join(parts)}. Está programado para el {due.strftime('%d/%m/%Y %H:%M')} hs, horario Argentina/Buenos_Aires."


# ---------------------------------------------------
# CONFIG DINÁMICA
# ---------------------------------------------------
def normalize_config_value(key, value):
    value = str(value).strip() if value is not None else None
    allowed = {
        "mode": {"asistente_general_tecnico", "gerente_general", "cto", "devops", "cybersec", "sysadmin", "diseñador_ux", "minimalista"},
        "response_style": {"natural_profesional", "ejecutivo", "tecnico", "cercano", "directo", "didactico"},
        "detail_level": {"bajo", "medio", "alto"},
        "technical_depth": {"bajo", "medio", "alto"},
        "project_behavior": {"draft_first", "auto_draft", "ask_before_project"},
        "agent_team": {"enabled", "disabled"},
        "auto_publish_projects": {"true", "false"},
        "web_search": {"smart", "true", "false"},
        "model": ALLOWED_MODELS,
        "max_output_tokens": {"500", "800", "1000", "1500", "2000"},
    }
    return value if key in allowed and value in allowed[key] else None


def get_bot_config(chat_id):
    config = dict(DEFAULT_BOT_CONFIG)
    for cid in (0, chat_id):
        try:
            res = supabase.table("bot_config").select("key, value").eq("chat_id", cid).execute()
            for item in res.data or []:
                if item.get("key"):
                    config[item["key"]] = str(item.get("value"))
        except Exception as e:
            logging.warning(f"No pude leer bot_config chat_id={cid}: {e}")
    return config


def save_bot_config(chat_id, changes):
    saved = {}
    for key, raw_value in changes.items():
        value = normalize_config_value(key, raw_value)
        if value is None:
            continue
        try:
            supabase.table("bot_config").upsert({"chat_id": chat_id, "key": key, "value": value, "updated_at": utc_iso()}, on_conflict="chat_id,key").execute()
            saved[key] = value
        except Exception as e:
            logging.error(f"Error guardando config {key}: {e}")
    return saved


def extract_config_changes(user_text):
    try:
        resp = openai_client.responses.create(model=OPENAI_MODEL, instructions=CONFIG_EXTRACT_PROMPT, input=user_text, max_output_tokens=400, temperature=0)
        data = parse_json_output(resp.output_text)
        return data if isinstance(data, dict) else {}
    except Exception as e:
        logging.error(f"Error extrayendo config: {e}")
        return {}


def get_model_from_config(config):
    model = config.get("model", OPENAI_MODEL)
    return model if model in ALLOWED_MODELS else OPENAI_MODEL


def get_max_tokens_from_config(config):
    try:
        return max(300, min(int(config.get("max_output_tokens", MAX_OUTPUT_TOKENS)), 2500))
    except Exception:
        return MAX_OUTPUT_TOKENS


def build_runtime_system_prompt(config):
    runtime = f"""
CONFIGURACIÓN DINÁMICA ACTUAL:
- Modo: {config.get('mode')}
- Estilo: {config.get('response_style')}
- Nivel de detalle: {config.get('detail_level')}
- Profundidad técnica: {config.get('technical_depth')}
- Equipo ficticio de agentes: {config.get('agent_team')}
- Auto-publicar proyectos: {config.get('auto_publish_projects')}
- Web search: {config.get('web_search')}

APLICACIÓN:
- Si mode = gerente_general, actuá como gerente general ficticio operativo de Iván.
- Si detail_level = bajo, respondé más corto.
- Si detail_level = alto, respondé con más profundidad.
- Si response_style = ejecutivo, respondé con foco en decisiones, impacto y próximos pasos.
- Si agent_team = enabled, podés simular internamente especialistas ficticios, pero entregá una respuesta final unificada.
"""
    return BASE_SYSTEM_PROMPT + "\n\n" + runtime


def format_config(config):
    return (
        "Configuración actual del bot:\n\n"
        f"- Modo: {config.get('mode')}\n"
        f"- Estilo: {config.get('response_style')}\n"
        f"- Nivel de detalle: {config.get('detail_level')}\n"
        f"- Profundidad técnica: {config.get('technical_depth')}\n"
        f"- Equipo ficticio de agentes: {config.get('agent_team')}\n"
        f"- Proyectos: {config.get('project_behavior')}\n"
        f"- Auto-publicar proyectos: {config.get('auto_publish_projects')}\n"
        f"- Web search: {config.get('web_search')}\n"
        f"- Modelo: {config.get('model')}\n"
        f"- Máximo tokens salida: {config.get('max_output_tokens')}"
    )


def classify_intent(user_text):
    lower = user_text.lower()
    if is_config_view_question(user_text):
        return "CONFIG_VIEW"
    if is_config_update_question(user_text):
        return "CONFIG_UPDATE"
    if is_time_remaining_question(user_text):
        return "TIME_REMAINING"
    if any(x in lower for x in ["todos los días", "diariamente", "recordame", "agendame", "programame", "mandame un reporte", "enviame un reporte", "envíame un reporte"]):
        return "TASK_CREATE"
    if any(x in lower for x in ["listar tareas", "ver tareas", "mis tareas", "tareas programadas"]):
        return "TASK_LIST"
    if any(x in lower for x in ["borrar tarea", "cancelar tarea", "desactivar tarea"]):
        return "TASK_DELETE"
    try:
        resp = openai_client.responses.create(model=OPENAI_MODEL, instructions=INTENT_PROMPT, input=user_text, max_output_tokens=20, temperature=0)
        intent = resp.output_text.strip().upper()
        valid = {"CHAT_SIMPLE", "CONFIG_UPDATE", "CONFIG_VIEW", "PROJECT_DRAFT_CREATE", "PROJECT_DRAFT_EDIT", "PROJECT_PUBLISH", "PROJECT_VIEW_DRAFT", "PROJECT_LIST", "PROJECT_VIEW_PUBLISHED", "TASK_CREATE", "TASK_LIST", "TASK_DELETE", "TIME_REMAINING"}
        return intent if intent in valid else "CHAT_SIMPLE"
    except Exception as e:
        logging.error(f"Error clasificando intención: {e}")
        return "CHAT_SIMPLE"


# ---------------------------------------------------
# MEMORIA / WEB
# ---------------------------------------------------
def get_openai_embedding(text):
    if not USE_EMBEDDINGS:
        return None
    try:
        resp = openai_client.embeddings.create(model=OPENAI_EMBEDDING_MODEL, input=trim_text(text, 6000))
        return resp.data[0].embedding
    except Exception as e:
        logging.error(f"Error embedding: {e}")
        return None


def save_memory(chat_id, role, content, embedding=None):
    try:
        data = {"chat_id": chat_id, "role": role, "content": trim_text(content, 5000)}
        if embedding is not None:
            data["embedding"] = embedding
        supabase.table("bot_memory").insert(data).execute()
    except Exception as e:
        logging.error(f"Error guardando memoria: {e}")


def get_recent_history(chat_id):
    try:
        res = supabase.table("bot_memory").select("role, content, created_at").eq("chat_id", chat_id).order("created_at", desc=True).limit(MAX_HISTORY_MESSAGES).execute()
        return list(reversed(res.data or []))
    except Exception as e:
        logging.error(f"Error historial: {e}")
        return []


def get_semantic_memories(chat_id, query_embedding):
    if not USE_EMBEDDINGS or query_embedding is None:
        return []
    try:
        res = supabase.rpc("match_bot_memory", {"query_embedding": query_embedding, "match_chat_id": chat_id, "match_count": MAX_MEMORY_RESULTS}).execute()
        return [m for m in (res.data or []) if m.get("similarity", 0) >= 0.25]
    except Exception as e:
        logging.error(f"Error memoria semántica: {e}")
        return []


def should_search_web(text, config=None):
    mode = (config or {}).get("web_search", USE_WEB_SEARCH)
    if mode == "false":
        return False
    if mode == "true":
        return True
    keywords = ["actual", "hoy", "último", "ultima", "última", "nuevo", "precio", "cotización", "version", "versión", "noticia", "cve", "vulnerabilidad", "render", "openai", "telegram", "supabase", "api", "documentación"]
    return any(k in text.lower() for k in keywords)


def get_web_context(user_text, config=None):
    if not tavily_client or not should_search_web(user_text, config):
        return ""
    try:
        res = tavily_client.search(query=user_text, max_results=3, search_depth="basic")
        compact = []
        for r in (res.get("results") or [])[:3]:
            compact.append({"title": r.get("title", ""), "url": r.get("url", ""), "content": trim_text(r.get("content", ""), 700)})
        return f"Contexto web reciente: {compact}"
    except Exception as e:
        logging.error(f"Error Tavily: {e}")
        return ""


# ---------------------------------------------------
# DRAFTS / PROYECTOS
# ---------------------------------------------------
def create_draft(chat_id, title, html_content, source_message):
    try:
        res = supabase.table("project_drafts").insert({"chat_id": chat_id, "title": trim_text(title, 150), "draft_type": "html", "html_content": html_content, "source_message": trim_text(source_message, 3000), "status": "draft", "updated_at": utc_iso()}).execute()
        return res.data[0] if res.data else None
    except Exception as e:
        logging.error(f"Error creando draft: {e}")
        return None


def get_latest_draft(chat_id):
    try:
        res = supabase.table("project_drafts").select("id, title, html_content, source_message, status").eq("chat_id", chat_id).eq("status", "draft").order("updated_at", desc=True).limit(1).execute()
        return res.data[0] if res.data else None
    except Exception as e:
        logging.error(f"Error obteniendo draft: {e}")
        return None


def update_draft(chat_id, draft_id, html_content, source_message):
    try:
        res = supabase.table("project_drafts").update({"html_content": html_content, "source_message": trim_text(source_message, 3000), "updated_at": utc_iso()}).eq("chat_id", chat_id).eq("id", draft_id).execute()
        return res.data[0] if res.data else None
    except Exception as e:
        logging.error(f"Error actualizando draft: {e}")
        return None


def publish_draft(chat_id, draft):
    try:
        res = supabase.table("projects").insert({"chat_id": chat_id, "title": draft["title"], "content": draft["html_content"], "source_message": draft.get("source_message", ""), "project_type": "html", "html_content": draft["html_content"], "updated_at": utc_iso()}).execute()
        project = res.data[0] if res.data else None
        if project:
            supabase.table("project_drafts").update({"status": "published", "updated_at": utc_iso()}).eq("id", draft["id"]).execute()
        return project
    except Exception as e:
        logging.error(f"Error publicando draft: {e}")
        return None


def list_projects(chat_id, limit=10):
    try:
        res = supabase.table("projects").select("id, title, project_type, created_at").eq("chat_id", chat_id).order("created_at", desc=True).limit(limit).execute()
        return res.data or []
    except Exception as e:
        logging.error(f"Error listando proyectos: {e}")
        return []


def get_project(chat_id, project_id):
    try:
        res = supabase.table("projects").select("id, title, content, html_content, project_type").eq("chat_id", chat_id).eq("id", project_id).limit(1).execute()
        return res.data[0] if res.data else None
    except Exception as e:
        logging.error(f"Error obteniendo proyecto: {e}")
        return None


def get_project_by_id(project_id):
    try:
        res = supabase.table("projects").select("id, title, content, html_content, project_type").eq("id", project_id).limit(1).execute()
        return res.data[0] if res.data else None
    except Exception as e:
        logging.error(f"Error proyecto público: {e}")
        return None


# ---------------------------------------------------
# TASKS
# ---------------------------------------------------
def parse_task(user_text):
    try:
        resp = openai_client.responses.create(model=OPENAI_MODEL, instructions=TASK_EXTRACT_PROMPT, input=f"Fecha y hora actual: {now_local().isoformat()}\nMensaje: {user_text}", max_output_tokens=300, temperature=0)
        data = parse_json_output(resp.output_text)
        data.setdefault("timezone", LOCAL_TZ_NAME)
        if not data.get("time_of_day") and data.get("schedule_type") == "daily":
            data["time_of_day"] = "09:00"
        return data
    except Exception as e:
        logging.error(f"Error parseando tarea: {e}")
        return {"title": trim_text(user_text, 80), "task_prompt": user_text, "schedule_type": "daily", "time_of_day": "09:00", "due_at": None, "timezone": LOCAL_TZ_NAME}


def create_scheduled_task(chat_id, task_data):
    try:
        res = supabase.table("scheduled_tasks").insert({"chat_id": chat_id, "title": task_data.get("title", "Tarea programada"), "task_prompt": task_data.get("task_prompt", ""), "schedule_type": task_data.get("schedule_type", "daily"), "time_of_day": task_data.get("time_of_day"), "due_at": task_data.get("due_at"), "timezone": task_data.get("timezone", LOCAL_TZ_NAME), "is_active": True}).execute()
        return res.data[0] if res.data else None
    except Exception as e:
        logging.error(f"Error creando tarea: {e}")
        return None


def list_tasks(chat_id):
    try:
        res = supabase.table("scheduled_tasks").select("id, title, task_prompt, schedule_type, time_of_day, due_at, timezone, is_active, last_run_at, created_at").eq("chat_id", chat_id).order("created_at", desc=True).limit(20).execute()
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
    try:
        supabase.table("scheduled_tasks").update({"is_active": False}).eq("chat_id", chat_id).eq("id", int(match.group(1))).execute()
        return True
    except Exception as e:
        logging.error(f"Error borrando tarea: {e}")
        return False


def generate_task_report(task_prompt, config=None):
    config = config or DEFAULT_BOT_CONFIG
    web_context = get_web_context(task_prompt, config)
    prompt = f"""
Generá el reporte solicitado por Iván.

Tarea:
{task_prompt}

Contexto web:
{web_context}

Respondé en español, claro, ejecutivo y útil.
"""
    resp = openai_client.responses.create(model=get_model_from_config(config), instructions=build_runtime_system_prompt(config), input=prompt, max_output_tokens=1200, temperature=0.4)
    return resp.output_text.strip()


def is_task_due(task):
    if not task.get("is_active"):
        return False
    now = now_local()
    if task.get("schedule_type") == "daily":
        try:
            hour, minute = map(int, (task.get("time_of_day") or "09:00").split(":")[:2])
        except Exception:
            hour, minute = 9, 0
        if now.hour != hour or now.minute != minute:
            return False
        last_run = parse_datetime_to_local(task.get("last_run_at"))
        return not (last_run and last_run.date() == now.date())
    if task.get("schedule_type") == "once" and task.get("due_at"):
        due = parse_datetime_to_local(task.get("due_at"))
        return bool(due and now >= due and not task.get("last_run_at"))
    return False


def run_due_tasks():
    try:
        res = supabase.table("scheduled_tasks").select("*").eq("is_active", True).execute()
        for task in res.data or []:
            if not is_task_due(task):
                continue
            chat_id = task["chat_id"]
            config = get_bot_config(chat_id)
            telegram_send_message(chat_id, f"Ejecutando tarea programada: {task['title']}")
            try:
                report = generate_task_report(task["task_prompt"], config)
                telegram_send_message(chat_id, report)
                update_data = {"last_run_at": utc_iso()}
                if task.get("schedule_type") == "once":
                    update_data["is_active"] = False
                supabase.table("scheduled_tasks").update(update_data).eq("id", task["id"]).execute()
            except Exception as e:
                logging.error(f"Error ejecutando tarea {task['id']}: {e}")
                telegram_send_message(chat_id, f"No pude ejecutar la tarea #{task['id']}. Revisá logs.")
    except Exception as e:
        logging.error(f"Error scheduler: {e}")


# ---------------------------------------------------
# OPENAI CHAT / BUILDER
# ---------------------------------------------------
def build_chat_input(user_text, history, semantic_memories, web_context):
    messages = []
    if semantic_memories:
        messages.append({"role": "user", "content": "Recuerdos relevantes:\n" + "\n".join(["- " + trim_text(m.get("content", ""), 800) for m in semantic_memories])})
    for m in history:
        role = m.get("role", "user") if m.get("role") in ["user", "assistant"] else "user"
        content = trim_text(m.get("content", ""), 1000)
        if content:
            messages.append({"role": role, "content": content})
    final = user_text + (f"\n\nContexto externo:\n{trim_text(web_context, 1800)}" if web_context else "")
    messages.append({"role": "user", "content": final})
    return messages


def ask_openai_chat(input_messages, config=None):
    config = config or DEFAULT_BOT_CONFIG
    resp = openai_client.responses.create(model=get_model_from_config(config), instructions=build_runtime_system_prompt(config), input=input_messages, max_output_tokens=get_max_tokens_from_config(config), temperature=0.4)
    return resp.output_text.strip() or "No pude generar una respuesta clara."


def generate_html_from_request(user_text, semantic_memories=None, config=None):
    memory_context = ""
    if semantic_memories:
        memory_context = "\n\nContexto útil:\n" + "\n".join([trim_text(m.get("content", ""), 700) for m in semantic_memories[:4]])
    resp = openai_client.responses.create(model=get_model_from_config(config or DEFAULT_BOT_CONFIG), instructions=HTML_BUILDER_PROMPT, input=f"Pedido del usuario:\n{user_text}{memory_context}", max_output_tokens=3000, temperature=0.35)
    return clean_html_output(resp.output_text)


def edit_html(old_html, change_request, config=None):
    prompt = f"""
HTML actual:
{old_html}

Cambio solicitado:
{change_request}

Devolvé el HTML completo actualizado.
"""
    resp = openai_client.responses.create(model=get_model_from_config(config or DEFAULT_BOT_CONFIG), instructions=HTML_BUILDER_PROMPT, input=prompt, max_output_tokens=3000, temperature=0.3)
    return clean_html_output(resp.output_text)


async def telegram_startup_cleanup(application):
    try:
        logging.info("Limpiando webhook y updates pendientes de Telegram...")
        await application.bot.delete_webhook(drop_pending_updates=True)
        logging.info("Webhook eliminado y updates pendientes limpiados.")
    except Exception as e:
        logging.error(f"Error limpiando Telegram al iniciar: {e}")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_text = update.message.text or ""
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    config = get_bot_config(chat_id)

    if is_task_capability_question(user_text):
        await update.message.reply_text("Sí, Iván. Puedo guardar tareas programadas y enviarte reportes automáticamente por Telegram.\n\nEjemplo:\nTodos los días a las 9 mandame un reporte de ciberseguridad.")
        return

    intent = classify_intent(user_text)
    logging.info(f"Intent detectado: {intent}")

    user_embedding = get_openai_embedding(user_text)
    save_memory(chat_id, "user", user_text, user_embedding)
    semantic_memories = get_semantic_memories(chat_id, user_embedding)
    history = get_recent_history(chat_id)
    web_context = get_web_context(user_text, config)

    project_saved = None
    draft_saved = None
    task_saved = None
    config_saved = None

    try:
        if intent == "CONFIG_VIEW":
            answer = format_config(config)

        elif intent == "CONFIG_UPDATE":
            changes = extract_config_changes(user_text)
            config_saved = save_bot_config(chat_id, changes)
            if config_saved:
                answer = "Listo Iván. Actualicé mi configuración sin tocar GitHub ni Render.\n\nCambios aplicados:\n" + "\n".join([f"- {k}: {v}" for k, v in config_saved.items()]) + "\n\n" + format_config(get_bot_config(chat_id))
            else:
                answer = "Entendí que querés cambiar mi configuración, pero no detecté un cambio válido. Ejemplos: activá modo gerente, respondé más corto, usá tono ejecutivo, cambiá el modelo a gpt-4o-mini."

        elif intent == "TIME_REMAINING":
            task = get_latest_active_task(chat_id)
            if not task:
                answer = "No tenés tareas programadas."
            elif task.get("schedule_type") == "daily":
                hour, minute = map(int, (task.get("time_of_day") or "09:00").split(":")[:2])
                now = now_local()
                due = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
                if due <= now:
                    due += timedelta(days=1)
                answer = calculate_time_remaining(due.isoformat())
            else:
                answer = calculate_time_remaining(task.get("due_at"))

        elif intent == "TASK_CREATE":
            task_saved = create_scheduled_task(chat_id, parse_task(user_text))
            if task_saved:
                if task_saved["schedule_type"] == "daily":
                    answer = f"Listo Iván. Tarea programada #{task_saved['id']}.\n\n{task_saved['title']}\nFrecuencia: todos los días a las {task_saved.get('time_of_day') or '09:00'} hs ({LOCAL_TZ_NAME})."
                else:
                    due_local = parse_datetime_to_local(task_saved.get("due_at"))
                    due_txt = due_local.strftime("%d/%m/%Y %H:%M") if due_local else task_saved.get("due_at")
                    answer = f"Listo Iván. Tarea programada #{task_saved['id']}.\n\n{task_saved['title']}\nFecha: {due_txt} hs ({LOCAL_TZ_NAME})."
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
                    when = f"todos los días a las {t.get('time_of_day') or '09:00'} hs" if t.get("schedule_type") == "daily" else (parse_datetime_to_local(t.get("due_at")).strftime("%d/%m/%Y %H:%M hs") if parse_datetime_to_local(t.get("due_at")) else "sin horario")
                    lines.append(f"#{t['id']} - {t['title']} | {when} | {status}")
                answer = "\n".join(lines)

        elif intent == "TASK_DELETE":
            answer = "Listo Iván. Tarea desactivada." if delete_task(chat_id, user_text) else "Decime el número de tarea. Ejemplo: borrar tarea 2"

        elif intent == "PROJECT_DRAFT_CREATE":
            html = generate_html_from_request(user_text, semantic_memories, config)
            draft_saved = create_draft(chat_id, trim_text(user_text, 100), html, user_text)
            if draft_saved and config.get("auto_publish_projects") == "true":
                project_saved = publish_draft(chat_id, draft_saved)
                answer = f"Listo Iván. Te armé y publiqué el proyecto como #{project_saved['id']}.\n\nVer online:\n{get_project_url(project_saved['id'])}" if project_saved else "Generé el borrador, pero no pude publicarlo."
            elif draft_saved:
                answer = "Listo Iván. Te armé un primer borrador del proyecto.\n\nTodavía no lo publiqué como URL final.\n\nPodés decirme:\n- publicalo\n- cambiar colores\n- agregar sección de contacto\n- ver borrador"
            else:
                answer = "Generé el borrador, pero no pude guardarlo."

        elif intent == "PROJECT_DRAFT_EDIT":
            draft = get_latest_draft(chat_id)
            if not draft:
                answer = "No tengo un borrador activo para editar. Primero pedime que cree una página o proyecto."
            else:
                new_html = edit_html(draft["html_content"], user_text, config)
                draft_saved = update_draft(chat_id, draft["id"], new_html, user_text)
                answer = "Listo Iván. Apliqué los cambios al borrador. Cuando quieras verlo online, decime: publicalo."

        elif intent == "PROJECT_PUBLISH":
            draft = get_latest_draft(chat_id)
            if not draft:
                answer = "No tengo un borrador activo para publicar."
            else:
                project_saved = publish_draft(chat_id, draft)
                answer = f"Listo Iván. Proyecto publicado como #{project_saved['id']}.\n\nVer online:\n{get_project_url(project_saved['id'])}" if project_saved else "No pude publicar el proyecto."

        elif intent == "PROJECT_VIEW_DRAFT":
            draft = get_latest_draft(chat_id)
            answer = f"Borrador activo #{draft['id']}\nTítulo: {draft['title']}\n\nDecime 'publicalo' para crear la URL." if draft else "No tengo un borrador activo."

        elif intent == "PROJECT_LIST":
            projects = list_projects(chat_id)
            answer = "Todavía no tenés proyectos publicados." if not projects else "Tus últimos proyectos publicados:\n\n" + "\n\n".join([f"#{p['id']} - {p['title']}\n{get_project_url(p['id'])}" for p in projects])

        elif intent == "PROJECT_VIEW_PUBLISHED":
            match = re.search(r"(\d+)", user_text)
            if not match:
                answer = "Decime el número del proyecto. Ejemplo: ver proyecto 3"
            else:
                project_id = int(match.group(1))
                answer = f"Proyecto #{project_id}:\n{get_project_url(project_id)}" if get_project(chat_id, project_id) else "No encontré ese proyecto."

        else:
            answer = ask_openai_chat(build_chat_input(user_text, history, semantic_memories, web_context), config)

    except Exception as e:
        logging.error(f"Error procesando mensaje: {e}")
        answer = "Che Iván, se me tildó la IA. Revisá logs de Render y probá de nuevo."

    save_memory(chat_id, "assistant", answer, get_openai_embedding(answer))
    send_to_webhook({"type": "bot_output", "intent": intent, "chat_id": chat_id, "user_message": user_text, "bot_response": answer, "draft_saved": draft_saved, "project_saved": project_saved, "task_saved": task_saved, "config_saved": config_saved, "model": get_model_from_config(config)})
    await update.message.reply_text(answer)


if __name__ == "__main__":
    threading.Thread(target=run_web_server, daemon=True).start()
    scheduler = BackgroundScheduler(timezone=LOCAL_TZ_NAME)
    scheduler.add_job(run_due_tasks, "cron", second=0)
    scheduler.start()
    application = ApplicationBuilder().token(TELEGRAM_TOKEN).post_init(telegram_startup_cleanup).build()
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    logging.info("Bozi-bot CEO Builder Scheduler Configurable listo.")
    application.run_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)
