import logging
import joblib
import numpy as np
from config.config import Config

logger = logging.getLogger("icl_engine")


class PumpPredictor:
    """Модуль инференса: загрузка модели и предсказание состояния насоса"""

    def __init__(self):
        self.model = None
        self.scaler = None
        self._load_artifacts()

    def _load_artifacts(self):
        """Загрузка обученных весов и скалера из папки models"""
        try:
            self.model = joblib.load(Config.MODEL_PATH)
            self.scaler = joblib.load(Config.SCALER_PATH)
            logger.info("Predictor: Model and Scaler loaded from %s", Config.MODEL_PATH)
        except Exception as e:
            logger.error("Predictor Error: Failed to load model artifacts. %s", e)
            # Мы не останавливаем программу, чтобы система могла работать в режиме сбора данных
            self.model = None
            self.scaler = None

    def predict(self, feature_vector):
        """
        Принимает вектор признаков, нормализует его и возвращает вердикт.
        """
        if self.model is None or self.scaler is None:
            return "UNKNOWN (Model not loaded)", 0.0

        try:
            # 1. Масштабирование признаков (приведение к среднему 0 и дисперсии 1)
            scaled_features = self.scaler.transform(feature_vector)

            # 2. Получение вероятности аномалии (Класс 1)
            # predict_proba возвращает массив [[prob_0, prob_1]]
            probabilities = self.model.predict_proba(scaled_features)[0]
            anomaly_prob = probabilities[1]

            # 3. Принятие решения на основе порогов из Config
            if anomaly_prob >= Config.PROB_CRITICAL:
                status = "CRITICAL"
            elif anomaly_prob >= Config.PROB_WARNING:
                status = "WARNING"
            else:
                status = "HEALTHY"

            return status, round(float(anomaly_prob), 3)

        except Exception as e:
            logger.warning("Inference Error: %s", e)
            return "ERROR", 0.0

    def get_diagnostics(self):
        """Возвращает важность признаков для интерпретации работы ИИ"""
        if self.model and hasattr(self.model, 'feature_importances_'):
            return self.model.feature_importances_
        return None