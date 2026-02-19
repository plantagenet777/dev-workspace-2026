# Приоритет правил и гистерезис

В документе описан порядок применения правил в `app/predictor.py` (через `app/rules.py`) и логика гистерезиса для устойчивого отображения статусов CRITICAL/WARNING без «дрожания».

---

## 1. Порядок правил (приоритет)

Правила выполняются **строго в порядке списка**. Первое правило, установившее причину (`reason`) или статус, имеет приоритет; последующие могут перезаписывать статус, но не всегда причину (например, вибрация Zone D не перезаписывает механическую причину).

| № | Правило | Файл | Назначение |
|---|---------|------|------------|
| 1 | **MechanicalRule** | rules.py | DEBRIS IMPACT: флаг `debris_impact` или высокий crest + Zone D → CRITICAL |
| 2 | **CavitationRule** | rules.py | Кавитация: ток ≥ 54 A, давление ≤ 4 бар, вибрация ≥ 9 мм/с → CRITICAL |
| 3 | **ChokedRule** | rules.py | Забивка нагнетания: ток ≤ 38 A, давление ≥ 7 бар, T ≥ 70°C → CRITICAL |
| 4 | **DegradationRule** | rules.py | Износ рабочего колеса: ток ≤ 40 A, давление ≤ 5.2 бар → WARNING (Zone C) |
| 5 | **DegradationHysteresisRule** | rules.py | Удержание WARNING до выхода из зоны (ток > 42 A, давление > 5.5 бар) |
| 6 | **TemperatureRule** | rules.py | T ≥ 75°C → CRITICAL; T ≥ 60°C при HEALTHY → WARNING |
| 7 | **OverloadRule** | rules.py | Ток ≥ 50 A → WARNING (перегрузка двигателя) |
| 8 | **HighPressureRule** | rules.py | Давление ≥ 7 бар при нормальном токе (не choked) → WARNING |
| 9 | **AirIngestionRule** | rules.py | Высокий crest + вибрация Zone C → WARNING (захват воздуха) |
| 10 | **VibrationZoneRule** | rules.py | Вибрация ≥ 7.1 мм/с → CRITICAL (Zone D); ≥ 5.5 мм/с + риск ≥ 15% → WARNING (Zone C) |
| 11 | **VibrationHysteresisRule** | rules.py | Удержание WARNING до vib < 4.5; CRITICAL до N шагов с vib < 6.0 |
| 12 | **InterlockRule** | rules.py | Вибрация ≥ Config.VIBRATION_INTERLOCK_MMPS (по умолчанию 9.0 мм/с, выше Zone D 7.1) → CRITICAL 99.9% |
| 13 | **FinalCleanupRule** | rules.py | CRITICAL: мин. отображаемый риск 0.85; замена MAINTENANCE на "High risk"; гистерезис риска для WARNING |

---

## 2. Гистерезис (сводка)

- **Вибрация Zone C:** выход из WARNING только при вибрации **< 4.5 мм/с** (VIBRATION_HYSTERESIS_EXIT_WARNING_MMPS).
- **Вибрация Zone D:** выход из CRITICAL только после **5** подряд шагов с вибрацией **< 6.0 мм/с** (VIBRATION_HYSTERESIS_EXIT_CRITICAL_MMPS).
- **Деградация (Zone C):** выход из WARNING только при токе **> 42 A** и давлении **> 5.5 бар**.
- **Риск (модель):** выход из WARNING только при сглаженной вероятности **< 0.25** (PROB_HYSTERESIS_EXIT_WARNING).
- **Кавитация:** удержание CRITICAL до давления **> 4.5 бар** (CAVITATION_HYSTERESIS_EXIT_PRESSURE_BAR) при сохранении условий по току/вибрации.

---

## 3. Упрощённое дерево решений

```
                    [Вход: сглаженная и последняя телеметрия]
                                        |
                    +-------------------+-------------------+
                    |                   |                   |
              debris_impact?      Кавитация (I↑, P↓, V↑)   Choked (I↓, P↑, T↑)
                    |                   |                   |
                   ДА                   ДА                   ДА
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
                    P ≥ 7 бар (не choked)? -> WARNING (HIGH_P)
                    Air (crest↑, V↑) ?   ->  WARNING (AIR)
                    V ≥ 7.1 мм/с ?       ->  CRITICAL (Zone D)
                    V ≥ 5.5 мм/с + риск? ->  WARNING (Zone C)
                    Гистерезис WARNING/CRITICAL по V, I, P, риск
                    V ≥ VIBRATION_INTERLOCK_MMPS (9.0) ? ->  CRITICAL (Вибрационный блок 99.9%)
                    Финальная очистка (мин. риск, замена MAINTENANCE при CRITICAL)
                                        |
                                        v
                              [Статус и причина для MQTT/CSV/Telegram]
```

---

## 4. Ссылки

- Пороги и сообщения: `config/config.py`
- Реализация правил: `app/rules.py`
- Сглаживание риска и оркестрация: `app/predictor.py`
- Полный список триггеров: [system_trigger_scenarios.md](system_trigger_scenarios.md)
