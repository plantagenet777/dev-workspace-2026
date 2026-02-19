"""Unit tests for app modules."""
import pytest
import numpy as np
import pandas as pd
from unittest.mock import patch, MagicMock

import config.config as config_module
from config.config import Config
from app.feature_extractor import FeatureExtractor
from app.data_processor import DataProcessor
from app.notifier import send_telegram_alert
import app.rules as rules_module


def apply_zone_mock(mock_config, window_size=5, risk_history_size=5):
    """Set common Config mock attributes for predictor/zone tests (avoids repeating the same block)."""
    mock_config.SMOOTHING_WINDOW_SIZE = window_size
    mock_config.RISK_HISTORY_SIZE = risk_history_size
    mock_config.SMOOTH_ALPHA_RISING = 0.7
    mock_config.SMOOTH_ALPHA_FALLING = 0.65
    mock_config.VIBRATION_WARNING_MMPS = 4.5
    mock_config.VIBRATION_CRITICAL_MMPS = 7.1
    mock_config.VIBRATION_HYSTERESIS_EXIT_CRITICAL_MMPS = 6.0
    mock_config.VIBRATION_HYSTERESIS_EXIT_WARNING_MMPS = 4.5
    mock_config.VIBRATION_INTERLOCK_MMPS = 9.0
    mock_config.CAVITATION_CURRENT_MIN_AMP = 54.0
    mock_config.CAVITATION_PRESSURE_MAX_BAR = 4.0
    mock_config.CAVITATION_VIBRATION_MIN_MMPS = 4.5
    mock_config.CAVITATION_ALERT_MESSAGE = (
        "CAVITATION: Check inlet valve or sump level."
    )
    mock_config.DEGRADATION_CURRENT_MAX_AMP = 42.0
    mock_config.DEGRADATION_PRESSURE_MAX_BAR = 5.0
    mock_config.DEGRADATION_ALERT_MESSAGE = "DEGRADATION: Maintenance required."
    mock_config.CHOKED_CURRENT_MAX_AMP = 38.0
    mock_config.CHOKED_PRESSURE_MIN_BAR = 7.0
    mock_config.CHOKED_TEMP_MIN_C = 70.0
    mock_config.DEGRADATION_HYSTERESIS_CURRENT_AMP = 2.0
    mock_config.DEGRADATION_HYSTERESIS_PRESSURE_BAR = 0.3
    mock_config.AIR_INGESTION_VIB_CREST_MIN = 5.5
    mock_config.AIR_INGESTION_VIB_RMS_MIN_MMPS = 5.0
    mock_config.TEMP_WARNING_C = 60.0
    mock_config.TEMP_CRITICAL_C = 75.0
    mock_config.TEMP_ALERT_MESSAGE = "High temperature."
    mock_config.OVERLOAD_CURRENT_MIN_AMP = 50.0
    mock_config.OVERLOAD_ALERT_MESSAGE = "Motor overload."
    mock_config.PRESSURE_HIGH_WARNING_BAR = 7.0
    mock_config.PRESSURE_HIGH_ALERT_MESSAGE = "High pressure."
    mock_config.PROB_CRITICAL = 0.8
    mock_config.PROB_WARNING = 0.65
    mock_config.PROB_CRITICAL_STARTUP = 0.95
    # Smoothing high-risk scaling
    mock_config.SMOOTH_HIGH_RISK_THRESHOLD = 0.8
    mock_config.SMOOTH_ALPHA_VERY_HIGH = 0.92
    mock_config.FEATURE_NAMES = Config.FEATURE_NAMES


# --- FeatureExtractor ---


def test_calculate_vibration_metrics():
    """Verify vibration metrics calculation."""
    signal = np.sin(2 * np.pi * 50 * np.linspace(0, 1, 1000))
    result = FeatureExtractor.calculate_vibration_metrics(signal)
    assert "vib_rms" in result
    assert "vib_crest" in result
    assert "vib_kurtosis" in result
    assert result["vib_rms"] > 0
    assert result["vib_crest"] > 0


def test_get_cavitation_index():
    """Verify cavitation index calculation."""
    assert FeatureExtractor.get_cavitation_index(5.0, 2.0) == 0.4
    assert FeatureExtractor.get_cavitation_index(0, 2.0) == 0


