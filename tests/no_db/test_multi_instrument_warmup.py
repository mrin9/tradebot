import pytest
from unittest.mock import MagicMock, patch
from packages.tradeflow.fund_manager import FundManager
from packages.config import settings
from packages.tradeflow.types import InstrumentCategoryType

def test_multi_instrument_drift_warmup():
    """
    Verifies that FundManager triggers warmup for both CE and PE instruments
    when a price drift (> 25 points) is detected on the Spot price.
    """
    
    # 1. Setup Mock Strategy and Config
    strategy_config = {
        "strategyId": "test-drift",
        "name": "Drift Test",
        "indicators": [],
        "timeframe_seconds": 60,
        "pythonStrategyPath": "packages/tradeflow/python_strategies.py:TripleLockStrategy"
    }
    position_config = {
        "symbol": "NIFTY",
        "budget": 10000,
        "invest_mode": "fixed",
        "instrument_type": "OPTIONS",
        "strike_selection": "ATM",
        "price_source": "close",
        "sl_points": 15.0,
        "target_points": [15, 25, 45],
        "tsl_points": 15.0,
        "use_be": True,
        "use_break_even": False,
        "pyramid_steps": 0,
        "pyramid_confirm_pts": 0,
        "python_strategy_path": "packages/tradeflow/python_strategies.py:TripleLockStrategy"
    }

    # 2. Mock Services
    mock_config_service = MagicMock()
    # Ensure config service returns our configs normalized
    mock_config_service.normalize_strategy_config.return_value = strategy_config
    mock_config_service.build_position_config.return_value = position_config

    mock_discovery = MagicMock()
    mock_history = MagicMock()
    
    # Initial ATM resolution (at price 22000)
    mock_discovery.get_atm_strike.side_effect = lambda p: round(p / 50) * 50
    # resolve_option_contract(strike, is_ce, current_ts)
    mock_discovery.resolve_option_contract.side_effect = [
        (1001, "NIFTY CE 22000"), # Initial CE
        (1002, "NIFTY PE 22000"), # Initial PE
        (2001, "NIFTY CE 22100"), # New CE after drift
        (2002, "NIFTY PE 22100")  # New PE after drift
    ]

    # 3. Initialize FundManager with mocked services
    from packages.tradeflow.types import SignalType
    with patch('packages.tradeflow.fund_manager.PythonStrategy') as mock_strat_cls:
        mock_strat_inst = mock_strat_cls.return_value
        mock_strat_inst.on_resampled_candle_closed.return_value = (SignalType.NEUTRAL, "Neutral", 0.0)
        
        fm = FundManager(
            strategy_config=strategy_config,
            position_config=position_config,
            config_service=mock_config_service,
            discovery_service=mock_discovery,
            history_service=mock_history,
            is_backtest=False # Simulate live-like behavior for drift checks
        )

    # 4. First Tick: Set initial spot price anchor
    # Price = 22000, TS = 1770000000
    fm.on_tick_or_base_candle({'i': 26000, 'p': 22000.0, 't': 1770000000})
    
    # Verify initial instruments are set and warmup called
    assert fm.active_instruments['CE'] == 1001
    assert fm.active_instruments['PE'] == 1002
    assert mock_history.run_warmup.call_count == 2
    
    # Reset mock to check for drift-induced calls
    mock_history.run_warmup.reset_mock()
    
    # 5. Second Tick: Small move (No drift)
    # Price = 22010 (drift = 10 < 25)
    fm.on_tick_or_base_candle({'i': 26000, 'p': 22010.0, 't': 1770000060})
    assert mock_history.run_warmup.call_count == 0
    
    # 6. Third Tick: Large move (Drift Triggered)
    # Price = 22100 (drift = 100 > 25)
    fm.on_tick_or_base_candle({'i': 26000, 'p': 22100.0, 't': 1770000120})
    
    # Verify new instruments selected
    assert fm.active_instruments['CE'] == 2001
    assert fm.active_instruments['PE'] == 2002
    
    # Verify run_warmup called for BOTH new instruments
    assert mock_history.run_warmup.call_count == 2
    
    # Verify exact calls
    calls = mock_history.run_warmup.call_args_list
    # call(fund_manager, instrument_id, current_ts, category, use_api)
    
    # Call 1: CE
    args_ce = calls[0][0]
    assert args_ce[1] == 2001 # CE ID
    assert args_ce[2] == 1770000120 # Current TS
    assert args_ce[3] == "CE" # Category
    
    # Call 2: PE
    args_pe = calls[1][0]
    assert args_pe[1] == 2002 # PE ID
    assert args_pe[2] == 1770000120 # Current TS
    assert args_pe[3] == "PE" # Category

    print("✅ Multi-instrument drift warmup test PASSED.")

if __name__ == "__main__":
    test_multi_instrument_drift_warmup()
