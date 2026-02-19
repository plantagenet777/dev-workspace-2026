"""Config validation: fail-fast at startup on invalid thresholds and required env."""
from config.config import Config


class ConfigValidationError(Exception):
    """Raised when config validation fails (invalid range or missing required value)."""


def _get(name: str, default: float | None = None) -> float:
    v = getattr(Config, name, default)
    if v is None:
        raise ConfigValidationError(f"Missing config: {name}")
    try:
        return float(v)
    except (TypeError, ValueError):
        raise ConfigValidationError(
            f"Config {name} must be numeric, got {type(v).__name__}"
        )


def validate_config() -> None:
    """Validate critical config values. Raises ConfigValidationError on first failure."""
    # Probabilities in [0, 1]
    for key in (
        "PROB_CRITICAL",
        "PROB_WARNING",
        "PROB_HYSTERESIS_EXIT_WARNING",
        "PROB_CRITICAL_STARTUP",
        "SMOOTH_ALPHA_RISING",
        "SMOOTH_ALPHA_FALLING",
        "SMOOTH_ALPHA_VERY_HIGH",
        "SMOOTH_HIGH_RISK_THRESHOLD",
        "PROB_MIN_FOR_VIBRATION_WARNING",
    ):
        v = _get(key, 0.5)
        if not (0 <= v <= 1):
            raise ConfigValidationError(f"{key} must be in [0, 1], got {v}")

    # Positive integers
    for key in (
        "FEATURE_WINDOW_SIZE",
        "SMOOTHING_WINDOW_SIZE",
        "RISK_HISTORY_SIZE",
        "STARTUP_ITERATIONS",
        "MQTT_BATCH_SIZE",
        "INFERENCE_RETRY_ATTEMPTS",
        "CRITICAL_EXIT_MIN_LOW_VIB_STEPS",
    ):
        v = _get(key, 1)
        if v < 1 or int(v) != v:
            raise ConfigValidationError(f"{key} must be a positive integer, got {v}")

    # Vibration: warning < critical <= interlock (mm/s)
    vib_warn = _get("VIBRATION_WARNING_ENTRY_MMPS", 5.5)
    vib_crit = _get("VIBRATION_CRITICAL_MMPS", 7.1)
    vib_exit_w = _get("VIBRATION_HYSTERESIS_EXIT_WARNING_MMPS", 4.5)
    vib_exit_c = _get("VIBRATION_HYSTERESIS_EXIT_CRITICAL_MMPS", 6.0)
    if vib_exit_w >= vib_warn:
        raise ConfigValidationError(
            f"VIBRATION_HYSTERESIS_EXIT_WARNING_MMPS ({vib_exit_w}) must be < VIBRATION_WARNING_ENTRY_MMPS ({vib_warn})"
        )
    if vib_exit_c >= vib_crit:
        raise ConfigValidationError(
            f"VIBRATION_HYSTERESIS_EXIT_CRITICAL_MMPS ({vib_exit_c}) must be < VIBRATION_CRITICAL_MMPS ({vib_crit})"
        )

    # Telemetry ranges: min < max
    telemetry_pairs = [
        ("TELEMETRY_VIB_RMS_MIN", "TELEMETRY_VIB_RMS_MAX"),
        ("TELEMETRY_PRESSURE_MIN", "TELEMETRY_PRESSURE_MAX"),
        ("TELEMETRY_TEMP_MIN", "TELEMETRY_TEMP_MAX"),
        ("TELEMETRY_CURRENT_MIN", "TELEMETRY_CURRENT_MAX"),
        ("TELEMETRY_CAVITATION_INDEX_MIN", "TELEMETRY_CAVITATION_INDEX_MAX"),
    ]
    for low, high in telemetry_pairs:
        lo = _get(low, 0)
        hi = _get(high, 100)
        if lo >= hi:
            raise ConfigValidationError(f"Config {low} ({lo}) must be < {high} ({hi})")

    # Paths are not validated here so that tests/simulate_failure can run without artifacts.
    # Use validate_artifacts() from main_app after validate_config() for fail-fast on missing model.


def validate_artifacts() -> None:
    """Ensure MODEL_PATH and SCALER_PATH exist. Raises ConfigValidationError if not."""
    from pathlib import Path

    for name, path_attr in (
        ("MODEL_PATH", "MODEL_PATH"),
        ("SCALER_PATH", "SCALER_PATH"),
    ):
        path = getattr(Config, path_attr, None)
        if path and isinstance(path, str) and not Path(path).is_file():
            raise ConfigValidationError(
                f"{name} does not exist or is not a file: {path}"
            )
