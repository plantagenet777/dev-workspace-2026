# Recommendations: LSTM and PINN in PdM Project

This document analyses the current PdM (Predictive Maintenance) stack and recommends how to introduce **LSTM** (Long Short-Term Memory) and **PINN** (Physics-Informed Neural Networks) while keeping the existing RF + rules pipeline and edge deployment in mind.

---

## 1. Current Architecture Summary

| Component | Current implementation |
|-----------|------------------------|
| **Input** | MQTT telemetry: `vib_rms`, `current`, `pressure`, `temp` (and derived `vib_crest`, `vib_kurtosis`, `cavitation_index`, `temp_delta`) |
| **Window** | `FEATURE_WINDOW_SIZE = 30` records per batch → one **aggregated** feature vector (8 scalars) per inference |
| **Smoothing** | Last `SMOOTHING_WINDOW_SIZE = 3` feature vectors averaged before prediction (reduces jitter) |
| **Model** | Random Forest classifier (3 classes: Healthy / Warning / Critical), `StandardScaler`, joblib |
| **Output** | Status (CRITICAL / WARNING / HEALTHY), smoothed risk score; rules layer (ISO 10816-3, cavitation, choked, debris, overtemp) overrides or refines cause |
| **Deployment** | Edge (Docker), Python 3.11, no GPU assumed; inference every `MQTT_BATCH_SIZE` messages when buffer is full |

The model is **non-sequential**: each inference uses a single 8-D vector (batch-aggregated). Temporal structure is only partially used via a 3-step rolling average.

---

## 2. LSTM: Recommendations

### 2.1 Why LSTM Fits This Project

- **Degradation trends**: Bearing wear and impeller wear often show gradual drift (e.g. rising `vib_rms`, changing `vib_crest`) over many batches. RF sees only the current snapshot; LSTM can use the last N steps.
- **Pre-failure ramps**: Before cavitation or vibration interlock, signals often ramp over several minutes. A sequence model can learn “ramp + Zone C → soon Zone D”.
- **Recurring patterns**: Cyclic load or process patterns (e.g. daily cycles) can be captured by LSTM for context-aware risk.
- **RUL / prognostics**: Optional extension: predict “time to Zone D” or “anomaly score in next K steps” instead of only current class.

### 2.2 Where to Use LSTM (Priority)

| Use case | Description | Priority |
|----------|-------------|----------|
| **Sequence-to-one classification** | Input: last K feature vectors (e.g. K=12 or 24). Output: same 3 classes (Healthy / Warning / Critical). Replaces or **complements** RF. | **High** |
| **Anomaly / risk from sequence** | LSTM encoder → scalar risk or “distance to Zone D”; fuse with current RF risk (e.g. max or weighted average) for alerts. | **High** |
| **RUL / trend warning** | Optional: regress “steps until critical” or “trend slope” for early maintenance planning. | Medium |

### 2.3 Data and Input Shape

- **Source**: Reuse `telemetry_history.csv` or buffer in memory: each row = one batch’s feature vector (8 features). Build sequences of length `T` (e.g. T=12 or 24) with stride 1.
- **Shape**: `(batch_size, T, 8)` for LSTM; labels = status at time T (or T+1 for “next-step” prediction).
- **Training**: Need enough **labeled sequences** (Healthy / Warning / Critical). Options:
  - **Synthetic**: Extend `train_and_save.py` / `simulate_failure.py` to output sequences with trends (gradual wear, ramps) and label by zone at sequence end.
  - **Real**: If you have historical runs with known events (e.g. “last 12 steps before interlock”), use those for fine-tuning.

### 2.4 Integration with Current Pipeline

- **Option A – Parallel**: Keep RF as primary; add LSTM as a second branch. Final risk = e.g. `max(RF_risk, LSTM_risk)` or `0.6*RF + 0.4*LSTM`. Rules (ISO, cavitation, choked, etc.) still apply on top.
- **Option B – Replace**: LSTM replaces RF for status/risk; keep same rules and thresholds. Requires more data and validation to match or improve RF.
- **Recommendation**: Start with **Option A** (parallel) and a small LSTM (1–2 layers, ~32–64 units) so that deployment and rollback stay simple.

