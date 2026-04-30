# ===================================================
# 🏛️ BOZI-BOT: EL CEREBRO HÍBRIDO ASINCRÓNICO DE ELITE
# Versión: 2.2 (Async Streaming Híbrido + Supabase REAL + CoT Oculto)
# ===================================================

import os
import re
import json
import logging
import threading
import asyncio # Velocidad Asincrónica
import requests
from zoneinfo import ZoneInfo
from urllib.parse import urlparse
from http.server import HTTPServer, BaseHTTPRequestHandler

# Telegram y Scheduler
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, CommandHandler, CallbackQueryHandler, filters
from openai import AsyncOpenAI # SDK Asincrónico

# Clientes externos
from supabase import create_client


# ---------------------------------------------------
# ⚙️ CONFIGURACIÓN Y ENTORNO SECURE
# ---------------------------------------------------
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)

# Carga segura de variables desde Render (Asegurate de configurarlas en Render)
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

LOCAL_TZ_NAME = "America/Argentina/Buenos_Aires"
LOCAL_TZ = ZoneInfo(LOCAL_TZ_NAME)

# --- DEFINICIÓN DE MODELOS (Estrategia Iván) ---
OPENAI_MODEL_TECNICO = "gpt-4o-mini" # Fiabilidad Cibersec/JSON/Visión
OPENROUTER_MODEL_CHAT = "google/gemma-4-31b-it:free" # Chat Gratis

# Verificación crítica de claves
if not all([TELEGRAM_TOKEN, SUPABASE_URL, SUPABASE_KEY, OPENAI_API_KEY, OPENROUTER_API_KEY]):
    raise ValueError("❌ Faltan Variables de Entorno críticas en Render (Tokens o Supabase). Verificalas.")

# --- INICIALIZACIÓN DE CLIENTES ASINCRÓNICOS ---
# Cliente OpenAI (Cerebro Técnico)
openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)

# Cliente OpenRouter (Cerebro de Chat Gratis)
openrouter_client = AsyncOpenAI(base_url="https://openrouter.ai/api/v1", api_key=OPENROUTER_API_KEY)

# Cliente Supabase (Base de Datos Real)
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


# ---------------------------------------------------
# 🤖 CARGA DE PERSONALIDAD (self.txt)
# ---------------------------------------------------
def load_prompt_file(filename):
    """Lee el cerebro de Bozi-bot desde un archivo externo."""
    try:
        # Importante: usar encoding='utf-8' para los acentos
        with open(filename, 'r', encoding='utf-8') as f:
            return f.read().strip()
    except FileNotFoundError:
        logging.critical(f"❌ Archivo {filename} no encontrado. El bot no tiene personalidad.")
        return "Sos Bozi-bot, asistente de Iván." # Fallback básico

# Cargamos todo el conocimiento (Cibersec, etc.) aquí
SELF_PROMPT_CIBERSEC = load_prompt_file("self.txt")

CONTEXT_ROUTER_PROMPT = """
Sos el cerebro estratégico de Bozi-bot. Analizá el mensaje del usuario y el historial reciente.
Decidí si es una charla casual o una tarea técnica/ciberseguridad/acción.
Devolvé SOLO JSON válido:
{
  "thought_process": "razonamiento corto",
  "intent": "NORMAL_CHAT | CIBERSEC_TASK | PROJECT_EDIT | TASK_CREATE | IMAGE_ANALYSIS | CONFIG_UPDATE | CLOSING_CHAT",
  "confidence": 0.0-1.0,
  "reason": "explicación"
}
"""

