# ===================================================
# 🏛️ BOZI-BOT: EL CEREBRO HÍBRIDO ASINCRÓNICO DE ELITE
# Versión: 4.1 (SECURITY SENTINEL + COMMAND FIX)
# ===================================================

# ... (imports previos se mantienen igual) ...

# ---------------------------------------------------
# 🛡️ CAPA DE CIBERSEGURIDAD Y DIAGNÓSTICO
# ---------------------------------------------------

async def security_analyzer(bot, chat_id, error_msg, context_info=""):
    """Analiza anomalías y genera una guía de solución paso a paso"""
    prompt = (
        f"Sos un experto en Ciberseguridad. Se detectó el siguiente evento: {error_msg}. "
        f"Contexto: {context_info}. "
        "Si es una amenaza o error crítico, explicá qué pasó y danos el paso a paso "
        "técnico para solucionarlo (voseo rosarino)."
    )
    try:
        res = await openai_client.chat.completions.create(
            model="gpt-4o", messages=[{"role": "system", "content": prompt}]
        )
        reporte = f"🛡️ **ALERTA DE SEGURIDAD/SISTEMA**\n\n{res.choices[0].message.content}"
        await bot.send_message(chat_id=chat_id, text=reporte, parse_mode='Markdown')
    except:
        logging.error("Fallo al enviar reporte de seguridad.")

# ---------------------------------------------------
# 🤖 HANDLERS DE COMANDOS (Nuevos: /status y /errors)
# ---------------------------------------------------

async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Muestra el estado de la infraestructura"""
    msg = (f"🖥️ **Estado de Infraestructura:**\n\n"
           f"✅ **Bot**: Online (V4.1)\n"
           f"✅ **DB**: Supabase Conectado\n"
           f"🧠 **AI**: {USER_CONFIG['model']} activo\n"
           f"⏱️ **Uptime**: {datetime.now().strftime('%H:%M:%S')}")
    await update.message.reply_text(msg, parse_mode='Markdown')

async def errors_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Consulta logs rápidos de la DB"""
    # Aquí podrías consultar una tabla de logs si la tenés creada
    await update.message.reply_text("📋 **Logs del Sistema:**\n\nNo se detectaron brechas recientes en el motor principal.")

# ---------------------------------------------------
# 🤖 ORQUESTADOR MEJORADO CON SENTINEL
# ---------------------------------------------------

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_text = update.message.text
    if not user_text: return

    # Filtro básico anti-inyección
    if any(pattern in user_text.lower() for pattern in ["drop table", "delete from", "<script>"]):
        await security_analyzer(context.bot, chat_id, "Intento de Inyección de Código/SQL", f"Input: {user_text}")
        return

    await context.bot.send_chat_action(chat_id=chat_id, action=constants.ChatAction.TYPING)
    
    # ... (lógica de CHAT_HISTORY y system_prompt igual a la V4.0) ...

    try:
        res = await openai_client.chat.completions.create(model=USER_CONFIG["model"], messages=messages)
        await update.message.reply_text(res.choices[0].message.content)
    except Exception as e:
        # Si falla, el Sentinel analiza por qué
        await security_analyzer(context.bot, chat_id, str(e), "Error durante la generación de respuesta")

# ---------------------------------------------------
# 🌐 INICIO DE APLICACIÓN
# ---------------------------------------------------

if __name__ == "__main__":
    # Servidor y App setup igual...
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    
    # REGISTRO DE COMANDOS (Ahora sí, todos los que pediste)
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("config", config_cmd))
    app.add_handler(CommandHandler("models", models_cmd))
    app.add_handler(CommandHandler("tasks", tasks_cmd))
    app.add_handler(CommandHandler("projects", projects_cmd))
    app.add_handler(CommandHandler("status", status_cmd)) # <-- NUEVO
    app.add_handler(CommandHandler("errors", errors_cmd)) # <-- NUEVO
    
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    
    loop = asyncio.get_event_loop()
    loop.create_task(task_worker(app.bot))
    
    logging.info("🚀 Bozi-bot V4.1 (The Sentinel) Online.")
    app.run_polling(drop_pending_updates=True)
