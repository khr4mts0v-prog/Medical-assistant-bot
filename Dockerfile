# Берем легковесный Python
FROM python:3.11-slim

# Обновляем пакеты и ставим Tesseract + русскую модель
RUN apt-get update && \
    apt-get install -y tesseract-ocr tesseract-ocr-rus poppler-utils && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Создаем рабочую директорию
WORKDIR /app

# Копируем файлы бота
COPY main.py requirements.txt ./

# Устанавливаем Python-зависимости
RUN pip install --no-cache-dir -r requirements.txt

# Устанавливаем переменные для Tesseract
ENV TESSDATA_PREFIX=/usr/share/tesseract-ocr/5/tessdata/

# Запуск бота
CMD ["python", "main.py"]
