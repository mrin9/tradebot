import pytest
from packages.utils.market_utils import MarketUtils

def test_normalize_1501_full_json():
    raw_data = {
        "Touchline": {
            "LastTradedPrice": 24500.5,
            "LastTradedQuantity": 50,
            "ExchangeInstrumentID": 26000,
            "ExchangeTimeStamp": 1772618459,
            "TotalTradedQuantity": 10000
        }
    }
    norm = MarketUtils.normalize_xts_event("1501", raw_data)
    assert norm["i"] == 26000
    assert norm["p"] == 24500.5
    assert norm["v"] == 50
    assert norm["q"] == 10000
    assert "isoDt" in norm

def test_normalize_1501_flat_json():
    # Test for emulated/simulator flat format
    raw_data = {
        "ltp": 24500.5,
        "ltq": 50,
        "i": 26000,
        "ltt": 1772618459,
        "v": 10000
    }
    norm = MarketUtils.normalize_xts_event("1501", raw_data)
    assert norm["i"] == 26000
    assert norm["p"] == 24500.5
    assert norm["v"] == 50

def test_normalize_1505_candle():
    raw_data = {
        "BarData": {
            "Open": 24500,
            "High": 24550,
            "Low": 24480,
            "Close": 24520,
            "Volume": 5000,
            "Timestamp": 1772618400,
            "ExchangeInstrumentID": 26000
        }
    }
    norm = MarketUtils.normalize_xts_event("1505", raw_data)
    assert norm["i"] == 26000
    assert norm["o"] == 24500
    assert norm["c"] == 24520
    assert norm["v"] == 5000

def test_normalize_1512_depth():
    raw_data = {
        "ExchangeInstrumentID": 26000,
        "LastTradedPrice": 24500,
        "ExchangeTimeStamp": 1772618459,
        "BidInfo": {"Price": 24495, "Size": 100},
        "AskInfo": {"Price": 24505, "Size": 100}
    }
    norm = MarketUtils.normalize_xts_event("1512", raw_data)
    assert norm["bid"] == 24495
    assert norm["ask"] == 24505
    assert norm["p"] == 24500
