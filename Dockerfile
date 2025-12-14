# --- Используем лёгкий Python ---
FROM python:3.11-slim

# --- Устанавливаем зависимости ---
RUN apt-get update && apt-get install -y \
    tesseract-ocr tesseract-ocr-rus poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# --- Рабочая директория ---
WORKDIR /app

# --- Копируем файлы ---
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

# --- Устанавливаем переменные окружения по необходимости ---
ENV TESSDATA_PREFIX=/usr/share/tesseract-ocr/5/tessdata

# --- Запуск бота ---
CMD ["python", "main.py"]
