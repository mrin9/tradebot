"""Tests for packages.tradeflow.ml_strategy — both dummy and real model modes."""

import pytest
import os
import tempfile
from packages.config import settings
from packages.tradeflow.rule_strategy import Signal, RuleStrategy
from packages.tradeflow.ml_strategy import MLStrategy, DummyMLStrategy

@pytest.fixture(autouse=True)
def setup_frozen_db():
    """Ensures this test uses the deterministic frozen database."""
    settings.DB_NAME = "tradebot_frozen_test"
    from packages.utils.mongo import MongoRepository
    MongoRepository.close()

def test_ml_prediction():
    pass

def test_neutral_on_warmup():
    """Should return NEUTRAL while warming up."""
    strategy = MLStrategy(confidence_threshold=0.65)
    candle = {'o': 100, 'h': 105, 'l': 95, 'c': 102, 't': 1000}
    signal, reason, confidence = strategy.on_resampled_candle_closed(candle)
    assert signal == Signal.NEUTRAL
    assert reason == "ML_WARMING_UP"

def test_neutral_no_model():
    """Should return ML_NO_MODEL if no model is loaded after warmup."""
    strategy = MLStrategy(confidence_threshold=0.65)
    for i in range(40):
        candle = {'o': 100, 'h': 105, 'l': 95, 'c': 102, 't': 1000 + i*60}
        signal, reason, confidence = strategy.on_resampled_candle_closed(candle)
    
    assert signal == Signal.NEUTRAL
    assert reason == "ML_NO_MODEL"

def test_alias_is_same_class():
    """Verify DummyMLStrategy alias still works."""
    assert DummyMLStrategy is MLStrategy

@pytest.fixture
def xgboost_model_file():
    """Train a tiny XGBoost model, save to a temp file, and provide the path."""
    try:
        import numpy as np
        from xgboost import XGBClassifier
        import joblib
        from packages.ml.feature_builder import FEATURE_COLUMNS
    except ImportError:
        pytest.skip("xgboost/joblib not installed")

    np.random.seed(42)
    n = 100
    X = np.random.rand(n, len(FEATURE_COLUMNS))
    y = np.random.choice([0, 1, 2], size=n)  # 3 classes

    model = XGBClassifier(
        n_estimators=10, max_depth=2,
        objective="multi:softprob", num_class=3,
        use_label_encoder=False, verbosity=0,
    )
    model.fit(X, y, verbose=False)

    tmp = tempfile.NamedTemporaryFile(suffix=".joblib", delete=False)
    joblib.dump(model, tmp.name)
    tmp_path = tmp.name
    tmp.close()

    yield tmp_path

    if os.path.exists(tmp_path):
        os.unlink(tmp_path)

def test_model_loaded(xgboost_model_file):
    """Model should be loaded from the joblib file."""
    strategy = MLStrategy(
        model_path=xgboost_model_file,
        confidence_threshold=0.1,
    )
    assert strategy.model is not None

def test_predict_returns_valid_signal(xgboost_model_file):
    """With enough candles, predict should result in a valid signal."""
    strategy = MLStrategy(
        model_path=xgboost_model_file,
        confidence_threshold=0.1,  # low threshold for test reliability
    )
    for i in range(40):
        candle = {
            'open': 100 + i, 'high': 105 + i, 'low': 95 + i, 'close': 102 + i, 
            'timestamp': 1000 + i*300
        }
        signal, reason, confidence = strategy.on_resampled_candle_closed(candle)
        
    assert isinstance(signal, Signal)
    assert isinstance(reason, str)
    assert reason.startswith("ML_PREDICTION")
