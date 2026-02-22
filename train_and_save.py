"""
PdM: Train Random Forest classifier for pump predictive maintenance.
Synthetic zones aligned with simulate_failure.py and ISO 10816-3; zone thresholds
and HEALTHY_MEANS / WARNING_MEANS / CRITICAL_MEANS are in config.config.Config.
Produces model, scaler, and an ML metrics report (models/ml_report.txt).
"""
import os
import pandas as pd
import numpy as np
import joblib
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import (
    classification_report,
    confusion_matrix,
    balanced_accuracy_score,
)

from config.config import Config


def generate_synthetic_data(samples=5000):
    """
    Generate data with three zones from Config (HEALTHY_MEANS, WARNING_MEANS, CRITICAL_MEANS).
    Aligned with ISO 10816-3 and simulate_failure.py digital twin.
    """
    np.random.seed(42)

    h, w, c = Config.HEALTHY_MEANS, Config.WARNING_MEANS, Config.CRITICAL_MEANS

    # 1. HEALTHY (target 0) – 80%; vib_rms below Config zone C (see VIBRATION_WARNING_MMPS)
    n_h = int(samples * 0.8)
    data_h = {
        "vib_rms": np.random.normal(h["v"], 0.5, n_h),
        "vib_crest": np.random.normal(3.0, 0.2, n_h),
        "vib_kurtosis": np.random.normal(2.8, 0.15, n_h),
        "current": np.random.normal(45.0, 2.0, n_h),
        "pressure": np.random.normal(h["p"], 0.2, n_h),
        "cavitation_index": np.random.normal(0.02, 0.01, n_h),
        "temp": np.random.normal(h["t"], 2.0, n_h),
        "temp_delta": np.random.normal(0.0, 0.5, n_h),
        "target": 0,
    }

    # 2. WARNING (target 1) – 10%; Zone C (Config VIBRATION_WARNING_MMPS – VIBRATION_CRITICAL_MMPS), moderate wear
    n_w = int(samples * 0.1)
    data_w = {
        "vib_rms": np.random.normal(w["v"], 0.6, n_w),
        "vib_crest": np.random.normal(5.5, 1.0, n_w),
        "vib_kurtosis": np.random.normal(4.5, 0.5, n_w),
        "current": np.random.normal(52.0, 2.5, n_w),
        "pressure": np.random.normal(w["p"], 0.3, n_w),
        "cavitation_index": np.random.normal(0.12, 0.03, n_w),
        "temp": np.random.normal(w["t"], 4.0, n_w),
        "temp_delta": np.random.normal(1.0, 1.0, n_w),
        "target": 1,
    }

    # 3. CRITICAL (target 2) – 10%; Zone D (≥ Config VIBRATION_CRITICAL_MMPS), failure / stone hit
    n_c = samples - n_h - n_w
    data_c = {
        "vib_rms": np.random.normal(c["v"], 2.0, n_c),
        "vib_crest": np.random.normal(7.5, 1.2, n_c),
        "vib_kurtosis": np.random.normal(6.5, 0.8, n_c),
        "current": np.random.normal(60.0, 3.0, n_c),
        "pressure": np.random.normal(c["p"], 0.3, n_c),
        "cavitation_index": np.random.normal(0.30, 0.08, n_c),
        "temp": np.random.normal(c["t"], 3.0, n_c),
        "temp_delta": np.random.normal(3.0, 1.5, n_c),
        "target": 2,
    }

    df = pd.concat([pd.DataFrame(data_h), pd.DataFrame(data_w), pd.DataFrame(data_c)])
    return df.sample(frac=1).reset_index(drop=True)


def _report_path() -> str:
    """Path to the ML metrics report file (next to model artifacts)."""
    base = os.path.dirname(Config.MODEL_PATH)
    return os.path.join(base, "ml_report.txt")


def train():
    print(
        "🧪 Starting Predictive Maintenance Engine model training (Advanced Calibration)..."
    )

    df = generate_synthetic_data()
    X = df[Config.FEATURE_NAMES]
    y = df["target"]

    X_train, X_val, y_train, y_val = train_test_split(
        X, y, test_size=0.2, stratify=y, random_state=42
    )

    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    X_val_scaled = scaler.transform(X_val)

    model = RandomForestClassifier(
        n_estimators=150, max_depth=10, class_weight="balanced", random_state=42
    )
    model.fit(X_train_scaled, y_train)

    y_pred = model.predict(X_val_scaled)
    bal_acc = balanced_accuracy_score(y_val, y_pred)
    report = classification_report(
        y_val,
        y_pred,
        target_names=["Healthy", "Warning", "Critical"],
        digits=4,
    )
    cm = confusion_matrix(y_val, y_pred)
    imp = dict(zip(Config.FEATURE_NAMES, model.feature_importances_))
    imp_sorted = sorted(imp.items(), key=lambda x: -x[1])

    report_lines = [
        "ML Training Report (PdM Pump Monitor)",
        "====================================",
        "",
        "Dataset: synthetic, 80% train / 20% val (stratified), seed=42.",
        "Model: RandomForestClassifier(n_estimators=150, max_depth=10, class_weight='balanced').",
        "",
        "Validation metrics",
        "------------------",
        f"Balanced accuracy: {bal_acc:.4f}",
        "",
        "Classification report (validation set):",
        report,
        "Confusion matrix (rows=true, cols=pred):",
        "  Healthy  Warning  Critical",
        f"  {cm[0][0]:7d}  {cm[0][1]:7d}  {cm[0][2]:8d}   <- Healthy",
        f"  {cm[1][0]:7d}  {cm[1][1]:7d}  {cm[1][2]:8d}   <- Warning",
        f"  {cm[2][0]:7d}  {cm[2][1]:7d}  {cm[2][2]:8d}   <- Critical",
        "",
        "Feature importance (validation):",
    ]
    for name, val in imp_sorted:
        report_lines.append(f"  {name}: {val:.4f}")
    report_lines.append("")
    report_text = "\n".join(report_lines)

    print(report_text)
    report_path = _report_path()
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    with open(report_path, "w") as f:
        f.write(report_text)
    print(f"📄 Report saved to {report_path}")

    print(f"💾 Saving model to {Config.MODEL_PATH}...")
    joblib.dump(model, Config.MODEL_PATH)

    print(f"💾 Saving scaler to {Config.SCALER_PATH}...")
    joblib.dump(scaler, Config.SCALER_PATH)

    print("✅ Training complete. Risk thresholds updated.")


if __name__ == "__main__":
    train()
