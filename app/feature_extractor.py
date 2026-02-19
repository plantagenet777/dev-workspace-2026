"""Feature extraction from telemetry for the ML model (vibration, process, cavitation)."""
import numpy as np
import pandas as pd
from scipy.stats import kurtosis

from config.config import Config


class FeatureExtractor:
    """Extract informative features from telemetry time series."""

    @staticmethod
    def calculate_vibration_metrics(signal: np.ndarray) -> dict[str, float]:
        """Compute vibration metrics for bearing diagnostics.

        Uses overall RMS over the window (no band filter in this path). For strict ISO 10816-3
        alignment, apply a standard band (e.g. 10–1000 Hz) to the raw signal before RMS.

        Args:
            signal: One-dimensional vibration sample array.

        Returns:
            Dict with keys vib_rms, vib_crest, vib_kurtosis.
        """
        rms = np.sqrt(np.mean(np.square(signal)))
        peak = np.max(np.abs(signal))
        crest_factor = peak / rms if rms > 0 else 0
        kurt = kurtosis(signal)
        # Constant or near-constant signal yields NaN; avoid breaking scaler/model
        if not np.isfinite(kurt):
            kurt = 0.0
        return {"vib_rms": rms, "vib_crest": crest_factor, "vib_kurtosis": kurt}

    @staticmethod
    def calculate_process_metrics(df: pd.DataFrame) -> dict[str, float]:
        """Compute mean process metrics.

        Args:
            df: DataFrame with columns current, pressure, temp.

        Returns:
            Dict of column means.
        """
        return {
            "current": df["current"].mean(),
            "pressure": df["pressure"].mean(),
            "temp": df["temp"].mean(),
        }

    @staticmethod
    def get_cavitation_index(pressure: float, vibration: float) -> float:
        """Simple cavitation index: high vibration at low pressure.

        Args:
            pressure: Inlet pressure.
            vibration: Vibration value (e.g. vib_rms).

        Returns:
            vibration / pressure when pressure > 0, else 0.
        """
        if pressure > 0:
            idx = vibration / pressure
            # Cap to avoid extreme values from bad/low pressure readings breaking the model
            return float(min(50.0, idx))
        return 0.0

    def get_feature_vector(
        self, df: pd.DataFrame, prev_temp: float | None = None
    ) -> np.ndarray:
        """Build feature vector for the model (order must match train_and_save.py).

        Args:
            df: DataFrame with telemetry columns including vib_rms, current, pressure, temp.
            prev_temp: Mean temperature from the previous batch; used to compute temp_delta.
                If None (e.g. first batch), temp_delta is 0.

        Returns:
            Array of shape (1, 8): vib_rms, vib_crest, vib_kurtosis, current, pressure,
            cavitation_index, temp, temp_delta.
        """
        vib_data = self.calculate_vibration_metrics(df["vib_rms"].values)
        proc_data = self.calculate_process_metrics(df)
        cav_index = self.get_cavitation_index(
            proc_data["pressure"], vib_data["vib_rms"]
        )
        current_temp = proc_data["temp"]
        temp_delta = (current_temp - prev_temp) if prev_temp is not None else 0.0
        vector = [
            vib_data["vib_rms"],
            vib_data["vib_crest"],
            vib_data["vib_kurtosis"],
            proc_data["current"],
            proc_data["pressure"],
            cav_index,
            current_temp,
            temp_delta,
        ]

        return np.array([vector])
