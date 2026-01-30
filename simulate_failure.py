import pandas as pd
import numpy as np
import joblib
from app.data_processor import DataProcessor
from app.predictor import PumpPredictor

# 1. Создаем "шумные" данные (нормальная работа)
normal_data = pd.DataFrame({
    'vib_rms': np.random.normal(2.0, 0.1, 30), # Низкая вибрация
    'current': np.random.normal(150, 5, 30),
    'pressure': np.random.normal(4.2, 0.1, 30),
    'temp': np.random.normal(45, 1, 30)
})

# 2. Создаем "аварийные" данные (рост вибрации и падение давления)
failure_data = pd.DataFrame({
    'vib_rms': np.random.normal(8.5, 1.5, 30), # Резкий скачок
    'current': np.random.normal(180, 10, 30),
    'pressure': np.random.normal(1.5, 0.5, 30), # Падение давления (кавитация)
    'temp': np.random.normal(75, 5, 30)
})

print("🚀 Starting Demo Simulation...")
processor = DataProcessor()
predictor = PumpPredictor()

# Демонстрируем обработку
for label, data in [("NORMAL", normal_data), ("FAILURE", failure_data)]:
    features, status = processor.prepare_batch(data.to_dict('records'))
    verdict, prob = predictor.predict(features)
    print(f"\n--- Scenario: {label} ---")
    print(f"Inferred Status: {verdict} (Probability: {prob:.2%})")