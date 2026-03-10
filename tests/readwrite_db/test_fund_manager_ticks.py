"""
Verifies that raw ticks from the socket (missing OHLC) are correctly normalized by the FundManager.
"""
import pytest
from datetime import datetime
from packages.tradeflow.fund_manager import FundManager
from packages.config import settings

@pytest.fixture(autouse=True)
def setup_test_db():
    """Ensures this test uses the volatile test database."""
    settings.DB_NAME = "tradebot_test"
    from packages.utils.mongo import MongoRepository
    MongoRepository.close()

# Mock Tick Data (matches structure from MarketUtils.normalize_xts_tick)
MOCK_TICK = {
    "ExchangeInstrumentID": 26000,
    "LastTradedPrice": 22350.5,
    "LastTradedQuantity": 100,
    "TotalBuyQuantity": 10000,
    "TotalSellQuantity": 15000,
    "LastTradedTime": 1770000000,
}

def test_fund_manager_tick_normalization_inplace():
    """
    Ensures that when FundManager receives a raw tick, it correctly
    populates the OHLC fields in the dictionary for downstream compatibility.
    """
    # 1. Setup raw tick (MOCK_TICK is normalized by MarketUtils usually has 'p' but no 'o','h','l','c')
    # Let's use a simpler one to match FundManager's logic
    tick = {
        'instrument_id': 26000,
        'p': 22350.5,
        't': 1770000000
    }
    
    position_config = {"python_strategy_path": "packages/tradeflow/python_strategies.py:TripleLockStrategy"}
    fm = FundManager(strategy_config={"strategyId": "test", "indicators": []}, position_config=position_config, is_backtest=True)
    
    # 2. Feed the tick
    fm.on_tick_or_base_candle(tick)
    
    # 3. Check that the tick dict was updated in-place with OHLC
    assert 'c' in tick
    assert tick['c'] == 22350.5
    assert tick['o'] == 22350.5
    assert tick['h'] == 22350.5
    assert tick['l'] == 22350.5
    assert tick['instrument_id'] == 26000

    # 4. Check FundManager's price cache
    assert fm.latest_tick_prices[26000] == 22350.5
