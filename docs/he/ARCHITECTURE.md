# ארכיטקטורת מערכת PdM (תחזוקה חיזויית)

תיאור קצר של רכיבים וזרימות נתונים. דיאגרמות ב-Mermaid.

---

## 1. סקירה ברמה גבוהה

```mermaid
flowchart TB
    subgraph Sources["מקורות נתונים"]
        MQTT[ברוקר MQTT\nנושא טלמטריה]
        SIM[simulate_failure.py\nתאום דיגיטלי]
    end

    subgraph Engine["מנוע PdM (app)"]
        BUF[מאגר טלמטריה\n30 דגימות]
        VAL[מאמת טלמטריה\nטווחי min/max]
        PROC[DataProcessor\nButterworth + batch]
        FEAT[FeatureExtractor\nRMS, Crest, Kurtosis, ...]
        PRED[PumpPredictor\nמודל RF + כללים]
        RULES[app/rules.py\nכללי CRITICAL/WARNING]
        CSV[CSV Logger\nתור + ניסיון חוזר]
    end

    subgraph Outputs["פלטים"]
        MQTT_A[נושא התראות MQTT]
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

## 2. זרימת נתונים (מנוע חי)

```mermaid
sequenceDiagram
    participant MQTT as ברוקר MQTT
    participant App as main_app.py
    participant Val as מאמת
    participant Proc as DataProcessor
    participant Pred as Predictor
    participant Rules as rules.py
    participant CSV as csv_logger
    participant Out as MQTT/Telegram

    MQTT->>App: הודעות טלמטריה
    App->>App: buffer.append (מקס 30)
    Note over App: כל MQTT_BATCH_SIZE הודעות
    App->>Val: validate_telemetry_batch(buffer)
    Val-->>App: OK / INVALID_RANGE
    App->>Proc: prepare_batch(buffer)
    Proc->>Proc: FeatureExtractor.get_feature_vector
    Proc-->>App: תכונות, סטטוס
    App->>Pred: predict(features, latest_telemetry)
    Pred->>Pred: החלקה, הסקת ML
    Pred->>Rules: RuleContext + RULES.evaluate()
    Rules-->>Pred: status, reason, display_prob
    Pred->>CSV: append_telemetry (תור)
    Pred-->>App: status, prob
    App->>Out: פרסום דוח, Telegram אם CRITICAL/WARNING
    App->>CSV: append_alert (תור)
    CSV->>CSV: כתיבה ברקע עם ניסיון חוזר
```

---

## 3. פורמט הודעת טלמטריה (MQTT)

כל הודעה בנושא הטלמטריה (`Config.TOPIC_TELEMETRY`) היא אובייקט JSON בודד עם השדות המספריים הבאים:

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

הסכמה הזו בשימוש עקבי על ידי:

- `app/main_app.py` — מאגר טלמטריה גולמית והעברה ל-`DataProcessor.prepare_batch()`.
- `app/data_processor.py` — אימות טלמטריה דרך `validate_telemetry_batch()` וקריאה ל-`FeatureExtractor`.
- `emulator.py` ו-`publish_mqtt_telemetry.py` — מפרסמים באותו סט שדות.

---

## 4. סימולציה (תאום דיגיטלי)

```mermaid
flowchart LR
    subgraph Sim["simulate_failure.py"]
        H[health 0..1]
        EV[אירועים נדירים:\nפגיעת אבן, חסימה, קוויטציה, ...]
        GEN[degradation_to_means\n+ רעש]
        BUF30[30 דגימות]
        PROC[DataProcessor]
        PRED[Predictor]
        SHUT[בדיקות עצירה:\nמגבלת רעידות, Debris,\nChoked, Cavitation,\nחום יתר]
    end

    H --> EV
    EV --> GEN
    GEN --> BUF30
    BUF30 --> PROC
    PROC --> PRED
    PRED --> SHUT
    SHUT --> H
```

ראה [צילומי מסך של הסימולציה](#5-צילומי-מסך-של-הסימולציה).

---

## 5. צילומי מסך של הסימולציה

דוגמת פלט של התאום הדיגיטלי (`make simulate`). צילומי המסך במאגר בתיקייה `screenshots/`.

| שלב / רגע | צילום מסך |
|-----------|------------|
| התחלת CLI / ריצה תקינה | ![simulate_cli_01](../../screenshots/simulate_cli_01.png) |
| מאגר / batch | ![simulate_cli_02](../../screenshots/simulate_cli_02.png) |
| אזור WARNING | ![simulate_cli_03](../../screenshots/simulate_cli_03.png) |
| CRITICAL / קוויטציה | ![simulate_cli_04](../../screenshots/simulate_cli_04.png) |
| הודעת עצירה | ![simulate_cli_05](../../screenshots/simulate_cli_05.png) |
| RESTART אחרי עצירה | ![simulate_cli_06](../../screenshots/simulate_cli_06.png) |
| התדרדרות / תחזוקה | ![simulate_cli_07](../../screenshots/simulate_cli_07.png) |
| חסימה / חום יתר | ![simulate_cli_08](../../screenshots/simulate_cli_08.png) |
| סיכום / יציאה | ![simulate_cli_09](../../screenshots/simulate_cli_09.png) |

גרפים אופציונליים מ-`plot_monitoring.py` (אזורי רעידות וסיכון לאורך זמן):

| גרף | צילום מסך |
|-----|------------|
| Figure 1 | ![Figure_1](../../screenshots/Figure_1.png) |
| Figure 2 | ![Figure_2](../../screenshots/Figure_2.png) |

---

## 6. מודולים ואחריות

| מודול | תכלית |
|-------|--------|
| **app/main_app.py** | לקוח MQTT, מאגר, הפעלת צינור, התחברות מחדש עם backoff, התראה על היעדר הודעות ממושך |
| **app/telemetry_validator.py** | אימות min/max של טלמטריה לפני DSP/ML |
| **app/data_processor.py** | מסנן Butterworth, הכנת batch, קריאה ל-FeatureExtractor |
| **app/feature_extractor.py** | חישוב תכונות (vib_rms, vib_crest, vib_kurtosis, current, pressure, cavitation_index, temp, temp_delta) |
| **app/predictor.py** | טעינת מודל/scaler, החלקת סיכון, ארגון כללים, רישום ל-CSV (דרך תור) |
| **app/rules.py** | מחלקות כלל (Mechanical, Cavitation, Choked, Degradation, Temperature, Overload, Pressure, Air, Vibration, Interlock, FinalCleanup) |
| **app/csv_logger.py** | תור כתיבת CSV עם ניסיון חוזר בשגיאה |
| **app/notifier.py** | משלוח התראות ל-Telegram |
| **app/healthcheck.py** | אימות config וארטיפקטים; exit 0/1 לבדיקות Docker/CI |
| **config/config.py** | ספים, נושאים, נתיבים, דגלי TLS |
| **config/validation.py** | אימות config בהפעלה; בשימוש ב-healthcheck |

---

## 7. מסמכים קשורים

- [system_trigger_scenarios.md](system_trigger_scenarios.md) — כל תרחישי הטריגר והספים
- [RULE_PRIORITY_AND_HYSTERESIS.md](RULE_PRIORITY_AND_HYSTERESIS.md) — עדיפות כללים והיסטרזיס
- [ML_REPORT.md](ML_REPORT.md) — מודל ML, מדדי ולידציה, חשיבות תכונות
