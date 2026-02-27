import time
import threading
import queue
import uuid
from datetime import datetime
from typing import Dict, Any, Optional, List

from packages.config import settings
from packages.data.connectors.xts_wrapper import XTSManager
from packages.tradeflow.fund_manager import FundManager
from packages.tradeflow.position_manager import MarketIntent
from packages.utils.market_utils import MarketUtils
from packages.utils.log_utils import setup_logger
from packages.utils.mongo import MongoRepository

logger = setup_logger("LiveTrader")

class LiveTradeEngine:
    """
    Orchestrates live trading by connecting XTS Socket to TradeFlow FundManager.
    """
    def __init__(self, strategy_config: Dict[str, Any], position_config: Dict[str, Any], subscribe_to: str = "Full", debug: bool = False):
        """
        Args:
            strategy_config: The strategy rule document.
            position_config: Configuration for PositionManager.
            subscribe_to: "Full" or "Partial" broadcast mode.
        """
        self.strategy_config = strategy_config
        self.position_config = position_config
        self.subscribe_to = subscribe_to
        self.session_id = f"live-{uuid.uuid4().hex[:8]}"
        
        # 1. Initialize FundManager
        self.fund_manager = FundManager(
            strategy_config=self.strategy_config,
            position_config=self.position_config,
            log_heartbeat=True
        )
        
        # Override on_signal to catch trades and signals
        self.fund_manager.on_signal = self._handle_signal
        
        # 2. Setup XTS Client & Socket
        self.xt_market = XTSManager.get_market_client()
        self.soc = XTSManager.get_market_data_socket(debug=debug)
        
        self.last_tick_time = time.time()
        self.tick_queue = queue.Queue()
        
        # Set subscription mode in settings temporarily or pass it?
        # The MDSocket_io reads from settings directly.
        # However, settings class is a singleton. Updating it might affect other parts.
        # But for are running a single CLI process, it is fine.
        settings.XTS_BROADCAST_MODE = subscribe_to
        
        # 3. Register Socket Callbacks
        self.soc.on_connect = self._on_connect
        
        # Restore Tick Callbacks
        if subscribe_to == "Full":
            self.soc.on_message1501_json_full = self._on_tick
            self.soc.on_message1512_json_full = self._on_tick
            self.soc.on_message1105_json_full = self._on_tick
        else:
            self.soc.on_message1501_json_partial = self._on_tick
            self.soc.on_message1512_json_partial = self._on_tick
            self.soc.on_message1105_json_partial = self._on_tick
            
        self.soc.on_disconnect = lambda: logger.warning("⚠️ Market Data Socket Disconnected!")
        self.soc.on_error = lambda data: logger.error(f"❌ Socket Error: {data}")

        self.subscribed_instruments = set() # Track for re-subscription
        self.last_subscribed_id = None
        self.is_running = False
        self.db = MongoRepository.get_db()
        
        # Persistence State
        self.active_signals = []
        self.current_atm_strike = None
        
    def start(self):
        """Starts the live trade engine."""
        logger.info(f"🚀 Starting Live Trade Engine | Session: {self.session_id}")
        logger.info(f"📈 Strategy: {self.strategy_config.get('name')} ({self.strategy_config.get('ruleId')})")
        
        # 1. Warm up FundManager with recent history
        self._warm_up()
        
        # 2. Initial Subscription Setup (Resolve NIFTY + Strike Chain)
        self.subscribed_instruments.add(settings.NIFTY_EXCHANGE_INSTRUMENT_ID)
        self._resync_strike_chain()
        
        # 3. Start Processor Thread
        logger.info("🧵 Starting Tick Processor Thread...")
        threading.Thread(target=self._process_loop, daemon=True).start()
        
        # 4. Connect Socket
        logger.info("🔌 Connecting to XTS Socket...")
        threading.Thread(target=self.soc.connect, daemon=True).start()
        
        # Wait a bit for connection to settle
        time.sleep(2)
        
        # 4. Main Loop
        self.is_running = True
        logger.info("🟢 ENGINE RUNNING. Monitoring for signals...")
        
        try:
            while self.is_running:
                # End of Day check (15:30)
                now = datetime.now()
                if now.hour == 15 and now.minute >= 30:
                    logger.info("🕒 End of Trading Day reached. Closing positions.")
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
            
    def _warm_up(self):
        """Fetches last 300 candles from DB to prime indicators (handling holidays)."""
        logger.info("🔥 Pruning/Warming up indicators from DB history...")
        self.fund_manager.is_warming_up = True
        now_ts = int(time.time())
        # Increase window to 7 days to account for long holidays/weekends
        # but limit to 300 candles to avoid excessive processing
        search_window = 7 * 24 * 3600 
        nifty_id = settings.NIFTY_EXCHANGE_INSTRUMENT_ID
        
        ticks = self.db[settings.NIFTY_CANDLE_COLLECTION].find({
            "i": nifty_id,
            "t": {"$gte": now_ts - search_window}
        }).sort("t", -1).limit(300) # Get latest 300
        
        # Sort back to chronological order for feeding
        ticks_list = sorted(list(ticks), key=lambda x: x['t'])
        
        count = 0
        for t in ticks_list:
            self.fund_manager.on_tick_or_base_candle(t)
            count += 1
            
        self.fund_manager.is_warming_up = False
        logger.info(f"✅ Warm-up complete. Processed {count} historical candles for NIFTY ({nifty_id}).")

    def _resync_strike_chain(self):
        """Initial strike chain resolution based on latest Nifty price."""
        last_candle = self.db[settings.NIFTY_CANDLE_COLLECTION].find_one(
            {"i": settings.NIFTY_EXCHANGE_INSTRUMENT_ID},
            sort=[("t", -1)]
        )
        if last_candle:
            spot = last_candle.get('c', last_candle.get('p', 25000))
            atm = round(spot / 50) * 50
            self._update_rolling_strikes(atm)

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
        now_ist = DateUtils.get_market_time()
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
