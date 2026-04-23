# Usamos una versión estable y liviana de Python
FROM python:3.10-slim

# Evita que Python genere archivos .pyc y asegura logs en tiempo real
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Definimos el directorio de trabajo
WORKDIR /app

# Instalamos dependencias mínimas de sistema necesarias para compilar algunas librerías
RUN apt-get update && apt-get install -y \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Actualizamos pip antes de instalar nada
RUN pip install --no-cache-dir --upgrade pip

# Copiamos el archivo de requerimientos
COPY requirements.txt .

# Instalamos las librerías forzando la resolución de dependencias que definimos
RUN pip install --no-cache-dir --force-reinstall -r requirements.txt

# Copiamos el resto del código del bot (app.py)
COPY . .

# Exponemos el puerto que usa Render por defecto
EXPOSE 10000

# Comando para arrancar Bozi-bot
CMD ["python", "app.py"]