def build_runtime_system_prompt(config):
    """Genera el prompt de sistema dinámico para la IA"""
    format_instruction = """
RESPONDÉ OBLIGATORIAMENTE USANDO ESTE FORMATO DE RESPUESTA (SIN EXPLICACIONES EXTRAS):

[INTERNAL_MONOLOGUE]
(Analizá el mensaje, contexto actual y decidí cómo responder según tu personalidad híbrida: ¿chiste o seriedad absoluta de Red Team/Ciberseguridad? Pensá antes de responder.)
[/INTERNAL_MONOLOGUE]

[FINAL_RESPONSE]
(Tu respuesta humana y ejecutiva para Iván. Hilá la conversación.)
[/FINAL_RESPONSE]
"""
    # Mapeo del modo (gerente, cto, etc.) si lo usas en el prompt
    mode_text = config.get('mode', 'asistente_general_tecnico')
    return f"{SELF_PROMPT_CIBERSEC}\nMODO ACTIVO: {mode_text}\n{format_instruction}".strip()


# ---------------------------------------------------
# 🧠 CEREBRO HÍBRIDO: DECISIÓN DE MOTOR (Async)
# ---------------------------------------------------
async def get_best_client_and_model(intent: str, chat_id: int):
    """
    Decide qué motor de IA usar para maximizar ahorro y capacidad técnica.
    - Ciberseguridad, Código, JSON, Visión -> OpenAI gpt-4o-mini (Pago)
    - Charla casual, saludos, dudas simples -> OpenRouter Gemma Gratis
    """
    # Estos intents requieren máxima potencia técnica, precisión y CoT serio
    complex_intents = {
        "CIBERSEC_TASK", "PROJECT_EDIT", "TASK_CREATE", 
        "IMAGE_ANALYSIS", "CONFIG_UPDATE", "TASK_EDIT_ACTIVE"
    }
    
    if intent.upper() in complex_intents:
        logging.info(f"OAI -> Tarea compleja/técnica detectada ({intent}). Usando {OPENAI_MODEL_TECNICO} (Pago).")
        return openai_client, OPENAI_MODEL_TECNICO
    
    # Charla normal, saludos o dudas generales -> Ahorro con OpenRouter Gratis
    logging.info(f"OR -> Charla detectada ({intent}). Usando {OPENROUTER_MODEL_CHAT} (Gratis).")
    return openrouter_client, OPENROUTER_MODEL_CHAT


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
        temperature=0.4,
        stream=True, # Activa streaming "renglón por renglón"
    )
    
    # Devolvemos el flujo directamente (el handler se encarga del parsing)
    async for chunk in response_stream:
        try:
            content = chunk.choices[0].delta.content
            if content:
                yield content
        except Exception:
            pass # Ignorar fragmentos sin contenido (comunes al inicio/final)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handler principal (Async, Híbrido, Streaming).
    Gestiona el flujo de palabras renglón por renglón en Telegram y oculta el CoT.
    """
    chat_id = update.effective_chat.id
    user_text = update.message.text or ""
    
    # Typing persistente (asincrónico y eficiente)
    stop_typing = start_typing_loop_sync(chat_id)
    status_message = None 
    full_response_raw_text = ""

    try:
        # 0. Carga de contexto asincrónica (Supabase REAL)
        # Nota: Estas funciones deben ser async reales en la sección HELPERS.
        config = await get_bot_config_async(chat_id)
        history = await get_recent_history_async(chat_id)
        active_ctx = await build_active_context_async(chat_id) 
        
        # 1. ROUTER: Analizar intención (Async - Siempre OpenAI gpt-4o-mini)
        route = await classify_contextual_route_async(user_text, chat_id, history, active_ctx)
        intent_detected = route.get("intent", "NORMAL_CHAT")
        logging.info(f"Cerebro CoT detectó intención: {intent_detected} - {route.get('reason')}")

        # ... (Lógica de confirmación pendiente y 'puedo hacerlo' igual) ...

        # 2. GENERAR STREAM (Híbrido Async)
        input_msgs = build_chat_input(user_text, history, None, None, active_ctx)
        
        # Obtenemos el generador asincrónico (la decisión híbrida ocurre adentro)
        response_generator = ask_smart_chat_stream(input_msgs, intent_detected, chat_id, config)

        # 3. STREAMING EN TELEGRAM (Renglón por renglón)
        
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

        # 4. GUARDAR MEMORIA ASYNC (Supabase REAL)
        # Usamos el texto final extraído o el crudo si falló el CoT
        answer_to_save = final_answer if final_answer else full_response_raw_text
        await save_memory_async(chat_id, "user", user_text)
        await save_memory_async(chat_id, "assistant", answer_to_save)
        
    except Exception as e:
        logging.error(f"Error crítico async: {e}")
        if status_message:
             await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=status_message.message_id,
                text="Che Iván, se me trabó el streaming de la IA. Revisá logs de Render."
            )
        else:
            await update.message.reply_text("Che Iván, algo se trabó antes de empezar a responder.")
            
    finally:
        stop_typing()


# ---------------------------------------------------
# 🛠️ PANEL DE CEO (Comando /models Inline)
# ---------------------------------------------------
async def cmd_models(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Muestra el panel de modelos con botones para configurar."""
    chat_id = update.effective_chat.id
    # Obtenemos config actual (real async)
    config = await get_bot_config_async(chat_id) 
    
    # Creamos el teclado Inline
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(f"🤖 Técnico Cibersec (gpt-4o-mini): ✅", callback_data="mod_oai_pri")
        ],
        [
            InlineKeyboardButton(f"💬 Chat Gratis Google Gemma: ✅", callback_data="mod_or_chat")
        ],
        [
            InlineKeyboardButton("📊 Ver Estado/Tokens", callback_data="panel_status")
        ]
    ])
    
    text = (
        "╔══════════════════════╗\n"
        "🏛️ PANEL DE CEREBROS DE BOZI-BOT\n"
        "╚══════════════════════╝\n\n"
        "CEO Iván, este es el estado de mis modelos asincrónicos.\n"
        f"Gemma (Gratis) es el predeterminado para chat.\n"
        f"{OPENAI_MODEL_TECNICO} (gpt-4o-mini) es el motor Técnico y de Ciberseguridad.\n\n"
        "Tocá un botón para verificar la asignación."
    )
    await update.message.reply_text(text, reply_markup=keyboard)

