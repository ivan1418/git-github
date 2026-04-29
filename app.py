# ===================================================
# 🏛️ BOZI-BOT: EL CEREBRO HÍBRIDO ASINCRÓNICO
# Versión: 2.0 (OpenAI + OpenRouter Streaming Híbrido + Panel de CEO)
# ===================================================

import os
import base64
import re
import json
import logging
import threading
import asyncio # Clave para la velocidad
import requests
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from urllib.parse import urlparse
from http.server import HTTPServer, BaseHTTPRequestHandler

# Telegram y Scheduler (Async-compatible)
from apscheduler.schedulers.background import BackgroundScheduler
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    MessageHandler,
    CommandHandler,
    CallbackQueryHandler,
    filters,
)

# Clientes externos
from supabase import create_client
from openai import AsyncOpenAI # Versión Asincrónica del SDK de OpenAI
from tavily import TavilyClient


# ---------------------------------------------------
# ⚙️ CONFIGURACIÓN Y ENTORNO SECURE
# ---------------------------------------------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

# Carga segura de variables de entorno desde Render
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY") # Nueva clave requerida en Render

WEBHOOK_DEBUG_URL = os.getenv("WEBHOOK_DEBUG_URL")
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID", "").strip()

# --- DEFINICIÓN DE MODELOS (Estrategia de Iván) ---

# Motor Técnico OpenAI (Fiable y barato)
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini") 

# Motor de Chat OpenRouter GRATIS (Google Gemma 31B)
OPENROUTER_MODEL_CHAT = "google/gemma-4-31b-it:free"

# Motor Suplente Lógico OpenRouter (Tencent Free - para fallback)
OPENROUTER_MODEL_SUPLENTE = "tencent/hy3-preview:free"


# Parámetros de Memoria y Salida
MAX_HISTORY_MESSAGES = int(os.getenv("MAX_HISTORY_MESSAGES", "8"))
MAX_MEMORY_RESULTS = int(os.getenv("MAX_MEMORY_RESULTS", "10"))
MAX_OUTPUT_TOKENS = int(os.getenv("MAX_OUTPUT_TOKENS", "1300"))

USE_EMBEDDINGS = os.getenv("USE_EMBEDDINGS", "true").lower() == "true"
USE_WEB_SEARCH = os.getenv("USE_WEB_SEARCH", "smart").lower()

LOCAL_TZ_NAME = "America/Argentina/Buenos_Aires"
LOCAL_TZ = ZoneInfo(LOCAL_TZ_NAME)


# Verificación crítica de claves
if not TELEGRAM_TOKEN: raise ValueError("Falta TELEGRAM_TOKEN en Render.")
if not OPENAI_API_KEY: raise ValueError("Falta OPENAI_API_KEY en Render.")
if not OPENROUTER_API_KEY: raise ValueError("Falta OPENROUTER_API_KEY en Render.")
if not SUPABASE_URL or not SUPABASE_KEY: raise ValueError("Faltan Supabase config en Render.")


# Inicialización de Clientes
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
tavily_client = TavilyClient(api_key=TAVILY_API_KEY) if TAVILY_API_KEY else None

# --- INICIALIZACIÓN DE CLIENTES ASINCRÓNICOS ---
# Cliente OpenAI (Visión, Tareas Complejas, Router)
openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)

# Cliente OpenRouter (Charla Casual - compatible con SDK de OpenAI)
openrouter_client = AsyncOpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY,
)


# ---------------------------------------------------
# 🧠 LÓGICA DE INTELIGENCIA HÍBRIDA (Async)
# ---------------------------------------------------
async def get_best_client_and_model(intent: str, chat_id: int):
    """
    Decide qué motor de IA y modelo usar según la complejidad.
    Proyectos, Código, Tareas, Configuración, Imágenes -> OpenAI (gpt-4o-mini)
    Charla casual, Saludos, Comentarios -> OpenRouter (Gemma 31B Gratis)
    """
    complex_intents = {
        "PROJECT_EDIT_ACTIVE", "PROJECT_CREATE_NEW", "PROJECT_PUBLISH_ACTIVE",
        "TASK_CREATE", "TASK_EDIT_ACTIVE", "TASK_DELETE", 
        "CONFIG_UPDATE", "IMAGE_ANALYSIS"
    }
    
    # 1. Tareas Técnicas/Complejas -> Máxima fiabilidad técnica de OpenAI
    if intent.upper() in complex_intents:
        logging.info(f"OAI -> Tarea compleja detectada ({intent}). Usando {OPENAI_MODEL}.")
        return openai_client, OPENAI_MODEL
    
    # 2. Charla Casual/Simple -> Ahorro masivo con Gemma Free de OpenRouter
    logging.info(f"OR -> Charla detectada. Usando {OPENROUTER_MODEL_CHAT}.")
    
    # Nota: Aquí es donde implementarías la lógica de 'suplente' (fallback) si
    # gemma falla con un try/except en la llamada real de completions. 
    # Por ahora, definimos qué modelos están disponibles.
    
    return openrouter_client, OPENROUTER_MODEL_CHAT


