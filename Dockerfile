FROM python:3.12-slim

WORKDIR /app

# Системные зависимости для openpyxl и compilations
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Зависимости
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Код
COPY backend/ ./backend/
COPY frontend/ ./frontend/

# БД и uploads будут монтироваться как volume — но создадим папки на всякий случай
RUN mkdir -p /app/uploads /app/data

# Порт берётся из переменной окружения PORT (Railway передаёт автоматически).
# Локально без PORT — используется 8000.
ENV PORT=8000
EXPOSE 8000

# PYTHONPATH чтобы импорты "app.xxx" работали
ENV PYTHONPATH=/app/backend
ENV DB_PATH=/app/data/oati.db

WORKDIR /app/backend

# Shell-форма, чтобы $PORT раскрылся
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
