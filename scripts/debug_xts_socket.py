import time
import json
import logging
from typing import Set, Dict, List
from packages.data.connectors.xts_wrapper import XTSManager
from packages.services.contract_discovery import ContractDiscoveryService
from packages.utils.log_utils import setup_logger
from packages.utils.date_utils import DateUtils
from datetime import datetime
from packages.utils.mongo import MongoRepository
from packages.config import settings


import argparse

# Configuration
SYMBOL = "NIFTY"
STRIKE_WINDOW = 3
NIFTY_ID = 26000
EVENT_CODE = "1501"  # Touchline
REDUCED_PRINT_COUNT = 500
# Setup logger
logger = setup_logger("XTS_Socket_Debug")
# Set level to INFO to see our own logs, but MDSocket_io will print raw messages if debug=True
logging.getLogger("XTS_Socket_Debug").setLevel(logging.INFO)

class XTSSocketDebugger:
    def __init__(self, print_mode: str = "all"):
        self.discovery_service = ContractDiscoveryService()
        self.current_nifty_price = 0.0
        self.current_atm_strike = 0
        self.subscribed_ids: Set[int] = set()
        self.print_mode = print_mode
        self.event_counter = 0
        
        # Initialize XTS Clients
        self.xts_market = XTSManager._get_market_client()
        self.socket_client = XTSManager.get_market_data_socket(debug=False)
        
        # Setup Callbacks
        self.socket_client.on_connect = self._on_connect
        self.socket_client.on_disconnect = self._on_disconnect
        self.socket_client.on_error = self._on_error
        
        # Attach the 1501-json-full handler
        self.socket_client.on_message1501_json_full = self._on_touchline_message


    def _on_connect(self):
        logger.info("🟢 Socket Connected successfully!")
        
        # 1. Always subscribe to Nifty
        self._subscribe_to_instruments({NIFTY_ID})
        
        # 2. Subscribe to the calculated ATM window (bootstrapped or previous)
        if self.subscribed_ids:
            self._subscribe_to_instruments(self.subscribed_ids)

    def _bootstrap(self):
        """Fetch current Nifty price and resolve ATM window before connecting."""
        try:
            logger.info("🔍 Bootstrapping Nifty price for initial ATM window...")
            response = self.xts_market.get_quote([{"exchangeSegment": 2, "exchangeInstrumentID": NIFTY_ID}], 1501, "JSON")
            
            logger.debug(f"Bootstrap Quote Response: {json.dumps(response)}")
            
            if response.get('type') != 'error' and 'result' in response:
                result = response['result']
                # Result could be a list or a dict depending on the version
                quotes = result.get('listQuotes', []) if isinstance(result, dict) else []
                
                if quotes:
                    quote_data = json.loads(quotes[0]) if isinstance(quotes[0], str) else quotes[0]
                    ltp = quote_data.get('lp', quote_data.get('LastTradedPrice'))
                    if ltp:
                        logger.info(f"✅ Bootstrapped Nifty Price: {ltp}")
                        self.current_nifty_price = float(ltp)
                        self.current_atm_strike = self.discovery_service.get_atm_strike(self.current_nifty_price)
                        self.subscribed_ids = self.discovery_service.get_strike_window_ids(
                            atm_strike=self.current_atm_strike,
                            window_size=STRIKE_WINDOW,
                            symbol=SYMBOL,
                            current_ts=time.time()
                        )
                        logger.info(f"🎯 Initial ATM Window resolved: {self.current_atm_strike} +/- {STRIKE_WINDOW}")
                        logger.info(f"📋 Candidate IDs for window: {list(self.subscribed_ids)}")
                else:
                    logger.warning(f"Bootstrap: No quotes found in result: {result}")
            
            # 3. Fallback to MongoDB if REST failed
            if not self.current_nifty_price:
                logger.info("🗄️ Falling back to MongoDB for latest Nifty price...")
                db = MongoRepository.get_db()
                doc = db[settings.NIFTY_CANDLE_COLLECTION].find_one(
                    {"i": NIFTY_ID},
                    sort=[("t", -1)]
                )
                if doc:
                    ltp = doc.get('p', doc.get('c'))
                    if ltp:
                        logger.info(f"✅ Found DB Fallback Nifty Price: {ltp} (from {DateUtils.market_timestamp_to_iso(doc['t'])})")
                        self.current_nifty_price = float(ltp)
            
            # 4. Finalize Window if we got a price
            if self.current_nifty_price:
                self.current_atm_strike = self.discovery_service.get_atm_strike(self.current_nifty_price)
                self.subscribed_ids = self.discovery_service.get_strike_window_ids(
                    atm_strike=self.current_atm_strike,
                    window_size=STRIKE_WINDOW,
                    symbol=SYMBOL,
                    current_ts=time.time()
                )
                logger.info(f"🎯 Initial ATM Window resolved: {self.current_atm_strike} +/- {STRIKE_WINDOW}")
                logger.info(f"📋 Candidate IDs for window: {list(self.subscribed_ids)}")
            else:
                logger.warning("Could not bootstrap Nifty price from REST or DB. Will wait for live tick.")
                
        except Exception as e:
            logger.error(f"Error during Nifty price bootstrap: {e}", exc_info=True)


    def _on_disconnect(self):
        logger.warning("🔴 Socket Disconnected!")

    def _on_error(self, data):
        logger.error(f"❌ Socket Error: {data}")

    def _on_touchline_message(self, data):
        """Handle raw messages from 1501-json-full event."""
        self.event_counter += 1
        
        should_print = False
        if self.print_mode == "all":
            should_print = True
        elif self.print_mode == "reduced":
            if self.event_counter % REDUCED_PRINT_COUNT == 0:
                should_print = True
        
        if should_print:
            # Print raw message with system time - Use flush=True for real-time visibility
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
            print(f"\n--- [{now}] RAW MESSAGE RECEIVED (Event #{self.event_counter}) ---\n{json.dumps(data, indent=2)}\n--------------------------\n", flush=True)



        
        # Extract data if it's Nifty to check for drift
        try:
            # data can be a string or dict depending on XTS SDK version/config
            if isinstance(data, str):
                msg = json.loads(data)
            else:
                msg = data
                
            inst_id = msg.get('i', msg.get('ExchangeInstrumentID'))
            if inst_id == NIFTY_ID:
                ltp = msg.get('lp', msg.get('LastTradedPrice'))
                if ltp:
                    self._handle_nifty_update(float(ltp))
        except Exception as e:
            logger.debug(f"Error parsing Nifty tick for drift check: {e}")

    def _handle_nifty_update(self, price: float):
        """Update Nifty price and check for ATM drift."""
        self.current_nifty_price = price
        new_atm = self.discovery_service.get_atm_strike(price)
        
        if new_atm != self.current_atm_strike:
            logger.info(f"🔄 Nifty Drift Detected: {self.current_nifty_price} -> New ATM: {new_atm}")
            self.current_atm_strike = new_atm
            self._update_subscriptions()

    def _update_subscriptions(self):
        """Resolve current window and update socket subscriptions."""
        try:
            # Resolve ATM +/- 3 strikes for CE and PE
            new_ids = self.discovery_service.get_strike_window_ids(
                atm_strike=self.current_atm_strike,
                window_size=STRIKE_WINDOW,
                symbol=SYMBOL,
                current_ts=time.time()
            )
            
            # IDs to unsubscribe: currently subscribed but not in new list
            to_unsubscribe = self.subscribed_ids - new_ids
            # IDs to subscribe: in new list but not currently subscribed
            to_subscribe = new_ids - self.subscribed_ids
            
            if to_unsubscribe:
                self._unsubscribe_from_instruments(to_unsubscribe)
            
            if to_subscribe:
                self._subscribe_to_instruments(to_subscribe)
            
            self.subscribed_ids = new_ids
            logger.info(f"✅ Subscription updated. Monitoring {len(self.subscribed_ids)} option instruments.")
            
        except Exception as e:
            logger.error(f"Failed to update subscriptions: {e}", exc_info=True)


    def _subscribe_to_instruments(self, ids: Set[int]):
        """Call XTS REST API to subscribe."""
        if not ids: return
        instruments = [{"exchangeSegment": 2, "exchangeInstrumentID": int(i)} for i in ids]
        logger.info(f"📡 Subscribing to: {[int(i) for i in ids]}")
        response = self.xts_market.send_subscription(instruments, 1501)
        
        # Silence "Already Subscribed" errors as they are harmless
        if response.get('type') == 'error':
            code = response.get('code', '')
            if code == 'e-session-0002' or "Already Subscribed" in response.get('description', ''):
                logger.debug(f"Instrument already subscribed: {ids}")
            else:
                logger.error(f"Subscription failed: {response}")


    def _unsubscribe_from_instruments(self, ids: Set[int]):
        """Call XTS REST API to unsubscribe."""
        if not ids: return
        instruments = [{"exchangeSegment": 2, "exchangeInstrumentID": int(i)} for i in ids]
        logger.info(f"🚫 Unsubscribing from: {[int(i) for i in ids]}")
        response = self.xts_market.send_unsubscription(instruments, 1501)
        if response.get('type') == 'error':
            logger.error(f"Unsubscription failed: {response}")

    def run(self):
        """Start the debugger."""
        logger.info("🚀 Starting XTS Socket Debugger...")
        logger.info(f"Watching {SYMBOL} for ATM +/- {STRIKE_WINDOW} drift...")
        logger.info("Waiting for data... (If market is closed, nothing will print)")
        
        try:
            # 1. Bootstrap the initial window
            self._bootstrap()
            
            # 2. Connect the socket (this is blocking)
            self.socket_client.connect()


            
        except KeyboardInterrupt:
            logger.info("Shutting down...")
        except Exception as e:
            logger.error(f"Debugger error: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="XTS Socket Debugger with Dynamic ATM Subscription")
    parser.add_argument(
        "--print-mode", 
        choices=["all", "none", "reduced"], 
        default="all",
        help="Control raw message printing: all (default), none, or reduced (every 100 events)"
    )
    args = parser.parse_args()
    
    debugger = XTSSocketDebugger(print_mode=args.print_mode)
    debugger.run()

