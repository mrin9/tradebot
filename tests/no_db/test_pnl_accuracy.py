import pytest
from datetime import datetime
from packages.tradeflow.position_manager import PositionManager
from packages.tradeflow.types import MarketIntentType as MarketIntent, InstrumentKindType as InstrumentType
from packages.config import settings

def test_pnl_currency_accuracy():
    """
    Specifically verifies that PnL is calculated as (price_diff * quantity * lot_size).
    For NIFTY, lot_size is 65.
    """
    pm = PositionManager(
        symbol="NIFTY", 
        quantity=10, # 10 lots
        stop_loss_points=20, 
        target_points=[50],
        instrument_type=InstrumentType.OPTIONS
    )
    
    # 1. Entry at 100
    pm.on_signal({'signal': MarketIntent.LONG, 'price': 100.0, 'timestamp': datetime.now()})
    
    # 2. Update price to 110 (+10 points)
    # Expected PnL: 10 points * 10 lots * 65 = 6500
    pm.update_tick({'ltp': 110.0, 'timestamp': datetime.now().timestamp()})
    
    assert pm.current_position.pnl == 10 * 10 * 65
    assert pm.current_position.pnl == 6500.0

    # 3. Partially exit on target hit (Target 1 is 150, let's hit it)
    # Target 1: 100 + 50 = 150
    # Hit at 150
    pm.update_tick({'ltp': 150.0, 'timestamp': datetime.now().timestamp()})
    
    # Fractional exit: quantity // (len(targets) + 1) = 10 // 2 = 5 lots
    # Target 1 realized PnL: (150 - 100) * 5 * 65 = 50 * 5 * 65 = 16250
    assert pm.current_position.total_realized_pnl == 16250.0
    assert pm.current_position.remaining_quantity == 5
    
    # Remaining PnL at 150: (150 - 100) * 5 * 65 = 16250
    assert pm.current_position.pnl == 16250.0

    # 4. Final exit at 160
    # Expected final realized PnL: 16250 (already realized) + (160 - 100) * 5 * 65
    # = 16250 + 60 * 5 * 65 = 16250 + 19500 = 35750
    pm._close_position(160.0, datetime.now(), "FINAL_EXIT")
    
    last_trade = pm.trades_history[-1]
    assert pm.trades_history[0].pnl == 16250.0 # Target chunk
    assert last_trade.pnl == 19500.0 # Final chunk
    
    total_realized = sum(t.pnl for t in pm.trades_history)
    assert total_realized == 35750.0
