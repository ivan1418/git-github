FROM python:3.9-slim

# Evita que Python guarde logs en buffer (los ves en tiempo real)
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Exponemos el puerto de Render
EXPOSE 10000

CMD ["python", "app.py"]
