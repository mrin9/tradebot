"""Tests for packages.tradeflow.ml_strategy — both dummy and real model modes."""

import pytest
import os
import tempfile
from packages.config import settings
from packages.tradeflow.rule_strategy import RuleStrategy
from packages.tradeflow.types import SignalType as Signal
from packages.tradeflow.ml_strategy import MLStrategy, DummyMLStrategy

@pytest.fixture(autouse=True)
def setup_frozen_db():
    """Ensures this test uses the deterministic frozen database."""
    settings.DB_NAME = "tradebot_frozen_test"
    from packages.utils.mongo import MongoRepository
    MongoRepository.close()

def test_ml_prediction():
    """Placeholder for ML prediction logic testing."""
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

