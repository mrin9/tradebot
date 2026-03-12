"""
End-to-End Strategy Tests: Verifying full signal and trade execution against seeded data.
Uses frozen data in tradebot_frozen_test to ensure deterministic results.
"""
import pytest
import os
import sys
import json
import tempfile
from datetime import datetime

from packages.utils.mongo import MongoRepository
from packages.tradeflow.fund_manager import FundManager
from packages.tradeflow.types import SignalType as Signal
from packages.config import settings

@pytest.fixture(scope="function", autouse=True)
def patch_settings():
    """Patch settings for the duration of each test to ensure frozen data isolation."""
    orig_db = settings.DB_NAME
    orig_nifty = settings.NIFTY_CANDLE_COLLECTION
    orig_opt = settings.OPTIONS_CANDLE_COLLECTION
    orig_inst = settings.INSTRUMENT_MASTER_COLLECTION
    
    settings.DB_NAME = "tradebot_frozen_test"
    settings.NIFTY_CANDLE_COLLECTION = "nifty_candle_test_data"
    settings.OPTIONS_CANDLE_COLLECTION = "options_candle_test_data"
    settings.INSTRUMENT_MASTER_COLLECTION = "instrument_master_test_data"
    
    # Reset MongoRepository cache to pickup new settings
    MongoRepository._client = None
    MongoRepository._db = None
    
    yield
    
    settings.DB_NAME = orig_db
    settings.NIFTY_CANDLE_COLLECTION = orig_nifty
    settings.OPTIONS_CANDLE_COLLECTION = orig_opt
    settings.INSTRUMENT_MASTER_COLLECTION = orig_inst
    
    MongoRepository._client = None
    MongoRepository._db = None

@pytest.fixture(scope="function")
def db_conn():
    return MongoRepository.get_db()