### 2.5 Implementation Sketch

- **Config**: Add e.g. `LSTM_SEQUENCE_LENGTH = 12`, `LSTM_MODEL_PATH`, `USE_LSTM_RISK = true`, `LSTM_RISK_WEIGHT = 0.4`.
- **Data**: In `main_app` or a new `sequence_buffer.py`, keep a deque of last `LSTM_SEQUENCE_LENGTH` feature vectors (each of length 8). When pipeline runs, form tensor `(1, T, 8)` and run LSTM inference.
- **Training script**: New `train_lstm.py`: load or generate sequences, train PyTorch or TensorFlow LSTM, export to ONNX or TorchScript for edge; persist scaler (same 8 features as RF).
- **Dependencies**: Add `torch` or `tensorflow` (and optionally `onnxruntime` for lighter inference). Document CPU-only inference for Docker.

### 2.6 Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| Few labeled sequences | Use long synthetic runs from `simulate_failure.py` with known failure modes; augment with noise and time shifts. |
| Overfitting | Small network, dropout, early stopping; validate on held-out sequences. |
| Latency / size on edge | Prefer small LSTM + ONNX; benchmark vs. RF; keep RF as fallback if LSTM disabled. |
| Interpretability | Keep rules and RF feature importance; use LSTM as “temporal risk” only, not sole decision maker at first. |

---

## 3. PINN: Recommendations

### 3.1 What “Physics” Exists in This Project

- **ISO 10816-3**: Zone boundaries 4.5 mm/s (B/C) and 7.1 mm/s (C/D). These are **thresholds**, not ODEs, but can be encoded as constraints or soft losses (e.g. penalty when predicted risk disagrees with zone).
- **Cavitation**: High vibration at low pressure; `cavitation_index = vibration / pressure` is already a heuristic. A PINN could learn or constrain a relationship like “vib ∝ f(1/pressure)” in the cavitation regime.
- **Process coupling**: Temperature vs. current/pressure (overload, choked); simple thermal or balance relations could be added if needed (e.g. dT/dt proxy from current).
- **Interlock**: 9.0 mm/s is an engineering limit; can be used as a hard constraint in loss (e.g. “above 9.0 → must predict CRITICAL”).

### 3.2 Where to Use PINN (Priority)

| Use case | Description | Priority |
|----------|-------------|----------|
| **Zone-consistent loss** | Add a physics loss: if `vib_rms ≥ 7.1` then model output should favour CRITICAL; if `vib_rms < 4.5` then favour Healthy. Reduces “obvious” misclassifications. | **High** |
| **Cavitation residual** | PINN predicts “expected vibration” from pressure/current; residual (observed − predicted) as cavitation indicator. Complements existing `cavitation_index`. | **High** |
| **Interlock constraint** | In training or inference: penalize or clamp outputs so that when `vib_rms ≥ VIBRATION_INTERLOCK_MMPS`, predicted class is CRITICAL. | Medium |
| **Full PINN surrogate** | Replace or augment feature extractor with a small NN that satisfies ODEs (e.g. simplified thermal or vibration dynamics). | Low (needs more formalized physics) |

### 3.3 How to Implement (Minimal First Step)

- **Physics loss (zones)**
  - In `train_and_save.py` (or a new `train_pinn.py`): for each sample, define a soft loss:
    - If `vib_rms >= 7.1`: encourage P(CRITICAL) high (e.g. cross-entropy with target CRITICAL or penalty for low P(CRITICAL)).
    - If `vib_rms < 4.5` and no other rule (cavitation, choked, etc.): encourage P(HEALTHY) high.
  - Same can be applied to an LSTM: add this physics term to the total loss.

