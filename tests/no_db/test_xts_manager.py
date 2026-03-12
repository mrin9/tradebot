"""
Unified Domain Tests for XTSManager.
Covers singleton client management, rate-limit retries, and session recovery logic.
"""
import pytest
from unittest.mock import MagicMock, patch
from packages.data.connectors.xts_wrapper import XTSManager

@pytest.fixture(autouse=True)
def reset_xts_manager():
    """Ensure a clean state for XTSManager singletons across tests."""
    XTSManager._market_client = None
    XTSManager._interactive_client = None
    XTSManager._socket_client = None
    yield
    XTSManager._market_client = None
    XTSManager._interactive_client = None
    XTSManager._socket_client = None

# --- Sub-Domain: Singleton Management ---

def test_xts_manager_singleton_market():
    """Verifies that XTSManager maintains a singleton for the Market Data client."""
    XTSManager._market_client = "mock_client"
    client1 = XTSManager._get_market_client()
    client2 = XTSManager._get_market_client()
    assert client1 == client2
    assert client1 == "mock_client"

def test_xts_manager_singleton_interactive():
    """Verifies that XTSManager maintains a singleton for the Interactive client."""
    XTSManager._interactive_client = "mock_client_i"
    client1 = XTSManager._get_interactive_client()
    client2 = XTSManager._get_interactive_client()
    assert client1 == client2
    assert client1 == "mock_client_i"

# --- Sub-Domain: API Resilience (Retries & Recovery) ---

def test_call_api_rate_limit_retry():
    """Verifies that call_api waits and retries when hitting rate limits."""
    mock_func = MagicMock()
    mock_func.side_effect = [
        {"type": "error", "code": "e-apirl-0004", "description": "Rate Limit reached"},
        {"type": "success", "result": "done"}
    ]
    
    with patch.object(XTSManager, "_get_market_client") as m_get, \
         patch("time.sleep") as m_sleep:
        mock_client = MagicMock()
        setattr(mock_client, "some_method", mock_func)
        m_get.return_value = mock_client
        
        resp = XTSManager.call_api("market", "some_method", max_retries=3)
        assert resp == {"type": "success", "result": "done"}
        assert mock_func.call_count == 2
        assert m_sleep.call_count == 1
        m_sleep.assert_called_with(1)

def test_call_api_session_expired_recovery():
    """Verifies that call_api re-logs when the session is invalid."""
    mock_func = MagicMock()
    mock_func.side_effect = [
        {"type": "error", "description": "Invalid Token"},
        {"type": "success", "result": "recovered"}
    ]
    
    with patch.object(XTSManager, "_get_market_client") as m_get:
        mock_client = MagicMock()
        setattr(mock_client, "some_method", mock_func)
        m_get.side_effect = [mock_client, mock_client] 
        
        resp = XTSManager.call_api("market", "some_method")
        assert resp == {"type": "success", "result": "recovered"}
        assert m_get.call_count >= 2
        m_get.assert_called_with(force_login=True)

def test_call_api_max_retries():
    """Verifies that call_api stops after max_retries."""
    mock_func = MagicMock()
    mock_func.return_value = {"type": "error", "code": "e-apirl-0004"}
    
    with patch.object(XTSManager, "_get_market_client") as m_get, \
         patch("time.sleep") as m_sleep:
        m_get.return_value = MagicMock()
        setattr(m_get.return_value, "fail_method", mock_func)
        resp = XTSManager.call_api("market", "fail_method", max_retries=2)
        assert mock_func.call_count == 2
        assert resp["code"] == "e-apirl-0004"