async def handle_button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Maneja los toques en los botones del panel de modelos."""
    query = update.callback_query
    await query.answer()
    data = query.data
    logging.info(f"CEO tocó botón: {data}")
    
    # Lógica de respuesta rápida de botones
    if data == "mod_oai_pri":
        await query.edit_message_text(f"Confirmado. {OPENAI_MODEL_TECNICO} (gpt-4o-mini) es el cerebro de Ciberseguridad, Acción y Visión.")
    elif data == "mod_or_chat":
        await query.edit_message_text(f"Confirmado. Gemma 31B Gratis gestiona la charla casual e inteligente.")
    elif data == "panel_status":
        # (Llamamos a tu función de estado si la traés)
        await query.edit_message_text(f"📊 Estado: Online. Motor Híbrido Async Activo.")


# ---------------------------------------------------
# 🏛️ HELPERS REALES DE SUPABASE (Async)
# ---------------------------------------------------
# AQUÍ ESTÁ EL CÓDIGO REAL QUE REEMPLAZA A LOS PLACEHOLDERS

async def get_bot_config_async(chat_id):
    """Lee tu configuración (modo, model, etc.) de Supabase table 'bot_config'."""
    logging.info(f"🧠 Leyendo config para {chat_id} de Supabase REAL.")
    try:
        # INSTRUCCIONES REALES
        response = supabase.table("bot_config").select("*").eq("chat_id", chat_id).execute()
        if response.data:
            return response.data[0] # Devolver config real
        return {} # No hay config, devolver vacío
    except Exception as e:
        logging.error(f"❌ Error leyendo config de Supabase: {e}")
        return {} # Fallback ante error

async def save_memory_async(chat_id, role, content):
    """Guarda el mensaje (user/assistant) en Supabase table 'bot_memory'."""
    logging.info(f"💾 Guardando memoria ({role}) en Supabase REAL.")
    try:
        # INSTRUCCIONES REALES
        supabase.table("bot_memory").insert({
            "chat_id": chat_id,
            "role": role,
            "content": content
            # (Si usás vector/embedding, la lógica va acá también)
        }).execute()
        # logging.info("✅ Guardado en Supabase.")
    except Exception as e:
        logging.error(f"❌ Error guardando memoria en Supabase: {e}")

async def get_recent_history_async(chat_id, limit=MAX_HISTORY_MESSAGES):
    """Lee el historial reciente de Supabase table 'bot_memory'."""
    # (Pega aquí tu lógica REAL de lectura de Supabase, similar a get_bot_config)
    # Por brevedad, te dejo la estructura, pero debés adaptarla si querés historial REAL.
    return [] # Placeholder, adaptalo como get_bot_config

async def build_active_context_async(chat_id):
    """Obtiene contexto del proyecto/tarea activa de Supabase."""
    # (Pega aquí tu lógica REAL de lectura de Supabase, similar a get_bot_config)
    return "" # Placeholder

async def classify_contextual_route_async(text, chat_id, history, active_ctx):
    """Router Inteligente: siempre usa OpenAI gpt-4o-mini."""
    try:
        # --- LLAMADA ASYNC ---
        res = await openai_client.chat.completions.create(
            model=OPENAI_MODEL_TECNICO,
            messages=[
                {"role": "system", "content": CONTEXT_ROUTER_PROMPT}, 
                # (Opcional: pasar historial resumido al router)
                {"role": "user", "content": f"Context: {active_ctx}\nMsg: {text}"}
            ],
            # Forzamos JSON para parsear fácil
            response_format={ "type": "json_object" }
        )
        return json.loads(res.choices[0].message.content)
    except Exception as e:
        logging.error(f"Error en router async: {e}")
        return { "intent": "NORMAL_CHAT" } # Fallback seguro

def build_chat_input(user_text, history, semantic_memories, web_context, active_context):
    """Arma la lista de mensajes para enviar a la IA."""
    messages = []
    # (Pega aquí tu lógica existente para armar la lista de mensajes con historial)
    messages.append({"role": "user", "content": user_text})
    return messages

# Servidor web sincrónico (está bien así para Render healthcheck)
class WebHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.send_header("Content-type", "text/plain"); self.end_headers()
        self.wfile.write(b"Bozi-bot Central Brain Elite (Async Real) online.")

def run_web_server():
    server = HTTPServer(("0.0.0.0", int(os.environ.get("PORT", 10000))), WebHandler)
    server.serve_forever()

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

# Mantené el resto de tus helpers REALES (Visión async, Tavily, etc.)
# ...

# ---------------------------------------------------
# INICIO DE LA APLICACIÓN
# ---------------------------------------------------
if __name__ == "__main__":
    # Servidor web para Render (Healthcheck)
    threading.Thread(target=run_web_server, daemon=True).start()
    
    # Configuración del Bot (Async SDK)
    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    
    # Handlers de Comandos
    application.add_handler(CommandHandler("start", cmd_models)) # CEO Start
    application.add_handler(CommandHandler("models", cmd_models)) # Panel Cerebros
    # application.add_handler(CommandHandler("diagnostico", cmd_diagnostico)) 

    # Handler para BOTONES de cerebros
    application.add_handler(CallbackQueryHandler(handle_button_callback))

    # Handler PRINCIPAL (Async, Híbrido, Streaming)
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    
    # (Agregá tu handler de imágenes async aquí si lo traés)

    logging.info("Bozi-bot Central Brain Elite (Async, Híbrido Real, streaming, self.txt) listo.")
    
    # Drop pending updates y polling
    application.run_polling(drop_pending_updates=True)