- **Cavitation PINN (residual)**
  - Train a small MLP or 1D CNN: inputs = `pressure`, `current`, maybe `temp`; output = “expected vib_rms” under non-cavitating conditions.
  - At inference: `cavitation_residual = observed_vib_rms - predicted_vib_rms`. High residual → cavitation.
  - This can feed into the existing rules (e.g. “cavitation residual > threshold” as an extra condition) or into a combined risk score.

- **Interlock constraint**
  - In training: for samples with `vib_rms >= 9.0`, set target to CRITICAL or add a strong penalty for non-CRITICAL.
  - In inference: optional post-processing “if vib_rms >= 9.0 then force status = CRITICAL” (already done by rules; PINN keeps the **model** itself aligned).

### 3.4 Implementation Sketch

- **Config**: Add e.g. `USE_PINN_ZONE_LOSS = true`, `PINN_ZONE_LOSS_WEIGHT = 0.2`, `CAVITATION_PINN_PATH` (optional).
- **Training**:
  - **Option 1**: Extend `train_and_save.py` with a physics loss term (zone + optional interlock); keep RF or use a small MLP/LSTM.
  - **Option 2**: New script `train_cavitation_pinn.py` for the cavitation residual model; input (pressure, current, temp) → expected vib; save small model (e.g. ONNX).
- **Inference**:
  - Zone loss only affects training (no extra runtime).
  - Cavitation PINN: in `feature_extractor` or `predictor`, compute `cavitation_residual` and pass it to rules or a simple threshold.

### 3.5 Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| Over-constraining | Keep physics loss weight modest (e.g. 0.1–0.3); validate that accuracy on real/synthetic data does not drop. |
| Wrong physics | Start with zone boundaries and cavitation residual; avoid complex ODEs until you have clear equations and data. |
| Extra latency | Cavitation PINN is one small forward pass; zone loss is training-only. |

---

## 4. Suggested Roadmap

| Phase | Step | Outcome |
|-------|------|---------|
| **1** | Add config flags and sequence buffer (last K feature vectors) in the engine. | Ready to feed sequences to an LSTM without changing RF path. |
| **2** | Implement zone physics loss in training (RF or small NN); validate on synthetic data. | PINN zone consistency; same or better accuracy. |
| **3** | Add a small LSTM (e.g. 1 layer, 32 units), train on synthetic sequences, export ONNX. | LSTM risk score available; run in parallel with RF. |
| **4** | Fuse LSTM risk with RF risk (e.g. max or weighted average); keep all existing rules. | One deployment with “RF + LSTM + rules”. |
| **5** | (Optional) Add cavitation residual PINN and use residual in rules or risk. | Better cavitation detection with physics. |
| **6** | (Optional) RUL or trend head on LSTM for maintenance planning. | Extra output for dashboards/planning. |

---

## 5. Dependencies and Deployment

- **LSTM**: Add `torch` (or `tensorflow`) and optionally `onnxruntime` for inference. In Docker, use CPU-only builds; document minimal version (e.g. Python 3.11, no GPU).
- **PINN**: Zone loss and interlock penalty need only NumPy/sklearn or the same framework as LSTM; cavitation residual model is a small NN (same stack).
- **Tests**: Unit tests for sequence buffer shape; tests that “vib_rms ≥ 9.0” always yields CRITICAL after training; smoke test with LSTM artifact disabled (fallback to RF only).

---

## 6. References (Short)

- **LSTM for PdM**: Sequence-to-class and RUL in vibration/condition monitoring (e.g. “LSTM for RUL prediction” in bearings/pumps).
- **PINN**: Physics-informed loss terms (zone boundaries, ODE residuals); Raissi et al. “Physics-informed neural networks”; for PdM, often used as soft constraints rather than full PDE solvers.
- **ISO 10816-3**: Zone limits 4.5 / 7.1 mm/s (Group 1, rigid); project already implements these in `config.config` and `app.rules`.

---

*Document derived from the current codebase (`app/predictor.py`, `app/feature_extractor.py`, `app/data_processor.py`, `config/config.py`, `train_and_save.py`). Thresholds and feature names match Config and rules.*
