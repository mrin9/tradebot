import pytest
import os
from packages.data.connectors.xts_wrapper import XTSManager
from packages.config import settings

@pytest.mark.live
def test_live_market_login():
    """Verify that we can login to XTS Market Data API."""
    client = XTSManager._get_market_client()
    assert client is not None
    assert client.token is not None

@pytest.mark.live
def test_live_interactive_login():
    """Verify that we can login to XTS Interactive API."""
    client = XTSManager._get_interactive_client()
    assert client is not None
    assert client.token is not None

@pytest.mark.live
def test_live_get_quote_structure():
    """Verify that get_quote returns expected keys (listQuotes)."""
    nifty_id = settings.NIFTY_EXCHANGE_INSTRUMENT_ID
    
    response = XTSManager.call_api(
        "market",
        "get_quote",
        instruments=[{'exchangeSegment': 1, 'exchangeInstrumentID': nifty_id}],
        xts_message_code=1501,
        publish_format="1"
    )
    
    assert response['type'] == 'success'
    assert 'listQuotes' in response['result']
    assert len(response['result']['listQuotes']) > 0

@pytest.mark.live
def test_live_get_ohlc_structure():
    """Verify that get_ohlc returns expected keys (dataReponse)."""
    nifty_id = settings.NIFTY_EXCHANGE_INSTRUMENT_ID
    
    # Use XTSManager.call_api for auto-recovery if session overlaps
    response = XTSManager.call_api(
        "market",
        "get_ohlc",
        exchange_segment=1,
        exchange_instrument_id=nifty_id,
        start_time='Feb 27 2026 100000', # Known trading day
        end_time='Feb 27 2026 110000',
        compression_value=60
    )
    
    assert response['type'] == 'success'
    # Check for either key (our code handles fallback)
    result = response['result']
    assert 'dataReponse' in result or 'data' in result

@pytest.mark.live
def test_live_get_master_structure():
    """Verify that get_master returns pipe-separated data."""
    response = XTSManager.call_api("market", "get_master", exchange_segment_list=['NSECM'])
    
    assert response['type'] == 'success'
    result = response.get('result')
    
    # Handle both formats: {'result': {'data': '...'}} and {'result': '...'}
    if isinstance(result, dict):
        assert 'data' in result
        data = result['data']
    else:
        data = result
        
    assert isinstance(data, str)
    assert 'NSECM|' in data or '|' in data
