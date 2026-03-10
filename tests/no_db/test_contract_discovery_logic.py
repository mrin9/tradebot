from datetime import datetime
from unittest.mock import MagicMock, patch
from packages.services.contract_discovery import ContractDiscoveryService

def test_derive_target_contracts_logic():
    """Verifies that derive_target_contracts calculates strikes and fetches correctly."""
    mock_db = MagicMock()
    mock_master_col = MagicMock()
    
    # Map collections
    mock_db.__getitem__.side_effect = lambda key: {
        "instrument_master": mock_master_col
    }.get(key, MagicMock())

    # Mock instrument_master find_one for expiry
    mock_master_col.find_one.return_value = {"contractExpiration": "2026-03-12T00:00:00"}
    
    # Mock instrument_master find for contracts
    mock_master_col.find.return_value = [
        {"exchangeInstrumentID": 1001, "strikePrice": 22450, "optionType": 3},
        {"exchangeInstrumentID": 1002, "strikePrice": 22450, "optionType": 4}
    ]
    
    service = ContractDiscoveryService(db=mock_db)
    dt = datetime(2026, 3, 10)
    
    with patch("packages.services.contract_discovery.MarketHistoryService") as mock_history_cls:
        mock_history = mock_history_cls.return_value
        mock_history.get_last_nifty_price.return_value = 22426  # ATM should be 22450
        
        contracts = service.derive_target_contracts(dt, strike_count=0) # Only ATM
    
    assert len(contracts) == 2
    # Verify strike calculation (22426 rounded to 50 step is 22450)
    args, kwargs = mock_master_col.find.call_args
    # find() is called with a filter dict as first positional arg
    assert 22450 in args[0]['strikePrice']['$in']

def test_derive_target_contracts_no_spot():
    """Verifies that it returns empty list if no spot price is found."""
    mock_db = MagicMock()
    
    service = ContractDiscoveryService(db=mock_db)
    
    with patch("packages.services.contract_discovery.MarketHistoryService") as mock_history_cls:
        mock_history = mock_history_cls.return_value
        mock_history.get_last_nifty_price.return_value = None
        
        contracts = service.derive_target_contracts(datetime.now())
    
    assert contracts == []

def test_get_atm_strike_rounding():
    """Tests the static rounding helper."""
    assert ContractDiscoveryService.get_atm_strike(22424) == 22400
    assert ContractDiscoveryService.get_atm_strike(22426) == 22450
    assert ContractDiscoveryService.get_atm_strike(22474) == 22450
    assert ContractDiscoveryService.get_atm_strike(22476) == 22500
