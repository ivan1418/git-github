FROM python:3.10-slim

# Evita que Python guarde logs en buffer
ENV PYTHONUNBUFFERED=1

# Instalamos dependencias mínimas de sistema por si alguna librería necesita compilar
RUN apt-get update && apt-get install -y \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copiamos primero requirements para usar el cache de capas de Docker
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiamos el resto del código
COPY . .

# Puerto para Render
EXPOSE 10000

# Usamos la variable de entorno PORT que Render asigna automáticamente
CMD ["python", "app.py"]
