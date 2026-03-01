"""
Tests for the PositionManager, verifying trade lifecycle, pnl, and risk controls.
"""
import pytest
import sys
import logging
from datetime import datetime
from io import StringIO
from packages.tradeflow.position_manager import PositionManager
from packages.tradeflow.types import MarketIntentType as MarketIntent, InstrumentKindType as InstrumentType

class MockOrderManager:
    def __init__(self):
        self.orders = []
    
    def place_order(self, symbol, side, quantity):
        self.orders.append({'symbol': symbol, 'side': side, 'qty': quantity})

@pytest.fixture
def pm_setup():
    om = MockOrderManager()
    pm = PositionManager(
        symbol="NIFTY", 
        quantity=50, 
        stop_loss_points=20, 
        target_points=[40, 80],
        instrument_type=InstrumentType.OPTIONS
    )
    pm.set_order_manager(om)
    
    held_output = StringIO()
    from packages.tradeflow.position_manager import logger as pm_logger
    handler = logging.StreamHandler(held_output)
    pm_logger.addHandler(handler)
    
    yield pm, om, held_output
    
    pm_logger.removeHandler(handler)

def test_options_long_intent_cycle(pm_setup, capsys):
    """Tests LONG intent (Buy Call) cycle for Options."""
    pm, om, held_output = pm_setup
    
    # 1. Entry
    now = datetime(2026, 2, 11, 9, 15)
    pm.on_signal({'signal': MarketIntent.LONG, 'price': 100.0, 'timestamp': now})
    
    assert pm.current_position is not None
    assert pm.current_position.intent == MarketIntent.LONG
    assert om.orders[0]['side'] == 'BUY'
    
    output = capsys.readouterr().out + held_output.getvalue()
    assert "🟢 [11-FEB-2026 09:15] Entry: [NIFTY] Purchased 50 lots(65) @ 100.0 | Total: ₹325,000.00" in output

    # 2. Break-Even
    pm.update_tick({'ltp': 141.0, 'timestamp': now.timestamp() + 180}) # +3 mins
    assert pm.current_position.stop_loss == 100.0
    
    output = capsys.readouterr().out + held_output.getvalue()
    assert "🤟 [11-FEB 09:18] Break-Even Triggered!" in output
    assert "🟠 [11-FEB-2026 09:18] TARGET_1 Hit" in output

    # 3. Exit (Trailing SL or Flip)
    from datetime import timedelta
    exit_time = now + timedelta(minutes=15)
    pm.on_signal({'signal': MarketIntent.SHORT, 'price': 120.0, 'timestamp': exit_time})
    assert pm.current_position is None
    
    output = capsys.readouterr().out + held_output.getvalue()
    assert "🔴 [11-FEB-2026 09:30] Exit SIGNAL_EXIT: [NIFTY] Sold 34 lots(65) @ 120.0 | Total: ₹265,200.00 | Action PnL: +44,200.00 | Total Trade PnL: ₹85,800.00" in output

def test_options_short_intent_entry(pm_setup):
    """Tests SHORT intent (Buy Put) for Options."""
    pm, om, _ = pm_setup
    pm.on_signal({'signal': MarketIntent.SHORT, 'price': 100.0, 'timestamp': datetime.now()})
    assert om.orders[0]['side'] == 'BUY' # Long the Put contract
    assert pm.current_position.intent == MarketIntent.SHORT

def test_cash_long_cycle(pm_setup):
    """Tests LONG cycle for Cash."""
    pm, om, _ = pm_setup
    pm.instrument_type = InstrumentType.CASH
    pm.on_signal({'signal': MarketIntent.LONG, 'price': 1000.0, 'timestamp': datetime.now()})
    assert om.orders[0]['side'] == 'BUY'
    
def test_fractional_exit(pm_setup, capsys):
    """Verifies that 1/(N+1) remains open after N targets are hit."""
    pm, om, held_output = pm_setup
    # Setup: 3 targets, initial qty 100. Chunk size = 100 // 4 = 25.
    pm.quantity = 100
    pm.target_steps = [10, 20, 30] 
    now = datetime(2026, 2, 11, 9, 15)
    
    # 1. Entry at 100. Targets: 110, 120, 130
    pm.on_signal({'signal': MarketIntent.LONG, 'price': 100.0, 'timestamp': now})
    
    # 2. Hit Target 1 (110)
    pm.update_tick({'ltp': 110.0, 'timestamp': now.timestamp() + 60})
    assert pm.current_position.remaining_quantity == 75
    
    # 3. Hit Target 2 (120)
    pm.update_tick({'ltp': 120.0, 'timestamp': now.timestamp() + 120})
    assert pm.current_position.remaining_quantity == 50
    
    # 4. Hit Target 3 (130)
    pm.update_tick({'ltp': 130.0, 'timestamp': now.timestamp() + 180})
    
    # Position should still be OPEN with 25 quantity (1/4th)
    assert pm.current_position is not None
    assert pm.current_position.remaining_quantity == 25
    
    output = capsys.readouterr().out + held_output.getvalue()
    assert "🟠 [11-FEB-2026 09:18] TARGET_3 Hit: [NIFTY] Sold 25 lots(65) @ 130.0 | Total: ₹211,250.00 (Action PnL: +48,750.00)" in output

