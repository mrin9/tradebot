"""
Tests for LiveTradeEngine logic and MarketUtils tick normalization.
"""
import pytest
from unittest.mock import patch
from packages.utils.market_utils import MarketUtils
from packages.livetrade.live_trader import LiveTradeEngine

def test_normalization_variants():
    """Verifies that different XTS tick formats (Full vs Partial) are correctly normalized."""
    print("Testing Normalization Variants (Full, Partial, IST)...")
    
    # 1. Full Format (with Touchline wrapper)
    full_payload = {
        "ExchangeInstrumentID": 26000,
        "Touchline": {
            "LastTradedPrice": 22000.5,
            "LastTradedQuantity": 50,
            "TotalTradedQuantity": 100000,
            "ExchangeTimeStamp": 1708435800 + 19800 # IST shifted
        }
    }
    norm_full = MarketUtils.normalize_1501_tick_event(full_payload)
    assert norm_full['p'] == 22000.5
    assert norm_full['t'] == 1708435800 # Should be corrected to UTC epoch
    
    # 2. Partial Format (Flat, ltp instead of LastTradedPrice)
    partial_payload = {
        "i": 26000,
        "ltp": 22100.0,
        "ltq": 100,
        "v": 500000,
        "ltt": 1708436000 + 19800,
        "bi": "1|22100.0|50",
        "ai": "1|22105.0|50"
    }
    norm_partial = MarketUtils.normalize_1501_tick_event(partial_payload)
    assert norm_partial['i'] == 26000
    assert norm_partial['p'] == 22100.0
    assert norm_partial['v'] == 100
    assert norm_partial['q'] == 500000
    assert norm_partial['t'] == 1708436000
    assert norm_partial['bid'] == 22100.0
    assert norm_partial['ask'] == 22105.0
    
    print("✅ Normalization Variants Passed.")

def test_engine_initialization():
    print("Testing LiveTradeEngine Initialization...")
    
    mock_strategy = {
        "ruleId": "TEST_01",
        "name": "Test Strategy",
        "indicators": []
    }
    pos_cfg = {
        "budget": 100000,
        "stop_loss_points": 10,
        "target_points": 20
    }
    
    with patch('packages.data.connectors.xts_wrapper.XTSManager.get_market_client'), \
         patch('packages.data.connectors.xts_wrapper.XTSManager.get_market_data_socket'):
        
        engine = LiveTradeEngine(mock_strategy, pos_cfg)
        assert engine.session_id.startswith("live-")
        assert engine.fund_manager.initial_budget == 100000
        
    print("✅ Engine Initialization Passed.")
