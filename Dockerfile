FROM python:3.12-slim

# Отключаем буферизацию вывода Python
ENV PYTHONUNBUFFERED=1
ENV PORT=7860

WORKDIR /app

# Установка зависимостей
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копирование исходного кода проекта
COPY . .

# Запуск бота
CMD ["python", "bot.py"]
