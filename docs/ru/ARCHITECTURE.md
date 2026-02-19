# Архитектура системы PdM (предиктивное обслуживание)

Краткое описание компонентов и потоков данных. Диаграммы в формате Mermaid.

---

## 1. Обзор высокого уровня

```mermaid
flowchart TB
    subgraph Sources["Источники данных"]
        MQTT[MQTT брокер\nТопик телеметрии]
        SIM[simulate_failure.py\nЦифровой двойник]
    end

    subgraph Engine["Ядро PdM (app)"]
        BUF[Буфер телеметрии\n30 сэмплов]
        VAL[Валидатор телеметрии\nмин/макс диапазоны]
        PROC[DataProcessor\nButterworth + батч]
        FEAT[FeatureExtractor\nRMS, Crest, Kurtosis, ...]
        PRED[PumpPredictor\nRF модель + правила]
        RULES[app/rules.py\nправила CRITICAL/WARNING]
        CSV[CSV Logger\nочередь + повторы]
    end

    subgraph Outputs["Выходы"]
        MQTT_A[MQTT топик алертов]
        CSV_T[telemetry_history.csv]
        CSV_A[alerts_history.csv]
        TG[Telegram]
    end

    MQTT --> BUF
    SIM --> BUF
    BUF --> VAL
    VAL --> PROC
    PROC --> FEAT
    FEAT --> PRED
    PRED --> RULES
    RULES --> PRED
    PRED --> CSV
    PRED --> MQTT_A
    CSV --> CSV_T
    CSV --> CSV_A
    PRED --> TG
```

---

## 2. Поток данных (рабочий движок)

```mermaid
sequenceDiagram
    participant MQTT as MQTT брокер
    participant App as main_app.py
    participant Val as Валидатор
    participant Proc as DataProcessor
    participant Pred as Predictor
    participant Rules as rules.py
    participant CSV as csv_logger
    participant Out as MQTT/Telegram

    MQTT->>App: сообщения телеметрии
    App->>App: buffer.append (макс 30)
    Note over App: каждые MQTT_BATCH_SIZE сообщений
    App->>Val: validate_telemetry_batch(buffer)
    Val-->>App: OK / INVALID_RANGE
    App->>Proc: prepare_batch(buffer)
    Proc->>Proc: FeatureExtractor.get_feature_vector
    Proc-->>App: признаки, статус
    App->>Pred: predict(features, latest_telemetry)
    Pred->>Pred: сглаживание, ML инференс
    Pred->>Rules: RuleContext + RULES.evaluate()
    Rules-->>Pred: status, reason, display_prob
    Pred->>CSV: append_telemetry (очередь)
    Pred-->>App: status, prob
    App->>Out: публикация отчёта, Telegram при CRITICAL/WARNING
    App->>CSV: append_alert (очередь)
    CSV->>CSV: фоновая запись с повтором
```

---

## 3. Формат сообщения телеметрии (MQTT)

Каждое сообщение в топике телеметрии (`Config.TOPIC_TELEMETRY`) — один JSON-объект с числовыми полями:

```json
{
  "vib_rms": 2.5,
  "vib_crest": 3.1,
  "vib_kurtosis": 3.2,
  "current": 45.0,
  "pressure": 6.0,
  "temp": 38.0,
  "cavitation_index": 0.05
}
```

Эту схему используют:

- `app/main_app.py` — буферизует телеметрию и передаёт в `DataProcessor.prepare_batch()`.
- `app/data_processor.py` — валидирует через `validate_telemetry_batch()` и вызывает `FeatureExtractor`.
- `emulator.py` и `publish_mqtt_telemetry.py` — издатели телеметрии в том же формате.

---

## 4. Симуляция (цифровой двойник)

```mermaid
flowchart LR
    subgraph Sim["simulate_failure.py"]
        H[health 0..1]
        EV[Редкие события:\nудар камня, забивка, кавитация, ...]
        GEN[degradation_to_means\n+ шум]
        BUF30[30 сэмплов]
        PROC[DataProcessor]
        PRED[Predictor]
        SHUT[Проверки останова:\nВибрация, Debris,\nChoked, Cavitation,\nПерегрев]
    end

    H --> EV
    EV --> GEN
    GEN --> BUF30
    BUF30 --> PROC
    PROC --> PRED
    PRED --> SHUT
    SHUT --> H
```

См. [скриншоты симуляции](#5-скриншоты-симуляции).

---

## 5. Скриншоты симуляции

Пример вывода цифрового двойника (`make simulate`). Файлы в репозитории: `screenshots/`.

| Момент | Скриншот |
|--------|----------|
| Старт CLI / нормальный режим | ![simulate_cli_01](../../screenshots/simulate_cli_01.png) |
| Буфер / батч | ![simulate_cli_02](../../screenshots/simulate_cli_02.png) |
| Зона WARNING | ![simulate_cli_03](../../screenshots/simulate_cli_03.png) |
| CRITICAL / кавитация | ![simulate_cli_04](../../screenshots/simulate_cli_04.png) |
| Сообщение об останове | ![simulate_cli_05](../../screenshots/simulate_cli_05.png) |
| RESTART после останова | ![simulate_cli_06](../../screenshots/simulate_cli_06.png) |
| Деградация / обслуживание | ![simulate_cli_07](../../screenshots/simulate_cli_07.png) |
| Забивка / перегрев | ![simulate_cli_08](../../screenshots/simulate_cli_08.png) |
| Итог / выход | ![simulate_cli_09](../../screenshots/simulate_cli_09.png) |

Графики из `plot_monitoring.py` (зоны вибрации и риск):

| График | Скриншот |
|--------|----------|
| Figure 1 | ![Figure_1](../../screenshots/Figure_1.png) |
| Figure 2 | ![Figure_2](../../screenshots/Figure_2.png) |

---

## 6. Модули и ответственность

| Модуль | Назначение |
|--------|------------|
| **app/main_app.py** | MQTT-клиент, буфер, вызов пайплайна, реконнект с backoff, алерт при длительном отсутствии сообщений |
| **app/telemetry_validator.py** | Проверка мин/макс телеметрии перед DSP/ML |
| **app/data_processor.py** | Фильтр Butterworth, подготовка батча, вызов FeatureExtractor |
| **app/feature_extractor.py** | Расчёт признаков (vib_rms, vib_crest, vib_kurtosis, current, pressure, cavitation_index, temp, temp_delta) |
| **app/predictor.py** | Загрузка модели/скалера, сглаживание риска, оркестрация правил, запись в CSV через очередь |
| **app/rules.py** | Классы правил (Mechanical, Cavitation, Choked, Degradation, Temperature, Overload, Pressure, Air, Vibration, Interlock, FinalCleanup) |
| **app/csv_logger.py** | Очередь записи CSV с повтором при ошибке |
| **app/notifier.py** | Отправка алертов в Telegram |
| **app/healthcheck.py** | Проверка конфига и артефактов; exit 0/1 для Docker/CI |
| **config/config.py** | Пороги, топики, пути, флаги TLS |
| **config/validation.py** | Валидация конфига при старте; используется healthcheck |

---

## 7. Связанные документы

- [system_trigger_scenarios.md](system_trigger_scenarios.md) — все сценарии срабатывания и пороги
- [RULE_PRIORITY_AND_HYSTERESIS.md](RULE_PRIORITY_AND_HYSTERESIS.md) — приоритет правил и гистерезис
- [ML_REPORT.md](ML_REPORT.md) — ML-модель, метрики, важность признаков
