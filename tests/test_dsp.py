import pytest
import numpy as np
from app.data_processor import DataProcessor


def test_butterworth_filter_noise_reduction():
    """Verify that the Butterworth filter reduces noise."""
    np.random.seed(42)
    processor = DataProcessor()
    fs = 1000  # sampling rate 1 kHz
    t = np.linspace(0, 1, fs)
    clean_signal = np.sin(2 * np.pi * 50 * t)
    noise = np.random.normal(0, 0.5, fs)
    noisy_signal = clean_signal + noise
    filtered_signal = processor.apply_butterworth_filter(noisy_signal)
    noise_error = np.linalg.norm(noisy_signal - clean_signal)
    filtered_error = np.linalg.norm(filtered_signal - clean_signal)

    assert filtered_error < noise_error
    print(f"\n[DSP Test] Filter efficiency: {noise_error/filtered_error:.2f}x cleaner")


def test_crest_factor_calculation():
    """Verify Crest Factor calculation accuracy."""
    # Cutoff 0.2 (100 Hz at fs=1000) so 50 Hz sine passes without distortion
    processor = DataProcessor(fs=1000, butter_cutoff=0.2)
    fs = 1000
    t = np.linspace(0, 1, fs)
    signal = np.sin(2 * np.pi * 50 * t)

    features = processor.extract_features(signal)

    assert pytest.approx(features["crest_factor"], rel=1e-2) == 1.414


def test_iso_band_rms_normal_and_edge_cases():
    """_iso_band_rms returns positive RMS for valid signal and None for edge cases."""
    processor = DataProcessor()
    fs = 1000
    t = np.linspace(0, 1, fs, endpoint=False)
    # 50 Hz sine with amplitude 1.0
    signal = np.sin(2 * np.pi * 50 * t)

    iso_rms = processor._iso_band_rms(signal, fs)
    assert iso_rms is not None
    assert iso_rms > 0

    # Too short signal
    short = np.ones(4)
    assert processor._iso_band_rms(short, fs) is None
