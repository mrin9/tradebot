import pytest
from packages.data.connectors.xts_normalizer import XTSNormalizer

def test_master_parsing():
    """Verifies the parsing of XTS Instrument Master CSV lines."""
    raw_line = "NSEFO|26000|1|NIFTY|NIFTY 50|IND|NIFTY IND|26000|0|0|75|0.05|50|1|||2026-02-26T00:00:00|0|0|NIFTY|1|1"
    parsed = XTSNormalizer.parse_xts_master_line(raw_line)
    
    assert parsed is not None
    assert parsed['exchangeSegment'] == 'NSEFO'
    assert parsed['exchangeInstrumentID'] == 26000
    assert parsed['lotSize'] == 50
    assert parsed['contractExpiration'] == '2026-02-26T00:00:00+05:30'

def test_1501_full_json():
    """Verifies normalization of 1501 (Touchline) full JSON events."""
    payload = {
        "ExchangeInstrumentID": 22,
        "ExchangeTimeStamp": 1205682251,
        "LastTradedPrice": 1567.95,
        "LastTradedQuantity": 20,
        "TotalTradedQuantity": 253453,
        "BidInfo": {"Price": 1567.95},
        "AskInfo": {"Price": 0}
    }
    
    norm = XTSNormalizer.normalize_xts_event("1501-json-full", payload)
    assert norm['i'] == 22
    assert norm['p'] == 1567.95
    assert norm['v'] == 20
    assert norm['q'] == 253453
    assert norm['t'] == 1521195251.0
    assert norm['isoDt'] == "2018-03-16T15:44:11+05:30"
    assert norm['bid'] == 1567.95
    assert norm['ask'] is None

def test_1501_partial_string():
    """Verifies normalization of 1501 (Touchline) pipe-separated string events."""
    payload = "t:1_22,ltp:1567.95,ltq:20,v:253453,ltt:1205682110,ai:0|1428|1567.95|10,bi:0|0|0|0|1"
    
    norm = XTSNormalizer.normalize_xts_event("1501-json-partial", payload)
    assert norm['i'] == 22
    assert norm['p'] == 1567.95
    assert norm['v'] == 20
    assert norm['q'] == 253453
    assert norm['t'] == 1521195110.0
    assert norm['isoDt'] == "2018-03-16T15:41:50+05:30"
    assert norm['bid'] == 0.0
    assert norm['ask'] == 1428.0

def test_1501_flat_json():
    """Verifies normalization of the flattened 1501 format used by the simulator."""
    payload = {
        "ltp": 24500.5,
        "ltq": 50,
        "i": 26000,
        "ltt": 1772618459,
        "v": 10000
    }
    norm = XTSNormalizer.normalize_xts_event("1501", payload)
    assert norm["i"] == 26000
    assert norm["p"] == 24500.5
    assert norm["v"] == 50

def test_1512_full_json():
    """Verifies normalization of 1512 (Snapshot/L2) full JSON events."""
    payload = {
        "ExchangeInstrumentID": 26000,
        "ExchangeTimeStamp": 1708435800,
        "LastTradedPrice": 22000.5,
        "LastTradedQuantity": 100,
        "TotalTradedQuantity": 1500000
    }
    norm = XTSNormalizer.normalize_xts_event("1512-json-full", payload)
    assert norm['i'] == 26000
    assert norm['p'] == 22000.5
    assert norm['v'] == 100
    assert norm['q'] == 1500000
    assert norm['t'] == 2023948800.0
    assert norm['isoDt'] == "2034-02-19T13:30:00+05:30"

def test_1512_depth():
    """Verifies normalization of XTS 1512 (Snapshot/L2) JSON format with depth."""
    payload = {
        "ExchangeInstrumentID": 26000,
        "LastTradedPrice": 24500,
        "ExchangeTimeStamp": 1772618459,
        "BidInfo": {"Price": 24495, "Size": 100},
        "AskInfo": {"Price": 24505, "Size": 100}
    }
    norm = XTSNormalizer.normalize_xts_event("1512", payload)
    assert norm["bid"] == 24495
    assert norm["ask"] == 24505
    assert norm["p"] == 24500

def test_1512_partial_string():
    """Verifies normalization of 1512 (Snapshot/L2) pipe-separated string events."""
    payload = "i:26000,ltp:22000.5,ltq:100,v:1500000,ltt:1708435800"
    norm = XTSNormalizer.normalize_xts_event("1512-json-partial", payload)
    assert norm['i'] == 26000
    assert norm['p'] == 22000.5
    assert norm['v'] == 100
    assert norm['q'] == 1500000
    assert norm['t'] == 2023948800.0
    assert norm['isoDt'] == "2034-02-19T13:30:00+05:30"

def test_1505_full_json():
    """Verifies normalization of 1505 (Candle/Bar) full JSON events."""
    payload = {
        "ExchangeInstrumentID": 26000,
        "BarData": {
            "Open": 21900, "High": 22100, "Low": 21850, "Close": 22050, "Volume": 5000, "Timestamp": 1708435800
        }
    }
    norm = XTSNormalizer.normalize_xts_event("1505-json-full", payload)
    assert norm['i'] == 26000
    assert norm['o'] == 21900
    assert norm['h'] == 22100
    assert norm['l'] == 21850
    assert norm['c'] == 22050
    assert norm['v'] == 5000
    assert norm['t'] == 2023948800.0

def test_1505_partial_string():
    """Verifies normalization of 1505 (Candle/Bar) pipe-separated string events."""
    payload = "i:26000,t:1708435800,o:21900,h:22100,l:21850,c:22050,v:5000"
    norm = XTSNormalizer.normalize_xts_event("1505-json-partial", payload)
    assert norm['i'] == 26000
    assert norm['o'] == 21900
    assert norm['h'] == 22100
    assert norm['l'] == 21850
    assert norm['c'] == 22050
    assert norm['v'] == 5000
    assert norm['t'] == 2023948800.0
