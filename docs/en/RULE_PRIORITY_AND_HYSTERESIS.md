# Rule Priority and Hysteresis

This document describes the order in which rules are applied in `app/predictor.py` (via `app/rules.py`) and the hysteresis logic for stable CRITICAL/WARNING status display without "jitter".

---

## 1. Rule Order (Priority)

Rules are executed **strictly in list order**. The first rule that sets cause (`reason`) or status has priority; later rules may overwrite status but do not always overwrite reason (e.g. vibration Zone D does not overwrite mechanical cause).

| # | Rule | File | Purpose |
|---|------|------|---------|
| 1 | **MechanicalRule** | rules.py | DEBRIS IMPACT (stone/mechanical damage): `debris_impact` flag or high crest + Zone D → CRITICAL |
| 2 | **CavitationRule** | rules.py | Cavitation: current ≥ 54 A, pressure ≤ 4 bar, vibration ≥ 9 mm/s → CRITICAL |
| 3 | **ChokedRule** | rules.py | Choked discharge: current ≤ 38 A, pressure ≥ 7 bar, T ≥ 70°C → CRITICAL |
| 4 | **DegradationRule** | rules.py | Impeller wear: current ≤ 40 A, pressure ≤ 5.2 bar → WARNING (Zone C) |
| 5 | **DegradationHysteresisRule** | rules.py | Hold WARNING until exit zone (current > 42 A, pressure > 5.5 bar) |
| 6 | **TemperatureRule** | rules.py | T ≥ 75°C → CRITICAL; T ≥ 60°C when HEALTHY → WARNING |
| 7 | **OverloadRule** | rules.py | Current ≥ 50 A → WARNING (motor overload) |
| 8 | **HighPressureRule** | rules.py | Pressure ≥ 7 bar with normal current (not choked) → WARNING |
| 9 | **AirIngestionRule** | rules.py | High crest + vibration Zone C → WARNING (air ingestion) |
| 10 | **VibrationZoneRule** | rules.py | Vibration ≥ 7.1 mm/s → CRITICAL (Zone D); ≥ 5.5 mm/s + risk ≥ 15% → WARNING (Zone C) |
| 11 | **VibrationHysteresisRule** | rules.py | Hold WARNING until vib < 4.5; hold CRITICAL until N steps with vib < 6.0 |
| 12 | **InterlockRule** | rules.py | Vibration ≥ Config.VIBRATION_INTERLOCK_MMPS (default 9.0 mm/s, above Zone D 7.1; vibration interlock) → CRITICAL 99.9% |
| 13 | **FinalCleanupRule** | rules.py | CRITICAL: min display 0.85; replace MAINTENANCE with "High risk"; risk hysteresis for WARNING |

---

## 2. Hysteresis (Summary)

- **Vibration Zone C:** exit WARNING only when vibration **< 4.5 mm/s** (VIBRATION_HYSTERESIS_EXIT_WARNING_MMPS).
- **Vibration Zone D:** exit CRITICAL only after **CRITICAL_EXIT_MIN_LOW_VIB_STEPS** (default 5) consecutive steps with vibration **< 6.0 mm/s** (VIBRATION_HYSTERESIS_EXIT_CRITICAL_MMPS).
- **Degradation (Zone C):** exit WARNING only when current **> 42 A** and pressure **> 5.5 bar** (exit zone with hysteresis).
- **Risk (model):** exit WARNING only when smoothed probability **< PROB_HYSTERESIS_EXIT_WARNING** (0.25).
- **Cavitation:** hold CRITICAL until pressure **> 4.5 bar** (CAVITATION_HYSTERESIS_EXIT_PRESSURE_BAR) with current/vib conditions still in zone.

---

## 3. Decision Tree (Simplified)

```
                    [Input: smoothed and latest telemetry]
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

## 4. References

- Thresholds and messages: `config/config.py`
- Rule implementation: `app/rules.py`
- Risk smoothing and orchestration: `app/predictor.py`
- Full list of triggers: [system_trigger_scenarios.md](system_trigger_scenarios.md)
