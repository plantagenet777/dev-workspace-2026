# Используем стабильный образ
FROM python:3.11-slim

# Установка системных зависимостей для сборки (если понадобятся для scipy/numpy)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Сначала копируем зависимости для кэширования слоев
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем код приложения
COPY . .

# Создаем папки для логов и данных
RUN mkdir -p logs data certs models

# Обучаем модель при сборке образа (если models/ пуст)
RUN python train_and_save.py

# Указываем Python не создавать файлы .pyc внутри контейнера
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Запускаем проверку и основное приложение
CMD ["sh", "-c", "python tests/test_smoke.py && python app/main_app.py"]