def run_strategy_backtest(db, strategy_id, pos_overrides=None, use_real_strategy=False, start_time=None):
    # 1. Fetch Strategy Config from the special test collection
    # Note: The test collection uses 'strategyId' (camelCase) instead of 'strategy_id'
    strategy_config = db["strategy_indicators_test_data"].find_one({"strategyId": strategy_id})
    if not strategy_config:
        # Fallback to strategy_id just in case
        strategy_config = db["strategy_indicators_test_data"].find_one({"strategy_id": strategy_id})
        
    assert strategy_config is not None, f"Strategy {strategy_id} not found in strategy_indicators_test_data"
    
    # Map camelCase to snake_case for the engine
    if "strategyId" in strategy_config:
        strategy_config["strategy_id"] = strategy_config["strategyId"]
    if "pythonStrategyPath" in strategy_config:
        strategy_config["python_strategy_path"] = strategy_config["pythonStrategyPath"]

    # 2. Setup Position Config
    # Default config for testing
    pos_config = {"budget": 200000, "quantity": 50, "instrument_type": "OPTIONS", "python_strategy_path": "packages/tradeflow/python_strategies.py:TripleLockStrategy"}
    if pos_overrides:
        pos_config.update(pos_overrides)
        
    # Create a dynamic python strategy mimicking the DB rules
    import tempfile
    import os
    
    # Simple mapping of rule_id to a dummy Python implementation 
    # that just hardcodes the expected trade logic for the test
    strategy_code = ""
    class_name = "DummyStrategy"
    
    if strategy_id == "ema-5x21+rsi-180s-triple":
        class_name = "TripleLockTestStrategy"
        strategy_code = '''
from typing import Dict, Any, Tuple, Optional
from packages.tradeflow.types import CandleType, SignalType, MarketIntentType

class TripleLockTestStrategy:
    """
    Dummy Strategy for Engine Pipeline Testing.
    Verifies that FundManager can drive signals based on indicator presence.
    """
    def __init__(self):
        self.trade_count = 0
        
    def on_resampled_candle_closed(self, candle: CandleType, indicators: Dict[str, Any], current_position_intent: Optional[MarketIntentType] = None) -> Tuple[SignalType, str, float]:
        ce_fast = indicators.get("ce-ema-5")
        if ce_fast is None: return SignalType.NEUTRAL, "WAITING_FOR_INDICATORS", 0.0
        
        if current_position_intent is None and self.trade_count < 14:
            self.trade_count += 1
            # Alternate entries to test both CALL and PUT logic
            if self.trade_count % 2 == 0:
                return SignalType.LONG, "DUMMY_CALL_ENTRY", 1.0
            else:
                return SignalType.SHORT, "DUMMY_PUT_ENTRY", 1.0
        
        # NOTE: We do NOT return SignalType.EXIT here by default.
        # This allows the engine's SL/Target parameters to be the primary exit driver.
        return SignalType.NEUTRAL, "NO_SIGNAL", 0.0
'''
    elif strategy_id == "ema-9x21+st+rsi-300s-active":
        class_name = "SupertrendTestStrategy"
        strategy_code = '''
from typing import Dict, Any, Tuple, Optional
from packages.tradeflow.types import CandleType, SignalType, MarketIntentType

class SupertrendTestStrategy:
    def __init__(self):
        self.trade_count = 0
        
    def on_resampled_candle_closed(self, candle: CandleType, indicators: Dict[str, Any], current_position_intent: Optional[MarketIntentType] = None) -> Tuple[SignalType, str, float]:
        a_f = indicators.get("active-ema-9")
        if a_f is None: return SignalType.NEUTRAL, "WAITING_FOR_INDICATORS", 0.0
        
        if current_position_intent is None and self.trade_count < 9:
            self.trade_count += 1
            if self.trade_count % 2 == 0:
                return SignalType.SHORT, "DUMMY_PUT", 1.0
            else:
                return SignalType.LONG, "DUMMY_CALL", 1.0
        
        return SignalType.NEUTRAL, "NO_SIGNAL", 0.0
'''
    elif strategy_id == "macd+st+slope-180s-dual":
        class_name = "MacdTestStrategy"
        strategy_code = '''
from typing import Dict, Any, Tuple, Optional
from packages.tradeflow.types import CandleType, SignalType, MarketIntentType

class MacdTestStrategy:
    def __init__(self):
        self.trade_count = 0
        
    def on_resampled_candle_closed(self, candle: CandleType, indicators: Dict[str, Any], current_position_intent: Optional[MarketIntentType] = None) -> Tuple[SignalType, str, float]:
        if current_position_intent is None and self.trade_count < 13:
            self.trade_count += 1
            if self.trade_count % 2 == 0:
                return SignalType.LONG, "DUMMY_MACD_LONG", 1.0
            else:
                return SignalType.SHORT, "DUMMY_MACD_SHORT", 1.0
        
        return SignalType.NEUTRAL, "NO_SIGNAL", 0.0
'''
    else:
        # Fallback dummy
        strategy_code = f"class {class_name}:\n    def on_resampled_candle_closed(self, *args, **kwargs): return __import__('packages.tradeflow.types', fromlist=['SignalType']).SignalType.NEUTRAL, '', 0.0"

    path = None
    if use_real_strategy:
        # Use the actual strategy from the codebase
        # The path in DB is relative to package root
        project_root = "/Users/mrin/work/trade-bot-v2"
        rel_path = strategy_config.get("python_strategy_path")
        pos_config["python_strategy_path"] = f"{project_root}/{rel_path}"
    else:
        fd, path = tempfile.mkstemp(suffix=".py")
        with os.fdopen(fd, 'w') as f:
            f.write(strategy_code)
        pos_config["python_strategy_path"] = f"{path}:{class_name}"

    fm = FundManager(
        strategy_config=strategy_config,
        position_config=pos_config,
        is_backtest=True,
        log_heartbeat=True
    )
    
    # We hook into position_manager signals to capture trade count
    captured_signals = []
    original_on_signal = fm.position_manager.on_signal
    
    def spy_on_signal(data):
        print(f"SPY SIGNAL CAUGHT: {data}")
        captured_signals.append(data)
        original_on_signal(data)
        
    fm.position_manager.on_signal = spy_on_signal
    
    # Spy on resampled candles
    resampled_counts = {"SPOT": 0, "CE": 0, "PE": 0}
    original_resampled = fm._on_resampled_candle_closed
    def spy_resampled(candle, category):
        cat_str = category.value if hasattr(category, 'value') else category
        resampled_counts[cat_str] = resampled_counts.get(cat_str, 0) + 1
        original_resampled(candle, category)
    fm._on_resampled_candle_closed = spy_resampled
    
    # 3. Fetch all sorted data (Nifty + Options)
    query = {}
    if start_time:
        query = {"t": {"$gte": start_time}}
        
    nifty_docs = list(db[settings.NIFTY_CANDLE_COLLECTION].find(query))
    options_docs = list(db[settings.OPTIONS_CANDLE_COLLECTION].find(query))
    
    all_docs = nifty_docs + options_docs
    # Sort by timestamp (t). If same timestamp, guarantee Nifty processes first to trigger _check_and_update_monitored_instruments
    all_docs.sort(key=lambda x: (x['t'], 0 if x['i'] == 26000 else 1))
    
    # 4. Stream data into FundManager
    for doc in all_docs:
        fm.on_tick_or_base_candle(doc)
    
    # Final logging of all trades
    for i, t in enumerate(fm.position_manager.trades_history):
        print(f"TRADE {i+1}: Symbol={t.symbol}, Entry={t.entry_price}, Exit={t.exit_price}, Reason={t.status}, PnL={t.pnl}")
        
    if path and os.path.exists(path):
        os.remove(path)
    return fm, captured_signals, resampled_counts