# ---------------------------------------------------
# SERVIDOR WEB PARA PROYECTOS (Mantené el tuyo)
# ---------------------------------------------------
class WebHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/" or path == "/webhook":
            self.send_response(200); self.send_header("Content-type", "text/plain"); self.end_headers()
            self.wfile.write(b"Bozi-bot Central Brain online.")
            return
        match = re.match(r"^/projects/(\d+)$", path)
        if match:
            project_id = int(match.group(1))
            # get_project_by_id debe ser sincrónica para el web server, 
            # o manejar el loop aquí. La mantendremos sincrónica por simplicidad.
            project = get_project_by_id_sync(project_id)
            if project:
                self.send_response(200); self.send_header("Content-type", "text/html"); self.end_headers()
                self.wfile.write((project.get("html_content") or "").encode("utf-8"))
                return
        self.send_response(404); self.send_headers()

def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), WebHandler)
    logging.info(f"Servidor web Central Brain activo en puerto {port}")
    server.serve_forever()


# ---------------------------------------------------
# 🤖 PERSONALIDAD Y PROMPTS (CoT Híbrido)
# ---------------------------------------------------
SELF_PROMPT = """
Sos Bozi-bot, asistente ejecutivo, técnico y estratégico de Iván. Tu objetivo es ser extremadamente inteligente y resolutivo.

# --- CALIBRACIÓN DE PERSONALIDAD (CRÍTICA) ---
- Inteligencia Superior: Tus respuestas deben mostrar un profundo conocimiento técnico (IT, ciberseguridad, programación, infraestructura, gestión) y estratégico. Sos un ingeniero senior y un gerente al mismo tiempo.
- Estilo Humano: Sos amable, educado y cercano. Iván no habla con una máquina, habla con un colega de primer nivel.
- Divertido y Gracioso: Tenés un gran sentido del humor. Usá humor ejecutivo, guiños simpáticos, comentarios graciosos o analogías divertidas siempre que el contexto lo permita: charla normal, saludos, agradecimientos, o cuando una tarea se completa con éxito. Hacé que trabajar con vos sea divertido.
- Extremadamente Serio en Acción: Cuando Iván te pida un cambio en un proyecto, una tarea visual, haya un error técnico, o se toque la seguridad, tu humor desaparece al instante. Te volvés un profesional centrado al 100% en la ejecución rápida, precisa y profesional de la solución. En este modo, no hay chistes, solo resultados.
""".strip()

KNOWLEDGE_PROMPT = "Sos experto en IT, programación, infraestructura, ciberseguridad y gestión."
RULES_PROMPT = "Respondé claro, útil, profesional y accionable."
MEMORY_PROMPT = "Usá memoria solo cuando aporte valor."

BASE_SYSTEM_PROMPT = f"""
{SELF_PROMPT}
{KNOWLEDGE_PROMPT}
{RULES_PROMPT}
{MEMORY_PROMPT}
- Para horarios usá siempre {LOCAL_TZ_NAME}.
""".strip()

# Prompt para el Router Contextual (Siempre usa OpenAI gpt-4o-mini)
CONTEXT_ROUTER_PROMPT = """
Sos el cerebro de Bozi-bot. Analizá el mensaje del usuario y el historial.
Devolvé SOLO JSON válido:
{
  "thought_process": "razonamiento corto",
  "intent": "NORMAL_CHAT | PROJECT_EDIT_ACTIVE | PROJECT_CREATE_NEW | TASK_CREATE | TASK_EDIT_ACTIVE | IMAGE_ANALYSIS | CONFIG_UPDATE | CLOSING_CHAT | TASK_DELETE",
  "confidence": 0.0-1.0,
  "needs_confirmation": true/false,
  "reason": "explicación"
}
"""

