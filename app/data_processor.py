import numpy as np
import pandas as pd
from scipy import signal

from app.feature_extractor import FeatureExtractor


class DataProcessor:
    def __init__(self):
        # Параметры фильтра
        self.fs = 1000  # Частота дискретизации
        self.cutoff = 100  # Частота среза
        
    def apply_butterworth_filter(self, data):
        """Очистка сигнала от шума."""
        nyquist = 0.5 * self.fs
        normal_cutoff = self.cutoff / nyquist
        b, a = signal.butter(4, normal_cutoff, btype='low', analog=False)
        return signal.filtfilt(b, a, data)

    def extract_features(self, raw_data):
        """
        Принимает либо массив, либо DataFrame. 
        Если массив — обрабатывает как вибрацию.
        """
        # Если пришел массив (как в тесте)
        if isinstance(raw_data, np.ndarray):
            vib_data = raw_data
        else:
            # Если пришел DataFrame (как будет в продакшене)
            vib_data = raw_data['vib_rms'].values

        clean_vib = self.apply_butterworth_filter(vib_data)
        
        # Считаем Crest Factor
        rms = np.sqrt(np.mean(clean_vib**2))
        peak = np.max(np.abs(clean_vib))
        crest_factor = peak / rms if rms != 0 else 0
        
        return {
            'rms': rms,
            'crest_factor': crest_factor
        }

    def prepare_batch(self, buffer):
        """
        Подготовка батча из буфера MQTT-телеметрии.
        Принимает список словарей, возвращает вектор признаков для Predictor.
        """
        if not buffer:
            return None, "EMPTY_BUFFER"
        try:
            df = pd.DataFrame(list(buffer))
            required = ['vib_rms', 'current', 'pressure', 'temp']
            missing = [c for c in required if c not in df.columns]
            if missing:
                return None, f"MISSING_COLUMNS:{','.join(missing)}"
            features = FeatureExtractor().get_feature_vector(df)
            return features, "OK"
        except Exception as e:
            return None, str(e)