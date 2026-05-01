# ===================================================
# 🏛️ BOZI-BOT: EL CEREBRO HÍBRIDO ASINCRÓNICO DE ELITE
# Versión: 3.8 (DIAGNOSTICS + DASHBOARD PRO + SHIELD)
# ===================================================

# ... (imports se mantienen igual) ...

# ---------------------------------------------------
# ⚙️ OPTIMIZACIÓN DE MEMORIA VOLÁTIL (CACHÉ)
# ---------------------------------------------------
_cache = {"rules": None, "self": None, "last_load": 0}

def get_optimized_content(key, filepath):
    now = time.time()
    # Recargar cada 5 minutos para ahorrar I/O
    if _cache[key] is None or (now - _cache["last_load"] > 300):
        _cache[key] = get_file_content(filepath)
        _cache["last_load"] = now
    return _cache[key]

# ---------------------------------------------------
# 🛠️ ACTION LAYER (MEJORADO CON DELETE)
# ---------------------------------------------------

async def manage_actions(chat_id, text):
    low_text = text.lower()
    # Agregamos soporte explícito para borrar
    if "borrá" in low_text or "eliminá" in low_text:
        try:
            # Borra la última tarea pendiente
            res = supabase.table("scheduled_tasks").delete().eq("chat_id", int(chat_id)).eq("status", "pending").order("created_at", desc=True).limit(1).execute()
            return "🗑️ Tarea eliminada de la base de datos, Iván."
        except Exception as e:
            return f"❌ No pude borrar la tarea: {e}"
    
    # ... (resto de manage_actions se mantiene igual) ...
    return None

# ---------------------------------------------------
# 🌐 DASHBOARD PRO (HTML + CSS)
# ---------------------------------------------------

class DashboardHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        
        # Un Dashboard más profesional con estilo
        html = f"""
        <html>
        <head>
            <title>Bozi-Panel V3.8</title>
            <style>
                body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: #1a1a1a; color: #eee; padding: 40px; }}
                .card {{ background: #252525; padding: 20px; border-radius: 10px; border-left: 5px solid #007bff; }}
                h1 {{ color: #007bff; }}
                .status {{ font-weight: bold; color: #28a745; }}
            </style>
        </head>
        <body>
            <h1>🏛️ Bozi-bot Orchestrator</h1>
            <div class="card">
                <p>Status: <span class="status">ONLINE</span></p>
                <p>Versión: 3.8.0</p>
                <p>Infraestructura: Render / Supabase</p>
                <hr style="border: 0.5px solid #444;">
                <p><b>Acceso Directo:</b> <a href="{SUPABASE_URL}" target="_blank" style="color: #007bff;">Base de Datos</a></p>
            </div>
        </body>
        </html>
        """
        self.wfile.write(html.encode())

# ... (handle_message y handle_photo se mantienen igual) ...

if __name__ == "__main__":
    # setup...
    logging.info("🚀 Bozi-bot V3.8 (Shield & Dashboard) Iniciado.")
    app.run_polling(drop_pending_updates=True)