def test_ema_triple_lock(db_conn):
    """
    Verifies Engine Pipeline: EMA 5x21 + RSI Filter (180s/3m Timeframe)
    Tests Multi-Instrument Monitoring, Warmup, and Entry Logic against GOLDEN COPY.
    """
    # Use the REAL strategy logic
    # Filter for Feb 6th to match Golden Copy window
    # Enable Compounding to match Golden Copy quantity logic
    fm, signals, counts = run_strategy_backtest(
        db_conn, 
        "ema-5x21+rsi-180s-triple", 
        use_real_strategy=True, 
        start_time=1770349500,
        pos_overrides={"invest_mode": "compound"}
    )
    
    trades = fm.position_manager.trades_history
    total_pnl = sum([t.pnl for t in trades])
    print(f"EMA Triple Lock Trades: {len(trades)} | PnL: {total_pnl}")
    
    # Fundamental pipeline integrity
    # Total candles in one day (375 mins / 3 mins = 125, but indexing might show 124/125)
    assert counts["SPOT"] >= 120, f"Expected ~120+ candles for Feb 6th, got {counts['SPOT']}"
    
    # Load Golden Copy for high-fidelity verification
    current_dir = os.path.dirname(os.path.abspath(__file__))
    golden_path = os.path.join(current_dir, "golden", "ema_triple_lock_golden_trades.json")
    with open(golden_path) as f:
        golden_trades = json.load(f)
        
    assert len(trades) == len(golden_trades), f"Trade count mismatch! Actual: {len(trades)}, Golden: {len(golden_trades)}"
    
    # Verify each trade against golden copy
    # We allow small price/pnl floats for precision, but timestamps and symbols must match exactly.
    for i, (actual, golden) in enumerate(zip(trades, golden_trades)):
        print(f"Verifying Trade {i+1}: {actual.symbol}")
        assert actual.symbol == golden["symbol"]
        assert actual.intent.name.replace("LONG", "MarketIntentType.LONG").replace("SHORT", "MarketIntentType.SHORT") == golden["intent"]
        
        # Price check (float tolerant)
        assert abs(actual.entry_price - golden["entry_price"]) < 0.1
        assert abs(actual.exit_price - golden["exit_price"]) < 0.1
        
        # PnL check (Formula verification)
        assert abs(actual.pnl - golden["pnl"]) < 1.0

    print("✅ Successfully verified Triple Lock Strategy against Golden Copy.")

def test_ema_supertrend_active_only(db_conn):
    """
    Verifies Engine Pipeline: EMA 9x21 + ST + RSI (300s/5m) - Active Only
    Tests Single-Instrument Resampling and Execution.
    """
    fm, signals, counts = run_strategy_backtest(db_conn, "ema-9x21+st+rsi-300s-active")
    
    trades = fm.position_manager.trades_history
    total_pnl = sum([t.pnl for t in trades])
    print(f"EMA Active Only Trades: {len(trades)} | PnL: {total_pnl}")

    assert counts["SPOT"] == 374, f"Expected 374 candles, got {counts['SPOT']}"
    assert len(trades) == 2
    assert round(total_pnl, 2) == 15600.0

def test_macd_dual(db_conn):
    """
    Verifies Engine Pipeline: MACD + ST + Slope (180s/3m)
    Tests Dual-Instrument Resampling and Execution.
    """
    fm, signals, counts = run_strategy_backtest(db_conn, "macd+st+slope-180s-dual")
    
    trades = fm.position_manager.trades_history
    total_pnl = sum([t.pnl for t in trades])
    print(f"MACD Dual Trades: {len(trades)} | PnL: {total_pnl}")
    
    assert counts["SPOT"] == 624, f"Expected 624 candles, got {counts['SPOT']}"
    assert len(trades) == 4
    assert round(total_pnl, 2) == 4875.0

def test_position_manager_parameters(db_conn):
    """
    Tests FundManager parameters: stop_loss, trailing_sl, and targets.
    Ensures engine-level exits work correctly even without strategy-level EXIT signals.
    """
    pos_overrides = {
        "sl_points": 5.0,
        "target_points": "5,10,15",
        "tsl_points": 2.0,
        "use_be": True
    }
    
    # Calibration run with these tighter parameters:
    # Target 1 (5pts @ 50 qty): 5 * 50 = 250 (Wait, qty is calculated from budget/price)
    # Actually, let's just run it and see the new PnL.
    
    fm, signals, counts = run_strategy_backtest(db_conn, "ema-9x21+st+rsi-300s-active", pos_overrides)
    
    trades = fm.position_manager.trades_history
    print(f"Position Manager Parameter Test Trades: {len(trades)}")
    
    assert len(trades) > 0
    
    exit_reasons = [t.status for t in trades]
    print(f"Exit Reasons: {exit_reasons}")
    
    # We expect some trades to exit via SL or Targets
    non_strategy_exits = [r for r in exit_reasons if r.startswith("TARGET") or r in ["STOP_LOSS", "TRAILING_SL"]]
    assert len(non_strategy_exits) > 0, "Expected at least one engine-level exit (SL/Target/TSL)"
    
    total_pnl = sum([t.pnl for t in trades])
    print(f"Parameter Test PnL: {total_pnl}")
    assert len(trades) == 15
    assert round(total_pnl, 2) == -11505.0
