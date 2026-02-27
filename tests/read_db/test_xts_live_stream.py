"""
Tests for MarketDataListener, verifying socket connection and data subscription.
"""
import sys
import os
import time
import logging

# Add project root
sys.path.append(os.getcwd())

from packages.data.stream.listener import MarketDataListener
from packages.utils.log_utils import setup_logger

logger = setup_logger("TestStream")

def test_listener():
    logger.info("Starting Stream Listener Test...")
    
    ticks_received = 0
    
    def on_tick(tick):
        nonlocal ticks_received
        ticks_received += 1
        if ticks_received % 10 == 0:
            logger.info(f"Received {ticks_received} ticks. Last: {tick['i']} -> {tick['p']}")

    listener = MarketDataListener(on_tick_callback=on_tick)
    
    # Get instruments (Requires active contracts in DB)
    instrs = listener.get_active_instruments()
    
    # If no instruments, manually add Nifty
    if not instrs:
        logger.warning("No active instruments found in DB! Adding NIFTY manual.")
        instrs = [{'exchangeSegment': 1, 'exchangeInstrumentID': 26000}]
        
    logger.info(f"Subscribing to {len(instrs)} instruments...")
    
    # Start in background
    listener.start(instrs, background=True)
    
    logger.info("Listening for 15 seconds...")
    time.sleep(15)
    
    logger.info(f"Test Complete. Total Ticks: {ticks_received}")
    
    assert ticks_received > 0, "No ticks received (Market might be closed or connection issue)."
    logger.info("SUCCESS: Stream received data.")

if __name__ == "__main__":
    test_listener()
