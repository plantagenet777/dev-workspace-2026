#!/bin/bash

echo "🚢 Starting ICL Pump Monitor Deployment..."

# 1. Сборка Docker-образа
docker build -t icl-predictive-pumps:v1.0 .

# 2. Остановка старого контейнера, если он есть
docker stop icl_monitor || true
docker rm icl_monitor || true

# 3. Запуск нового контейнера с монтированием сертификатов
# Мы используем --restart always для отказоустойчивости
docker run -d \
  --name icl_monitor \
  --restart always \
  -v /etc/icl/certs:/app/certs:ro \
  -v ./logs:/app/logs \
  --env-file .env \
  icl-predictive-pumps:v1.0

echo "✅ Deployment finished. System is running in background."