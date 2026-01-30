import pytest
import numpy as np
from app.data_processor import DataProcessor # Убедись, что путь верный

def test_butterworth_filter_noise_reduction():
    """Проверяем, что фильтр Баттерворта реально подавляет шум."""
    processor = DataProcessor()
    
    # Генерируем чистую синусоиду (например, 50 Гц — работа насоса)
    fs = 1000  # частота дискретизации 1 кГц
    t = np.linspace(0, 1, fs)
    clean_signal = np.sin(2 * np.pi * 50 * t)
    
    # Добавляем высокочастотный шум
    noise = np.random.normal(0, 0.5, fs)
    noisy_signal = clean_signal + noise
    
    # Пропускаем через фильтр
    filtered_signal = processor.apply_butterworth_filter(noisy_signal)
    
    # Проверка: среднеквадратичное отклонение ошибки должно уменьшиться
    # (отфильтрованный сигнал должен быть ближе к оригиналу, чем зашумленный)
    noise_error = np.linalg.norm(noisy_signal - clean_signal)
    filtered_error = np.linalg.norm(filtered_signal - clean_signal)
    
    assert filtered_error < noise_error
    print(f"\n[DSP Test] Filter efficiency: {noise_error/filtered_error:.2f}x cleaner")

def test_crest_factor_calculation():
    """Проверяем математическую точность расчета Crest Factor."""
    processor = DataProcessor()
    
    # Для чистой синусоиды Crest Factor теоретически равен sqrt(2) ≈ 1.414
    fs = 1000
    t = np.linspace(0, 1, fs)
    signal = np.sin(2 * np.pi * 50 * t)
    
    features = processor.extract_features(signal)
    
    # Допускаем небольшую погрешность из-за дискретизации
    assert pytest.approx(features['crest_factor'], rel=1e-2) == 1.414