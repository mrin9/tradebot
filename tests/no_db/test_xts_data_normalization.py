"""
Tests for MarketUtils parsing and normalization functions for various market data events.
Redundant tests consolidated into 'Full (JSON)' and 'Partial (String)' formats.
"""
import sys
import os
from datetime import datetime

# Add project root
sys.path.append(os.getcwd())

from packages.utils.market_utils import MarketUtils

def test_master_parsing():
    """Verifies the parsing of XTS Instrument Master CSV lines."""
    print("Testing Master Data Parsing...")
    raw_line = "NSEFO|26000|1|NIFTY|NIFTY 50|IND|NIFTY IND|26000|0|0|75|0.05|50|1|||2026-02-26T00:00:00|0|0|NIFTY|1|1"
    parsed = MarketUtils.parse_xts_master_line(raw_line)
    
    assert parsed is not None
    assert parsed['exchangeSegment'] == 'NSEFO'
    assert parsed['exchangeInstrumentID'] == 26000
    assert parsed['lotSize'] == 50
    assert parsed['contractExpiration'] == '2026-02-26T00:00:00'
    print("✅ Master Data Parsing Passed.")

# --- 1501 (TICK) ---

def test_1501_full_json():
    print("Testing 1501 (Tick) - Full Format (JSON)...")
    payload = {
        "ExchangeInstrumentID": 22,
        "ExchangeTimeStamp": 1205682251,
        "LastTradedPrice": 1567.95,
        "LastTradedQunatity": 20,
        "TotalTradedQuantity": 253453,
        "BidInfo": {"Price": 1567.95},
        "AskInfo": {"Price": 0}
    }
    
    norm = MarketUtils.normalize_xts_event("1501-json-full", payload)
    assert norm['i'] == 22
    assert norm['p'] == 1567.95
    assert norm['v'] == 20
    assert norm['q'] == 253453
    assert norm['t'] == 1205662451 # 1205682251 - 19800
    assert norm['bid'] == 1567.95
    assert norm['ask'] is None
    print("✅ 1501 Full JSON Passed.")

def test_1501_partial_string():
    print("Testing 1501 (Tick) - Partial Format (String)...")
    payload = "t:1_22,ltp:1567.95,ltq:20,v:253453,ltt:1205682110,ai:0|1428|1567.95|10,bi:0|0|0|0|1"
    
    norm = MarketUtils.normalize_xts_event("1501-json-partial", payload)
    assert norm['i'] == 22
    assert norm['p'] == 1567.95
    assert norm['v'] == 20
    assert norm['q'] == 253453
    assert norm['t'] == 1205662310 # 1205682110 - 19800
    assert norm['bid'] == 0.0
    assert norm['ask'] == 1428.0
    print("✅ 1501 Partial String Passed.")

# --- 1512 (SNAPSHOT) ---

def test_1512_full_json():
    print("Testing 1512 (Snapshot) - Full Format (JSON)...")
    payload = {
        "ExchangeInstrumentID": 26000,
        "ExchangeTimeStamp": 1708435800,
        "LastTradedPrice": 22000.5,
        "LastTradedQuantity": 100,
        "TotalTradedQuantity": 1500000
    }
    norm = MarketUtils.normalize_xts_event("1512-json-full", payload)
    assert norm['i'] == 26000
    assert norm['p'] == 22000.5
    assert norm['v'] == 100
    assert norm['q'] == 1500000
    assert norm['t'] == 1708416000
    print("✅ 1512 Full JSON Passed.")

def test_1512_partial_string():
    print("Testing 1512 (Snapshot) - Partial Format (String)...")
    payload = "i:26000,ltp:22000.5,ltq:100,v:1500000,ltt:1708435800"
    norm = MarketUtils.normalize_xts_event("1512-json-partial", payload)
    assert norm['i'] == 26000
    assert norm['p'] == 22000.5
    assert norm['v'] == 100
    assert norm['q'] == 1500000
    assert norm['t'] == 1708416000
    print("✅ 1512 Partial String Passed.")

# --- 1505 (CANDLE) ---

def test_1505_full_json():
    print("Testing 1505 (Candle) - Full Format (JSON)...")
    payload = {
        "ExchangeInstrumentID": 26000,
        "BarData": {
            "Open": 21900, "High": 22100, "Low": 21850, "Close": 22050, "Volume": 5000, "Timestamp": 1708435800
        }
    }
    norm = MarketUtils.normalize_xts_event("1505-json-full", payload)
    assert norm['i'] == 26000
    assert norm['o'] == 21900
    assert norm['h'] == 22100
    assert norm['l'] == 21850
    assert norm['c'] == 22050
    assert norm['v'] == 5000
    assert norm['t'] == 1708416000
    print("✅ 1505 Full JSON Passed.")

def test_1505_partial_string():
    print("Testing 1505 (Candle) - Partial Format (String)...")
    payload = "i:26000,t:1708435800,o:21900,h:22100,l:21850,c:22050,v:5000"
    norm = MarketUtils.normalize_xts_event("1505-json-partial", payload)
    assert norm['i'] == 26000
    assert norm['o'] == 21900
    assert norm['h'] == 22100
    assert norm['l'] == 21850
    assert norm['c'] == 22050
    assert norm['v'] == 5000
    assert norm['t'] == 1708416000
    print("✅ 1505 Partial String Passed.")

if __name__ == "__main__":
    try:
        test_master_parsing()
        test_1501_full_json()
        test_1501_partial_string()
        test_1512_full_json()
        test_1512_partial_string()
        test_1505_full_json()
        test_1505_partial_string()
        print("\nAll Parser Tests Passed! 🚀")
    except Exception as e:
        print(f"\n❌ Test Failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
