"""Unit tests for app modules."""
import pytest
import numpy as np
import pandas as pd
from unittest.mock import patch, MagicMock

from app.feature_extractor import FeatureExtractor
from app.data_processor import DataProcessor
from app.notifier import send_telegram_alert


# --- FeatureExtractor ---

def test_calculate_vibration_metrics():
    """Проверка расчёта метрик вибрации."""
    signal = np.sin(2 * np.pi * 50 * np.linspace(0, 1, 1000))
    result = FeatureExtractor.calculate_vibration_metrics(signal)
    assert "vib_rms" in result
    assert "vib_crest" in result
    assert "vib_kurtosis" in result
    assert result["vib_rms"] > 0
    assert result["vib_crest"] > 0


def test_get_cavitation_index():
    """Проверка расчёта индекса кавитации."""
    assert FeatureExtractor.get_cavitation_index(5.0, 2.0) == 0.4
    assert FeatureExtractor.get_cavitation_index(0, 2.0) == 0


def test_get_feature_vector():
    """Проверка формирования вектора признаков."""
    df = pd.DataFrame({
        "vib_rms": np.random.normal(2.5, 0.3, 30),
        "current": np.random.normal(45, 2, 30),
        "pressure": np.random.normal(6.0, 0.2, 30),
        "temp": np.random.normal(38, 2, 30),
    })
    extractor = FeatureExtractor()
    vector = extractor.get_feature_vector(df)
    assert vector.shape == (1, 7)


# --- DataProcessor.prepare_batch ---

def test_prepare_batch_valid():
    """Проверка prepare_batch с корректными данными."""
    processor = DataProcessor()
    buffer = [
        {"vib_rms": 2.0, "current": 45, "pressure": 6.0, "temp": 38}
        for _ in range(30)
    ]
    features, status = processor.prepare_batch(buffer)
    assert features is not None
    assert status == "OK"
    assert features.shape == (1, 7)


def test_prepare_batch_empty():
    """Проверка prepare_batch с пустым буфером."""
    processor = DataProcessor()
    features, status = processor.prepare_batch([])
    assert features is None
    assert status == "EMPTY_BUFFER"


def test_prepare_batch_missing_columns():
    """Проверка prepare_batch при отсутствии колонок."""
    processor = DataProcessor()
    buffer = [{"vib_rms": 2.0} for _ in range(30)]
    features, status = processor.prepare_batch(buffer)
    assert features is None
    assert "MISSING_COLUMNS" in status


# --- PumpPredictor ---

def test_predictor_without_model():
    """Проверка predictor при отсутствии модели."""
    with patch("app.predictor.Config") as mock_config:
        mock_config.MODEL_PATH = "/nonexistent/model.joblib"
        mock_config.SCALER_PATH = "/nonexistent/scaler.joblib"
        from app.predictor import PumpPredictor
        predictor = PumpPredictor()
        status, prob = predictor.predict(np.zeros((1, 7)))
        assert status == "UNKNOWN (Model not loaded)"
        assert prob == 0.0


def test_predictor_with_mock_model():
    """Проверка predictor с замоканной моделью."""
    mock_model = MagicMock()
    mock_model.predict_proba.return_value = [[0.2, 0.8]]
    mock_scaler = MagicMock()
    mock_scaler.transform.return_value = np.zeros((1, 7))

    with patch("app.predictor.joblib.load") as mock_load:
        mock_load.side_effect = [mock_model, mock_scaler]
        from app.predictor import PumpPredictor
        with patch("app.predictor.Config") as mock_config:
            mock_config.MODEL_PATH = "model.joblib"
            mock_config.SCALER_PATH = "scaler.joblib"
            mock_config.PROB_CRITICAL = 0.85
            mock_config.PROB_WARNING = 0.60
            predictor = PumpPredictor()
            status, prob = predictor.predict(np.zeros((1, 7)))
            assert status in ["CRITICAL", "WARNING", "HEALTHY"]
            assert 0 <= prob <= 1


# --- Notifier ---

def test_send_telegram_alert_skips_when_not_configured():
    """Проверка, что notifier пропускает отправку без токена."""
    with patch("app.notifier.Config") as mock_config:
        mock_config.TELEGRAM_TOKEN = ""
        mock_config.TELEGRAM_CHAT_ID = ""
        send_telegram_alert("test")  # Не должен падать


def test_send_telegram_alert_success():
    """Проверка успешной отправки в Telegram."""
    with patch("app.notifier.Config") as mock_config:
        mock_config.TELEGRAM_TOKEN = "fake_token"
        mock_config.TELEGRAM_CHAT_ID = "123"
        with patch("app.notifier.requests.post") as mock_post:
            mock_post.return_value.status_code = 200
            send_telegram_alert("test message")
