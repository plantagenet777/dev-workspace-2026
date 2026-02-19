"""Integration tests: end-to-end pipeline and shutdown-trigger scenarios."""
import pytest
import numpy as np
import pandas as pd
from unittest.mock import patch, MagicMock

from config.config import Config
from app.data_processor import DataProcessor
from app.predictor import PumpPredictor
from app.telemetry_validator import validate_telemetry_batch, validate_telemetry_record
from app.rules import (
    RULES,
    RuleContext,
    ChokedRule,
    MechanicalRule,
    CavitationRule,
    VibrationZoneRule,
)


# --- Telemetry validation ---


def test_validate_telemetry_record_ok():
    """Valid record passes."""
    rec = {
        "vib_rms": 2.0,
        "current": 45,
        "pressure": 6.0,
        "temp": 42,
        "cavitation_index": 0.1,
    }
    ok, detail = validate_telemetry_record(rec)
    assert ok is True
    assert detail == ""


def test_validate_telemetry_record_out_of_range():
    """Out-of-range pressure is rejected."""
    rec = {
        "vib_rms": 2.0,
        "current": 45,
        "pressure": 100.0,  # above TELEMETRY_PRESSURE_MAX
        "temp": 42,
        "cavitation_index": 0.1,
    }
    ok, detail = validate_telemetry_record(rec)
    assert ok is False
    assert "PRESSURE" in detail or "RANGE" in detail


def test_validate_telemetry_batch_rejects_invalid():
    """Batch with one invalid record is rejected."""
    good = {
        "vib_rms": 2.0,
        "current": 45,
        "pressure": 6.0,
        "temp": 42,
        "cavitation_index": 0.1,
    }
    bad = {**good, "temp": 200.0}  # above TEMP_MAX
    valid_list, status = validate_telemetry_batch([good, bad, good])
    assert valid_list is None
    assert "INVALID" in status or "RANGE" in status


# --- Rule evaluation (unit-style, no model) ---


def test_choked_rule_sets_critical():
    """ChokedRule sets CRITICAL and reason when current low, P and T high."""
    ctx = RuleContext(
        vib_rms=3.0,
        vib_crest=3.0,
        current=36.0,
        pressure=7.5,
        temp=72.0,
        latest_vib=3.0,
        latest_crest=3.0,
        latest_current=36.0,
        latest_pressure=7.5,
        latest_temp=72.0,
        smoothed_prob=0.3,
        prev_reason=None,
        last_status="HEALTHY",
        debris_flag=False,
        status="HEALTHY",
        reason=None,
        display_prob=0.3,
        critical_low_vib_steps=0,
    )
    ChokedRule().evaluate(ctx)
    assert ctx.status == "CRITICAL"
    assert ctx.reason is not None
    assert "CHOKED" in (ctx.reason or "")


def test_mechanical_rule_debris_flag():
    """MechanicalRule sets CRITICAL when debris_impact flag is True."""
    ctx = RuleContext(
        vib_rms=2.0,
        vib_crest=3.0,
        current=45.0,
        pressure=6.0,
        temp=42.0,
        latest_vib=2.0,
        latest_crest=3.0,
        latest_current=45.0,
        latest_pressure=6.0,
        latest_temp=42.0,
        smoothed_prob=0.2,
        prev_reason=None,
        last_status="HEALTHY",
        debris_flag=True,
        status="HEALTHY",
        reason=None,
        display_prob=0.2,
        critical_low_vib_steps=0,
    )
    MechanicalRule().evaluate(ctx)
    assert ctx.status == "CRITICAL"
    assert ctx.reason is not None
    assert "DEBRIS" in (ctx.reason or "")


def test_vibration_zone_d_sets_critical():
    """VibrationZoneRule sets CRITICAL when vib >= 7.1 mm/s."""
    ctx = RuleContext(
        vib_rms=7.5,
        vib_crest=4.0,
        current=45.0,
        pressure=6.0,
        temp=42.0,
        latest_vib=7.5,
        latest_crest=4.0,
        latest_current=45.0,
        latest_pressure=6.0,
        latest_temp=42.0,
        smoothed_prob=0.5,
        prev_reason=None,
        last_status="HEALTHY",
        debris_flag=False,
        status="HEALTHY",
        reason=None,
        display_prob=0.5,
        critical_low_vib_steps=0,
    )
    VibrationZoneRule().evaluate(ctx)
    assert ctx.status == "CRITICAL"
    assert ctx.reason is not None
    assert "Zone D" in (ctx.reason or "") or "7.1" in (ctx.reason or "")


# --- Pipeline: prepare_batch + validation ---


def test_pipeline_prepare_batch_after_validation():
    """Full batch passes validation and prepare_batch returns features."""
    processor = DataProcessor()
    buffer = [
        {
            "vib_rms": 2.0 + 0.1 * (i % 5),
            "current": 45,
            "pressure": 6.0,
            "temp": 42,
            "vib_crest": 3.0,
            "vib_kurtosis": 3.2,
            "cavitation_index": 0.05,
        }
        for i in range(30)
    ]
    valid_list, v_status = validate_telemetry_batch(buffer)
    assert valid_list is not None
    assert v_status == "OK"
    features, status, iso_vib_rms = processor.prepare_batch(buffer)
    assert features is not None
    assert status == "OK"
    assert iso_vib_rms is None


def test_pipeline_rejects_invalid_batch():
    """Batch with out-of-range value returns INVALID_RANGE and no features."""
    processor = DataProcessor()
    buffer = [
        {
            "vib_rms": 2.0,
            "current": 45,
            "pressure": 6.0,
            "temp": 150.0,  # above default TELEMETRY_TEMP_MAX
            "vib_crest": 3.0,
            "vib_kurtosis": 3.2,
            "cavitation_index": 0.05,
        }
        for _ in range(30)
    ]
    features, status, iso_vib_rms = processor.prepare_batch(buffer)
    assert features is None
    assert "INVALID" in status or "RANGE" in status or "TEMP" in status
    assert iso_vib_rms is None


# --- End-to-end: predictor with mocked model (optional) ---


@pytest.mark.skipif(
    not __import__("pathlib").Path(Config.MODEL_PATH).is_file(),
    reason="Model artifact not found; run train_and_save.py",
)
def test_e2e_predictor_choked_returns_critical():
    """With real model, choked-like features produce CRITICAL and choked reason."""
    predictor = PumpPredictor()
    if predictor.model is None:
        pytest.skip("Model not loaded")
    # Features that imply choked: low current, high P, high T
    n = len(Config.FEATURE_NAMES)
    row = [
        3.0,  # vib_rms
        3.0,  # vib_crest
        4.0,  # vib_kurtosis
        36.0,  # current
        7.5,  # pressure
        0.1,  # cavitation_index
        72.0,  # temp
        0.0,  # temp_delta
    ]
    assert n == 8
    features_df = pd.DataFrame([row], columns=Config.FEATURE_NAMES)
    latest = {
        "current": 36.0,
        "pressure": 7.5,
        "temp": 72.0,
        "vib_rms": 3.0,
        "vib_crest": 3.0,
    }
    status, prob = predictor.predict(
        features_df, is_startup=False, latest_telemetry=latest
    )
    assert status == "CRITICAL"
    reason = getattr(predictor, "last_alert_reason", None)
    assert reason is not None
    assert "CHOKED" in reason
