"""
Tests for the IndicatorCalculator, verifying sliding window management and technical analysis calculations.
"""
import pytest
from packages.tradeflow.indicator_calculator import IndicatorCalculator
from packages.tradeflow.types import InstrumentCategoryType

@pytest.fixture
def calc_instance():
    # Mock indicator config from strategy_rules DB format
    config = [
        {
            "indicatorId": "fast_ema",
            "type": "EMA",
            "params": {"period": 5},
            "InstrumentType": "SPOT"
        },
        {
            "indicatorId": "rsi",
            "type": "RSI",
            "params": {"period": 14},
            "InstrumentType": "CE"
        }
    ]
    return IndicatorCalculator(indicators_config=config, max_window_size=50)

def test_initialization(calc_instance):
    # Should create two deques for SPOT and CE
    assert InstrumentCategoryType.SPOT in calc_instance.category_candles
    assert InstrumentCategoryType.CE in calc_instance.category_candles
    
def test_single_category_calculation(calc_instance):
    # Feed 20 candles into SPOT (enough for EMA 5)
    res = {}
    for i in range(1, 21):
        # Use unique timestamps to avoid deduplication logic
        res = calc_instance.add_candle({'c': i * 10, 'o': 0, 'h': 0, 'l': 0, 'v': 0, 't': 1000 + i*60}, instrument_category=InstrumentCategoryType.SPOT)

    assert 'NIFTY_fast_ema' in res
    assert res['NIFTY_fast_ema'] > 0
    assert 'NIFTY_fast_ema_prev' in res
    assert 'rsi' not in res # RSI is on CE
    
    # EMA of linear sequence 10,20...200 with span 5 should lag by ~ (5-1)/2 * 10 = 20
    # 200 - 20 = 180.
    assert 170 < res['NIFTY_fast_ema'] < 190
    assert 160 < res['NIFTY_fast_ema_prev'] < 180

def test_dynamic_category_init(calc_instance):
    # Feed candle to PE (not in config)
    # Should initialize gracefully but return empty dict since no indicators configured
    res = calc_instance.add_candle({'c': 100}, instrument_category=InstrumentCategoryType.PE)
    assert res == {}
    assert InstrumentCategoryType.PE in calc_instance.category_candles