def test_get_feature_vector():
    """Verify feature vector shape and content (includes temp_delta)."""
    df = pd.DataFrame(
        {
            "vib_rms": np.random.normal(2.5, 0.3, 30),
            "current": np.random.normal(45, 2, 30),
            "pressure": np.random.normal(6.0, 0.2, 30),
            "temp": np.random.normal(38, 2, 30),
        }
    )
    extractor = FeatureExtractor()
    vector = extractor.get_feature_vector(df)
    assert vector.shape == (1, 8)
    vector_with_prev = extractor.get_feature_vector(df, prev_temp=36.0)
    assert vector_with_prev.shape == (1, 8)
    assert vector_with_prev[0, -1] != 0  # temp_delta when prev_temp given


# --- DataProcessor.prepare_batch ---


def test_prepare_batch_valid():
    """Verify prepare_batch with full column set."""
    processor = DataProcessor()
    buffer = [
        {
            "vib_rms": 2.0,
            "current": 45,
            "pressure": 6.0,
            "temp": 38,
            "vib_crest": 3.0,
            "vib_kurtosis": 3.2,
            "cavitation_index": 0.05,
        }
        for _ in range(30)
    ]
    features, status, iso_vib_rms = processor.prepare_batch(buffer)
    assert features is not None
    assert status == "OK"
    assert iso_vib_rms is None  # USE_ISO_BAND_FOR_ZONES default False


def test_prepare_batch_empty():
    """Verify prepare_batch with empty buffer."""
    processor = DataProcessor()
    features, status, iso_vib_rms = processor.prepare_batch([])
    assert features is None
    assert status == "EMPTY_BUFFER"
    assert iso_vib_rms is None


def test_prepare_batch_missing_columns():
    """Verify prepare_batch when columns are missing."""
    processor = DataProcessor()
    buffer = [{"vib_rms": 2.0} for _ in range(30)]
    features, status, iso_vib_rms = processor.prepare_batch(buffer)
    assert features is None
    assert "MISSING_COLUMNS" in status
    assert iso_vib_rms is None


def test_prepare_batch_iso_band_returns_rms():
    """When USE_ISO_BAND_FOR_ZONES is True, prepare_batch returns iso_vib_rms in 10–1000 Hz band."""
    processor = DataProcessor()
    buffer = [
        {
            "vib_rms": 2.0 + 0.05 * (i % 10),
            "current": 45,
            "pressure": 6.0,
            "temp": 38,
            "vib_crest": 3.0,
            "vib_kurtosis": 3.2,
            "cavitation_index": 0.05,
        }
        for i in range(30)
    ]
    with patch("app.data_processor.Config") as mock_config:
        mock_config.USE_ISO_BAND_FOR_ZONES = True
        mock_config.ISO_BAND_LOW_HZ = 10.0
        mock_config.ISO_BAND_HIGH_HZ = 1000.0
        features, status, iso_vib_rms = processor.prepare_batch(buffer)
    assert features is not None
    assert status == "OK"
    assert iso_vib_rms is not None
    assert isinstance(iso_vib_rms, float)
    assert iso_vib_rms >= 0


# --- PumpPredictor ---


def test_predictor_without_model():
    """Verify predictor when model is missing: mock Config before importing predictor."""
    try:
        with patch("app.predictor.Config") as mock_config:
            mock_config.MODEL_PATH = "/nonexistent/model.joblib"
            mock_config.SCALER_PATH = "/nonexistent/scaler.joblib"
            apply_zone_mock(mock_config)
            mock_config.CAVITATION_ALERT_MESSAGE = "CAVITATION test message."
            mock_config.DEGRADATION_ALERT_MESSAGE = "DEGRADATION test message."
            from app.predictor import PumpPredictor

            predictor = PumpPredictor()
            n_features = len(Config.FEATURE_NAMES)
            status, prob = predictor.predict(np.zeros((1, n_features)))
            assert status == "UNKNOWN (No Model)"
            assert prob == 0.0
    finally:
        rules_module.Config = config_module.Config


def test_predictor_with_mock_model():
    """Verify predictor with mocked model: joblib.load patched before creating predictor."""
    mock_model = MagicMock()
    mock_model.predict_proba.return_value = [[0.2, 0.8]]
    mock_scaler = MagicMock()
    n_features = len(Config.FEATURE_NAMES)
    mock_scaler.transform.return_value = np.zeros((1, n_features))

    try:
        with patch("app.predictor.joblib.load") as mock_load:
            mock_load.side_effect = [mock_model, mock_scaler]
            with patch("app.predictor.Config", config_module.Config):
                from app.predictor import PumpPredictor

                predictor = PumpPredictor()
                predictor.feature_names = Config.FEATURE_NAMES
                test_features = pd.DataFrame(
                    np.zeros((1, n_features)), columns=predictor.feature_names
                )
                status, prob = predictor.predict(test_features)

                assert any(
                    word in status for word in ["CRITICAL", "WARNING", "HEALTHY"]
                )
                mock_load.assert_called()
    finally:
        rules_module.Config = config_module.Config


