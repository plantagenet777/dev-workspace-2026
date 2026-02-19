"""Shared config helpers for rules, predictor, and other modules."""
from typing import Any


def config_float(config: Any, name: str, default: float) -> float:
    """Return numeric config value; use default when missing or not a number (e.g. under Mock)."""
    v = getattr(config, name, default)
    if isinstance(v, (int, float)):
        return float(v)
    return default