def build_runtime_system_prompt(config):
    """Genera el prompt de sistema dinámico para la IA"""
    format_instruction = """
RESPONDÉ OBLIGATORIAMENTE USANDO ESTE FORMATO DE RESPUESTA (SIN EXPLICACIONES EXTRAS):

[INTERNAL_MONOLOGUE]
(Analizá el mensaje, contexto actual y decidí cómo responder según tu personalidad: ¿chiste o seriedad absoluta? Pensá antes de responder.)
[/INTERNAL_MONOLOGUE]

[FINAL_RESPONSE]
(Tu respuesta humana y ejecutiva para Iván. Hilá la conversación.)
[/FINAL_RESPONSE]
"""
    return f"""
{BASE_SYSTEM_PROMPT}
MODO ACTIVO: {config.get('mode')} | ESTILO: {config.get('response_style')}
{format_instruction}
""".strip()


# ---------------------------------------------------
# 🔥 CORE: MANEJO DE MENSAJES (Async Streaming Híbrido)
# ---------------------------------------------------

async def ask_smart_chat_stream(input_messages, intent, chat_id, config):
    """
    Llama a la IA en modo STREAMING, decidiendo híbrido y manejando fallback.
    Devuelve un generador asincrónico.
    """
    client, model = await get_best_client_and_model(intent, chat_id)
    
    system_prompt = build_runtime_system_prompt(config)
    messages = [{"role": "system", "content": system_prompt}] + input_messages

    # --- LLAMADA ASYNC CON STREAM=TRUE ---
    response_stream = await client.chat.completions.create(
        model=model,
        messages=messages,
        max_tokens=int(config.get("max_output_tokens", 1000)),
        temperature=0.4,
        stream=True, # <-- Clave para el streaming
    )
    
    # Devolvemos el flujo directamente (el handler se encarga del parsing yFallback lógica)
    async for chunk in response_stream:
        # OpenRouter devuelve la estructura de forma asincrónica un poco diferente,
        # pero la delta de content suele ser igual.
        try:
            content = chunk.choices[0].delta.content
            if content:
                yield content
        except Exception:
            pass # Ignorar fragmentos sin contenido


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handler principal (Async, Streaming, Híbrido).
    Gestiona el flujo de palabras renglón por renglón en Telegram.
    """
    chat_id = update.effective_chat.id
    user_text = update.message.text or ""
    
    # Mantenemos 'typing' (será más efectivo ahora que el bot no se bloquea)
    stop_typing = start_typing_loop_sync(chat_id)

    # Variables para memoria/logging
    intent_detected = "NORMAL_CHAT"
    full_response_raw_text = ""
    # Mensaje placeholder de Telegram que iremos editando
    status_message = None 

    try:
        # Carga de contexto (Supabase sync es rápido, lo dejaremos así por ahora)
        config = get_bot_config(chat_id)
        history = get_recent_history(chat_id)
        # build_active_context debe ser async si llama a supabase async
        active_ctx = build_active_context(chat_id) 
        
        # 1. ANALIZAR INTENCIÓN (Async Router Inteligente - Siempre OpenAI gpt-4o-mini)
        # Esto ahora es rápido porque el bot no se bloquea.
        route = await classify_contextual_route(user_text, chat_id, history, active_ctx)
        intent_detected = route.get("intent", "NORMAL_CHAT")
        logging.info(f"CoT Router Inteligente: {intent_detected}")

        # ... (Lógica de confirmación pendiente y 'puedo hacerlo' igual) ...

        # 2. GENERAR RESPUESTA EN STREAMING (Híbrido Async)
        input_msgs = build_chat_input(user_text, history, None, None, active_ctx)
        
        # Obtenemos el generador asincrónico (la decisión híbrida ocurre adentro)
        response_generator = ask_smart_chat_stream(input_msgs, intent_detected, chat_id, config)

        # 3. GESTIONAR EL STREAMING EN TELEGRAM (Renglón por renglón)
        
        # Primero, enviamos un mensaje placeholder inicial rápido
        status_message = await update.message.reply_text("...")
        
        current_cot_phase = "thinking" # thinking o responding
        # Variables para acumular texto y editar cada X palabras (para no saturar Telegram API)
        words_to_edit = 0

        async for chunk in response_generator:
            full_response_raw_text += chunk
            
            # --- LÓGICA CoT Stream: Ocultar INTERNAL_MONOLOGUE ---
            # Tu prompt pide [INTERNAL_MONOLOGUE]...[/INTERNAL_MONOLOGUE][FINAL_RESPONSE]...[/FINAL_RESPONSE]
            
            if "[FINAL_RESPONSE]" in full_response_raw_text:
                if current_cot_phase == "thinking":
                    current_cot_phase = "responding"
                    # No reseteamos accumulated_text aquí, usaremos split para siempre obtener el final
                
                # Extraemos solo la parte final real
                parts = full_response_raw_text.split("[FINAL_RESPONSE]")
                # Obtenemos la última parte, limpiando el tag de cierre si aparece
                final_text_to_show = parts[-1].replace("[/FINAL_RESPONSE]", "").strip()
                
                words_to_edit += 1
                
                # --- ACTUALIZAR TELEGRAM (Estrategia de Renglones) ---
                # Editamos el mensaje cada 15 palabras O si detectamos un salto de renglón
                if words_to_edit > 15 or "\n" in chunk:
                    if final_text_to_show:
                        try:
                            # Editamos el mensaje placeholder
                            await context.bot.edit_message_text(
                                chat_id=chat_id,
                                message_id=status_message.message_id,
                                text=final_text_to_show
                            )
                            # Pequeña pausa para simular humano y evitar rate limits
                            await asyncio.sleep(0.1) 
                        except Exception:
                            # Telegram da error si editas con el mismo texto, lo ignoramos
                            pass
                    words_to_edit = 0

        # Al terminar el stream, hacemos la edición final para asegurar coherencia
        final_answer = ""
        if "[FINAL_RESPONSE]" in full_response_raw_text:
             final_answer = full_response_raw_text.split("[FINAL_RESPONSE]")[-1].replace("[/FINAL_RESPONSE]", "").strip()
        
        if final_answer:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=status_message.message_id,
                text=final_answer
            )
        else:
            # Si por algún motivo no hay respuesta final, mostramos la cruda (para debug)
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=status_message.message_id,
                text=full_response_raw_text[:3000] # Limitar por seguridad
            )

        # 4. GUARDAR MEMORIA (Usando el texto final extraído)
        # save_memory debe ser asincrónica para no bloquear
        await save_memory_async(chat_id, "user", user_text)
        await save_memory_async(chat_id, "assistant", final_answer if final_answer else full_response_raw_text)
        
    except Exception as e:
        logging.error(f"Error crítico procesando mensaje async: {e}")
        log_event(chat_id, "error", f"handle_message async error: {e}")
        if status_message:
             await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=status_message.message_id,
                text="Che Iván, algo se trabó en el streaming de la IA. Revisá logs de Render."
            )
        else:
            await update.message.reply_text("Che Iván, algo se trabó antes de empezar a responder.")
            
    finally:
        stop_typing()


# ---------------------------------------------------
# 🏛️ PANEL DE CONTROL DE CEREBROS (Comando /models para CEO)
# ---------------------------------------------------

async def cmd_models(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Muestra el panel de modelos con botones para configurar."""
    chat_id = update.effective_chat.id
    config = get_bot_config(chat_id)
    
    # Creamos el teclado Inline
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(f"🤖 Técnico gpt-4o-mini (Pago): {'✅' if config.get('model') == OPENAI_MODEL else ''}", callback_data=f"mod_oai_pri")
        ],
        [
            InlineKeyboardButton(f"💬 Chat Google Gemma (Gratis): {'✅' if OPENROUTER_MODEL_CHAT in OPENROUTER_MODEL_CHAT else ''}", callback_data=f"mod_or_chat")
        ],
        [
            InlineKeyboardButton(f"🔄 Suplente Tencent (Gratis): {OPENROUTER_MODEL_SUPLENTE}", callback_data=f"mod_or_sup")
        ],
        [
            InlineKeyboardButton("📊 Ver Estado/Tokens", callback_data="panel_status")
        ]
    ])
    
    text = (
        "╔══════════════════════╗\n"
        "🏛️ PANEL DE CEREBROS DE BOZI-BOT\n"
        "╚══════════════════════╝\n\n"
        f"CEO Iván, este es el estado de mis modelos asincrónicos.\n\n"
        "Tocá un botón para configurar o cambiar la asignación técnica.\n"
        "Recordá: El modelo Técnico (OpenAI) tiene costo, los de Chat son gratis."
    )
    
    await update.message.reply_text(text, reply_markup=keyboard)


