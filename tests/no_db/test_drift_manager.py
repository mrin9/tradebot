from unittest.mock import MagicMock

import pytest

from packages.services.contract_discovery import ContractDiscoveryService
from packages.tradeflow.drift_manager import DriftManager


@pytest.fixture
def mock_discovery():
    discovery = MagicMock(spec=ContractDiscoveryService)
    discovery.get_atm_strike.side_effect = lambda p: round(p / 50) * 50
    discovery.resolve_option_contract.side_effect = lambda s, ce, ts: (
        (s + (1 if ce else 0)),
        f"NIFTY {'CE' if ce else 'PE'} {s}",
    )
    return discovery


def test_drift_manager_initial_selection(mock_discovery):
    dm = DriftManager(mock_discovery)

    # First check triggers initial selection
    dm.check_drift(25000, 1710240000)  # Some timestamp

    assert dm.active_instruments["CE"] == 25001  # 25000 + 1 (mock logic)
    assert dm.active_instruments["PE"] == 25000  # 25000 + 0 (mock logic)
    assert dm.selection_spot_price == 25000


def test_drift_manager_threshold_trigger(mock_discovery):
    dm = DriftManager(mock_discovery, drift_threshold=25)
    dm.check_drift(25000, 1710240000)

    # Move price by 20 (below threshold)
    updated = dm.check_drift(25020, 1710240100)
    assert not updated
    assert dm.selection_spot_price == 25000

    # Move price by 30 (above threshold)
    # 25030 rounding to nearest 50 is still 25000, so ids might not change based on mock logic
    # but the selection_spot_price should update.
    updated = dm.check_drift(25030, 1710240200)
    assert updated
    assert dm.selection_spot_price == 25030


def test_drift_manager_day_change_trigger(mock_discovery):
    dm = DriftManager(mock_discovery)
    dm.check_drift(25000, 1710240000)  # Day 1

    # Small price change but different day
    # 1710240000 is 2024-03-12 10:40:00 UTC
    # 1710326400 is 2024-03-13 10:40:00 UTC (+1 day)
    updated = dm.check_drift(25005, 1710326400)
    assert updated
    assert dm.last_day_str == "2024-03-13"


def test_drift_manager_callback(mock_discovery):
    dm = DriftManager(mock_discovery)
    callback = MagicMock()
    dm.on_instruments_changed = callback

    # Initial
    dm.check_drift(25000, 1710240000)
    assert callback.call_count == 1

    # Move to new strike (25100)
    dm.check_drift(25100, 1710240100)
    assert callback.call_count == 2

    changed_info = callback.call_args[0][0]
    instruments = changed_info["instruments"]
    assert instruments["CE"]["is_new"] is True
    assert instruments["CE"]["id"] == 25101