def test_cash_short_blocking(pm_setup):
    """Verifies that SHORT intent is blocked for CASH/FUTURES."""
    pm, om, _ = pm_setup
    pm.instrument_type = InstrumentType.CASH
    pm.on_signal({'signal': MarketIntent.SHORT, 'price': 1000.0, 'timestamp': datetime.now()})
    
    assert pm.current_position is None
    assert len(om.orders) == 0

@pytest.fixture
def pyramid_setup():
    om = MockOrderManager()
    held_output = StringIO()
    from packages.tradeflow.position_manager import logger as pm_logger
    handler = logging.StreamHandler(held_output)
    pm_logger.addHandler(handler)
    
    yield om, held_output
    
    pm_logger.removeHandler(handler)

def test_pyramid_default_100_behaves_like_all_in(pyramid_setup):
    """pyramid_steps=[100] should enter full quantity on first signal (current behavior)."""
    om, _ = pyramid_setup
    pm = PositionManager(
        symbol="NIFTY", quantity=100, stop_loss_points=20,
        target_points=[40], instrument_type=InstrumentType.OPTIONS,
        pyramid_steps=[100]
    )
    pm.set_order_manager(om)
    
    now = datetime(2026, 2, 11, 9, 15)
    pm.on_signal({'signal': MarketIntent.LONG, 'price': 100.0, 'timestamp': now})
    
    assert pm.current_position is not None
    assert pm.current_position.remaining_quantity == 100
    assert pm.current_position.initial_quantity == 100
    assert om.orders[0]['qty'] == 100

def test_pyramid_staged_entry(pyramid_setup):
    """pyramid_steps=[25,50,25] should enter 25% first, then add 50% and 25% on confirmation."""
    om, _ = pyramid_setup
    pm = PositionManager(
        symbol="NIFTY", quantity=100, stop_loss_points=20,
        target_points=[40], instrument_type=InstrumentType.OPTIONS,
        pyramid_steps=[25, 50, 25], pyramid_confirm_pts=10.0
    )
    pm.set_order_manager(om)
    
    now = datetime(2026, 2, 11, 9, 15)
    
    # Step 1: Initial entry → 25% of 100 = 25 lots
    pm.on_signal({'signal': MarketIntent.LONG, 'price': 100.0, 'timestamp': now})
    assert pm.current_position.remaining_quantity == 25
    assert pm.current_position.pyramid_step == 0
    assert om.orders[0]['qty'] == 25
    
    # Same-direction signal but price NOT confirmed (only +5, need +10)
    pm.on_signal({'signal': MarketIntent.LONG, 'price': 105.0, 'timestamp': now})
    assert pm.current_position.remaining_quantity == 25  # No change
    
    # Step 2: Same-direction signal WITH confirmation (+15 pts) → 50% of 100 = 50 lots
    pm.on_signal({'signal': MarketIntent.LONG, 'price': 115.0, 'timestamp': now})
    assert pm.current_position.remaining_quantity == 75  # 25 + 50
    assert pm.current_position.pyramid_step == 1
    assert om.orders[-1]['qty'] == 50
    
    # Step 3: Final step → 25% of 100 = 25 lots (need price to move beyond new avg entry)
    new_avg = pm.current_position.entry_price
    confirm_price = new_avg + 15  # Enough to confirm
    pm.on_signal({'signal': MarketIntent.LONG, 'price': confirm_price, 'timestamp': now})
    assert pm.current_position.remaining_quantity == 100  # 75 + 25
    assert pm.current_position.pyramid_step == 2

def test_pyramid_max_steps_stops_adding(pyramid_setup):
    """After all pyramid steps are used, same-direction signals should be ignored."""
    om, _ = pyramid_setup
    pm = PositionManager(
        symbol="NIFTY", quantity=100, stop_loss_points=20,
        target_points=[40], instrument_type=InstrumentType.OPTIONS,
        pyramid_steps=[50, 50], pyramid_confirm_pts=5.0
    )
    pm.set_order_manager(om)
    
    now = datetime(2026, 2, 11, 9, 15)
    
    # Step 1: 50% = 50 lots
    pm.on_signal({'signal': MarketIntent.LONG, 'price': 100.0, 'timestamp': now})
    assert pm.current_position.remaining_quantity == 50
    
    # Step 2: Another 50% = 50 lots (confirmed)
    pm.on_signal({'signal': MarketIntent.LONG, 'price': 115.0, 'timestamp': now})
    assert pm.current_position.remaining_quantity == 100
    assert pm.current_position.pyramid_step == 1
    
    # Step 3: Should NOT add more — all steps exhausted
    qty_before = pm.current_position.remaining_quantity
    pm.on_signal({'signal': MarketIntent.LONG, 'price': 130.0, 'timestamp': now})
    assert pm.current_position.remaining_quantity == qty_before