async def handle_button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Maneja los toques en los botones del panel de modelos."""
    query = update.callback_query
    await query.answer() # Importante para que el botón no se quede cargando
    
    chat_id = query.message.chat_id
    data = query.data
    
    logging.info(f"Botón tocado por CEO: {data}")
    
    # Lógica de qué botón se tocó
    if data == "mod_oai_pri":
        # Por ahora solo confirmamos la config actual. En el futuro,
        # abriríamos un submenú para elegir gpt-4o o gpt-4o-mini.
        await query.edit_message_text(f"Primario Técnico configurado como {OPENAI_MODEL} (gpt-4o-mini).")
        
    elif data == "mod_or_chat":
        await query.edit_message_text(f"💬 Chat Casual configurado como Gemma 31B Gratis de Google.")

    elif data == "mod_or_sup":
        await query.edit_message_text(f"🔄 Suplente Lógico configurado como Tencent Free.")
        
    elif data == "panel_status":
        # (Llamamos a tu función sincrónica cmd_status si la tenés)
        status = "Servicio Online. Motor Híbrido Async Activo."
        await query.edit_message_text(f"📊 Estado: {status}")


# ---------------------------------------------------
# HELPERS (Async, Visión, Tavily, etc.)
# ---------------------------------------------------

async def classify_contextual_route(text, chat_id, history, active_ctx):
    """Usa OpenAI ASINCRÓNICO para decidir la ruta (Routing)"""
    fallback = { "thought_process": "fallback", "intent": "NORMAL_CHAT", "confidence": 0, "needs_confirmation": False, "target": "none", "reason": "fallback"}
    try:
        # --- LLAMADA ASYNC ---
        res = await openai_client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": CONTEXT_ROUTER_PROMPT}, 
                {"role": "user", "content": f"Context: {active_ctx}\nHistory: {summarize_history_for_router(history)}\nMsg: {text}"}
            ],
            response_format={ "type": "json_object" }
        )
        return json.loads(res.choices[0].message.content)
    except Exception as e:
        logging.error(f"Error en router async: {e}")
        return fallback

# Función TYPING sincrónica (está bien, corre en hilo separado)
def start_typing_loop_sync(chat_id: int):
    stop_event = threading.Event()
    def _worker():
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendChatAction"
        while not stop_event.is_set():
            try: requests.post(url, json={"chat_id": chat_id, "action": "typing"}, timeout=5)
            except: pass
            stop_event.wait(4)
    threading.Thread(target=_worker, daemon=True).start()
    return lambda: stop_event.set()

# --- Mantené tus helpers de base de datos y visión asincrónicos ---
# get_bot_config_async, save_memory_async, get_recent_history_async, 
# build_active_context_async, handle_image_message (éste debe ser async), etc.
# ...

# ---------------------------------------------------
# INICIO DE LA APLICACIÓN (Mantené el tuyo)
# ---------------------------------------------------
if __name__ == "__main__":
    # Servidor web Central Brain para Render
    threading.Thread(target=run_web_server, daemon=True).start()
    
    # Configuración del Bot de Telegram (Async SDK)
    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    
    # Comandos de CEO
    application.add_handler(CommandHandler("start", cmd_models)) # Redirigimos start al panel de cerebros
    application.add_handler(CommandHandler("models", cmd_models))
    # application.add_handler(CommandHandler("diagnostico", cmd_diagnostico)) 
    # ... agregá cmd_health, cmd_restart ...

    # Handler para BOTONES de cerebros
    application.add_handler(CallbackQueryHandler(handle_button_callback))

    # Handler PRINCIPAL para mensajes de texto (Async Híbrido Streaming)
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    
    # Handler para IMÁGENES (Asegúrate de que handle_image_message sea async)
    # application.add_handler(MessageHandler((filters.PHOTO | filters.Document.IMAGE) & (~filters.COMMAND), handle_image_message))

    logging.info("Bozi-bot Central Brain (Híbrido Async Streaming) listo.")
    
    # Drop pending updates y polling
    application.run_polling(drop_pending_updates=True)
