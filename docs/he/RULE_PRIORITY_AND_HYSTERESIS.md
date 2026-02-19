# עדיפות כללים והיסטרזיס

מסמך זה מתאר את סדר יישום הכללים ב-`app/predictor.py` (דרך `app/rules.py`) ואת לוגיקת ההיסטרזיס לתצוגת סטטוס CRITICAL/WARNING יציבה ללא "ריצוד".

---

## 1. סדר כללים (עדיפות)

הכללים מבוצעים **בדיוק לפי סדר הרשימה**. לכלל הראשון שקובע סיבה (`reason`) או סטטוס יש עדיפות; כללים מאוחרים עשויים לדרוס סטטוס אך לא תמיד סיבה (למשל רעידות Zone D לא דורסות סיבה מכנית).

| # | כלל | קובץ | תכלית |
|---|-----|------|--------|
| 1 | **MechanicalRule** | rules.py | DEBRIS IMPACT: דגל `debris_impact` או crest גבוה + Zone D → CRITICAL |
| 2 | **CavitationRule** | rules.py | קוויטציה: זרם ≥ 54 A, לחץ ≤ 4 bar, רעידות ≥ 9 mm/s → CRITICAL |
| 3 | **ChokedRule** | rules.py | פריקה חסומה: זרם ≤ 38 A, לחץ ≥ 7 bar, T ≥ 70°C → CRITICAL |
| 4 | **DegradationRule** | rules.py | בלאי impeller: זרם ≤ 40 A, לחץ ≤ 5.2 bar → WARNING (Zone C) |
| 5 | **DegradationHysteresisRule** | rules.py | החזקת WARNING עד יציאה מאזור (זרם > 42 A, לחץ > 5.5 bar) |
| 6 | **TemperatureRule** | rules.py | T ≥ 75°C → CRITICAL; T ≥ 60°C כש-HEALTHY → WARNING |
| 7 | **OverloadRule** | rules.py | זרם ≥ 50 A → WARNING (עומס יתר מנוע) |
| 8 | **HighPressureRule** | rules.py | לחץ ≥ 7 bar עם זרם תקין (לא choked) → WARNING |
| 9 | **AirIngestionRule** | rules.py | Crest גבוה + רעידות Zone C → WARNING (בליעת אוויר) |
| 10 | **VibrationZoneRule** | rules.py | רעידות ≥ 7.1 mm/s → CRITICAL (Zone D); ≥ 5.5 mm/s + סיכון ≥ 15% → WARNING (Zone C) |
| 11 | **VibrationHysteresisRule** | rules.py | החזקת WARNING עד vib < 4.5; החזקת CRITICAL עד N צעדים עם vib < 6.0 |
| 12 | **InterlockRule** | rules.py | רעידות ≥ Config.VIBRATION_INTERLOCK_MMPS (ברירת מחדל 9.0 mm/s, מעל Zone D 7.1) → CRITICAL 99.9% |
| 13 | **FinalCleanupRule** | rules.py | CRITICAL: תצוגה מינימלית 0.85; החלפת MAINTENANCE ב-"High risk"; היסטרזיס סיכון ל-WARNING |

---

## 2. היסטרזיס (סיכום)

- **רעידות Zone C:** יציאה מ-WARNING רק כאשר רעידות **< 4.5 mm/s** (VIBRATION_HYSTERESIS_EXIT_WARNING_MMPS).
- **רעידות Zone D:** יציאה מ-CRITICAL רק אחרי **5** צעדים רצופים עם רעידות **< 6.0 mm/s** (VIBRATION_HYSTERESIS_EXIT_CRITICAL_MMPS).
- **התדרדרות (Zone C):** יציאה מ-WARNING רק כאשר זרם **> 42 A** ולחץ **> 5.5 bar**.
- **סיכון (מודל):** יציאה מ-WARNING רק כאשר הסתברות ממוצעת **< 0.25** (PROB_HYSTERESIS_EXIT_WARNING).
- **קוויטציה:** החזקת CRITICAL עד לחץ **> 4.5 bar** (CAVITATION_HYSTERESIS_EXIT_PRESSURE_BAR) עם תנאי זרם/רעידות עדיין באזור.

---

## 3. עץ החלטות (מפושט)

```
                    [קלט: טלמטריה ממוצעת ואחרונה]
                                        |
                    +-------------------+-------------------+
                    |                   |                   |
              debris_impact?      Cavitation (I↑, P↓, V↑)   Choked (I↓, P↑, T↑)
                    |                   |                   |
                   YES                  YES                  YES
                    |                   |                   |
                    v                   v                   v
              CRITICAL (DEBRIS)   CRITICAL (CAVITATION)  CRITICAL (CHOKED)
                    |                   |                   |
                    +-------------------+-------------------+
                                        |
                    Degradation (I↓, P↓) ?  ->  WARNING (MAINTENANCE)
                    T ≥ 75°C ?           ->  CRITICAL (TEMP)
                    T ≥ 60°C ?           ->  WARNING (TEMP)
                    I ≥ 50 A ?           ->  WARNING (OVERLOAD)
                    P ≥ 7 bar (not choked)? -> WARNING (HIGH_P)
                    Air (crest↑, V↑) ?   ->  WARNING (AIR)
                    V ≥ 7.1 mm/s ?       ->  CRITICAL (Zone D)
                    V ≥ 5.5 mm/s + risk? ->  WARNING (Zone C)
                    Hysteresis WARNING/CRITICAL for V, I, P, risk
                    V ≥ VIBRATION_INTERLOCK_MMPS (9.0) ? ->  CRITICAL (Vibration interlock 99.9%)
                    Final cleanup (min risk, replace MAINTENANCE when CRITICAL)
                                        |
                                        v
                              [Status and reason for MQTT/CSV/Telegram]
```

---

## 4. מקורות

- ספים והודעות: `config/config.py`
- יישום כללים: `app/rules.py`
- החלקת סיכון וארגון: `app/predictor.py`
- רשימת טריגרים מלאה: [system_trigger_scenarios.md](system_trigger_scenarios.md)
