# Usamos la imagen liviana de Python 3.10
FROM python:3.10-slim

# Evita que Python genere archivos .pyc y asegura logs en tiempo real en Render
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Directorio de trabajo
WORKDIR /app

# Instalamos dependencias mínimas de sistema (compilación básica)
RUN apt-get update && apt-get install -y \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Actualizamos pip a la última versión
RUN pip install --no-cache-dir --upgrade pip

# Copiamos el archivo de requerimientos (punto crítico de las versiones)
COPY requirements.txt .

# Instalamos las librerías respetando el "punto de equilibrio" de versiones
RUN pip install --no-cache-dir -r requirements.txt

# Copiamos el código del bot
COPY . .

# Exponemos el puerto de Render
EXPOSE 10000

# Comando para arrancar el bot
CMD ["python", "app.py"]
