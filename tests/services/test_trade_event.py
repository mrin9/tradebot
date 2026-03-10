import pytest
from unittest.mock import MagicMock, patch
from packages.services.trade_event import TradeEventService

@pytest.fixture
def mock_persistence():
    with patch("packages.services.trade_event.TradePersistence") as tp:
        yield tp.return_value

def test_trade_event_record_init(mock_persistence):
    with patch("packages.services.trade_event.MongoRepository.get_db") as mock_get_db:
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        service = TradeEventService("test-session")
        
        mock_col = MagicMock()
        mock_db.__getitem__.return_value = mock_col
        
        service.record_init({"strategyId": "test"})
        assert mock_col.insert_one.call_count == 1
        args = mock_col.insert_one.call_args[0][0]
        assert args["type"] == "INIT"
        assert args["sessionId"] == "test-session"

def test_trade_event_record_signal(mock_persistence):
    service = TradeEventService("test-session")
    payload = {
        "symbol": "50001",
        "reason": "LONG",
        "reason_desc": "Supertrend",
        "timestamp": 1770000000,
        "timeframe": 300
    }
    service.record_signal(payload)
    assert len(service.active_signals) == 1
    assert service.active_signals[0]["symbol"] == "50001"

def test_trade_event_record_trade(mock_persistence):
    service = TradeEventService("test-session")
    mock_fm = MagicMock()
    mock_fm.latest_tick_prices = {26000: 22000.0}
    mock_pos = MagicMock()
    mock_pos.symbol = "50001"
    mock_pos.to_cycle_dict.return_value = {}
    mock_fm.position_manager.current_position = mock_pos
    
    event_data = {"type": "ENTRY", "transaction": "Buy NIFTY CE"}
    service.record_trade_event(event_data, mock_fm)
    
    # Should call persist granular event
    assert mock_persistence.record_granular_event.call_count == 1
    args = mock_persistence.record_granular_event.call_args[1]
    assert args["session_id"] == "test-session"
    assert args["event_type"] == "ENTRY"
