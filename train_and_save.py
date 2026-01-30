import pandas as pd
import numpy as np
import joblib
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import StandardScaler
from config.config import Config

def generate_synthetic_data(samples=1200):
    """
    Генерация данных, имитирующих работу насоса Warman на Ротеме.
    Включает 7 признаков, которые ожидает FeatureExtractor.
    """
    np.random.seed(42)
    
    # Класс 0: Здоровое состояние (Healthy)
    n_healthy = int(samples * 0.9)
    data_healthy = {
        'vib_rms': np.random.normal(2.5, 0.4, n_healthy),
        'vib_crest': np.random.normal(3.2, 0.3, n_healthy),
        'vib_kurtosis': np.random.normal(2.9, 0.2, n_healthy),
        'current': np.random.normal(45.0, 2.0, n_healthy),
        'pressure': np.random.normal(6.1, 0.3, n_healthy),
        'cavitation_index': np.random.normal(0.02, 0.01, n_healthy),
        'temp': np.random.normal(38.0, 3.0, n_healthy),
        'target': 0
    }

    # Класс 1: Аномалия/Износ (Critical/Warning)
    n_anomaly = samples - n_healthy
    data_anomaly = {
        'vib_rms': np.random.normal(7.5, 1.5, n_anomaly),
        'vib_crest': np.random.normal(8.5, 2.0, n_anomaly),
        'vib_kurtosis': np.random.normal(6.0, 1.0, n_anomaly),
        'current': np.random.normal(56.0, 5.0, n_anomaly),
        'pressure': np.random.normal(3.8, 0.8, n_anomaly),
        'cavitation_index': np.random.normal(0.20, 0.05, n_anomaly),
        'temp': np.random.normal(72.0, 8.0, n_anomaly),
        'target': 1
    }

    df_h = pd.DataFrame(data_healthy)
    df_a = pd.DataFrame(data_anomaly)
    return pd.concat([df_h, df_a]).sample(frac=1).reset_index(drop=True)

def train():
    print("🧪 Начинаю процесс обучения модели ICL Reliability Engine...")
    
    # 1. Подготовка данных
    df = generate_synthetic_data()
    X = df[Config.FEATURE_NAMES]
    y = df['target']

    # 2. Обучение скалера (нормализация)
    # Это критично для стабильности модели
    scaler = StandardScaler()
    X_scaled = scaler.fit_all(X) if hasattr(scaler, 'fit_all') else scaler.fit_transform(X)
    
    # 3. Обучение модели Random Forest
    # class_weight='balanced' критически важен, так как аномалий мало
    model = RandomForestClassifier(
        n_estimators=100, 
        max_depth=7, 
        class_weight='balanced',
        random_state=42
    )
    model.fit(X_scaled, y)
    
    # 4. Сохранение артефактов в пути, указанные в Config
    print(f"💾 Сохранение модели в {Config.MODEL_PATH}...")
    joblib.dump(model, Config.MODEL_PATH)
    
    print(f"💾 Сохранение скалера в {Config.SCALER_PATH}...")
    joblib.dump(scaler, Config.SCALER_PATH)
    
    print("✅ Обучение завершено. Файлы готовы для использования в основном приложении.")

if __name__ == "__main__":
    train()