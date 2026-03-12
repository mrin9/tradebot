import json
import random
import string
import time
import threading
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

from packages.utils.log_utils import setup_logger
from packages.utils.date_utils import DateUtils
from packages.utils.trade_formatter import TradeFormatter
from packages.data.connectors.xts_normalizer import XTSNormalizer
from packages.utils.mongo import MongoRepository
from packages.config import settings
from packages.data.connectors.xts_wrapper import XTSManager

from packages.services.live_market import LiveMarketService
from packages.services.trade_event import TradeEventService
from packages.services.trade_config_service import TradeConfigService
from packages.services.contract_discovery import ContractDiscoveryService
from packages.services.market_history import MarketHistoryService
from packages.tradeflow.fund_manager import FundManager

logger = setup_logger("LiveTrader")

class LiveTradeEngine:
    """
    Orchestrates live trading by connecting LiveMarketService to TradeFlow FundManager.
    """
    def __init__(self, strategy_config: Dict[str, Any], position_config: Dict[str, Any], debug: bool = False):
        self.strategy_config = strategy_config
        self.position_config = position_config
        
        # Session ID
        self.session_id = DateUtils.generate_session_id(strategy_config.get("strategyId", "python"))
        
        # 1. Initialize Services
        self.config_service = TradeConfigService()
        self.discovery_service = ContractDiscoveryService()
        self.history_service = MarketHistoryService(fetch_ohlc_api_fn=self._fetch_ohlc_api)
        
        self.market_service = LiveMarketService(debug=debug)
        self.event_service = TradeEventService(self.session_id, record_papertrade=position_config.get("record_papertrade", True))
        
        # 2. Initialize FundManager with services
        self.fund_manager = FundManager(
            strategy_config=self.strategy_config,
            position_config=self.position_config,
            log_heartbeat=True,
            config_service=self.config_service,
            discovery_service=self.discovery_service,
            history_service=self.history_service,
            fetch_quote_fn=self._fetch_quote_api
        )
        
        # Hook FundManager events into TradeEventService
        self.fund_manager.on_signal = self._handle_signal
        self.fund_manager.position_manager.on_trade_event = lambda ev: self.event_service.record_trade_event(ev, self.fund_manager)
        
        self.last_tick_time = time.time()
        self.is_running = False
        self.has_warmed_up = False
        self.current_atm_strike = None
        
    def start(self):
        logger.info(TradeFormatter.format_session_start(self.session_id, self.strategy_config.get('name'), self.strategy_config.get('strategyId')))
        
        # Initial subscriptions
        self._resync_strike_chain()
        
        # Start Services
        self.market_service.start(on_tick=self._process_tick)
        
        self.is_running = True
        
        try:
            while self.is_running:
                now = datetime.now()
                # EOD Settlement
                if now.hour == 15 and now.minute >= 30:
                    self.fund_manager.handle_eod_settlement(time.time())
                    self.stop()
                    break
                
                # Health Check (Socket & Drift)
                if time.time() - self.last_tick_time > 30:
                    self.market_service.ensure_connection()
                    self.last_tick_time = time.time()
                
                time.sleep(1)
        except KeyboardInterrupt:
            self.stop()
        finally:
            self.stop()

    def stop(self):
        if not self.is_running: return
        self.is_running = False
        self.market_service.stop()
        self.event_service.sync_session_summary(self.fund_manager)
        logger.info("🏁 Live Trade Engine Stopped.")

    def _process_tick(self, tick: Dict):
        """Passed as callback to LiveMarketService."""
        self.last_tick_time = time.time()
        
        # 1. Warmup Check
        if not self.has_warmed_up:
            if not self.fund_manager.is_warming_up:
                threading.Thread(target=self._warm_up, args=(tick['t'],), daemon=True).start()
            return # Drop ticks during warmup, they'll be processed after resub

        # 2. FundManager Feed
        self.fund_manager.on_tick_or_base_candle(tick)
        
        # 3. ATM Drift Check (Nifty only)
        if tick['i'] == settings.NIFTY_EXCHANGE_INSTRUMENT_ID:
            spot = tick['p']
            atm = self.discovery_service.get_atm_strike(spot)
            if self.current_atm_strike is None or abs(spot - self.current_atm_strike) > 40:
                self._update_rolling_strikes(atm)
        
    def _handle_signal(self, payload: Dict):
        """FundManager signal callback."""
        self.event_service.record_signal(payload)
        
        # Ensure we are subscribed to the signal instrument
        symbol = int(payload.get('symbol'))
        if symbol not in self.market_service.subscribed_instruments:
            self.market_service.subscribe([symbol])
            
    def _warm_up(self, anchor_timestamp: int):
        if self.has_warmed_up: return
        self.fund_manager.is_warming_up = True
        
        try:
            self.history_service.run_warmup(self.fund_manager, settings.NIFTY_EXCHANGE_INSTRUMENT_ID, anchor_timestamp, "SPOT", use_api=True)
            self.has_warmed_up = True
            
            # Record INIT event with enriched config
            self.event_service.record_init(self.fund_manager, mode="live")
        finally:
            self.fund_manager.is_warming_up = False

    def _resync_strike_chain(self):
        """Initial ATM resolution and subscription."""
        try:
            quote = self._fetch_quote_api(1, settings.NIFTY_EXCHANGE_INSTRUMENT_ID)
            spot = quote.get('p') if quote else None
            if not spot:
                # Fallback to DB
                db = MongoRepository.get_db()
                last = db[settings.NIFTY_CANDLE_COLLECTION].find_one({"i": settings.NIFTY_EXCHANGE_INSTRUMENT_ID}, sort=[("t", -1)])
                spot = last['c'] if last else 25000
            
            self._update_rolling_strikes(self.discovery_service.get_atm_strike(spot))
        except Exception as e:
            logger.error(f"❌ Error in _resync_strike_chain: {e}")

    def _update_rolling_strikes(self, new_atm):
        """Calculates window and delegates to MarketService."""
        if self.current_atm_strike is not None:
            logger.info(f"🔄 Rolling ATM Shift: {self.current_atm_strike} -> {new_atm}")
        else:
            logger.info(f"Targeting ATM: {new_atm}")
        
        new_ids = self.discovery_service.get_strike_window_ids(new_atm)
        if not new_ids: return
        
        # Add Nifty Spot
        new_ids.add(settings.NIFTY_EXCHANGE_INSTRUMENT_ID)
        
        # Identify protected instruments (currently in position)
        protected = set()
        active_pos = self.fund_manager.position_manager.current_position
        if active_pos: 
            protected.add(int(active_pos.symbol))
        
        current_subs = self.market_service.subscribed_instruments
        to_sub = list(new_ids - current_subs)
        to_unsub = list((current_subs - new_ids) - protected)
        
        if to_sub: self.market_service.subscribe(to_sub)
        if to_unsub: self.market_service.unsubscribe(to_unsub)
        
        self.current_atm_strike = new_atm

    def _fetch_ohlc_api(self, segment: int, instrument_id: int, start_time: str = None, end_time: str = None) -> List[Dict]:
        """Wrapper for XTS REST API."""
        try:
            if not start_time or not end_time:
                now = datetime.now(DateUtils.MARKET_TZ)
                fmt = "%b %d %Y %H%M%S"
                end_time = now.strftime(fmt)
                start_time = (now - timedelta(hours=1)).strftime(fmt)

            response = XTSManager.call_api(
                "market",
                "get_ohlc",
                exchange_segment=segment, 
                exchange_instrument_id=instrument_id, 
                start_time=start_time, 
                end_time=end_time, 
                compression_value=60
            )
            if response and isinstance(response, dict) and response.get('type') == 'success':
                raw = response.get('result', {}).get('dataReponse', '')
                candles = []
                for rec in raw.strip().split(','):
                    parts = rec.strip().split('|')
                    if len(parts) >= 6:
                        try:
                            ts = DateUtils.rest_timestamp_to_utc(parts[0])
                        except:
                            continue
                        candles.append({"i": instrument_id, "t": ts, "o": float(parts[1]), "h": float(parts[2]), "l": float(parts[3]), "c": float(parts[4]), "v": int(parts[5])})
                return candles
        except Exception as e:
            logger.error(f"💥 Exception in _fetch_ohlc_api: {e}")
        return []

    def _fetch_quote_api(self, segment: int, instrument_id: int) -> Optional[Dict]:
        """Wrapper for XTS Quote REST API."""
        try:
            response = XTSManager.call_api(
                "market",
                "get_quote",
                instruments=[{'exchangeSegment': segment, 'exchangeInstrumentID': instrument_id}], 
                xts_message_code=1501, 
                publish_format="1"
            )
            if response and isinstance(response, dict) and response.get('type') == 'success':
                quotes = response.get('result', {}).get('listQuotes', [])
                if quotes:
                    data = json.loads(quotes[0]) if isinstance(quotes[0], str) else quotes[0]
                    return XTSNormalizer.normalize_xts_event("1501-json-full", data)
        except Exception as e:
            logger.error(f"💥 Exception in _fetch_quote_api: {e}")
        return None
