import time
import threading
import queue
import random
import string
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List

from packages.config import settings
from packages.data.connectors.xts_wrapper import XTSManager
from packages.tradeflow.fund_manager import FundManager
from packages.tradeflow.types import MarketIntentType
from packages.utils.market_utils import MarketUtils
from packages.utils.log_utils import setup_logger
from packages.utils.mongo import MongoRepository
from packages.utils.date_utils import DateUtils
from packages.utils.trade_formatter import TradeFormatter

logger = setup_logger("LiveTrader")

class LiveTradeEngine:
    """
    Orchestrates live trading by connecting XTS Socket to TradeFlow FundManager.
    """
    def __init__(self, strategy_config: Dict[str, Any], position_config: Dict[str, Any], debug: bool = False):
        """
        Args:
            strategy_config: The strategy rule document.
            position_config: Configuration for PositionManager.
            debug: Enable socket debug logging.
        """
        self.strategy_config = strategy_config
        self.position_config = position_config
        
        # Session ID format: mar05-0915-xyz
        now = datetime.now()
        rand_alpha = ''.join(random.choices(string.ascii_lowercase, k=3))
        self.session_id = f"{now.strftime('%b%d').lower()}-{now.strftime('%H%M')}-{rand_alpha}"
        
        # 1. Initialize FundManager
        self.fund_manager = FundManager(
            strategy_config=self.strategy_config,
            position_config=self.position_config,
            log_heartbeat=True,
            fetch_ohlc_fn=self._fetch_ohlc_api,
            fetch_quote_fn=self._fetch_quote_api
        )
        
        # Override on_signal to catch trades and signals
        self.fund_manager.on_signal = self._handle_signal
        
        # Register Paper Trading Log Handler
        self.fund_manager.position_manager.on_trade_event = self._record_papertrade_event
        
        # 2. Setup XTS Client & Socket
        self.xt_market = XTSManager.get_market_client()
        self.soc = XTSManager.get_market_data_socket(debug=debug)
        
        self.last_tick_time = time.time()
        self.tick_queue = queue.Queue()
        
        # Force Full mode for XTS Market Data Socket explicitly
        settings.XTS_BROADCAST_MODE = "Full"
        
        # 3. Register Socket Callbacks
        self.soc.on_connect = self._on_connect
        
        # Register Tick Callback for 1501 Full
        self.soc.on_message1501_json_full = self._on_tick
            
        self.soc.on_message1501_json_full = self._on_tick
            
        self.soc.on_disconnect = lambda: logger.warning(TradeFormatter.format_connection("disconnected", "Market Data Socket Disconnected!"))
        self.soc.on_error = lambda data: logger.error(TradeFormatter.format_connection("error", f"Socket Error: {data}"))

        self.subscribed_instruments = set() # Track for re-subscription
        self.last_subscribed_id = None
        self.is_running = False
        self.has_warmed_up = False
        self.db = MongoRepository.get_db()
        
        # Persistence State
        self.active_signals = []
        self.current_atm_strike = None
        
    def start(self):
        """Starts the live trade engine."""
        logger.info(TradeFormatter.format_session_start(self.session_id, self.strategy_config.get('name'), self.strategy_config.get('ruleId')))
        
        # 1. Initial Subscription Setup (Resolve NIFTY + Strike Chain)
        self.subscribed_instruments.add(settings.NIFTY_EXCHANGE_INSTRUMENT_ID)
        self._resync_strike_chain()
        
        # 2. Connect Socket first. 
        # In test environments, we must wait for the first 1501 Tick to get the true Replay Time,
        # so we DO NOT warm up here. Warmup is triggered dynamically inside _process_loop
        logger.info(TradeFormatter.format_connection("connecting", "Connecting to XTS Socket to detect Market Time..."))
        threading.Thread(target=self.soc.connect, daemon=True).start()
        
        # 3. Start Processor Thread
        logger.info(f"{TradeFormatter.EMOJI_THREAD} Starting Tick Processor Thread...")
        threading.Thread(target=self._process_loop, daemon=True).start()
        
        # 4. Connect Socket
        logger.info(TradeFormatter.format_connection("connecting", "Connecting to XTS Socket..."))
        threading.Thread(target=self.soc.connect, daemon=True).start()
        
        # Wait a bit for connection to settle
        time.sleep(2)
        
        # 4. Main Loop
        self.is_running = True
        logger.info("🟢 ENGINE RUNNING. Waiting for first tick to sync market time before processing signals...")
        
        try:
            while self.is_running:
                # End of Day check (15:30)
                now = datetime.now()
                if now.hour == 15 and now.minute >= 30:
                    logger.info(f"{TradeFormatter.EMOJI_MOON} End of Trading Day reached. Closing positions.")
                    self.fund_manager.handle_eod_settlement(time.time())
                    self.is_running = False
                
                # Keep-Alive & Watchdog: Check connection every 30s
                if time.time() - self.last_tick_time > 30:
                    self._ensure_connection()
                    self.last_tick_time = time.time()
                    
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("🛑 Manually stopping engine...")
        finally:
            self.stop()

    def stop(self):
        self.is_running = False
        # Potentially disconnect socket, but XTSManager shares it.
        # For CLI usage, exiting the process is sufficient.
        logger.info("🏁 Live Trade Engine Stopped.")

    def _on_tick(self, data):
        """Callback for incoming ticks from XTS Socket."""
        # Minimal work in the network thread: just drop into queue
        self.tick_queue.put(data)

    def _process_loop(self):
        """Main loop for processing ticks from the queue (Logic Thread)."""
        logger.info("🟢 Tick Processor Loop started.")
        while True:
            try:
                data = self.tick_queue.get()
                if data is None: break # Shutdown signal
                
                tick = MarketUtils.normalize_xts_event("1501-json-full", data)
                if not tick:
                    continue
                    
                self.last_tick_time = time.time()
                
                # Halt processing until Warmup is complete
                if not self.has_warmed_up:
                    if not self.fund_manager.is_warming_up:
                        logger.info(f"⏳ Detected First Market Tick Time: {tick['isoDt']} ({tick['t']})")
                        threading.Thread(target=self._warm_up, args=(tick['t'],), daemon=True).start()
                    
                    # Re-queue tick and wait gently so we don't lose data while warming up
                    time.sleep(0.5)
                    self.tick_queue.put(data)
                    continue
                
                # 2. Feed to FundManager
                self.fund_manager.on_tick_or_base_candle(tick)
                
                # 3. Rolling Strike Chain Check (If Nifty tick)
                if tick['i'] == settings.NIFTY_EXCHANGE_INSTRUMENT_ID:
                    spot = tick['p']
                    if self.current_atm_strike is None:
                        new_atm = round(spot / 50) * 50
                        self._update_rolling_strikes(new_atm)
                    else:
                        # Hysteresis: Only shift ATM if price moves beyond strike midpoint +/- buffer
                        # Threshold for shift = 25 (midpoint) + 15 (buffer) = 40 pts from current ATM.
                        buffer = 15
                        if abs(spot - self.current_atm_strike) > (25 + buffer):
                            new_atm = round(spot / 50) * 50
                            self._update_rolling_strikes(new_atm)
                
            except Exception as e:
                logger.error(f"💥 Error in Tick Processor: {e}", exc_info=True)
            finally:
                self.tick_queue.task_done()
        
    def _handle_signal(self, payload: Dict):
        """Callback received from FundManager when a signal is generated."""
        signal_type = payload.get('signal')
        symbol = str(payload.get('symbol'))
        
        # 1. Persist Signal
        self.active_signals.append(payload)
        try:
            self._sync_to_db()
        except Exception as e:
            logger.error(f"⚠️ Non-critical error syncing signal to DB: {e}")
        
        # 2. Dynamic Subscription for Options
        if symbol != str(settings.NIFTY_EXCHANGE_INSTRUMENT_ID) and symbol != self.last_subscribed_id:
            # XTS Option segments are usually 2 (NSEFO)
            # Find segment from master data if possible, or assume 2 for NIFTY options
            segment = 2 # Default for NIFTY Options
            self.xt_market.send_subscription([{'exchangeSegment': segment, 'exchangeInstrumentID': int(symbol)}], 1501)
            self.subscribed_instruments.add(int(symbol))
            self.last_subscribed_id = symbol
            
    def _record_papertrade_event(self, event_data: Dict):
        """Records granular trade events to the 'papertrade' collection."""
        if not self.fund_manager.record_papertrade_db:
            return
            
        # Enrich event data
        event_data.update({
            "sessionID": self.session_id,
            "cycleId": event_data.get("cycleId", "N/A"),
            "cycleSeq": event_data.get("cycleSeq", 1),
            "ruleId": self.strategy_config.get("ruleId"),
            "strategyName": self.strategy_config.get("name"),
            "niftyPrice": self.fund_manager.latest_tick_prices.get(26000, 0.0),
            "recordedAt": DateUtils.market_timestamp_to_iso(self.fund_manager.latest_market_time) if self.fund_manager.latest_market_time else datetime.now(DateUtils.MARKET_TZ).strftime("%Y-%m-%dT%H:%M:%S")
        })
        
        try:
            self.db["papertrade"].insert_one(event_data)
            logger.debug(f"📝 Recorded papertrade event: {event_data['type']} for {event_data['instrument']}")
        except Exception as e:
            logger.error(f"❌ Failed to record papertrade event: {e}")

    def _ensure_connection(self):
        """Checks socket health and attempts reconnection if down."""
        if self.soc.sid.connected:
            # Send Keep-Alive subscription to keep pipe open
            nifty_id = settings.NIFTY_EXCHANGE_INSTRUMENT_ID
            try:
                self.xt_market.send_subscription([{'exchangeSegment': 1, 'exchangeInstrumentID': nifty_id}], 1501)
            except Exception as e:
                logger.error(f"❌ Failed to send Keep-Alive: {e}")
            return

        logger.warning("🔌 Socket disconnected. Attempting RE-CONNECT...")
        try:
            # Check if a connection attempt is already likely in progress
            # sid.connect() will raise an error if already connected/connecting
            threading.Thread(target=self.soc.connect, daemon=True).start()
            
            # Wait a few seconds for _on_connect to fire and handle re-subscriptions
            time.sleep(3)
        except Exception as e:
            logger.error(f"❌ Re-connection attempt failed: {e}")

    def _on_connect(self):
        """Callback for socket connection. Re-subscribes to all instruments."""
        try:
            logger.info("✅ Market Data Socket Connected!")
            if self.subscribed_instruments:
                # Log specific IDs for transparency
                ids_str = ", ".join(map(str, sorted(list(self.subscribed_instruments))))
                logger.info(f"🔄 Re-subscribing to {len(self.subscribed_instruments)} instruments: [{ids_str}]")
                
                nse_eq = [i for i in self.subscribed_instruments if i == settings.NIFTY_EXCHANGE_INSTRUMENT_ID]
                nse_fo = [i for i in self.subscribed_instruments if i != settings.NIFTY_EXCHANGE_INSTRUMENT_ID]
                
                if nse_eq:
                    self.xt_market.send_subscription([{'exchangeSegment': 1, 'exchangeInstrumentID': i} for i in nse_eq], 1501)
                if nse_fo:
                    self.xt_market.send_subscription([{'exchangeSegment': 2, 'exchangeInstrumentID': i} for i in nse_fo], 1501)
        except Exception as e:
            logger.error(f"❌ Error in _on_connect: {e}", exc_info=True)
            
    def _warm_up(self, anchor_timestamp: int):
        """Fetches last 300 candles from XTS API to prime indicators."""
        if self.has_warmed_up:
            return
            
        logger.info(f"🔥 Warmup: Fetching historical candles anchored at {anchor_timestamp}...")
        self.fund_manager.is_warming_up = True
        
        nifty_id = settings.NIFTY_EXCHANGE_INSTRUMENT_ID
        
        # Calculate time range
        # Note: anchor_timestamp is the current market tick time. 
        # We want data BEFORE this time.
        end_dt = DateUtils.market_timestamp_to_datetime(anchor_timestamp)
        start_dt = end_dt - timedelta(days=2) # Default 2 days back
        
        # XTS get_ohlc expects format: 'Oct 01 2023 091500' or similar? 
        # Actually it's 'Oct 20 2021 151500' based on SDK docs
        fmt = "%b %d %Y %H%M%S"
        start_str = start_dt.strftime(fmt)
        end_str = end_dt.strftime(fmt)
        
        candles = self._fetch_ohlc_api(1, nifty_id, start_str, end_str)
        
        if not candles:
            logger.warning("⚠️ No historical data returned from API for warmup. Checking DB fallback...")
            # DB Fallback if API fails
            search_window = 7 * 24 * 3600
            fallback_ticks = list(self.db[settings.NIFTY_CANDLE_COLLECTION].find({
                "i": nifty_id,
                "t": {"$gte": anchor_timestamp - search_window, "$lt": anchor_timestamp}
            }).sort("t", -1).limit(300))
            candles = sorted(fallback_ticks, key=lambda x: x['t'])

        count = 0
        for t in candles:
            # Only process if older than anchor
            if t['t'] < anchor_timestamp:
                self.fund_manager.on_tick_or_base_candle(t)
                count += 1
            
        self.fund_manager.is_warming_up = False
        self.has_warmed_up = True
        logger.info(f"✅ Warmup complete. Processed {count} candles for NIFTY ending before {anchor_timestamp}.")

        # Record Engine Initialization in PaperTrade DB
        init_data = {
            "type": "INIT",
            "tradetime": DateUtils.market_timestamp_to_iso(anchor_timestamp),
            "cycleSeq": 1,
            "actionPnL": 0.0,
            "cyclePnL": 0.0,
            "totalPnL": 0.0,
            "instrument": "NIFTY",
            "price": self.fund_manager.latest_tick_prices.get(26000, 0.0),
            "msg": "Trading session initialized after successful warmup.",
            "config": {
                "budget": self.position_config.get("budget"),
                "sl": self.position_config.get("stop_loss_points"),
                "target": self.position_config.get("target_points"),
                "trailing_sl": self.position_config.get("trailing_sl_points"),
                "strategy_mode": self.position_config.get("strategy_mode")
            }
        }
        self._record_papertrade_event(init_data)

    def _resync_strike_chain(self):
        """Initial strike chain resolution based on latest Nifty price via API."""
        try:
            # 1. Try Quote API for Nifty (26000)
            quote_data = self._fetch_quote_api(1, settings.NIFTY_EXCHANGE_INSTRUMENT_ID)
            if quote_data:
                spot = quote_data.get('p', 0)
                if spot > 0:
                    atm = round(spot / 50) * 50
                    self._update_rolling_strikes(atm)
                    return

            # 2. DB Fallback if Quote API fails
            last_candle = self.db[settings.NIFTY_CANDLE_COLLECTION].find_one(
                {"i": settings.NIFTY_EXCHANGE_INSTRUMENT_ID},
                sort=[("t", -1)]
            )
            if last_candle:
                spot = last_candle.get('c', last_candle.get('p', 25000))
                atm = round(spot / 50) * 50
                self._update_rolling_strikes(atm)
        except Exception as e:
            logger.error(f"❌ Error in _resync_strike_chain: {e}")

    def _update_rolling_strikes(self, new_atm):
        """
        Maintains a rolling ATM +/- 3 strike window. 
        Subscribes to new entries, unsubscribes from old ones (protected by active trades).
        """
        if self.current_atm_strike is not None:
            logger.info(f"🔄 Rolling ATM Shift: {self.current_atm_strike} -> {new_atm}")
        else:
            logger.info(f"🎯 Setting Initial ATM: {new_atm}")
        
        # 1. Resolve new window IDs
        new_ids = self._resolve_strike_ids(new_atm)
        if not new_ids: return
        
        # 2. Identify new subscriptions
        to_sub = new_ids - self.subscribed_instruments
        
        # 3. Identify unsubscriptions (with protection)
        active_pos = self.fund_manager.position_manager.current_position
        active_ids = {int(active_pos.symbol)} if active_pos else set()
        protected = active_ids | {settings.NIFTY_EXCHANGE_INSTRUMENT_ID}
        if self.last_subscribed_id: protected.add(int(self.last_subscribed_id))
        
        to_unsub = (self.subscribed_instruments - new_ids) - protected
        
        # 4. Perform Subscriptions
        if to_sub:
            logger.info(f"  + Rolling Sub: {list(to_sub)}")
            self.xt_market.send_subscription([{'exchangeSegment': 2, 'exchangeInstrumentID': i} for i in to_sub], 1501)
            self.subscribed_instruments |= to_sub
            
        # 5. Perform Unsubscriptions
        if to_unsub:
            logger.info(f"  - Rolling Unsub: {list(to_unsub)}")
            self.xt_market.send_unsubscription([{'exchangeSegment': 2, 'exchangeInstrumentID': i} for i in to_unsub], 1501)
            self.subscribed_instruments -= to_unsub
            
        self.current_atm_strike = new_atm

    def _resolve_strike_ids(self, atm_strike) -> set:
        """Helper to get a set of IDs for ATM +/- 3 strikes."""
        now_iso = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        target_strikes = [atm_strike + (i * 50) for i in range(-3, 4)]
        
        opt_ref = self.db['instrument_master'].find_one({
            "name": "NIFTY", "series": "OPTIDX", "contractExpiration": {"$gte": now_iso}
        }, sort=[("contractExpiration", 1)])
        
        if not opt_ref: return set()
        
        expiry = opt_ref["contractExpiration"]
        contracts = list(self.db['instrument_master'].find({
            "name": "NIFTY", "series": "OPTIDX", "contractExpiration": expiry, "strikePrice": {"$in": target_strikes}
        }))
        
        return {int(c['exchangeInstrumentID']) for c in contracts}

    def _fetch_ohlc_api(self, segment: int, instrument_id: int, start_time: str = None, end_time: str = None) -> List[Dict]:
        """
        Helper to fetch 1-minute OHLC data from XTS REST API.
        Returns a list of normalized candle dicts.
        """
        try:
            if not start_time or not end_time:
                # Default to last hour if not specified
                now = datetime.now(DateUtils.MARKET_TZ)
                fmt = "%b %d %Y %H%M%S"
                end_time = now.strftime(fmt)
                start_time = (now - timedelta(hours=1)).strftime(fmt)

            logger.debug(f"🌐 API OHLC Request: {instrument_id} ({start_time} - {end_time})")
            response = self.xt_market.get_ohlc(
                exchangeSegment=segment,
                exchangeInstrumentID=instrument_id,
                startTime=start_time,
                endTime=end_time,
                compressionValue=60 # 1 minute
            )

            if response and response.get('type') == 'success':
                result = response.get('result', {})
                # XTS often uses "dataReponse" (typo in API) for OHLC results
                raw_data = result.get('dataReponse', result.get('data', ''))
                if not raw_data: return []
                
                # Parse the comma-separated records
                # Each record is "Timestamp|Open|High|Low|Close|Volume|OI|"
                records = raw_data.strip().split(',')
                candles = []
                for rec in records:
                    parts = rec.strip().split('|')
                    if len(parts) >= 6:
                        # Extract and normalize
                        try:
                            ts = int(parts[0]) - settings.XTS_TIME_OFFSET
                        except:
                            continue
                            
                        candles.append({
                            "i": instrument_id,
                            "t": ts,
                            "isoDt": DateUtils.market_timestamp_to_iso(ts),
                            "o": float(parts[1]),
                            "h": float(parts[2]),
                            "l": float(parts[3]),
                            "c": float(parts[4]),
                            "v": int(parts[5])
                        })
                return candles
            else:
                logger.warning(f"⚠️ API OHLC Failed for {instrument_id}: {response}")
        except Exception as e:
            logger.error(f"💥 Exception in _fetch_ohlc_api: {e}")
        return []

    def _fetch_quote_api(self, segment: int, instrument_id: int) -> Optional[Dict]:
        """
        Helper to fetch latest LTP from XTS Quotes API.
        """
        try:
            logger.debug(f"🌐 API Quote Request: {instrument_id}")
            # publishFormat: 1-JSON, 2-Binary
            response = self.xt_market.get_quote(
                Instruments=[{'exchangeSegment': segment, 'exchangeInstrumentID': instrument_id}],
                xtsMessageCode=1501, 
                publishFormat="1" 
            )

            if response and response.get('type') == 'success':
                result = response.get('result', {})
                quotes = result.get('listQuotes', [])
                if quotes:
                    raw_quote = quotes[0]
                    # The response for 1501 quote usually has Touchline data
                    quote_data = json.loads(raw_quote) if isinstance(raw_quote, str) else raw_quote
                    return MarketUtils.normalize_xts_event("1501-json-full", quote_data)
            else:
                logger.warning(f"⚠️ API Quote Failed for {instrument_id}: {response}")
        except Exception as e:
            logger.error(f"💥 Exception in _fetch_quote_api: {e}")
        return None

    def _sync_to_db(self):
        """Persists the current trading session state to 'live_trades' collection."""
        history = self.fund_manager.position_manager.trades_history
        
        # Convert objects to serializable dicts (matching backtest_results schema)
        trades_data = []
        for t in history:
            trade_dict = {
                "id": t.symbol,
                "symbol": t.symbol,
                "entryTime": t.entry_time.isoformat() if t.entry_time else None,
                "exitTime": t.exit_time.isoformat() if t.exit_time else None,
                "entryPrice": t.entry_price,
                "exitPrice": t.exit_price,
                "quantity": getattr(t, 'quantity', t.initial_quantity),
                "type": t.intent.name if hasattr(t.intent, 'name') else str(t.intent),
                "pnl": t.pnl,
                "realizedPnl": t.pnl, # In live, they are same
                "exitReason": getattr(t, 'status', 'CLOSED'),
                "tradeCycle": t.trade_cycle,
                "signal": t.entry_signal
            }
            trades_data.append(trade_dict)
            
        # 1. Sanitize active_signals for MongoDB (convert Enums to strings)
        clean_signals = []
        for sig in self.active_signals:
            clean_sig = {}
            for k, v in sig.items():
                if hasattr(v, 'name') and hasattr(v, 'value'): # Enum check
                    clean_sig[k] = v.name
                else:
                    clean_sig[k] = v
            clean_signals.append(clean_sig)
            
        # 2. Calculate Daily PnL
        daily_pnl = {}
        now_ist = datetime.now(DateUtils.MARKET_TZ)
        today_str = now_ist.strftime("%Y-%m-%d")
        daily_pnl[today_str] = sum(t.pnl for t in history if t.pnl is not None)
            
        session_doc = {
            "sessionID": self.session_id,
            "ruleId": self.strategy_config.get("ruleId"),
            "strategyName": self.strategy_config.get("name"),
            "timestamp": now_ist,
            "trades": trades_data,
            "dailyPnl": daily_pnl,
            "activeSignals": clean_signals,
            "status": "ACTIVE" if self.is_running else "COMPLETED"
        }
        
        # Upsert by sessionID
        self.db["live_trades"].update_one(
            {"sessionID": self.session_id},
            {"$set": session_doc},
            upsert=True
        )
