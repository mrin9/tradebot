"""
Tests for the FundManager orchestration, verifying the end-to-end signal flow from tick data to position manager.
"""
import pytest
from datetime import datetime

from packages.tradeflow.fund_manager import FundManager
from packages.config import settings
from packages.tradeflow.types import MarketIntentType as MarketIntent

@pytest.fixture(autouse=True)
def setup_frozen_db():
    """Ensures this test uses the deterministic frozen database."""
    settings.DB_NAME = "tradebot_frozen_test"
    from packages.utils.mongo import MongoRepository
    MongoRepository.close()

def create_mock_ticks(instrument_id, start_price, count):
    ticks = []
    for i in range(count):
        timestamp = 1000000000 + i * 60  # Use a realistic timestamp
        ticks.append({
            'instrument_id': instrument_id,
            'c': float(start_price + i * 10),
            'o': float(start_price + i * 10),
            'h': float(start_price + i * 10),
            'l': float(start_price + i * 10),
            'v': 100,
            'timestamp': timestamp
        })
    return ticks

def test_orchestration():
    """
    Simulates a sequence of market data ticks and verifies that FundManager
    correctly triggers a LONG signal when RSI exceeds a threshold.
    """
    # 1. Setup a valid strategy config
    strategy_config = {
        "ruleId": "test-rule",
        "name": "Test Rule",
        "indicators": [
            {"indicatorId": "rsi_14", "displayLabel": "RSI", "type": "RSI", "params": {"period": 14}, "timeframe": 60}
        ],
        "entry": {
            "intent": "AUTO",
            "evaluateSpot": True,
            "evaluateInverse": False,
            "operator": "AND",
            "conditions": [
                {"type": "threshold", "indicatorId": "rsi_14", "op": ">", "value": 60}
            ]
        },
        "exit": {
            "operator": "AND",
            "conditions": [
                {"type": "threshold", "indicatorId": "rsi_14", "op": "<", "value": 40}
            ]
        }
    }
    
    fm = FundManager(strategy_config=strategy_config, is_backtest=True)
    
    signals_received = []
    original_on_signal = fm.position_manager.on_signal
    fm.position_manager.on_signal = lambda data: signals_received.append(data) or original_on_signal(data)
    
    # 2. Feed enough data to trigger indicators (Spot ID: 26000)
    start_price = 100
    for i in range(100):
        timestamp = 1000000000 + i*60 # Use a realistic timestamp
        fm.on_tick_or_base_candle({
            'instrument_id': 26000,
            'c': float(start_price + i*10), 
            'o': float(start_price + i*10), 
            'h': float(start_price + i*10), 
            'l': float(start_price + i*10), 
            'v': 100, 
            'timestamp': timestamp
        })
        
    # At this point, RSI should be 100 (LONG)
    assert len(signals_received) > 0
    
    # Verify Signal Label
    sig_data = signals_received[-1]
    assert sig_data['signal'] == MarketIntent.LONG
    assert sig_data['symbol'] == "26000"
    
    print("FundManager Test Verified: Signal Received.")