def test_predictor_reset_smoothing():
    """Verify reset_smoothing clears state and predictor still works after reset."""
    mock_model = MagicMock()
    mock_model.predict_proba.return_value = [[0.8, 0.1, 0.1]]  # healthy
    mock_scaler = MagicMock()
    n_features = len(Config.FEATURE_NAMES)
    mock_scaler.transform.return_value = np.zeros((1, n_features))

    try:
        with patch("app.predictor.joblib.load") as mock_load:
            mock_load.side_effect = [mock_model, mock_scaler]
            with patch("app.predictor.Config", config_module.Config):
                from app.predictor import PumpPredictor

                predictor = PumpPredictor()
                predictor.feature_names = Config.FEATURE_NAMES
                df = pd.DataFrame(
                    np.zeros((1, n_features)), columns=predictor.feature_names
                )
                predictor.predict(df)
                predictor.reset_smoothing()
                assert len(predictor.risk_history) == 0
                assert predictor.smoothed_risk is None
                assert len(predictor._feature_buffer) == 0
                status, prob = predictor.predict(df)
                assert any(
                    word in status for word in ["CRITICAL", "WARNING", "HEALTHY"]
                )
    finally:
        rules_module.Config = config_module.Config


def test_predictor_cavitation_detection():
    """When high current + low pressure + high vibration, status is CRITICAL and last_alert_reason is set."""
    mock_model = MagicMock()
    mock_model.predict_proba.return_value = [[0.2, 0.3, 0.5]]  # some risk
    mock_scaler = MagicMock()
    n_features = len(Config.FEATURE_NAMES)
    mock_scaler.transform.return_value = np.zeros((1, n_features))

    try:
        with patch("app.predictor.joblib.load") as mock_load:
            mock_load.side_effect = [mock_model, mock_scaler]
            with patch("app.predictor.Config", config_module.Config):
                from app.predictor import PumpPredictor

                predictor = PumpPredictor()
                predictor.feature_names = Config.FEATURE_NAMES
                # Cavitation rule: current >= 54, pressure <= 4, vib >= 9 mm/s (Config).
                # High flow (55) + low pressure (3.5) + vib 9.5 -> CavitationRule fires.
                row = {
                    "vib_rms": 9.5,
                    "vib_crest": 4.0,
                    "vib_kurtosis": 3.0,
                    "current": 55.0,
                    "pressure": 3.5,
                    "cavitation_index": 0.2,
                    "temp": 50.0,
                    "temp_delta": 0.0,
                }
                df = pd.DataFrame([row])
                for _ in range(3):
                    status, prob = predictor.predict(df, is_startup=False)
                assert status == "CRITICAL"
                alarm_causes = getattr(predictor, "last_alarm_causes", []) or []
                assert rules_module.AlarmCause.CAVITATION in alarm_causes
                assert predictor.last_alert_reason is not None
                assert "CAVITATION" in predictor.last_alert_reason
    finally:
        rules_module.Config = config_module.Config


def test_predictor_degradation_detection():
    """When low current + low pressure (vs Q–H curve), status is WARNING and last_alert_reason is set."""
    mock_model = MagicMock()
    mock_model.predict_proba.return_value = [[0.7, 0.2, 0.1]]  # mostly healthy
    mock_scaler = MagicMock()
    n_features = len(Config.FEATURE_NAMES)
    mock_scaler.transform.return_value = np.zeros((1, n_features))

    try:
        with patch("app.predictor.joblib.load") as mock_load:
            mock_load.side_effect = [mock_model, mock_scaler]
            with patch("app.predictor.Config", config_module.Config):
                from app.predictor import PumpPredictor

                predictor = PumpPredictor()
                predictor.feature_names = Config.FEATURE_NAMES
                # Low flow (current 40) + low pressure (4.5) -> degradation (pressure 4.5 < 5.0 mock threshold)
                row = {
                    "vib_rms": 3.5,
                    "vib_crest": 3.0,
                    "vib_kurtosis": 2.8,
                    "current": 40.0,
                    "pressure": 4.5,
                    "cavitation_index": 0.05,
                    "temp": 48.0,
                    "temp_delta": 0.0,
                }
                df = pd.DataFrame([row])
                for _ in range(3):
                    status, prob = predictor.predict(df, is_startup=False)
                assert status == "WARNING"
                assert predictor.last_alert_reason is not None
                assert (
                    "MAINTENANCE" in predictor.last_alert_reason
                    or "wear" in predictor.last_alert_reason.lower()
                )
                assert (
                    "Residual" in predictor.last_alert_reason
                    or "shutdown" in predictor.last_alert_reason.lower()
                )
    finally:
        rules_module.Config = config_module.Config


