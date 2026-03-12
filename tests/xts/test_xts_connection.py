"""
Connectivity tests for the XTS API and Socket.IO connection.
Requires valid credentials in config.
"""
import time
import threading
import sys
import os

# Add project root to path
sys.path.append(os.getcwd())

from packages.data.connectors.xts_wrapper import XTSManager
from packages.utils.log_utils import setup_logger

logger = setup_logger("test_xts_connection")

def test_api_login():
    """
    Tests the REST API Login functionality.
    """
    logger.info("--- Testing XTS Market Data API Login ---")
    try:
        # This will trigger the login flow if not already logged in
        client = XTSManager._get_market_client()
        
        if client.token:
            logger.info(f"✅ API Login Successful! Token: {client.token[:10]}...")
            return True
        else:
            logger.error("❌ API Login Failed: No token received.")
        
        assert client.token is not None, "API Login Failed: No token received"
            
    except Exception as e:
        logger.error(f"❌ API Login Exception: {e}")
        raise e

def test_socket_connection():
    """
    Tests the Socket.IO connection.
    Connects, waits for the 'connect' event, and then disconnects.
    """
    logger.info("\n--- Testing XTS Market Data Socket Connection ---")
    
    try:
        soc = XTSManager.get_market_data_socket()
    except Exception as e:
        logger.error(f"❌ Failed to get socket client: {e}")
        return False
    
    # Event to signal connection success
    connected_event = threading.Event()
    
    def on_connect():
        logger.info("✅ Socket Connect Event Received!")
        connected_event.set()
        
    def on_error(data):
        logger.error(f"❌ Socket Error Event: {data}")

    def on_disconnect():
        logger.info("ℹ️ Socket Disconnected.")
        
    # Hook into the callbacks
    soc.on_connect = on_connect
    soc.on_error = on_error
    soc.on_disconnect = on_disconnect
    
    # Connect in a separate thread because soc.connect() blocks with self.sid.wait()
    if soc.sid.connected:
        logger.info("✅ Socket Already Connected!")
        connected_event.set()
    else:
        logger.info("Attempting to connect to Socket...")
        t = threading.Thread(target=soc.connect, kwargs={'transports': ['websocket']})
        t.daemon = True
        t.start()
    
    # Wait for the connection event
    logger.info("Waiting specifically for 'connect' event (max 10s)...")
    try:
        is_connected = connected_event.wait(timeout=10)
        
        if is_connected:
            logger.info("Socket connected successfully. Keeping alive for 2 seconds...")
            time.sleep(2)
            logger.info("Disconnecting...")
            soc.sid.disconnect()
            return True
        else:
            logger.error("❌ Socket connection timed out. Check your internet or API credentials.")
            # Try to clean up even if failed
            soc.sid.disconnect()
            return False
        
        assert is_connected is True, "Socket connection timed out"
    except Exception as e:
        logger.error(f"❌ Socket test error: {e}")
        raise e

if __name__ == "__main__":
    print("Running XTS Connectivity Tests...")
    
    api_success = test_api_login()
    if not api_success:
        print("\n❌ API Login Failed. Aborting Socket Test.")
        sys.exit(1)
        
    socket_success = test_socket_connection()
    
    if api_success and socket_success:
        print("\n✅ All XTS Connectivity Tests Passed!")
        sys.exit(0)
    else:
        print("\n❌ Some tests failed.")
        sys.exit(1)
