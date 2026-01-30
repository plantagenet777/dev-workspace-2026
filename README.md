# ICL Pump Monitor: Predictive Maintenance System

![Python](https://img.shields.io/badge/Python-3.11-blue)
![Docker](https://img.shields.io/badge/Docker-Enabled-green)
![Security](https://img.shields.io/badge/Security-TLS_v1.2-red)

## Обзор проекта

Система мониторинга промышленных насосов (IIoT) для активов **ICL Rotem** (центробежные насосы Warman). Потребляет телеметрию по MQTT, применяет цифровую обработку сигналов и машинное обучение для прогнозирования отказов до их возникновения.

### Основные возможности

- **Обработка сигналов** — фильтр Баттерворта для выделения частот подшипников из шума 6кВ привода
- **ML-анализ** — классификатор Random Forest для детекции кавитации, износа подшипников, утечек
- **Безопасность** — TLS v1.2 для MQTT, секреты через переменные окружения
- **Smoke-тесты** — проверка модели и окружения перед запуском

---

## Структура проекта

```
├── app/                    # Ядро приложения
│   ├── main_app.py         # MQTT-клиент и конвейер анализа
│   ├── data_processor.py   # Обработка и подготовка батчей
│   ├── feature_extractor.py# Извлечение признаков
│   ├── predictor.py        # Инференс модели
│   └── notifier.py         # Telegram-алерты
├── config/
│   └── config.py           # Конфигурация
├── models/                 # Артефакты ML (.joblib)
├── certs/                  # TLS-сертификаты
├── tests/
│   ├── test_smoke.py       # Проверка готовности системы
│   └── test_dsp.py         # Тесты DSP
├── train_and_save.py       # Обучение модели
├── simulate_failure.py     # Демо без MQTT
├── requirements.txt
├── Dockerfile
└── docker-compose.yml
```

---

## Быстрый старт

### 1. Установка зависимостей

```bash
python -m venv venv
source venv/bin/activate   # Linux/macOS
# или: venv\Scripts\activate  # Windows
pip install -r requirements.txt
```

### 2. Конфигурация

```bash
cp .env.example .env
# Отредактируйте .env: MQTT_BROKER, MQTT_PORT, TG_TOKEN, TG_CHAT_ID
```

### 3. Обучение модели

```bash
PYTHONPATH=. python train_and_save.py
```

### 4. Проверка работоспособности

```bash
# Все тесты
PYTHONPATH=. pytest tests/ -v

# Smoke-тест
PYTHONPATH=. python tests/test_smoke.py

# Демо конвейера (без MQTT)
PYTHONPATH=. python simulate_failure.py
```

### 5. Запуск приложения

**С TLS** (нужны сертификаты в `certs/`):

```bash
PYTHONPATH=. python app/main_app.py
```

**Без TLS** (локальная разработка, порт 1883):

```bash
MQTT_USE_TLS=false MQTT_PORT=1883 PYTHONPATH=. python app/main_app.py
```

---

## Переменные окружения

| Переменная    | Описание                    | По умолчанию   |
|---------------|-----------------------------|----------------|
| MQTT_BROKER   | Адрес MQTT-брокера          | 10.20.30.45    |
| MQTT_PORT     | Порт (8883 TLS, 1883 plain) | 8883           |
| MQTT_USE_TLS  | Использовать TLS            | true           |
| PUMP_ID       | Идентификатор насоса        | WARMAN_04      |
| TG_TOKEN      | Токен Telegram-бота         | —              |
| TG_CHAT_ID    | ID чата для алертов         | —              |
| CERT_DIR      | Путь к папке сертификатов   | certs/         |

---

## Docker

```bash
# Сборка и запуск
docker-compose up --build

# Или через скрипт
chmod +x deploy.sh
./deploy.sh
```

Перед запуском `main_app.py` контейнер выполняет `test_smoke.py`. Сертификаты монтируются в `/app/certs`.

---

## Безопасность

- **Шифрование** — MQTT по порту 8883 с TLS v1.2
- **Секреты** — только через переменные окружения, не в образе
- **Сертификаты** — `ca.crt`, `client.crt`, `client.key` в `certs/`

---

## Технологии

- **Python 3.11** — язык
- **Scikit-learn, Pandas, NumPy, SciPy** — ML и обработка сигналов
- **Paho-MQTT** — протокол MQTT(S)
- **Docker** — контейнеризация

---

## Разработчик

Dmitrii German / ICL Reliability Team