def test_update_smoothing_uses_iso_vib_rms_over_latest_telemetry():
    """_update_smoothing_and_status should prefer iso_vib_rms for vibration metrics."""
    mock_model = MagicMock()
    mock_model.predict_proba.return_value = [[0.1, 0.2, 0.7]]
    mock_scaler = MagicMock()
    n_features = len(Config.FEATURE_NAMES)
    mock_scaler.transform.return_value = np.zeros((1, n_features))

    try:
        with patch("app.predictor.joblib.load") as mock_load:
            mock_load.side_effect = [mock_model, mock_scaler]
            with patch("app.predictor.Config") as mock_config:
                apply_zone_mock(mock_config, window_size=1, risk_history_size=1)
                from app.predictor import PumpPredictor

                predictor = PumpPredictor()
                predictor.feature_names = Config.FEATURE_NAMES
                base_row = {
                    "vib_rms": 2.0,
                    "vib_crest": 3.0,
                    "vib_kurtosis": 3.0,
                    "current": 45.0,
                    "pressure": 6.0,
                    "cavitation_index": 0.1,
                    "temp": 40.0,
                    "temp_delta": 0.0,
                }
                df = pd.DataFrame([base_row])
                iso_vib = 5.5
                latest = {**base_row, "vib_rms": 9.9}

                (
                    smoothed_df,
                    display_prob,
                    status,
                    vib_rms,
                    vib_crest,
                    current,
                    pressure,
                    temp,
                    latest_vib,
                    latest_crest,
                    latest_current,
                    latest_pressure,
                    latest_temp,
                    smoothed_prob,
                ) = predictor._update_smoothing_and_status(
                    df,
                    is_startup=False,
                    latest_telemetry=latest,
                    iso_vib_rms=iso_vib,
                )

                assert vib_rms == pytest.approx(iso_vib)
                assert latest_vib == pytest.approx(iso_vib)
    finally:
        rules_module.Config = config_module.Config


def test_update_smoothing_uses_latest_telemetry_without_iso():
    """_update_smoothing_and_status should override latest_* from latest_telemetry when iso_vib_rms is None."""
    mock_model = MagicMock()
    mock_model.predict_proba.return_value = [[0.1, 0.2, 0.7]]
    mock_scaler = MagicMock()
    n_features = len(Config.FEATURE_NAMES)
    mock_scaler.transform.return_value = np.zeros((1, n_features))

    try:
        with patch("app.predictor.joblib.load") as mock_load:
            mock_load.side_effect = [mock_model, mock_scaler]
            with patch("app.predictor.Config") as mock_config:
                apply_zone_mock(mock_config, window_size=1, risk_history_size=1)
                from app.predictor import PumpPredictor

                predictor = PumpPredictor()
                predictor.feature_names = Config.FEATURE_NAMES
                base_row = {
                    "vib_rms": 2.0,
                    "vib_crest": 3.0,
                    "vib_kurtosis": 3.0,
                    "current": 45.0,
                    "pressure": 6.0,
                    "cavitation_index": 0.1,
                    "temp": 40.0,
                    "temp_delta": 0.0,
                }
                df = pd.DataFrame([base_row])
                latest = {
                    "vib_rms": 7.0,
                    "vib_crest": 4.5,
                    "current": 50.0,
                    "pressure": 5.5,
                    "temp": 55.0,
                }

                (
                    smoothed_df,
                    display_prob,
                    status,
                    vib_rms,
                    vib_crest,
                    current,
                    pressure,
                    temp,
                    latest_vib,
                    latest_crest,
                    latest_current,
                    latest_pressure,
                    latest_temp,
                    smoothed_prob,
                ) = predictor._update_smoothing_and_status(
                    df,
                    is_startup=False,
                    latest_telemetry=latest,
                    iso_vib_rms=None,
                )

                assert latest_vib == pytest.approx(7.0)
                assert latest_crest == pytest.approx(4.5)
                assert latest_current == pytest.approx(50.0)
                assert latest_pressure == pytest.approx(5.5)
                assert latest_temp == pytest.approx(55.0)
    finally:
        rules_module.Config = config_module.Config


