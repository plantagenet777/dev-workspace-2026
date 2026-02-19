# Pump Monitoring System (PdM) Trigger Scenarios

This document lists all scenarios in which the system raises warnings (WARNING), critical states (CRITICAL), or performs an automatic block/shutdown (SHUTDOWN). Thresholds and message texts are defined in `config/config.py`; logic is implemented in `app/predictor.py` and `simulate_failure.py`.

**Principles:**

- The type of automatic block and the message shown are determined **only by the cause** (predictor `reason` or sensor condition for that cause). Events do not override each other; the block always matches the diagnosed cause.
- **Model-only risk (Elevated/High risk) never triggers automatic shutdown on its own.** All SHUTDOWN scenarios are tied to physical/engineering causes (vibration, cavitation, choked discharge, overtemperature, debris impact).

---

## 1. Automatic Blocks (SHUTDOWN)

Each block is triggered only when the **cause** matches; the message states the cause explicitly (e.g. "AUTOMATIC BLOCK — Cause: …").

### 1.1 Vibration interlock

| Condition | Displayed vibration **vib_display** ≥ `VIBRATION_INTERLOCK_MMPS` (default 9.0 mm/s, set **above** ISO Zone D entry at 7.1 mm/s) **and** predictor reason is vibration (Zone D / 7.1 / INTERLOCK) — not cavitation, choked, temp, or debris. |
| Message | `[AUTOMATIC BLOCK] Cause: vibration interlock (engineering limit). Vibration X.XX mm/s — trip limit exceeded.` |
| Where checked | `simulate_failure.py` after predictor (cause-based). See [ARCHITECTURE.md](ARCHITECTURE.md#5-simulation-screenshots) for CLI screenshots. |

### 1.2 Debris impact (stone hit / mechanical damage)

| Condition | Predictor returns **CRITICAL** with reason = `MECHANICAL_DAMAGE_ALERT_MESSAGE` or `DEBRIS_IMPACT_ALERT_MESSAGE` (DEBRIS IMPACT Zone D). |
| Message | `[DEBRIS IMPACT SHUTDOWN] Debris impact (stone hit, Zone D). Immediate stop.` + REPAIR (inspect impeller, wear plate, liner; do not restart without inspection) + **Restart only after manual inspection and operator clearance.** |
| Where checked | `simulate_failure.py` after predictor (cause-based). |

### 1.3 Choked discharge (blocked discharge / closed valve)

| Condition | Predictor returns **CRITICAL** with reason starting with **"CHOKED DISCHARGE"** (cause only; scenario flag is not used). |
| Message | `[AUTOMATIC BLOCK] Cause: choked discharge (low flow + high P/T). Overheat risk. Immediate stop.` |
| Where checked | `simulate_failure.py` after predictor (cause-based). |

### 1.4 Cavitation

| Condition | Predictor returns **CRITICAL** with reason = `CAVITATION_ALERT_MESSAGE`, sustained for at least **CAVITATION_AUTO_SHUTDOWN_SEC** (default 10 s). |
| Message | `[AUTOMATIC BLOCK] Cause: cavitation sustained 10 s. Check inlet valve / sump level.` |
| Where checked | `simulate_failure.py` (cavitation timer, cause-based). |

### 1.5 Overtemperature

| Condition | Predictor reason indicates **HIGH TEMPERATURE** **and** mean temperature **T ≥ 75°C** for at least **TEMP_CRITICAL_AUTO_SHUTDOWN_SEC** (default 10 s). |
| Message | `[OVERTEMPERATURE SHUTDOWN] Elevated temperature — overtemperature (T >= 75°C sustained 10 s).` If vibration ≥ **VIBRATION_INTERLOCK_MMPS** at the same time, one combined message: *Elevated temperature and vibration interlock (Zone D) — T >= 75°C sustained 10 s. Vibration X.XX mm/s — limit exceeded.* |
| Where checked | `simulate_failure.py` (temperature timer, cause-based). |

---

## 2. Critical States (CRITICAL) Without Mandatory SHUTDOWN

Predictor sets status CRITICAL and reason; automatic shutdown for these may be applied separately (see Section 1).

### 2.1 DEBRIS IMPACT (stone hit / mechanical damage)

| Condition | Telemetry provides **debris_impact** flag (e.g. after "STONE HIT" in simulation) **or** high crest factor (≥ `DEBRIS_IMPACT_CREST_MIN`, 6.0) with Zone D vibration or already CRITICAL, **or** hysteresis with mechanical reason. |
| Thresholds | Vibration Zone D: ≥ 7.1 mm/s. Crest ≥ 6.0. |
| Message | DEBRIS IMPACT (Zone D): inspect impeller, wear plate and liner; do not restart without inspection if damage suspected. |

### 2.2 CAVITATION

| Condition | Current ≥ **CAVITATION_CURRENT_MIN_AMP** (54 A), pressure ≤ **CAVITATION_PRESSURE_MAX_BAR** (4.0 bar), vibration ≥ **CAVITATION_VIBRATION_MIN_MMPS** (9.0 mm/s) — smoothed or latest; or exit hysteresis (e.g. pressure ≤ 4.5 bar with vib/current still in zone). |
| Message | CAVITATION (Zone D): check inlet valve / sump level. |

### 2.3 CHOKED DISCHARGE

| Condition | Current ≤ **CHOKED_CURRENT_MAX_AMP** (38 A), pressure ≥ **CHOKED_PRESSURE_MIN_BAR** (7.0 bar), temperature ≥ **CHOKED_TEMP_MIN_C** (70°C) — smoothed or latest. |
| Message | CHOKED DISCHARGE: P=… bar, T=…°C, I=… A — low flow + high P/T. Overheat risk. Immediate stop. |

### 2.4 HIGH TEMPERATURE (Zone D)

| Condition | Temperature ≥ **TEMP_CRITICAL_C** (75°C) — smoothed or latest. |
| Message | HIGH TEMPERATURE (Zone D): …°C — inspect cooling and flow rate. |

### 2.5 VIBRATION Zone D (ISO 10816-3)

| Condition | Vibration (RMS) ≥ **VIBRATION_CRITICAL_MMPS** (7.1 mm/s). If no higher-priority reason (mechanical, cavitation, choked), vibration message is set. This is a CRITICAL **alarm**, not necessarily a trip. |
| Message | VIBRATION (Zone D): ≥7.1 mm/s unacceptable; reduce load or stop for inspection. |

### 2.6 Vibration interlock (engineering limit in predictor)

| Condition | Vibration ≥ **VIBRATION_INTERLOCK_MMPS** from Config (default **9.0 mm/s**, above ISO Zone D boundary of 7.1 mm/s). |
| Action | Force CRITICAL, risk 99.9%. Message: shutdown limit exceeded; stop and inspect. |

### 2.7 High risk (model)

| Condition | Status CRITICAL from model but last reason was "MAINTENANCE (Zone C)" — replaced with generic high-risk message. |
| Message | High risk (model): inspect equipment. |
| Automatic shutdown | **None** — this is an advisory-only state; trips are driven by physical causes described in Section 1. |

### 2.8 CRITICAL vibration hysteresis

| Condition | Previous step was CRITICAL; current vibration < **VIBRATION_HYSTERESIS_EXIT_CRITICAL_MMPS** (6.0). Status remains CRITICAL until **CRITICAL_EXIT_MIN_LOW_VIB_STEPS** (5) consecutive low-vibration steps, then transition to WARNING is allowed. |

---

## 3. Warnings (WARNING)

### 3.1 MAINTENANCE / Degradation (Zone C) — impeller wear

| Condition | Current ≤ **DEGRADATION_CURRENT_MAX_AMP** (40 A) and pressure ≤ **DEGRADATION_PRESSURE_MAX_BAR** (5.2 bar) — both smoothed and latest. Or hysteresis: was WARNING and current/pressure not yet above exit zone (current < 42 A or pressure < 5.5 bar). |
| Message | MAINTENANCE (Zone C): P=… bar, I=… A — inspect impeller & wear plate, assess on shutdown. |

### 3.2 HIGH TEMPERATURE (Zone C)

| Condition | Temperature ≥ **TEMP_WARNING_C** (60°C), status otherwise HEALTHY. |
| Message | HIGH TEMPERATURE (Zone C): …°C — inspect cooling and flow rate. |

### 3.3 Motor overload

| Condition | Current ≥ **OVERLOAD_CURRENT_MIN_AMP** (50 A), status HEALTHY. |
| Message | Motor overload: inspect for motor strain. |

### 3.4 High discharge pressure

| Condition | Pressure ≥ **PRESSURE_HIGH_WARNING_BAR** (7.0 bar) and current **> CHOKED_CURRENT_MAX_AMP** (38 A) on both sides — i.e. not choked scenario. Status HEALTHY. |
| Message | High discharge pressure: check discharge valves. |

### 3.5 AIR INGESTION

| Condition | Vibration crest factor ≥ **AIR_INGESTION_VIB_CREST_MIN** (5.5) **and** vibration RMS ≥ **AIR_INGESTION_VIB_RMS_MIN_MMPS** (4.5 mm/s). Status otherwise HEALTHY. |
| Message | AIR INGESTION: check sump level, reduce speed. |

### 3.6 VIBRATION Zone C (ISO 10816-3)

| Condition | Vibration ≥ **VIBRATION_WARNING_ENTRY_MMPS** (5.5 mm/s) smoothed and latest, smoothed probability ≥ **PROB_MIN_FOR_VIBRATION_WARNING** (0.15), status otherwise HEALTHY. Or hysteresis: was WARNING and vibration ≥ **VIBRATION_HYSTERESIS_EXIT_WARNING_MMPS** (4.5 mm/s). |
| Message | VIBRATION (Zone C): plan maintenance; monitor trend. |

### 3.7 Elevated risk (model)

| Condition | Previous step was WARNING, current model status HEALTHY but smoothed probability ≥ **PROB_HYSTERESIS_EXIT_WARNING** (0.25). Remain WARNING. |
| Message | Elevated risk (model): continue monitoring. |

---

## 4. Default Threshold Summary (config)

| Parameter | Default | Purpose |
|-----------|---------|---------|
| VIBRATION_CRITICAL_MMPS | 7.1 | ISO 10816-3 Zone D CRITICAL alarm. |
| VIBRATION_WARNING_ENTRY_MMPS | 5.5 | ISO 10816-3 Zone C WARNING entry. |
| VIBRATION_INTERLOCK_MMPS | 9.0 | Vibration trip (engineering limit, above Zone D). |
| CHOKED_CURRENT_MAX_AMP | 38 | Choked: upper current bound (low flow). |
| CHOKED_PRESSURE_MIN_BAR | 7.0 | Choked: lower pressure bound. |
| CHOKED_TEMP_MIN_C | 70.0 | Choked: lower temperature bound. |
| TEMP_WARNING_C | 60 | Temperature Zone C. |
| TEMP_CRITICAL_C | 75 | Temperature Zone D; auto shutdown after sustain. |
| CAVITATION_* | 54 A, 4 bar, 9 mm/s | Cavitation. |
| DEGRADATION_* | 40 A, 5.2 bar | Zone C degradation/maintenance. |
| OVERLOAD_CURRENT_MIN_AMP | 50 | Overload warning. |
| PRESSURE_HIGH_WARNING_BAR | 7.0 | High pressure with normal current. |

---

*Document derived from `config/config.py`, `app/predictor.py`, and `simulate_failure.py`. Thresholds follow ISO 10816‑3 for vibration zones and ANSI/HI guidance for pump operation; the interlock is intentionally placed above Zone D for an additional safety step before hard trip.*
