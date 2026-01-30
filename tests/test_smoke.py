import os
import sys
from pathlib import Path

# Добавляем корень проекта в пути поиска модулей
sys.path.append(str(Path(__file__).resolve().parent.parent))

from config.config import Config

def run_smoke_test():
    print("🔍 Starting ICL Reliability Engine Smoke Test...")
    errors = 0

    # 1. Проверка структуры папок
    for folder in ['models', 'app', 'config']:
        if os.path.exists(folder):
            print(f"✅ Folder found: {folder}")
        else:
            print(f"❌ Folder missing: {folder}")
            errors += 1

    # 2. Проверка файлов моделей
    if os.path.exists(Config.MODEL_PATH):
        print(f"✅ Model artifact found: {Config.MODEL_PATH}")
    else:
        print(f"⚠️ Model artifact missing: {Config.MODEL_PATH}")
        print("   (Note: Run 'python3 train_and_save.py' to generate it)")
        errors += 1

    # 3. Проверка библиотек (Импорты)
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

    # 4. Проверка конфига
    try:
        test_id = Config.PUMP_ID
        print(f"✅ Config check: Monitoring Asset ID -> {test_id}")
    except Exception as e:
        print(f"❌ Config error: {e}")
        errors += 1

    # Итог
    print("-" * 40)
    if errors == 0:
        print("🚀 SMOKE TEST PASSED: System is ready for launch.")
        return True
    else:
        print(f"🛑 SMOKE TEST FAILED: Found {errors} issues.")
        return False

if __name__ == "__main__":
    success = run_smoke_test()
    sys.exit(0 if success else 1)