# --- Notifier ---


def test_send_telegram_alert_skips_when_not_configured():
    """Verify notifier skips send when token is not configured."""
    with patch("app.notifier.Config") as mock_config:
        mock_config.TELEGRAM_TOKEN = ""
        mock_config.TELEGRAM_CHAT_ID = ""
        send_telegram_alert("test")


def test_send_telegram_alert_success():
    """Verify successful Telegram send."""
    with patch("app.notifier.Config") as mock_config:
        mock_config.TELEGRAM_TOKEN = "fake_token"
        mock_config.TELEGRAM_CHAT_ID = "123"
        with patch("app.notifier.requests.post") as mock_post:
            mock_post.return_value.status_code = 200
            send_telegram_alert("test message")


# --- Rule trip/alarm causes ---


@pytest.mark.parametrize(
    "rule_cls,ctx_kwargs,expected_trip,expected_alarm_contains",
    [
        (
            rules_module.MechanicalRule,
            {
                "vib_rms": 8.0,
                "vib_crest": 7.0,
                "current": 45.0,
                "pressure": 6.0,
                "temp": 60.0,
                "latest_vib": 8.0,
                "latest_crest": 7.0,
                "latest_current": 45.0,
                "latest_pressure": 6.0,
                "latest_temp": 60.0,
                "smoothed_prob": 0.9,
                "prev_reason": None,
                "last_status": None,
                "debris_flag": True,
            },
            rules_module.TripCause.DEBRIS_IMPACT,
            rules_module.AlarmCause.DEBRIS_IMPACT,
        ),
        (
            rules_module.CavitationRule,
            {
                "vib_rms": 9.5,
                "vib_crest": 5.0,
                "current": 55.0,
                "pressure": 3.5,
                "temp": 55.0,
                "latest_vib": 9.5,
                "latest_crest": 5.0,
                "latest_current": 55.0,
                "latest_pressure": 3.5,
                "latest_temp": 55.0,
                "smoothed_prob": 0.9,
                "prev_reason": None,
                "last_status": None,
                "debris_flag": False,
            },
            rules_module.TripCause.CAVITATION,
            rules_module.AlarmCause.CAVITATION,
        ),
        (
            rules_module.ChokedRule,
            {
                "vib_rms": 3.0,
                "vib_crest": 3.0,
                "current": 37.0,
                "pressure": 7.5,
                "temp": 72.0,
                "latest_vib": 3.0,
                "latest_crest": 3.0,
                "latest_current": 37.0,
                "latest_pressure": 7.5,
                "latest_temp": 72.0,
                "smoothed_prob": 0.9,
                "prev_reason": None,
                "last_status": None,
                "debris_flag": False,
            },
            rules_module.TripCause.CHOKED_DISCHARGE,
            rules_module.AlarmCause.CHOKED_DISCHARGE,
        ),
        (
            rules_module.TemperatureRule,
            {
                "vib_rms": 4.0,
                "vib_crest": 3.0,
                "current": 45.0,
                "pressure": 6.0,
                "temp": 76.0,
                "latest_vib": 4.0,
                "latest_crest": 3.0,
                "latest_current": 45.0,
                "latest_pressure": 6.0,
                "latest_temp": 76.0,
                "smoothed_prob": 0.9,
                "prev_reason": None,
                "last_status": None,
                "debris_flag": False,
            },
            rules_module.TripCause.OVERTEMP,
            rules_module.AlarmCause.OVERTEMP,
        ),
    ],
)
def test_rules_set_trip_and_alarm_causes(
    rule_cls, ctx_kwargs, expected_trip, expected_alarm_contains
):
    """Each CRITICAL rule sets structured trip_cause and corresponding alarm_causes."""
    ctx = rules_module.RuleContext(
        **ctx_kwargs,
        status="HEALTHY",
        reason=None,
        display_prob=0.0,
        critical_low_vib_steps=0,
        trip_cause=None,
        alarm_causes=[],
    )
    rule = rule_cls()
    rule.evaluate(ctx)
    assert ctx.trip_cause == expected_trip
    assert expected_alarm_contains in ctx.alarm_causes
