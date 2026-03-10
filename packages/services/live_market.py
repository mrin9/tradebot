import time
import threading
import queue
from typing import Dict, List, Set, Optional, Callable
from packages.config import settings
from packages.data.connectors.xts_wrapper import XTSManager
from packages.data.connectors.xts_normalizer import XTSNormalizer
from packages.utils.log_utils import setup_logger
from packages.utils.trade_formatter import TradeFormatter

logger = setup_logger("LiveMarketService")

class LiveMarketService:
    """
    Consolidates market data streaming, socket management, and instrument subscriptions.
    """
    def __init__(self, debug: bool = False):
        self.debug = debug
        self.soc = XTSManager.get_market_data_socket(debug=debug)
        
        self.tick_queue = queue.Queue()
        self.on_tick_callback: Optional[Callable[[Dict], None]] = None
        
        self.subscribed_instruments: Set[int] = set()
        self.is_running = False
        self.last_tick_time = time.time()
        
        # Socket callbacks
        self.soc.on_connect = self._on_connect
        self.soc.on_message1501_json_full = self._on_tick_raw
        self.soc.on_disconnect = self._on_disconnect
        self.soc.on_error = self._on_error
        
        self._processor_thread: Optional[threading.Thread] = None

    def start(self, on_tick: Callable[[Dict], None]):
        """
        Connects to XTS and starts the tick processing loop.
        """
        self.on_tick_callback = on_tick
        self.is_running = True
        
        logger.info(TradeFormatter.format_connection("connecting", "Connecting to Market Data Socket..."))
        threading.Thread(target=self.soc.connect, daemon=True).start()
        
        self._processor_thread = threading.Thread(target=self._tick_processor_loop, daemon=True)
        self._processor_thread.start()

    def stop(self):
        """
        Stops the service and disconnects the socket.
        """
        self.is_running = False
        # No explicit disconnect for simplicity, as it runs in daemon threads
        logger.info("🏁 Live Market Service Stopped.")

    def subscribe(self, instrument_ids: List[int]):
        """Subscribes to a list of instruments."""
        if not instrument_ids: return
        new_ids = [i for i in instrument_ids if i not in self.subscribed_instruments]
        if not new_ids: return
        
        if self._send_subscription_batch(new_ids, subscribe=True):
            self.subscribed_instruments.update(new_ids)
            logger.info(f"➕ Subscribed to {len(new_ids)} instruments.")

    def unsubscribe(self, instrument_ids: List[int]):
        """Unsubscribes from a list of instruments."""
        if not instrument_ids: return
        ids_to_unsub = [i for i in instrument_ids if i in self.subscribed_instruments]
        if not ids_to_unsub: return
        
        if self._send_subscription_batch(ids_to_unsub, subscribe=False):
            self.subscribed_instruments.difference_update(ids_to_unsub)
            logger.info(f"➖ Unsubscribed from {len(ids_to_unsub)} instruments.")

    def _send_subscription_batch(self, instrument_ids: List[int], subscribe: bool = True) -> bool:
        """Helper to group instruments by segment and send (un)subscription command."""
        try:
            nse_eq = [i for i in instrument_ids if i == settings.NIFTY_EXCHANGE_INSTRUMENT_ID]
            nse_fo = [i for i in instrument_ids if i != settings.NIFTY_EXCHANGE_INSTRUMENT_ID]
            
            func_name = "send_subscription" if subscribe else "send_unsubscription"
            
            if nse_eq:
                XTSManager.call_api(
                    "market", 
                    func_name,
                    instruments=[{'exchangeSegment': 1, 'exchangeInstrumentID': i} for i in nse_eq], 
                    xts_message_code=1501
                )
            if nse_fo:
                XTSManager.call_api(
                    "market", 
                    func_name,
                    instruments=[{'exchangeSegment': 2, 'exchangeInstrumentID': i} for i in nse_fo], 
                    xts_message_code=1501
                )
            return True
        except Exception as e:
            action = "Subscription" if subscribe else "Unsubscription"
            logger.error(f"❌ {action} failed: {e}")
            return False

    def ensure_connection(self):
        """
        Monitors health and forces reconnection if needed.
        """
        if not self.soc.sid.connected:
            logger.warning("🔌 Socket disconnected. Attempting RE-CONNECT...")
            threading.Thread(target=self.soc.connect, daemon=True).start()
        else:
            # Send keep-alive (re-subscribe to Nifty)
            try:
                XTSManager.call_api(
                    "market", 
                    "send_subscription",
                    instruments=[{'exchangeSegment': 1, 'exchangeInstrumentID': settings.NIFTY_EXCHANGE_INSTRUMENT_ID}], 
                    xts_message_code=1501
                )
            except Exception as e:
                logger.error(f"❌ Keep-alive failed: {e}")

    def _on_tick_raw(self, data):
        self.tick_queue.put(data)

    def _tick_processor_loop(self):
        while self.is_running:
            data = None
            try:
                data = self.tick_queue.get(timeout=1)
                tick = XTSNormalizer.normalize_xts_event("1501-json-full", data)
                if tick:
                    self.last_tick_time = time.time()
                    if self.on_tick_callback:
                        self.on_tick_callback(tick)
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"💥 Error in Live Market Processor: {e}", exc_info=True)
            finally:
                if data is not None:
                    self.tick_queue.task_done()

    def _on_connect(self):
        logger.info(TradeFormatter.format_connection("connected", "XTS Socket Connected!"))
        if self.subscribed_instruments:
            logger.info(f"🔄 Re-subscribing to {len(self.subscribed_instruments)} instruments...")
            # Re-subscribe all on reconnect
            nse_eq = [i for i in self.subscribed_instruments if i == settings.NIFTY_EXCHANGE_INSTRUMENT_ID]
            nse_fo = [i for i in self.subscribed_instruments if i != settings.NIFTY_EXCHANGE_INSTRUMENT_ID]
            
            if nse_eq:
                XTSManager.call_api("market", "send_subscription", instruments=[{'exchangeSegment': 1, 'exchangeInstrumentID': i} for i in nse_eq], xts_message_code=1501)
            if nse_fo:
                XTSManager.call_api("market", "send_subscription", instruments=[{'exchangeSegment': 2, 'exchangeInstrumentID': i} for i in nse_fo], xts_message_code=1501)

    def _on_disconnect(self):
        logger.warning(TradeFormatter.format_connection("disconnected", "XTS Socket Disconnected!"))

    def _on_error(self, data):
        logger.error(TradeFormatter.format_connection("error", f"XTS Socket Error: {data}"))
