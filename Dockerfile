# Берём стабильный Python 3.11
FROM python:3.11-slim

# Создаём рабочую директорию
WORKDIR /app

# Копируем зависимости и устанавливаем их
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем код бота
COPY . .

# Команда запуска
CMD ["python", "main.py"]
