import pytest
from packages.data.connectors.xts_wrapper import XTSManager

def test_xts_manager_singleton_market():
    """Verifies that XTSManager maintains a singleton for the Market Data client."""
    # Force reset
    XTSManager._market_client = "mock_client"
    client1 = XTSManager.get_market_client()
    client2 = XTSManager.get_market_client()
    
    assert client1 == client2
    assert client1 == "mock_client"
    
    # Cleanup for other tests
    XTSManager._market_client = None

def test_xts_manager_singleton_interactive():
    """Verifies that XTSManager maintains a singleton for the Interactive client."""
    # Force reset
    XTSManager._interactive_client = "mock_client_i"
    client1 = XTSManager.get_interactive_client()
    client2 = XTSManager.get_interactive_client()
    
    assert client1 == client2
    assert client1 == "mock_client_i"
    
    # Cleanup for other tests
    XTSManager._interactive_client = None
