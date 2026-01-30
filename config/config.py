import os
from pathlib import Path
from dotenv import load_dotenv

# Загружаем переменные из .env файла, если он существует
load_dotenv()

class Config:
    """Централизованная конфигурация системы мониторинга ICL Rotem"""

    # --- ПУТИ К ДИРЕКТОРИЯМ ---
    # Определяем корень проекта для корректной работы путей
    BASE_DIR = Path(__file__).resolve().parent.parent
    
    # --- MQTT SETTINGS ---
    MQTT_BROKER = os.getenv("MQTT_BROKER", "10.20.30.45")
    MQTT_PORT = int(os.getenv("MQTT_PORT", 8883))  # По умолчанию TLS порт
    MQTT_USE_TLS = os.getenv("MQTT_USE_TLS", "true").lower() in ("true", "1", "yes")
    MQTT_KEEPALIVE = 60

    # --- ASSET IDENTITY ---
    PUMP_ID = os.getenv("PUMP_ID", "WARMAN_04")
    SECTION_ID = os.getenv("SECTION_ID", "ROTEM_PHOSPHORIC_4")

    # --- TELEGRAM ---
    TELEGRAM_TOKEN = os.getenv("TG_TOKEN", "")
    TELEGRAM_CHAT_ID = os.getenv("TG_CHAT_ID", "")

    # --- TOPICS ---
    TOPIC_TELEMETRY = f"rotem/pumps/{PUMP_ID}/telemetry"
    TOPIC_ALERTS = f"rotem/pumps/{PUMP_ID}/alerts"
    TOPIC_STATUS = f"rotem/pumps/{PUMP_ID}/status"

    # --- SECURITY (TLS) ---
    # В контейнере это будет /app/certs, локально — папка certs в проекте
    CERT_DIR = os.getenv("CERT_DIR", str(BASE_DIR / "certs"))
    CA_CERT = os.path.join(CERT_DIR, "ca.crt")
    CLIENT_CERT = os.path.join(CERT_DIR, "client.crt")
    CLIENT_KEY = os.path.join(CERT_DIR, "client.key")

    # --- LOGGING ---
    LOG_DIR = os.getenv("LOG_DIR", str(BASE_DIR / "logs"))
    PREDICTION_HISTORY_PATH = os.path.join(LOG_DIR, "prediction_history.csv")
    APP_STATUS_PATH = os.path.join(LOG_DIR, "app_status.log")

    # --- MODEL PARAMETERS ---
    # Модели лежат в папке models в корне
    MODEL_PATH = str(BASE_DIR / "models" / "pump_rf_v1.joblib")
    SCALER_PATH = str(BASE_DIR / "models" / "scaler_v1.joblib")
    FEATURE_NAMES = [
        "vib_rms", "vib_crest", "vib_kurtosis",
        "current", "pressure", "cavitation_index", "temp"
    ]

    # --- THRESHOLDS (Пороги чувствительности) ---
    PROB_CRITICAL = 0.85 
    PROB_WARNING = 0.60 
    WINDOW_SIZE = 30  # Размер скользящего окна (30 секунд при 1Гц)

    # --- SIGNAL PROCESSING ---
    BUTTER_ORDER = 3
    BUTTER_CUTOFF = 0.1  # Частота среза

    @staticmethod
    def get_info():
        return f"--- Config loaded for {Config.PUMP_ID} (Broker: {Config.MQTT_BROKER}) ---"