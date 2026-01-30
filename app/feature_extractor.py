import numpy as np
import pandas as pd
from scipy.stats import kurtosis, skew
from config.config import Config

class FeatureExtractor:
    """Извлечение информативных признаков из временных рядов телеметрии"""

    @staticmethod
    def calculate_vibration_metrics(signal):
        """Расчет специфических метрик вибрации для диагностики подшипников"""
        rms = np.sqrt(np.mean(np.square(signal)))
        peak = np.max(np.abs(signal))
        
        # Crest Factor (Пик-фактор) — важен для обнаружения ударных нагрузок
        crest_factor = peak / rms if rms > 0 else 0
        
        # Kurtosis (Куртозис) — мера "остроты" сигнала (индикатор дефектов качения)
        kurt = kurtosis(signal)
        
        return {
            "vib_rms": rms,
            "vib_crest": crest_factor,
            "vib_kurtosis": kurt
        }

    @staticmethod
    def calculate_process_metrics(df):
        """Расчет средних показателей технологического процесса"""
        return {
            "current": df['current'].mean(),
            "pressure": df['pressure'].mean(),
            "temp": df['temp'].mean()
        }

    @staticmethod
    def get_cavitation_index(pressure, vibration):
        """
        Упрощенный расчет индекса кавитации.
        Высокая вибрация при низком давлении на входе — признак кавитации.
        """
        if pressure > 0:
            return vibration / pressure
        return 0

    def get_feature_vector(self, df):
        """
        Формирует итоговый вектор для модели. 
        ВАЖНО: Порядок признаков должен быть идентичен train_and_save.py
        """
        # 1. Анализируем вибрацию
        vib_data = self.calculate_vibration_metrics(df['vib_rms'].values)
        
        # 2. Анализируем процесс
        proc_data = self.calculate_process_metrics(df)
        
        # 3. Рассчитываем синтетический признак (кавитация)
        cav_index = self.get_cavitation_index(proc_data['pressure'], vib_data['vib_rms'])

        # Собираем в строгом порядке для Scaler и Random Forest
        vector = [
            vib_data['vib_rms'],
            vib_data['vib_crest'],
            vib_data['vib_kurtosis'],
            proc_data['current'],
            proc_data['pressure'],
            cav_index,
            proc_data['temp']
        ]

        return np.array([vector])