# PdM System Architecture (Predictive Maintenance)

Brief description of components and data flows. Diagrams use Mermaid.

---

## 1. High-Level Overview

```mermaid
flowchart TB
    subgraph Sources["Data Sources"]
        MQTT[MQTT Broker\nTelemetry Topic]
        SIM[simulate_failure.py\nDigital Twin]
    end

    subgraph Engine["PdM Engine (app)"]
        BUF[Telemetry Buffer\n30 samples]
        VAL[Telemetry Validator\nmin/max ranges]
        PROC[DataProcessor\nButterworth + batch]
        FEAT[FeatureExtractor\nRMS, Crest, Kurtosis, ...]
        PRED[PumpPredictor\nRF model + Rules]
        RULES[app/rules.py\nCRITICAL/WARNING rules]
        CSV[CSV Logger\nqueue + retry]
    end

    subgraph Outputs["Outputs"]
        MQTT_A[MQTT Alerts Topic]
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

## 2. Data Flow (Live Engine)

```mermaid
sequenceDiagram
    participant MQTT as MQTT Broker
    participant App as main_app.py
    participant Val as Validator
    participant Proc as DataProcessor
    participant Pred as Predictor
    participant Rules as rules.py
    participant CSV as csv_logger
    participant Out as MQTT/Telegram

    MQTT->>App: telemetry messages
    App->>App: buffer.append (max 30)
    Note over App: every MQTT_BATCH_SIZE msgs
    App->>Val: validate_telemetry_batch(buffer)
    Val-->>App: OK / INVALID_RANGE
    App->>Proc: prepare_batch(buffer)
    Proc->>Proc: FeatureExtractor.get_feature_vector
    Proc-->>App: features, status
    App->>Pred: predict(features, latest_telemetry)
    Pred->>Pred: smoothing, ML inference
    Pred->>Rules: RuleContext + RULES.evaluate()
    Rules-->>Pred: status, reason, display_prob
    Pred->>CSV: append_telemetry (queue)
    Pred-->>App: status, prob
    App->>Out: publish report, Telegram if CRITICAL/WARNING
    App->>CSV: append_alert (queue)
    CSV->>CSV: background write with retry
```

---

## 3. Telemetry Message Format (MQTT)

Each message on the telemetry topic (`Config.TOPIC_TELEMETRY`) is a single JSON object
with the following numeric fields:

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

This schema is used consistently by:

- `app/main_app.py` → buffers raw telemetry and passes it to `DataProcessor.prepare_batch()`.
- `app/data_processor.py` → validates telemetry via `validate_telemetry_batch()` and calls `FeatureExtractor`.
- `emulator.py` and `publish_mqtt_telemetry.py` → local/sandbox publishers that emit
  the same field set so that the engine behaves identically with real or simulated data.

---

## 4. Simulation (Digital Twin)

```mermaid
flowchart LR
    subgraph Sim["simulate_failure.py"]
        H[health 0..1]
        EV[Rare events:\nstone hit, choked, cavitation, ...]
        GEN[degradation_to_means\n+ noise]
        BUF30[30 samples]
        PROC[DataProcessor]
        PRED[Predictor]
        SHUT[Shutdown checks:\nVibration interlock, Debris,\nChoked, Cavitation,\nOvertemperature]
    end

    H --> EV
    EV --> GEN
    GEN --> BUF30
    BUF30 --> PROC
    PROC --> PRED
    PRED --> SHUT
    SHUT --> H
```

See [Simulation screenshots](#5-simulation-screenshots) for example CLI output.

---

## 5. Simulation screenshots

Example output of the digital twin (`make simulate`). Screenshots are in the repository under `screenshots/`.

| Step / moment | Screenshot |
|---------------|------------|
| CLI start / healthy run | ![simulate_cli_01](../../screenshots/simulate_cli_01.png) |
| Buffer / batch | ![simulate_cli_02](../../screenshots/simulate_cli_02.png) |
| WARNING zone | ![simulate_cli_03](../../screenshots/simulate_cli_03.png) |
| CRITICAL / cavitation | ![simulate_cli_04](../../screenshots/simulate_cli_04.png) |
| Shutdown message | ![simulate_cli_05](../../screenshots/simulate_cli_05.png) |
| RESTART after shutdown | ![simulate_cli_06](../../screenshots/simulate_cli_06.png) |
| Degradation / maintenance | ![simulate_cli_07](../../screenshots/simulate_cli_07.png) |
| Choked / overtemp | ![simulate_cli_08](../../screenshots/simulate_cli_08.png) |
| Summary / exit | ![simulate_cli_09](../../screenshots/simulate_cli_09.png) |

Optional plots from `plot_monitoring.py` (vibration zones and risk over time):

| Plot | Screenshot |
|------|------------|
| Figure 1 | ![Figure_1](../../screenshots/Figure_1.png) |
| Figure 2 | ![Figure_2](../../screenshots/Figure_2.png) |

---

## 6. Modules and Responsibilities

| Module | Purpose |
|--------|---------|
| **app/main_app.py** | MQTT client, buffer, pipeline invocation, reconnect with backoff, alert on prolonged message absence |
| **app/telemetry_validator.py** | Min/max validation of telemetry before DSP/ML |
| **app/data_processor.py** | Butterworth filter, batch preparation, FeatureExtractor invocation |
| **app/feature_extractor.py** | Feature computation (vib_rms, vib_crest, vib_kurtosis, current, pressure, cavitation_index, temp, temp_delta) |
| **app/predictor.py** | Model/scaler loading, risk smoothing, rule orchestration, telemetry logging to CSV (via queue) |
| **app/rules.py** | Rule classes (Mechanical, Cavitation, Choked, Degradation, Temperature, Overload, Pressure, Air, Vibration, Interlock, FinalCleanup) |
| **app/csv_logger.py** | CSV write queue with retry on error (telemetry_history, alerts_history) |
| **app/notifier.py** | Telegram alert delivery |
| **app/healthcheck.py** | Config and artifact validation; exit 0/1 for Docker/CI health checks |
| **config/config.py** | Thresholds, topics, paths, TLS flags |
| **config/validation.py** | Config validation at startup (fail-fast); used by healthcheck |

---

## 7. Related Documents

- [system_trigger_scenarios.md](system_trigger_scenarios.md) — all trigger scenarios and thresholds
- [RULE_PRIORITY_AND_HYSTERESIS.md](RULE_PRIORITY_AND_HYSTERESIS.md) — rule priority and hysteresis
- [ML_REPORT.md](ML_REPORT.md) — ML model, validation metrics, feature importance
