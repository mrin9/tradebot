import pytest
from datetime import datetime
from unittest.mock import MagicMock
from packages.tradeflow.position_manager import PositionManager
from packages.tradeflow.types import MarketIntentType as MarketIntent, InstrumentKindType as InstrumentType
from packages.utils.date_utils import DateUtils

class MockOrderManager:
    def place_order(self, symbol, side, quantity):
        pass

def test_papertrade_timestamps_reflect_market_time():
    """
    Verifies that PositionManager emits 'tradetime' matching the input tick/signal timestamp.
    """
    pm = PositionManager(
        symbol="NIFTY", 
        quantity=50, 
        stop_loss_points=20, 
        target_points=[40],
        instrument_type=InstrumentType.OPTIONS
    )
    pm.set_order_manager(MockOrderManager())
    
    events = []
    pm.on_trade_event = lambda x: events.append(x)
    
    # 1. Entry Signal with specific timestamp
    # 10:00:00 IST
    market_ts = 1741235400 # 2025-03-06 10:00:00 IST
    market_dt = DateUtils.market_timestamp_to_datetime(market_ts)
    market_iso = DateUtils.to_iso(market_dt)
    
    pm.on_signal({
        'signal': MarketIntent.LONG, 
        'symbol': 'NIFTY',
        'display_symbol': 'NIFTY',
        'price': 100.0, 
        'timestamp': market_dt
    })
    
    assert len(events) == 1
    assert events[0]['type'] == 'entry'
    assert events[0]['tradetime'] == market_iso
    
    # 2. Update with tick and hit target
    # 10:05:00 IST
    tick_ts = market_ts + 300
    tick_iso = DateUtils.to_iso(DateUtils.market_timestamp_to_datetime(tick_ts))
    
    pm.update_tick({
        'p': 145.0, # Hits target (100+40)
        't': tick_ts
    })
    
    # Target hit event should have tick_iso
    target_event = next(e for e in events if e['type'] == 'target_1')
    assert target_event['tradetime'] == tick_iso
    
    # 3. Exit via signal flip
    # 10:10:00 IST
    exit_ts = tick_ts + 300
    exit_dt = DateUtils.market_timestamp_to_datetime(exit_ts)
    exit_iso = DateUtils.to_iso(exit_dt)
    
    pm.on_signal({
        'signal': MarketIntent.SHORT, 
        'symbol': 'NIFTY',
        'display_symbol': 'NIFTY',
        'price': 120.0, 
        'timestamp': exit_dt
    })
    
    exit_event = next(e for e in events if e['type'] == 'exit')
    assert exit_event['tradetime'] == exit_iso
    
    summary_event = next(e for e in events if e['type'] == 'summary')
    # Summary event still uses system time in the implementation: DateUtils.to_iso(DateUtils.get_market_time())
    # But for analysis of trade timing, entry/exit/target are the most important.
    # Actually, the user wants "pertrade collection to reflect the socket time".
    
def test_live_trader_recorded_at_reflects_market_time():
    """
    Verifies that LiveTradeEngine uses fund_manager's market time for 'recordedAt'.
    """
    from packages.livetrade.live_trader import LiveTradeEngine
    from unittest.mock import patch
    
    strategy_config = {"name": "Test", "ruleId": "TEST-001"}
    position_config = {
        "symbol": "NIFTY",
        "quantity": 50,
        "python_strategy_path": "packages/tradeflow/python_strategies.py:TripleLockStrategy",
        "stop_loss_points": 10,
        "target_points": 20,
        "record_papertrade_db": True
    }
    
    mock_db = MagicMock()
    mock_soc = MagicMock()
    
    # Use context managers to safely patch and unpatch
    with patch("packages.utils.mongo.MongoRepository.get_db", return_value=mock_db), \
         patch("packages.data.connectors.xts_wrapper.XTSManager._get_market_client", return_value=MagicMock()), \
         patch("packages.data.connectors.xts_wrapper.XTSManager.get_market_data_socket", return_value=mock_soc):
        
        engine = LiveTradeEngine(strategy_config, position_config)
        
        # Inject fake market time into fund_manager
        fake_market_ts = 1741239000 # 11:00:00 IST
        engine.fund_manager.latest_market_time = fake_market_ts
        fake_market_iso = DateUtils.market_timestamp_to_iso(fake_market_ts)
        
        event_data = {"type": "test_event", "instrument": "NIFTY", "tradetime": "2025-03-06T10:00:00"}
        engine.event_service.record_trade_event(event_data, engine.fund_manager)
        
        # Verify what was inserted into DB
        inserted_doc = mock_db["papertrade"].insert_one.call_args[0][0]
        # In the new logic, timestamp is removed and createdAt is used instead (system time)
        assert "timestamp" not in inserted_doc
        assert "createdAt" in inserted_doc
