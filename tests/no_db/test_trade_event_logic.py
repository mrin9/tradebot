import pytest
from unittest.mock import MagicMock
from packages.services.trade_event import TradeEventService
from packages.utils.date_utils import DateUtils

def test_build_config_summary_enrichment():
    # Mock FundManager
    fm = MagicMock()
    fm.config = {
        "strategyId": "triple-confirmation",
        "name": "Triple Confirmation Momentum Strategy"
    }
    fm.position_config = {
        "budget": 100000,
        "python_strategy_path": "path/to/strat", 
        "pyramid_steps": [100], 
        "pyramid_confirm_pts": 10.0
    }
    fm.global_timeframe = 180
    fm.indicator_calculator.config = [
        {"indicator": "ema-5", "InstrumentType": "SPOT"},
        {"indicator": "ema-21", "InstrumentType": "OPTIONS_BOTH"}
    ]
    fm.tsl_indicator_id = "SPOT-EMA-5"
    fm.invest_mode = "fixed"
    fm.stop_loss_points = 15.0
    fm.target_points = [15.0, 25.0, 50.0]
    fm.trailing_sl_points = 0.0
    fm.use_break_even = True
    fm.strike_selection = "ATM"
    fm.price_source = "close"
    
    summary = TradeEventService.build_config_summary(fm, mode="live")
    
    assert summary["strategyId"] == "triple-confirmation"
    assert summary["indicators"] == ["SPOT-EMA-5", "OPTIONS-BOTH-EMA-21"]
    assert summary["budget"] == 100000
    assert summary["target_points"] == [15.0, 25.0, 50.0]

def test_session_id_generation():
    session_id = DateUtils.generate_session_id("triple-confirmation")
    # Format: monthday-hourminute-strategyPrefix-rand3
    # Example: mar12-0928-triple-hlf
    parts = session_id.split("-")
    assert len(parts) == 4
    assert parts[2] == "triple"
    assert len(parts[3]) == 3

def test_trade_event_service_granular_pnl_passing():
    persistence_mock = MagicMock()
    service = TradeEventService(session_id="test-session")
    service.persistence = persistence_mock
    service.db = MagicMock() # Mock DB for insert_one
    
    fund_manager = MagicMock()
    pos = MagicMock()
    pos.symbol = "NIFTY"
    pos.display_symbol = "NIFTY"
    pos.current_price = 100.0
    pos.remaining_quantity = 50
    pos.total_realized_pnl = 500.0
    fund_manager.position_manager.current_position = pos
    fund_manager.position_manager.session_realized_pnl = 1000.0
    fund_manager.latest_tick_prices = {26000: 25000.0}
    
    event_data = {
        "type": "target",
        "transaction": "Target 1 Hit",
        "actionPnL": 250.0
    }
    
    service.record_trade_event(event_data, fund_manager)
    
    # Verify persistence.record_granular_event called with correct action_pnl
    args, kwargs = persistence_mock.record_granular_event.call_args
    assert kwargs["action_pnl"] == 250.0
    assert kwargs["msg"] == "Target 1 Hit"

def test_persist_non_position_event_structure():
    service = TradeEventService(session_id="test-session")
    service.db = MagicMock()
    
    event_data = {
        "type": "INIT",
        "msg": "Initialization",
        "timestamp": "2026-03-12T09:00:00+05:30" # Should be removed
    }
    
    service._persist_non_position_event(event_data)
    
    # Verify timestamp removed and createdAt added
    inserted_doc = service.db["papertrade"].insert_one.call_args[0][0]
    assert "timestamp" not in inserted_doc
    assert "createdAt" in inserted_doc
    assert inserted_doc["sessionId"] == "test-session"

def test_skip_summary_in_papertrade():
    service = TradeEventService(session_id="test-session")
    service.db = MagicMock()
    persistence_mock = MagicMock()
    service.persistence = persistence_mock
    
    # Case 1: Position active
    fund_manager = MagicMock()
    fund_manager.position_manager.current_position = MagicMock()
    
    event_data = {"type": "SUMMARY"}
    service.record_trade_event(event_data, fund_manager)
    
    # Both position and non-position persistence should NOT be called
    assert not persistence_mock.record_granular_event.called
    assert not service.db["papertrade"].insert_one.called
    
    # Case 2: No position active
    service.record_trade_event({"type": "SUMMARY"}, MagicMock())
    assert not service.db["papertrade"].insert_one.called
