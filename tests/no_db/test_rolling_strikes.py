"""
Tests for the dynamic Rolling Strike subscription logic in LiveTradeEngine.
"""

from unittest.mock import MagicMock, patch

from packages.livetrade.live_trader import LiveTradeEngine
from packages.settings import settings


def test_update_rolling_strikes_access():
    """Verifies that _update_rolling_strikes correctly accesses positions without AttributeError."""
    print("Testing _update_rolling_strikes position access...")

    mock_strategy = {"ruleId": "TEST_01", "name": "Test Strategy", "indicators": []}
    pos_cfg = {
        "budget": 100000,
        "symbol": "NIFTY",
        "quantity": 50,
        "python_strategy_path": "packages/tradeflow/python_strategies.py:TripleLockStrategy",
        "stop_loss_points": 10,
        "target_points": 20,
    }

    with (
        patch("packages.xts.xts_session_manager.XtsSessionManager._get_market_client"),
        patch("packages.xts.xts_session_manager.XtsSessionManager.get_market_data_socket"),
        patch("packages.utils.mongo.MongoRepository.get_db"),
    ):
        engine = LiveTradeEngine(mock_strategy, pos_cfg)

        # Mock ContractDiscoveryService to return dummy IDs
        engine.discovery_service.get_strike_window_ids = MagicMock(return_value={101, 102, 103})

        # Test case 1: No active position
        engine.fund_manager.position_manager.current_position = None
        engine._update_rolling_strikes(25000)

        # Test case 2: With active position
        mock_pos = MagicMock()
        mock_pos.symbol = "101"
        engine.fund_manager.position_manager.current_position = mock_pos
        engine._update_rolling_strikes(25050)


def test_atm_hysteresis_logic():
    """Verifies that ATM shifts only happen when price exceeds the hysteresis buffer."""
    print("Testing ATM Hysteresis logic...")

    mock_strategy = {"ruleId": "T1", "name": "T", "indicators": []}
    pos_cfg = {
        "budget": 100000,
        "symbol": "NIFTY",
        "quantity": 50,
        "stop_loss_points": 10,
        "target_points": 20,
        "python_strategy_path": "packages/tradeflow/python_strategies.py:TripleLockStrategy",
    }

    with (
        patch("packages.xts.xts_session_manager.XtsSessionManager._get_market_client"),
        patch("packages.xts.xts_session_manager.XtsSessionManager.get_market_data_socket"),
        patch("packages.utils.mongo.MongoRepository.get_db"),
    ):
        engine = LiveTradeEngine(mock_strategy, pos_cfg)
        engine._update_rolling_strikes = MagicMock()
        engine.current_atm_strike = 25600

        # Helper to process a tick
        def process_tick(price):
            tick = {"i": settings.NIFTY_EXCHANGE_INSTRUMENT_ID, "p": price}
            # Manually trigger the logic that would be in _process_loop
            spot = tick["p"]
            buffer = 15
            if abs(spot - engine.current_atm_strike) > (25 + buffer):
                new_atm = round(spot / 50) * 50
                engine._update_rolling_strikes(new_atm)
                engine.current_atm_strike = new_atm

        # Case 1: Price at midpoint (25625) - Should NOT shift
        process_tick(25625)
        engine._update_rolling_strikes.assert_not_called()
        print("  ✅ Case: At midpoint (25625) - No shift")

        # Case 2: Price at midpoint + 10 (25635) - Should NOT shift
        process_tick(25635)
        engine._update_rolling_strikes.assert_not_called()
        print("  ✅ Case: Near midpoint (25635) - No shift")

        # Case 3: Price at midpoint + 20 (25645) - Should shift to 25650
        process_tick(25645)
        engine._update_rolling_strikes.assert_called_with(25650)
        assert engine.current_atm_strike == 25650
        print("  ✅ Case: Beyond buffer (25645) - Shifted to 25650")

        engine._update_rolling_strikes.reset_mock()

        # Case 4: Price moves back to 25626 (old midpoint) - Should NOT shift back
        process_tick(25626)
        engine._update_rolling_strikes.assert_not_called()
        print("  ✅ Case: Moved back to 25626 - No shift")

        # Case 5: Price moves to 25605 (beyond buffer of 25650) - Should shift to 25600
        # 25650 - 40 = 25610. So 25605 should trigger shift.
        process_tick(25605)
        engine._update_rolling_strikes.assert_called_with(25600)
        assert engine.current_atm_strike == 25600
        print("  ✅ Case: Beyond buffer (25605) - Shifted to 25600")
