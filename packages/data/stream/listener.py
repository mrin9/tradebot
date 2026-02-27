from datetime import datetime
import threading
import time
from typing import Callable, List, Dict

from packages.config import settings
from packages.data.connectors.xts_wrapper import XTSManager
from packages.utils.market_utils import MarketUtils
from packages.utils.log_utils import setup_logger
from packages.utils.mongo import MongoRepository

logger = setup_logger(__name__)

class MarketDataListener:
    """
    Manages Real-time Market Data Stream.
    Connects to XTS Socket, subscribes to active contracts, and streams ticks.
    """
    def __init__(self, on_tick_callback: Callable[[Dict], None] | None = None):
        self.soc = XTSManager.get_market_data_socket()
        self.xts = XTSManager.get_market_client()
        self.on_tick = on_tick_callback
        self.is_connected = False
        self.lock = threading.Lock()
        self._setup_callbacks()

    def _setup_callbacks(self):
        # Socket Connection Callbacks
        self.soc.on_connect = self._on_connect
        self.soc.on_disconnect = self._on_disconnect
        self.soc.on_error = self._on_error

        # Data Event Callbacks (Touchline & Index)
        # 1501: Level 1 (Touchline) - Most common for LTP/Bid/Ask
        self.soc.on_message1501_json_full = lambda data: self._on_market_data("1501-json-full", data)
        self.soc.on_message1501_json_partial = lambda data: self._on_market_data("1501-json-partial", data)
        
        # 1505: Candle data
        self.soc.on_message1505_json_full = lambda data: self._on_market_data("1505-json-full", data)

        # 1105: Index Data
        self.soc.on_message1105_json_full = lambda data: self._on_market_data("1105-json-full", data)
        self.soc.on_message1105_json_partial = lambda data: self._on_market_data("1105-json-partial", data)

    def _on_connect(self):
        logger.info("Market Data Socket Connected.")
        self.is_connected = True

    def _on_disconnect(self):
        logger.warning("Market Data Socket Disconnected.")
        self.is_connected = False

    def _on_error(self, data):
        logger.error(f"Socket Error: {data}")

    def _on_market_data(self, event_type, data):
        """
        Unified handler for market data events.
        Uses MarketUtils for normalization.
        """
        if not data:
            return

        try:
            tick = MarketUtils.normalize_xts_event(event_type, data)
            
            # Index (1105) might have different structure (not yet in MarketUtils if strictly 1105)
            # For now, MarketUtils handles 1501 and 1505
            if not tick and "IndexValue" in data:
                 # Minimal fallback for 1105 if not normalized
                 tick = {
                     "i": data.get("ExchangeInstrumentID"),
                     "p": data.get("IndexValue"),
                     "t": data.get("LastTradedTime")
                 }
                 
            # Ensure we have minimal data
            if tick and tick.get("i") and tick.get("p") is not None:
                if self.on_tick:
                    self.on_tick(tick)
                else:
                    logger.debug(f"Tick: {tick}")
                    
        except Exception as e:
            logger.error(f"Error parse tick: {e} | Data: {data}")

    def start(self, instruments: List[Dict] = None, background=True):
        """
        Starts the socket connection and subscribes to instruments.
        """
        # 1. Connect
        threading.Thread(target=self.soc.connect, daemon=True).start()
        
        # Wait for connection
        logger.info("Waiting for socket connection...")
        retry = 0
        while not self.soc.sid.connected and retry < 10:
            time.sleep(1)
            retry += 1
            
        if not self.soc.sid.connected:
            logger.error("Failed to connect to XTS Socket.")
            return

        # 2. Subscribe
        if instruments:
            self.subscribe(instruments)
            
        if not background:
            # Block main thread
            while True:
                time.sleep(1)

    def subscribe(self, instruments: List[Dict]):
        """
        Subscribes to a list of instruments.
        Format: [{'exchangeSegment': 1, 'exchangeInstrumentID': 123}, ...]
        """
        if not instruments:
            return

        logger.info(f"Subscribing to {len(instruments)} instruments...")
        
        # Events to subscribe
        events = [1501] # Touchline
        
        # Check if any indices in list? (NIFTY is Segment 1)
        # NIFTY might need 1105? XTS doc is vague, let's try 1501 first as typical.
        # User mentioned 1105 for Index. Let's add it if 1501 fails? Both?
        # Let's adding 1501 first.
        
        for event in events:
            resp = self.xts.send_subscription(instruments, event)
            logger.info(f"Subscription {event}: {resp}")

    def get_active_instruments(self) -> List[Dict]:
        """
        Fetches 'today' active contracts + NIFTY Index for subscription.
        """
        db = MongoRepository.get_db()
        coll = db[settings.ACTIVE_CONTRACT_COLLECTION]
        
        # Get active contracts for today (or latest available)
        # Or just get all distinct IDs that are active 'today'
        # DateUtils.to_iso_date(datetime.now())
        today = datetime.now().strftime("%Y-%m-%d")
        
        cursor = coll.find({"activeDates": today})
        instruments = []
        
        # 1. Add NIFTY
        instruments.append({
            "exchangeSegment": settings.NIFTY_EXCHANGE_SEGMENT,
            "exchangeInstrumentID": settings.NIFTY_EXCHANGE_INSTRUMENT_ID
        })
        
        # 2. Add Active Contracts
        count = 0
        for doc in cursor:
            instruments.append({
                "exchangeSegment": doc["exchangeSegment"],
                "exchangeInstrumentID": doc["exchangeInstrumentID"]
            })
            count += 1
            
        logger.info(f"Found {count} active contracts for {today} + NIFTY.")
        return instruments

if __name__ == "__main__":
    # Test Run
    def print_tick(t):
        print(f"TICK: {t['i']} -> {t['p']}")

    listener = MarketDataListener(on_tick_callback=print_tick)
    
    # Fetch instruments
    instrs = listener.get_active_instruments()
    
    # Start
    listener.start(instrs, background=False)
