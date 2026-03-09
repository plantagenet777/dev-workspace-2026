"""Smoke test: verify environment and artifacts before launch.

When run as script, exits 0 on success, 1 on failure (Docker/CI).
When run via pytest, executes as test_smoke_run().
"""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.config import Config


def run_smoke_test() -> bool:
    print("🔍 Starting Predictive Maintenance Engine Smoke Test...")
    errors = 0

    for folder in ["models", "app", "config"]:
        if os.path.exists(folder):
            print(f"✅ Folder found: {folder}")
        else:
            print(f"❌ Folder missing: {folder}")
            errors += 1

    if os.path.exists(Config.MODEL_PATH):
        print(f"✅ Model artifact found: {Config.MODEL_PATH}")
    else:
        print(f"⚠️ Model artifact missing: {Config.MODEL_PATH}")
        print("   (Note: Run 'python3 train_and_save.py' to generate it)")
        errors += 1

    try:
        import joblib
        import pandas
        import sklearn
        import scipy
        import paho.mqtt

        print("✅ All core libraries are installed correctly.")
    except ImportError as e:
        print(f"❌ Library missing: {e}")
        errors += 1

    try:
        test_id = Config.PUMP_ID
        print(f"✅ Config check: Monitoring Asset ID -> {test_id}")
    except Exception as e:
        print(f"❌ Config error: {e}")
        errors += 1

    print("-" * 40)
    if errors == 0:
        print("🚀 SMOKE TEST PASSED: System is ready for launch.")
        return True
    else:
        print(f"🛑 SMOKE TEST FAILED: Found {errors} issues.")
        return False


def test_smoke_run() -> None:
    """Pytest smoke test (artifacts and environment). Skipped if model missing (CI without train). Script run yields exit 0/1."""
    if not os.path.exists(Config.MODEL_PATH):
        pytest.skip(
            "Model not found (run 'make train'); smoke exit codes checked when run as script"
        )
    assert (
        run_smoke_test() is True
    ), "Smoke test failed: run 'make train' or fix environment"


if __name__ == "__main__":
    success = run_smoke_test()
    sys.exit(0 if success else 1)
