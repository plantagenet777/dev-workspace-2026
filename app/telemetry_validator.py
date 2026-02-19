"""Validate raw telemetry ranges before DSP/ML to avoid corrupted features from sensor faults."""
from collections.abc import Sequence
from typing import Any

from config.config import Config


def _get_float(config: type, name: str, default: float) -> float:
    v = getattr(config, name, default)
    return float(v) if isinstance(v, (int, float)) else default


def validate_telemetry_record(record: dict[str, Any]) -> tuple[bool, str]:
    """Validate a single telemetry record against configured min/max ranges.

    Args:
        record: Single telemetry dict with vib_rms, current, pressure, temp, cavitation_index, etc.

    Returns:
        (is_valid, error_detail): True and empty string if valid; False and message if invalid.

    Note:
        Missing fields are handled later in DataProcessor (MISSING_COLUMNS). Here we only
        enforce range checks for fields that are present, to keep backward-compatible
        error codes for missing columns.
    """
    try:
        vib = float(record.get("vib_rms", 0.0))
        p = float(record.get("pressure", 0.0))
        t = float(record.get("temp", 0.0))
        i = float(record.get("current", 0.0))
        cav = float(record.get("cavitation_index", 0.0))
    except (TypeError, ValueError):
        return False, "INVALID_NUMERIC"

    v_min = _get_float(Config, "TELEMETRY_VIB_RMS_MIN", 0.0)
    v_max = _get_float(Config, "TELEMETRY_VIB_RMS_MAX", 25.0)
    if not (v_min <= vib <= v_max):
        return False, f"VIB_RMS_OUT_OF_RANGE:{vib}"

    p_min = _get_float(Config, "TELEMETRY_PRESSURE_MIN", 0.0)
    p_max = _get_float(Config, "TELEMETRY_PRESSURE_MAX", 15.0)
    if not (p_min <= p <= p_max):
        return False, f"PRESSURE_OUT_OF_RANGE:{p}"

    t_min = _get_float(Config, "TELEMETRY_TEMP_MIN", -20.0)
    t_max = _get_float(Config, "TELEMETRY_TEMP_MAX", 120.0)
    if not (t_min <= t <= t_max):
        return False, f"TEMP_OUT_OF_RANGE:{t}"

    i_min = _get_float(Config, "TELEMETRY_CURRENT_MIN", 0.0)
    i_max = _get_float(Config, "TELEMETRY_CURRENT_MAX", 80.0)
    if not (i_min <= i <= i_max):
        return False, f"CURRENT_OUT_OF_RANGE:{i}"

    cav_min = _get_float(Config, "TELEMETRY_CAVITATION_INDEX_MIN", 0.0)
    cav_max = _get_float(Config, "TELEMETRY_CAVITATION_INDEX_MAX", 50.0)
    if not (cav_min <= cav <= cav_max):
        return False, f"CAVITATION_INDEX_OUT_OF_RANGE:{cav}"

    return True, ""


def validate_telemetry_batch(
    buffer: Sequence[dict[str, Any]],
) -> tuple[list[dict[str, Any]] | None, str]:
    """Validate a batch of telemetry records; return only valid records or None with error.

    If any record is invalid, the whole batch is rejected to avoid mixing bad and good data
    in the feature window.

    Args:
        buffer: List or deque of telemetry dicts.

    Returns:
        (valid_list, status): (list of records, "OK") if all valid;
        (None, "INVALID_RANGE:...") if any record fails validation.
    """
    records = list(buffer)
    if not records:
        return None, "EMPTY_BUFFER"
    for idx, rec in enumerate(records):
        ok, detail = validate_telemetry_record(rec)
        if not ok:
            return None, f"INVALID_RANGE:{detail}"
    return records, "OK"
