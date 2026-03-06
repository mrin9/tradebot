"""
Tests for RuleStrategy, verifying entry/exit logic and condition matching using internal rule engine.
"""
import pytest
from packages.tradeflow.rule_strategy import RuleStrategy
from packages.tradeflow.types import SignalType as Signal
from packages.config import settings

@pytest.fixture(autouse=True)
def setup_frozen_db():
    """Ensures this test uses the deterministic frozen database."""
    settings.DB_NAME = "tradebot_frozen_test"
    from packages.utils.mongo import MongoRepository
    MongoRepository.close()

@pytest.fixture
def strategy():
    """Returns a RuleStrategy instance with a standard crossover/threshold config."""
    config = {
        "entry": {
            "intent": "AUTO",
            "evaluateSpot": True,
            "evaluateInverse": False,
            "operator": "AND",
            "conditions": [
                {
                    "type": "crossover",
                    "fastIndicatorId": "fast_ema",
                    "slowIndicatorId": "slow_ema"
                },
                {
                    "type": "threshold",
                    "indicatorId": "rsi",
                    "op": ">",
                    "value": 60
                }
            ]
        }
    }
    return RuleStrategy(strategy_config=config)

def test_hold_signal(strategy):
    """Verifies that missing or weak data results in a NEUTRAL signal."""
    # Missing data -> HOLD
    signal, reason, confidence = strategy.on_resampled_candle_closed({}, {})
    assert signal == Signal.NEUTRAL
    assert confidence == 0.0
    
    # Conditions not met: EMA crossed but RSI weak
    ind_weak_rsi = {'fast_ema': 105, 'slow_ema': 100, 'rsi': 55}
    signal, reason, confidence = strategy.on_resampled_candle_closed({}, ind_weak_rsi)
    assert signal == Signal.NEUTRAL
    
def test_buy_signal(strategy):
    """Verifies that LONG signal is triggered when crossover and threshold conditions are met."""
    ind_buy = {
        'NIFTY_fast_ema': 105, 'NIFTY_slow_ema': 100, 
        'NIFTY_fast_ema_prev': 95, 'NIFTY_slow_ema_prev': 100,
        'NIFTY_rsi': 65
    }
    signal, reason, confidence = strategy.on_resampled_candle_closed({}, ind_buy)
    assert signal == Signal.LONG
    assert confidence == 1.0
    assert "crossed over" in reason

def test_no_redundant_buy_signal(strategy):
    """Verifies that no redundant signals are generated if the condition was already met."""
    ind_already_crossed = {
        'NIFTY_fast_ema': 110, 'NIFTY_slow_ema': 100, 
        'NIFTY_fast_ema_prev': 105, 'NIFTY_slow_ema_prev': 100,
        'NIFTY_rsi': 65
    }
    signal, reason, confidence = strategy.on_resampled_candle_closed({}, ind_already_crossed)
    assert signal == Signal.NEUTRAL
    
def test_sell_signal(strategy):
    """Verifies that SHORT signal is triggered when inverse conditions are detected (AUTO mode)."""
    ind_sell = {
        'NIFTY_fast_ema': 95, 'NIFTY_slow_ema': 100, 
        'NIFTY_fast_ema_prev': 105, 'NIFTY_slow_ema_prev': 100,
        'NIFTY_rsi': 35
    }
    signal, reason, confidence = strategy.on_resampled_candle_closed({}, ind_sell)
    assert signal == Signal.SHORT
    assert confidence == 1.0

def test_or_operator():
    """Verifies that OR operator correctly triggers signal if any condition is met."""
    config_or = {
        "entry": {
            "intent": "AUTO",
            "evaluateSpot": True,
            "evaluateInverse": False,
            "operator": "OR",
            "conditions": [
                {"type": "threshold", "indicatorId": "rsi", "op": ">", "value": 60},
                {"type": "threshold", "indicatorId": "ema", "op": ">", "value": 100}
            ]
        }
    }
    strat_or = RuleStrategy(strategy_config=config_or)
    
    # RSI strong
    ind_only_rsi = {'NIFTY_rsi': 65, 'NIFTY_ema': 95}
    signal, _, _ = strat_or.on_resampled_candle_closed({}, ind_only_rsi)
    assert signal == Signal.LONG
    
    # EMA strong
    ind_only_ema = {'NIFTY_rsi': 55, 'NIFTY_ema': 105}
    signal, _, _ = strat_or.on_resampled_candle_closed({}, ind_only_ema)
    assert signal == Signal.LONG
