import argparse
import time
import threading
import sys
import os
from datetime import datetime
import json

# Add project root to path
sys.path.append(os.getcwd())

from packages.config import settings
from packages.data.connectors.xts_wrapper import XTSManager
from packages.utils.market_utils import MarketUtils
from packages.utils.log_utils import setup_logger
from packages.utils.mongo import MongoRepository

logger = setup_logger("XTS_Socket_Test")

class XTSSocketTester:
    def __init__(self, store_in_db=False, events_mode="1501-partial"):
        self.store_in_db = store_in_db
        self.events_mode = events_mode
        self.db = None
        self.collection_name = "xts_socket_data_collection_test"
        
        if self.store_in_db:
            self.db = MongoRepository.get_db()
            logger.info("MongoDB Connection initialized for storage.")
        
        # Set broadcast mode based on requested events
        if "partial" in events_mode.lower():
            settings.XTS_BROADCAST_MODE = "Partial"
        else:
            settings.XTS_BROADCAST_MODE = "Full"
            
        logger.info(f"Setting XTS Broadcast Mode: {settings.XTS_BROADCAST_MODE}")
        
        # Reset socket client to pick up new settings if it was already initialized
        XTSManager._socket_client = None
        
        self.xt_market = XTSManager.get_market_client()
        self.soc = XTSManager.get_market_data_socket(debug=False)
        
        self.subscribed_instruments = set()
        self.is_running = threading.Event()
        
    def _on_connect(self):
        logger.info("✅ Connected to XTS Socket!")
        self._subscribe_all()

    def _on_error(self, data):
        logger.error(f"❌ Socket Error: {data}")

    def _on_disconnect(self):
        logger.warning("⚠️ Socket Disconnected!")

    def _on_message(self, data):
        """Catch-all for any message from the socket."""
        logger.info(f"📥 General Message Received: {data}")

    def _handle_market_event(self, event_code, data):
        """Generic handler for all market events."""
        # Check if we should ignore this event based on user args
        if self.events_mode != "all" and self.events_mode not in str(event_code):
            return

        logger.info(f"🎯 Market Event: {event_code} | Data: {data}")
        
        parsed_data = MarketUtils.normalize_xts_event(str(event_code), data)
        logger.info(f"✅ Parsed Data: {parsed_data}")
        
        if self.store_in_db:
            doc = {
                "xtsEvent": event_code,
                "rawData": data,
                "parsedData": parsed_data,
                "timestamp": datetime.now()
            }
            try:
                self.db[self.collection_name].insert_one(doc)
            except Exception as e:
                logger.error(f"Failed to store in DB: {e}")

    def _subscribe_all(self):
        """Subscribes to NIFTY Index only."""
        logger.info("🔭 Subscribing to NIFTY Index (26000)...")
        
        nifty_id = settings.NIFTY_EXCHANGE_INSTRUMENT_ID
        self.subscribed_instruments.add(nifty_id)
        
        # Send Subscriptions for common event codes
        logger.info(f"Sending subscriptions for NIFTY (26000)...")
        # 1501: Touchline/LTP
        self.xt_market.send_subscription([{'exchangeSegment': 1, 'exchangeInstrumentID': nifty_id}], 1501)
        # 1502: Market Data
        self.xt_market.send_subscription([{'exchangeSegment': 1, 'exchangeInstrumentID': nifty_id}], 1502)
        # 1505: Candle Data
        self.xt_market.send_subscription([{'exchangeSegment': 1, 'exchangeInstrumentID': nifty_id}], 1505)
        # 1512: LTP
        self.xt_market.send_subscription([{'exchangeSegment': 1, 'exchangeInstrumentID': nifty_id}], 1512)

    def run(self):
        # Setup callbacks
        self.soc.on_connect = self._on_connect
        self.soc.on_error = self._on_error
        self.soc.on_disconnect = self._on_disconnect
        # Commented out to avoid duplicate logs for everything
        # self.soc.on_message = self._on_message
        
        # Register handlers for ALL possible event formats to ensure we don't miss anything
        # We exclude 1105 as it is just instrument property change noise
        codes = ["1501", "1502", "1504", "1505", "1507", "1510", "1512"]
        for code in codes:
            # We map both full and partial to our handler
            setattr(self.soc, f"on_message{code}_json_full", lambda d, c=code: self._handle_market_event(f"{c}-full", d))
            setattr(self.soc, f"on_message{code}_json_partial", lambda d, c=code: self._handle_market_event(f"{c}-partial", d))

        # Connect
        logger.info("Connecting to XTS Socket...")
        threading.Thread(target=self.soc.connect, daemon=True).start()
        
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("Stopping...")
        finally:
            self.soc.sid.disconnect()

def main():
    parser = argparse.ArgumentParser(description="XTS Socket Integration Test")
    parser.add_argument("--store-in-db", action="store_true", help="Store data in MongoDB")
    parser.add_argument("--events", type=str, choices=["all", "1501-full", "1501-partial", "1505-full", "1505-partial", "1512-full", "1512-partial"], 
                        default="1501-partial", help="Filter for specific events")
    
    args = parser.parse_args()
    
    tester = XTSSocketTester(store_in_db=args.store_in_db, events_mode=args.events)
    tester.run()

if __name__ == "__main__":
    main()
