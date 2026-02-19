"""Healthcheck for container and local runs.

Uses Config.MODEL_PATH and Config.SCALER_PATH; project root is derived from
Config.BASE_DIR (config.__file__), so it works both in Docker (/app) and locally.
"""
import os
import sys

# Add project root to PYTHONPATH when run directly (e.g. python app/healthcheck.py)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.validation import ConfigValidationError, validate_artifacts, validate_config


def check_health() -> None:
    """Validate config and model/scaler artifacts; exit 0 on success, 1 on failure."""
    exit_code = 0
    try:
        validate_config()
        validate_artifacts()
    except ConfigValidationError as e:
        print(f"Healthcheck failed: {e}")
        exit_code = 1
    sys.exit(exit_code)


if __name__ == "__main__":
    check_health()
