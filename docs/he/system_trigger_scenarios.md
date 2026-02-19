# תרחישי טריגר במערכת PdM (ניטור משאבה)

מסמך זה מפרט את כל התרחישים שבהם המערכת מפעילה אזהרות (WARNING), מצבים קריטיים (CRITICAL) או ביצוע חסימה/עצירה אוטומטית (SHUTDOWN). הספים וטקסטי ההודעות מוגדרים ב-`config/config.py`; הלוגיקה ב-`app/predictor.py` ו-`simulate_failure.py`.

**עקרונות:**

- סוג החסימה האוטומטית וההודעה נקבעים **רק לפי הסיבה** (שדה `reason` של המנבא או תנאי חיישן). אירועים לא דורסים זה את זה; החסימה תמיד תואמת את הסיבה המאובחנת.
- **סיכון מהמודל בלבד (Elevated/High risk) לא מפעיל עצירה אוטומטית לבד.** כל תרחישי SHUTDOWN קשורים לסיבות פיזיות/הנדסיות (רעידות, קוויטציה, פריקה חסומה, חום יתר, פגיעת גוף זר).

---

## 1. חסימות אוטומטיות (SHUTDOWN)

### 1.1 מגבלת רעידות (Vibration interlock)

| תנאי | **vib_display** ≥ `VIBRATION_INTERLOCK_MMPS` (ברירת מחדל 9.0 mm/s, **מעל** כניסה ל-Zone D ב-7.1 mm/s) **ו-**סיבת המנבא היא רעידות (Zone D / INTERLOCK). |
| הודעה | `[AUTOMATIC BLOCK] Cause: vibration interlock (engineering limit). Vibration X.XX mm/s — trip limit exceeded.` |
| איפה נבדק | `simulate_failure.py` אחרי המנבא. צילומי CLI: [ARCHITECTURE.md](ARCHITECTURE.md#5-צילומי-מסך-של-הסימולציה). |

### 1.2 פגיעת גוף זר (Debris impact / נזק מכני)

| תנאי | המנבא מחזיר **CRITICAL** עם reason = `MECHANICAL_DAMAGE_ALERT_MESSAGE` או `DEBRIS_IMPACT_ALERT_MESSAGE`. |
| הודעה | `[DEBRIS IMPACT SHUTDOWN] Debris impact (stone hit, Zone D). Immediate stop.` + REPAIR + **Restart only after manual inspection and operator clearance.** |
| איפה נבדק | `simulate_failure.py` אחרי המנבא. |

### 1.3 פריקה חסומה (Choked discharge)

| תנאי | המנבא מחזיר **CRITICAL** עם reason שמתחיל ב-**"CHOKED DISCHARGE"**. |
| הודעה | `[AUTOMATIC BLOCK] Cause: choked discharge (low flow + high P/T). Overheat risk. Immediate stop.` |
| איפה נבדק | `simulate_failure.py` אחרי המנבא. |

### 1.4 קוויטציה (Cavitation)

| תנאי | המנבא מחזיר **CRITICAL** עם reason = `CAVITATION_ALERT_MESSAGE`, למשך לפחות **CAVITATION_AUTO_SHUTDOWN_SEC** (10 s). |
| הודעה | `[AUTOMATIC BLOCK] Cause: cavitation sustained 10 s. Check inlet valve / sump level.` |
| איפה נבדק | `simulate_failure.py` (טיימר קוויטציה). |

### 1.5 חום יתר (Overtemperature)

| תנאי | סיבת המנבא **HIGH TEMPERATURE** **ו-**טמפרטורה ממוצעת **T ≥ 75°C** לפחות **TEMP_CRITICAL_AUTO_SHUTDOWN_SEC** (10 s). |
| הודעה | `[OVERTEMPERATURE SHUTDOWN] Elevated temperature — overtemperature (T >= 75°C sustained 10 s).` |
| איפה נבדק | `simulate_failure.py` (טיימר טמפרטורה). |

---

## 2. מצבים קריטיים (CRITICAL) ללא SHUTDOWN חובה

המנבא קובע סטטוס CRITICAL וסיבה; עצירה אוטומטית יכולה להיות מופעלת בנפרד (סעיף 1).

### 2.1 DEBRIS IMPACT

| תנאי | דגל **debris_impact** בטלמטריה **או** crest גבוה (≥ 6.0) עם רעידות Zone D או כבר CRITICAL, **או** היסטרזיס עם סיבה מכנית. |
| ספים | רעידות Zone D: ≥ 7.1 mm/s. Crest ≥ 6.0. |

### 2.2 CAVITATION

| תנאי | זרם ≥ **54 A**, לחץ ≤ **4.0 bar**, רעידות ≥ **9.0 mm/s** (ממוצע או אחרון); או יציאה מהיסטרזיס. |
| הודעה | CAVITATION (Zone D): check inlet valve / sump level. |

### 2.3 CHOKED DISCHARGE

| תנאי | זרם ≤ **38 A**, לחץ ≥ **7.0 bar**, טמפרטורה ≥ **70°C**. |
| הודעה | CHOKED DISCHARGE: P=… bar, T=…°C, I=… A — low flow + high P/T. Overheat risk. Immediate stop. |

### 2.4 HIGH TEMPERATURE (Zone D)

| תנאי | טמפרטורה ≥ **75°C**. |

### 2.5 VIBRATION Zone D (ISO 10816-3)

| תנאי | רעידות (RMS) ≥ **7.1 mm/s**. אם אין סיבה בעדיפות גבוהה יותר — הודעת רעידות. זה **אלרם** CRITICAL, לא בהכרח trip. |

### 2.6 מגבלת רעידות במנבא (Interlock)

| תנאי | רעידות ≥ **VIBRATION_INTERLOCK_MMPS** מ-Config (ברירת מחדל **9.0 mm/s**, מעל גבול Zone D 7.1 mm/s). |
| פעולה | CRITICAL כפוי, סיכון 99.9%. |

### 2.7 סיכון גבוה (מודל)

| תנאי | סטטוס CRITICAL מהמודל אך הסיבה האחרונה הייתה "MAINTENANCE (Zone C)" — מוחלפת בהודעת סיכון גבוה כללית. |
| עצירה אוטומטית | **אין** — מצב ייעוצי בלבד; ה-trips נקבעים על ידי סיבות פיזיות (סעיף 1). |

### 2.8 היסטרזיס CRITICAL ברעידות

| תנאי | הצעד הקודם היה CRITICAL; רעידות נוכחיות < **6.0 mm/s**. הסטטוס נשאר CRITICAL עד **5** צעדים רצופים עם רעידות נמוכות, אז מותר מעבר ל-WARNING. |

---

## 3. אזהרות (WARNING)

### 3.1 MAINTENANCE / Degradation (Zone C)

| תנאי | זרם ≤ **40 A** ולחץ ≤ **5.2 bar** (ממוצע ואחרון). או היסטרזיס: היה WARNING וזרם/לחץ עדיין לא מעל אזור היציאה. |
| הודעה | MAINTENANCE (Zone C): P=… bar, I=… A — inspect impeller & wear plate, assess on shutdown. |

### 3.2 HIGH TEMPERATURE (Zone C)

| תנאי | טמפרטורה ≥ **60°C**, סטטוס אחרת HEALTHY. |

### 3.3 עומס יתר מנוע

| תנאי | זרם ≥ **50 A**, סטטוס HEALTHY. |

### 3.4 לחץ פריקה גבוה

| תנאי | לחץ ≥ **7.0 bar** וזרם **> 38 A** (לא תרחיש choked). |

### 3.5 בליעת אוויר (Air ingestion)

| תנאי | Crest רעידות ≥ **5.5** **ו-**RMS רעידות ≥ **4.5 mm/s**. סטטוס אחרת HEALTHY. |

### 3.6 VIBRATION Zone C (ISO 10816-3)

| תנאי | רעידות ≥ **5.5 mm/s** (ממוצע ואחרון), הסתברות ממוצעת ≥ **0.15**, סטטוס אחרת HEALTHY. או היסטרזיס. |
| הודעה | VIBRATION (Zone C): plan maintenance; monitor trend. |

### 3.7 סיכון מוגבר (מודל)

| תנאי | הצעד הקודם WARNING, סטטוס המודל הנוכחי HEALTHY אך הסתברות ממוצעת ≥ **0.25**. נשארים ב-WARNING. |

---

## 4. סיכום ספים (config)

| פרמטר | ברירת מחדל | תכלית |
|--------|------------|--------|
| VIBRATION_CRITICAL_MMPS | 7.1 | ISO 10816-3 Zone D אלרם CRITICAL. |
| VIBRATION_WARNING_ENTRY_MMPS | 5.5 | ISO 10816-3 Zone C כניסה ל-WARNING. |
| VIBRATION_INTERLOCK_MMPS | 9.0 | Trip רעידות (מגבלה הנדסית, מעל Zone D). |
| CHOKED_CURRENT_MAX_AMP | 38 | Choked: גבול עליון זרם. |
| CHOKED_PRESSURE_MIN_BAR | 7.0 | Choked: גבול תחתון לחץ. |
| CHOKED_TEMP_MIN_C | 70.0 | Choked: גבול תחתון טמפרטורה. |
| TEMP_WARNING_C | 60 | טמפרטורה Zone C. |
| TEMP_CRITICAL_C | 75 | טמפרטורה Zone D; עצירה אוטומטית אחרי החזקה. |
| CAVITATION_* | 54 A, 4 bar, 9 mm/s | קוויטציה. |
| DEGRADATION_* | 40 A, 5.2 bar | Zone C התדרדרות/תחזוקה. |
| OVERLOAD_CURRENT_MIN_AMP | 50 | אזהרת עומס יתר. |
| PRESSURE_HIGH_WARNING_BAR | 7.0 | לחץ גבוה עם זרם תקין. |

---

*מבוסס על `config/config.py`, `app/predictor.py` ו-`simulate_failure.py`. הספים תואמים ל-ISO 10816‑3 לאזורי רעידות; ה-interlock ממוקם במכוון מעל Zone D לשלב בטיחות נוסף לפני trip קשיח.*
