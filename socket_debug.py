import time
import threading
import queue
from datetime import datetime
from packages.config import settings
from packages.data.connectors.xts_wrapper import XTSManager
from packages.utils.mongo import MongoRepository

# Simple logger for this script
import logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger("SocketDebug")

# Explicitly silence the background socket libraries
logging.getLogger('socketio').setLevel(logging.WARNING)
logging.getLogger('engineio').setLevel(logging.WARNING)
logging.getLogger('urllib3').setLevel(logging.WARNING)

class SocketTester:
    def __init__(self):
        self.db = MongoRepository.get_db()
        self.market_client = XTSManager.get_market_client()
        # Disable debug logging to prevent terminal-log-blocking
        self.soc = XTSManager.get_market_data_socket(debug=False)
        
        # Add a queue to decouple socket thread from logging
        self.tick_queue = queue.Queue()
        
        # Register callbacks
        self.soc.on_connect = self._on_connect
        self.soc.on_disconnect = self._on_disconnect
        self.soc.on_error = self._on_error
        self.soc.on_message1501_json_full = self._on_tick
        self.soc.on_message1501_json_partial = self._on_tick
        self.soc.on_message1512_json_full = self._on_tick
        self.soc.on_message1512_json_partial = self._on_tick
        self.soc.on_message1105_json_full = self._on_tick
        self.soc.on_message1105_json_partial = self._on_tick
        
        self.subscribed_instruments = set()
        
        # Start worker thread
        threading.Thread(target=self._process_loop, daemon=True).start()
        
    def _on_connect(self):
        logger.info("✅ Socket Connected!")
        self._subscribe_all()

    def _on_disconnect(self):
        logger.warning("⚠️ Socket Disconnected!")

    def _on_error(self, data):
        logger.error(f"❌ Socket Error: {data}")

    def _on_tick(self, data):
        # Return IMMEDIATELY, push to queue
        self.tick_queue.put(data)

    def _process_loop(self):
        """Worker thread to handle logging without blocking the socket."""
        from packages.utils.market_utils import MarketUtils
        while True:
            try:
                raw_data = self.tick_queue.get()
                data = MarketUtils.normalize_raw_socket_data(raw_data)
                
                if not data:
                    self.tick_queue.task_done()
                    continue

                i = data.get('ExchangeInstrumentID', data.get('i', '?'))
                ltp = data.get('Touchline', {}).get('LastTradedPrice', data.get('ltp', '?'))
                v = data.get('Touchline', {}).get('TotalTradedQuantity', data.get('v', '?'))
                logger.info(f"Tick consumed (Queue Size: {self.tick_queue.qsize()}) | ID: {i} | LTP: {ltp} | Vol: {v}")
                self.tick_queue.task_done()
            except Exception as e:
                logger.error(f"Error in process loop: {e}")

    def _resolve_instruments(self):
        logger.info("🔍 Resolving instruments for subscription...")
        # Resolve Nifty Strike Chain (same logic as live_trader)
        last_candle = self.db[settings.NIFTY_CANDLE_COLLECTION].find_one(
            {"i": settings.NIFTY_EXCHANGE_INSTRUMENT_ID},
            sort=[("t", -1)]
        )
        if not last_candle:
            logger.error("No NIFTY data in DB. Using fallback NIFTY ID.")
            return [settings.NIFTY_EXCHANGE_INSTRUMENT_ID]
            
        spot_price = last_candle.get('c', last_candle.get('close', last_candle.get('p', 25000)))
        atm_strike = round(spot_price / 50) * 50
        target_strikes = [atm_strike + (i * 50) for i in range(-10, 11)]
        
        now_iso = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        opt_ref = self.db['instrument_master'].find_one({
            "name": "NIFTY", 
            "series": "OPTIDX",
            "contractExpiration": {"$gte": now_iso}
        }, sort=[("contractExpiration", 1)])
        
        if not opt_ref:
            logger.error("No active NIFTY options found.")
            return [settings.NIFTY_EXCHANGE_INSTRUMENT_ID]
            
        expiry = opt_ref["contractExpiration"]
        contracts = list(self.db['instrument_master'].find({
            "name": "NIFTY",
            "series": "OPTIDX",
            "contractExpiration": expiry,
            "strikePrice": {"$in": target_strikes}
        }))
        
        inst_ids = [settings.NIFTY_EXCHANGE_INSTRUMENT_ID]
        for c in contracts:
            inst_ids.append(int(c['exchangeInstrumentID']))
            
        logger.info(f"Resolved {len(inst_ids)} instruments for expiry {expiry}")
        return inst_ids

    def _subscribe_all(self):
        inst_ids = self._resolve_instruments()
        # Segment 1 for NIFTY, Segment 2 for Options
        nifty_ids = [i for i in inst_ids if i == settings.NIFTY_EXCHANGE_INSTRUMENT_ID]
        option_ids = [i for i in inst_ids if i != settings.NIFTY_EXCHANGE_INSTRUMENT_ID]
        
        if nifty_ids:
            self.market_client.send_subscription([{'exchangeSegment': 1, 'exchangeInstrumentID': i} for i in nifty_ids], 1501)
        if option_ids:
            self.market_client.send_subscription([{'exchangeSegment': 2, 'exchangeInstrumentID': i} for i in option_ids], 1501)
        logger.info("Subscription requests sent.")

    def run(self):
        logger.info("Starting Socket Debugger...")
        # Run connect in its own thread to avoid blocking wait()
        threading.Thread(target=self.soc.connect, daemon=True).start()
        
        # Keep process alive
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("Stopping...")

if __name__ == "__main__":
    tester = SocketTester()
    tester.run()
