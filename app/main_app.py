import json
import os
import ssl
import time
import logging
from collections import deque
from pathlib import Path

import paho.mqtt.client as mqtt

from config.config import Config
from app.data_processor import DataProcessor
from app.predictor import PumpPredictor
from app.notifier import send_telegram_alert
from app.logger import setup_logging

logger = logging.getLogger("icl_engine")


def _append_prediction(timestamp: str, pump_id: str, status: str, prob: float, sensor_status: str):
    """Добавить запись в prediction_history.csv."""
    try:
        path = Path(Config.PREDICTION_HISTORY_PATH)
        path.parent.mkdir(parents=True, exist_ok=True)
        file_exists = path.exists()
        with open(path, "a", encoding="utf-8") as f:
            if not file_exists:
                f.write("timestamp,pump_id,status,anomaly_probability,sensor_status\n")
            f.write(f"{timestamp},{pump_id},{status},{prob},{sensor_status}\n")
    except (OSError, PermissionError) as e:
        logger.warning("Failed to write prediction history: %s", e)


class ICLReliabilityEngine:
    def __init__(self):
        setup_logging()
        logger.info(Config.get_info())
        
        # 1. Инициализация компонентов
        self.processor = DataProcessor()
        self.predictor = PumpPredictor()
        
        # 2. Буфер данных (окно 30 сек)
        self.buffer = deque(maxlen=Config.WINDOW_SIZE)
        
        # 3. Настройка MQTT клиента
        self.client = mqtt.Client(client_id=Config.PUMP_ID, clean_session=False)
        self.setup_security()
        
        # Привязка обработчиков
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        self.client.on_disconnect = self.on_disconnect

    def setup_security(self):
        """Настройка TLS v1.2 для защищенного контура завода (или пропуск для локальной разработки)"""
        if not Config.MQTT_USE_TLS:
            logger.warning("TLS disabled (MQTT_USE_TLS=false) — local dev mode")
            return
        try:
            self.client.tls_set(
                ca_certs=Config.CA_CERT,
                certfile=Config.CLIENT_CERT,
                keyfile=Config.CLIENT_KEY,
                tls_version=ssl.PROTOCOL_TLSv1_2
            )
            self.client.tls_insecure_set(True)
        except Exception as e:
            logger.critical("Security Config Error: %s", e)
            exit(1)

    def on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            mode = "Secure" if Config.MQTT_USE_TLS else "Plain"
            logger.info("Connected to %s Broker: %s", mode, Config.MQTT_BROKER)
            self.client.subscribe(Config.TOPIC_TELEMETRY, qos=1)
        else:
            logger.error("Connection failed. Code: %s", rc)

    def on_disconnect(self, client, userdata, rc):
        logger.warning("Disconnected from broker. Retrying...")

    def on_message(self, client, userdata, msg):
        try:
            # Парсинг входящей телеметрии
            payload = json.loads(msg.payload)
            self.buffer.append(payload)

            # Начинаем анализ, когда накопили полное окно данных
            if len(self.buffer) == Config.WINDOW_SIZE:
                self.run_analysis_pipeline()
                
        except Exception as e:
            logger.error("Error parsing message: %s", e)

    def run_analysis_pipeline(self):
        """Главный конвейер: Обработка -> Фильтрация -> ИИ -> Нотификация"""
        
        # 1. Подготовка батча и проверка здоровья датчиков
        features, sensor_status = self.processor.prepare_batch(self.buffer)
        
        if features is None:
            # Если система OFFLINE или данные критически повреждены
            self.publish_report({"status": "OFFLINE", "reason": sensor_status})
            return

        # 2. Получение предсказания от модели Random Forest
        status, prob = self.predictor.predict(features)

        # 3. Формирование финального отчета
        report = {
            "pump_id": Config.PUMP_ID,
            "status": status,
            "anomaly_probability": prob,
            "sensor_health": sensor_status,
            "timestamp": time.ctime()
        }

        # 4. Запись в prediction_history.csv
        _append_prediction(
            report["timestamp"], Config.PUMP_ID, status, prob, sensor_status
        )

        # 5. Публикация в сеть завода и отправка алертов
        self.publish_report(report)

        if status in ["CRITICAL", "WARNING"]:
            alert_msg = f"Pump: {Config.PUMP_ID}\nStatus: {status}\nProb: {prob}\nSensors: {sensor_status}"
            send_telegram_alert(alert_msg)
            logger.warning("ALERT SENT: %s (%.3f)", status, prob)

    def publish_report(self, report):
        self.client.publish(Config.TOPIC_ALERTS, json.dumps(report), qos=1)

    def start(self):
        try:
            logger.info("Starting Monitor Engine for %s...", Config.PUMP_ID)
            self.client.connect(Config.MQTT_BROKER, Config.MQTT_PORT, Config.MQTT_KEEPALIVE)
            self.client.loop_forever()
        except KeyboardInterrupt:
            logger.info("Stopping engine...")
            self.client.disconnect()

if __name__ == "__main__":
    engine = ICLReliabilityEngine()
    engine.start()