"""Telemetry batch processing: Butterworth filter and feature preparation for the predictor."""
import numpy as np
import pandas as pd
from collections.abc import Sequence
from collections import deque
from typing import Any

from scipy import signal

from config.config import Config
from app.feature_extractor import FeatureExtractor
from app.telemetry_validator import validate_telemetry_batch


class DataProcessor:
    """Process and prepare vibration batches for the predictor.

    Butterworth filter parameters come from Config; override via constructor
    args when needed (e.g. in tests).
    """

    def __init__(
        self,
        window_size: int | None = None,
        fs: int | None = None,
        butter_order: int | None = None,
        butter_cutoff: float | None = None,
    ):
        """Initialize the processor.

        Args:
            window_size: Feature window size (number of records per batch). Default Config.FEATURE_WINDOW_SIZE (30).
            fs: Sampling rate in Hz. Default Config.SAMPLE_RATE_HZ.
            butter_order: Butterworth filter order. Default Config.BUTTER_ORDER.
            butter_cutoff: Normalized cutoff Wn (0 < Wn < 1, 1 = Nyquist). Default Config.BUTTER_CUTOFF.
        """
        self.fs = fs if fs is not None else Config.SAMPLE_RATE_HZ
        self.butter_order = (
            butter_order if butter_order is not None else Config.BUTTER_ORDER
        )
        self.butter_cutoff = (
            butter_cutoff if butter_cutoff is not None else Config.BUTTER_CUTOFF
        )
        self.window_size = (
            window_size if window_size is not None else Config.FEATURE_WINDOW_SIZE
        )
        self.buffer = deque(maxlen=self.window_size)
        self._last_temp: float | None = None

    def apply_butterworth_filter(self, data: np.ndarray) -> np.ndarray:
        """Low-pass filter the signal with a Butterworth filter.

        Uses BUTTER_CUTOFF as normalized Wn (fraction of Nyquist): e.g. Wn=0.1
        at fs=1000 Hz corresponds to 50 Hz cutoff.

        Args:
            data: One-dimensional vibration sample array.

        Returns:
            Filtered signal, same length.
        """
        b, a = signal.butter(
            self.butter_order,
            self.butter_cutoff,
            btype="low",
            analog=False,
        )
        return signal.filtfilt(b, a, data)

    def _iso_band_rms(self, vib_signal: np.ndarray, fs: float) -> float | None:
        """Compute RMS in ISO 10816-3 band (10–1000 Hz) for zone/shutdown decisions.

        Args:
            vib_signal: One-dimensional velocity signal (mm/s), e.g. window of vib_rms samples.
            fs: Sampling rate in Hz.

        Returns:
            RMS in mm/s over the band, or None if signal too short or band invalid.
        """
        low_hz = getattr(Config, "ISO_BAND_LOW_HZ", 10.0)
        high_hz = getattr(Config, "ISO_BAND_HIGH_HZ", 1000.0)
        nyq = fs / 2.0
        high_cap = min(high_hz, nyq * 0.99)
        if low_hz >= high_cap or vib_signal.size < 8:
            return None
        order = 4
        b, a = signal.butter(order, [low_hz, high_cap], btype="band", fs=fs)
        try:
            filtered = signal.filtfilt(b, a, vib_signal)
        except Exception:
            return None
        return float(np.sqrt(np.mean(np.square(filtered))))

    def extract_features(self, raw_data: np.ndarray | pd.DataFrame) -> dict[str, float]:
        """Extract RMS and Crest Factor from vibration (with filtering).

        Args:
            raw_data: One-dimensional vibration array or DataFrame with column "vib_rms".

        Returns:
            Dict with keys "rms" and "crest_factor".
        """
        if isinstance(raw_data, np.ndarray):
            vib_data = raw_data
        else:
            vib_data = raw_data["vib_rms"].values

        clean_vib = self.apply_butterworth_filter(vib_data)
        rms = np.sqrt(np.mean(clean_vib**2))
        peak = np.max(np.abs(clean_vib))
        crest_factor = peak / rms if rms != 0 else 0

        return {"rms": rms, "crest_factor": crest_factor}

    def prepare_batch(
        self, buffer: Sequence[dict[str, Any]]
    ) -> tuple[np.ndarray | None, str, float | None]:
        """Prepare a batch from the MQTT telemetry buffer.

        Args:
            buffer: List or deque of telemetry dicts with vib_rms, current, pressure, temp, vib_crest, vib_kurtosis, cavitation_index.

        Returns:
            (features, status, iso_vib_rms): feature array, "OK" or error code, and optional RMS in 10–1000 Hz band
            for zone/shutdown when USE_ISO_BAND_FOR_ZONES is True; otherwise iso_vib_rms is None.
        """
        if not buffer:
            return None, "EMPTY_BUFFER", None
        try:
            valid_list, validation_status = validate_telemetry_batch(buffer)
            if valid_list is None:
                return None, validation_status, None
            df = pd.DataFrame(valid_list)
            required = [
                "vib_rms",
                "current",
                "pressure",
                "temp",
                "vib_crest",
                "vib_kurtosis",
                "cavitation_index",
            ]
            missing = [c for c in required if c not in df.columns]
            if missing:
                return None, f"MISSING_COLUMNS:{','.join(missing)}", None
            features = FeatureExtractor().get_feature_vector(
                df, prev_temp=self._last_temp
            )
            self._last_temp = float(df["temp"].mean())
            iso_vib_rms = None
            if getattr(Config, "USE_ISO_BAND_FOR_ZONES", False):
                iso_vib_rms = self._iso_band_rms(df["vib_rms"].values, self.fs)
            return features, "OK", iso_vib_rms
        except Exception as e:
            return None, str(e), None
