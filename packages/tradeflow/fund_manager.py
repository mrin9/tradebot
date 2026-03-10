from typing import Dict, Callable, Any, List
from packages.utils.date_utils import DateUtils
from datetime import datetime
from packages.utils.trade_formatter import TradeFormatter
import logging
from packages.tradeflow.indicator_calculator import IndicatorCalculator
from packages.tradeflow.python_strategy_loader import PythonStrategy
from packages.utils.log_utils import setup_logger
from packages.tradeflow.types import SignalType, MarketIntentType, InstrumentKindType, InstrumentCategoryType

from packages.tradeflow.position_manager import PositionManager
from packages.tradeflow.order_manager import PaperTradingOrderManager
from packages.tradeflow.candle_resampler import CandleResampler
from packages.utils.mongo import MongoRepository
from packages.config import settings
import time

logger = setup_logger(__name__)

class FundManager:
    """
    The Orchestrator (Brain) for Multi-Timeframe Analysis (MTFA).
    Coordinates data flow between Market Data, multiple Timeframe Resamplers, Indicators, and Strategy Logic.
    """
    def __init__(self, strategy_config: Dict[str, Any], position_config: Dict[str, Any] | None = None, log_heartbeat: bool = False, is_backtest: bool = False, fetch_ohlc_fn: Callable = None, fetch_quote_fn: Callable = None):
        """
        Args:
            strategy_config (Dict): The full JSON-DSL strategy rule document from the database.
            position_config (Dict, optional): Configuration for PositionManager (quantity, stop_loss, target).
            log_heartbeat (bool): If True, logs indicator state on every candle close (useful for live).
            is_backtest (bool): If True, running in backtest mode.
            fetch_ohlc_fn (Callable, optional): API callback to fetch historical OHLC (for live warmup).
            fetch_quote_fn (Callable, optional): API callback to fetch latest Quote (for live fallbacks).
        """
        self.config = strategy_config
        self.indicators_config = self.config.get('Indicators', self.config.get('indicators', []))
        self.log_heartbeat = log_heartbeat
        self.is_backtest = is_backtest
        self.pos_config = position_config or {}
        
        # 1. Initialize Indicator Calculator (managing multiple timeframes)
        self.indicator_calculator = IndicatorCalculator(indicators_config=self.indicators_config)
        
        # 2. Initialize Strategy Logic (Python script only)
        # Priority: pos_config (CLI override) > strategy_config (DB)
        python_path = self.pos_config.get("python_strategy_path") or self.config.get("pythonStrategyPath")
        
        if not python_path:
            raise ValueError("No 'python_strategy_path' found in position_config or strategy_config.")
            
        self.strategy = PythonStrategy(script_path=python_path)
        logger.info(f"🐍 Strategy: Python Code ({python_path})")
        
        # 3. Core Parameters (using centralized defaults)
        self.initial_budget = self.pos_config.get("budget", 200000.0)
        self.invest_mode = self.pos_config.get("invest_mode", settings.BACKTEST_INVEST_MODE)
        self.stop_loss_points = self.pos_config.get('stop_loss_points', settings.BACKTEST_STOP_LOSS)
        
        target_pts = self.pos_config.get('target_points', settings.BACKTEST_TARGET_STEPS)
        if isinstance(target_pts, str):
            self.target_points = [float(x.strip()) for x in target_pts.split(',')]
        else:
            self.target_points = target_pts
            
        self.trailing_sl_points = self.pos_config.get('trailing_sl_points', 0.0)
        self.tsl_indicator_id = self.pos_config.get('tsl_indicator_id', self.config.get('tslIndicatorId'))
        self.use_break_even = self.pos_config.get('use_break_even', True)
        self.record_papertrade_db = self.pos_config.get('record_papertrade_db', True)
        
        self.trade_instrument_type = self.pos_config.get("instrument_type", "CASH").upper() # CASH, OPTIONS, FUTURES
        self.strike_selection = self.pos_config.get("strike_selection", self.pos_config.get("option_type", "ATM")).upper() # ATM, ITM, OTM
        
        # Map string to InstrumentKindType enum
        enum_map = {
            "CASH": InstrumentKindType.CASH,
            "OPTIONS": InstrumentKindType.OPTIONS,
            "FUTURES": InstrumentKindType.FUTURES
        }
        instr_enum = enum_map.get(self.trade_instrument_type, InstrumentKindType.CASH)
        if self.trade_instrument_type not in enum_map:
            logger.warning(f"Unrecognized instrument type '{self.trade_instrument_type}', defaulting to CASH")
        
        # Parse pyramid steps
        pyramid_steps_raw = self.pos_config.get("pyramid_steps", "100")
        if isinstance(pyramid_steps_raw, str):
            pyramid_steps = [int(s.strip()) for s in pyramid_steps_raw.split(',')]
        else:
            pyramid_steps = pyramid_steps_raw
        
        self.position_manager = PositionManager(
            symbol=self.pos_config.get("symbol", "NIFTY"), 
            quantity=self.pos_config.get("quantity", 50), 
            stop_loss_points=self.stop_loss_points, 
            target_points=self.target_points,
            instrument_type=instr_enum,
            trailing_sl_points=self.trailing_sl_points,
            use_break_even=self.use_break_even,
            pyramid_steps=pyramid_steps,
            pyramid_confirm_pts=self.pos_config.get("pyramid_confirm_pts", 10.0),
            price_source=self.pos_config.get("price_source", settings.BACKTEST_PRICE_SOURCE),
            tsl_indicator_id = self.tsl_indicator_id
        )
        self.order_manager = PaperTradingOrderManager()
        self.position_manager.set_order_manager(self.order_manager)
        
        self.price_source = self.pos_config.get("price_source", settings.BACKTEST_PRICE_SOURCE).lower() # "open" or "close"
        
        self.on_signal: Callable[[Dict], None] | None = None
        self.db = MongoRepository.get_db()
        self.latest_tick_prices: Dict[int, float] = {}
        self.fetch_ohlc_fn = fetch_ohlc_fn
        self.fetch_quote_fn = fetch_quote_fn
        
        # 4. Global Timeframe and Multi-Instrument Streams
        self.global_timeframe = self.config.get('timeframe_seconds', self.config.get('timeframe', settings.DEFAULT_TIMEFRAME))
        
        # Track active instruments being monitored {category: instrument_id}
        self.active_instruments: Dict[str, int] = {"SPOT": 26000}
        self.selection_spot_price: float | None = None
        
        # Initialize Resamplers per instrument_id
        self.resamplers: Dict[int, CandleResampler] = {}
        self._ensure_resampler(26000, InstrumentCategoryType.SPOT)
            
        # 5. Global cache 
        self.latest_indicators_state: Dict[str, float] = {}
        self.is_warming_up = False
        self.latest_market_time: float | None = None
        
        # Track last sync timestamp per instrument to optimize re-warmups
        self.instrument_last_sync: Dict[int, float] = {}

        # Track the last processed day to force instrument re-selection on day change
        self.last_day_str: str | None = None

    def _ensure_resampler(self, instrument_id: int, category: InstrumentCategoryType):
        """Ensures a resampler exists for the given instrument ID."""
        if instrument_id not in self.resamplers:
            self.resamplers[instrument_id] = CandleResampler(
                instrument_id=instrument_id,
                interval_seconds=self.global_timeframe,
                on_candle_closed=lambda c, cat=category: self._on_resampled_candle_closed(c, cat)
            )
            logger.debug(f"🛠️ Created dynamic resampler for {category.value} ({instrument_id})")
        
    def _resolve_option_contract(self, strike: float, is_ce: bool, current_ts: float) -> tuple[int | None, str | None]:
        """Resolves the nearest expiry option contract ID and description for NIFTY from DB given a strike."""
        # Convert timestamp to ISO string for comparison with contractExpiration
        dt_iso = DateUtils.market_timestamp_to_iso(current_ts)
        
        opt_type_num = 3 if is_ce else 4 # CE=3, PE=4 in XTS
        
        # Simplification: Sort by contractExpiration and get the first one (nearest expiry)
        contract = self.db[settings.INSTRUMENT_MASTER_COLLECTION].find_one(
            {
                "name": "NIFTY", 
                "series": "OPTIDX", 
                "strikePrice": strike, 
                "optionType": opt_type_num,
                "contractExpiration": {"$gte": dt_iso}
            },
            sort=[("contractExpiration", 1)]
        )
        
        if contract:
            return contract["exchangeInstrumentID"], contract.get("description", contract.get("displayName"))
        return None, None
        
    def _check_and_update_monitored_instruments(self, current_spot: float, current_ts: float):
        """Continuously manages the CE and PE instruments being monitored. Handles drift re-selection."""
        if self.is_warming_up:
            return  # Defer option resolution until warmup completes to avoid API burst
            
        atm_strike = round(current_spot / 50) * 50
        
        # 0. Check for Day Change
        current_day_str = DateUtils.market_timestamp_to_datetime(current_ts).strftime("%Y-%m-%d")
        is_new_day = False
        if self.last_day_str != current_day_str:
            is_new_day = True
            self.last_day_str = current_day_str
            
        needs_update = False
        if self.selection_spot_price is None or is_new_day:
            needs_update = True
        elif abs(current_spot - self.selection_spot_price) > 25:
            # Price drifted significantly, recalculate ATM and re-map
            logger.debug(TradeFormatter.format_drift(current_spot, self.selection_spot_price))
            needs_update = True
            
        if needs_update:
            self.selection_spot_price = current_spot
            
            # Resolve CE
            ce_id, ce_desc = self._resolve_option_contract(atm_strike, True, current_ts)
            if ce_id:
                new_ce_id = int(ce_id)
                if self.active_instruments.get("CE") != new_ce_id:
                    self.active_instruments["CE"] = new_ce_id
                    self.active_instruments["CE_DESC"] = ce_desc
                    # 1. Ensure Resampler and Reset it for clean start
                    self._ensure_resampler(new_ce_id, InstrumentCategoryType.CE)
                    self.resamplers[new_ce_id].current_candle = None 
                    self.resamplers[new_ce_id].last_period_start = None
                    # 2. Extract cached indicators immediately to avoid stale data
                    cached_indicators = self.indicator_calculator.extract_indicators(new_ce_id, InstrumentCategoryType.CE)
                    if cached_indicators:
                        self.latest_indicators_state.update(cached_indicators)
                    # 3. Perform Top-up/Initial Warmup
                    self._warmup_instrument("CE", new_ce_id, current_ts)
            
            # Resolve PE
            pe_id, pe_desc = self._resolve_option_contract(atm_strike, False, current_ts)
            if pe_id:
                new_pe_id = int(pe_id)
                if self.active_instruments.get("PE") != new_pe_id:
                    self.active_instruments["PE"] = new_pe_id
                    self.active_instruments["PE_DESC"] = pe_desc
                    # 1. Ensure Resampler and Reset
                    self._ensure_resampler(new_pe_id, InstrumentCategoryType.PE)
                    self.resamplers[new_pe_id].current_candle = None
                    self.resamplers[new_pe_id].last_period_start = None
                    # 2. Extract cached indicators immediately
                    cached_indicators = self.indicator_calculator.extract_indicators(new_pe_id, InstrumentCategoryType.PE)
                    if cached_indicators:
                        self.latest_indicators_state.update(cached_indicators)
                    # 3. Perform Warmup
                    self._warmup_instrument("PE", new_pe_id, current_ts)

    def _fetch_historical_candles(self, segment: int, instrument_id: int, start_ts: float, end_ts: float, limit: int = settings.GLOBAL_WARMUP_CANDLES) -> list[Dict]:
        """Unified helper to fetch historical candles from API (live) or DB (backtest)."""
        if self.fetch_ohlc_fn and not self.is_backtest:
            # Live Mode: Fetch from API
            fmt = "%b %d %Y %H%M%S"
            start_dt = DateUtils.market_timestamp_to_datetime(start_ts)
            end_dt = DateUtils.market_timestamp_to_datetime(end_ts)
            history = self.fetch_ohlc_fn(segment, instrument_id, start_dt.strftime(fmt), end_dt.strftime(fmt))
            # fetch_ohlc_fn should return normalized list of dicts
            if history:
                return history[-limit:]
            # API returned empty — fall through to DB fallback
            logger.warning(f"⚠️ API returned no data for {instrument_id} ({start_dt.strftime('%Y-%m-%d %H:%M')} → {end_dt.strftime('%Y-%m-%d %H:%M')}). Falling back to DB...")

        # Backtest, Default, or API Fallback: Fetch from DB
        query = {"i": instrument_id, "t": {"$lte": end_ts}}
        if start_ts:
            query["t"]["$gte"] = start_ts
            
        history_cursor = list(self.db[settings.OPTIONS_CANDLE_COLLECTION].find(
            query
        ).sort("t", -1).limit(limit))
        return sorted(history_cursor, key=lambda x: x['t'])

    def _warmup_instrument(self, category: str, instrument_id: int, current_ts: float):
        """
        Fetches historical 1m candles for the new instrument and warms up the resampler/indicators.
        Uses intelligent top-up syncing to avoid redundant fetches.
        """
        last_sync = self.instrument_last_sync.get(instrument_id)
        
        # 1. Temporal Caching: If synced very recently (< 5 mins), skip entirely
        if last_sync and (current_ts - last_sync) < 300:
             # logger.debug(f"⚡ Skipping re-warmup for {category} ({instrument_id}). Already synced recently.")
             return

        # 2. Determine Sync Range
        is_same_day = False
        if last_sync:
            last_dt = DateUtils.market_timestamp_to_datetime(last_sync)
            current_dt = DateUtils.market_timestamp_to_datetime(current_ts)
            is_same_day = last_dt.date() == current_dt.date()

        if last_sync and is_same_day:
            # Top-up: Fetch missing gap since last seen (only within the same day)
            start_ts = last_sync
            limit = 500 # Generous cap for a drift gap
            mode_desc = "Top-up"
        else:
            # Full/Initial Warmup: Fetch baseline (e.g. 200 candles)
            # We do this on a new day to ensure indicators have full historical context
            start_ts = current_ts - 3600 * 24 * 4 # 4 days back to cover weekends
            limit = settings.GLOBAL_WARMUP_CANDLES
            mode_desc = "Initial"

        # 3. Suppress signals during replay logic
        saved_warming_up = self.is_warming_up
        self.is_warming_up = True
        
        try:
            start_dt_str = DateUtils.market_timestamp_to_datetime(start_ts).strftime('%Y-%m-%d %H:%M')
            end_dt_str = DateUtils.market_timestamp_to_datetime(current_ts).strftime('%Y-%m-%d %H:%M')
            
            history = self._fetch_historical_candles(2, instrument_id, start_ts, current_ts, limit=limit)
            
            if not history:
                logger.warning(f"⚠️ No history found for {category} ({instrument_id}) warmup. Range: {start_dt_str} → {end_dt_str}")
                return
            
            self._ensure_resampler(instrument_id, InstrumentCategoryType(category))
            resampler = self.resamplers.get(instrument_id)
            if resampler:
                # Suppress heartbeats during warmup replay
                saved_heartbeat = self.log_heartbeat
                self.log_heartbeat = False
                
                resampler.instrument_id = int(instrument_id)
                for candle in history:
                    resampler.add_candle(candle)
                
                self.log_heartbeat = saved_heartbeat
                
                # 4. Update sync state
                self.instrument_last_sync[instrument_id] = current_ts
                
                # Retrieve description if available
                desc = self.active_instruments.get(f"{category}_DESC", f"{instrument_id}")
                logger.info(f"Warmup complete for {category} ({instrument_id} - {desc}): {len(history)} candles ({mode_desc} sync {start_dt_str} → {end_dt_str}).")
        finally:
            self.is_warming_up = saved_warming_up

    def _fetch_fallback_quote(self, segment: int, instrument_id: int, current_ts: float | None) -> float | None:
        """Unified helper to fetch a fallback quote from API (live) or DB (backtest)."""
        if self.fetch_quote_fn and not self.is_backtest:
            # Live Mode: Fetch from API
            quote = self.fetch_quote_fn(segment, instrument_id)
            if quote and quote.get('p'):
                logger.info(f"✅ Found API fallback price for {instrument_id}: {quote.get('p')}")
                return quote.get('p')

        # DB Fallback (Backup or Backtest)
        query = {"i": instrument_id}
        if current_ts:
            query["t"] = {"$lte": current_ts}
            
        fallback = self.db['options_candle'].find_one(query, sort=[("t", -1)])
        if fallback:
            price = fallback.get('c', fallback.get('p'))
            if price is not None:
                logger.info(f"✅ Found DB fallback price for {instrument_id}: {price}")
                return price
                
        return None

    def _get_fallback_option_price(self, symbol_id: int, current_ts: float | None, is_entry: bool = False) -> float | None:
        """
        Attempts to find a reliable price for an option when the live tick is missing.
        Priority:
        1. Tick Cache
        2. API/DB Fallback (nearest quote/candle before or at current_ts)
        3. Position Manager's current_price (only for exits)
        """
        # 1. Tick Cache
        price = self.latest_tick_prices.get(symbol_id)
        if price:
            return price
            
        # 2. API/DB Fallback
        logger.info(f"🔍 No live tick for {symbol_id}. Checking fallbacks...")
        price = self._fetch_fallback_quote(2, symbol_id, current_ts)
        if price is not None:
            return price
            
        # 3. Position Manager Fallback (Exits Only)
        if not is_entry and self.position_manager.current_position and str(symbol_id) == self.position_manager.current_position.symbol:
            price = self.position_manager.current_position.current_price
            if price is not None and price > 0:
                logger.info(f"⚠️ Using PositionManager last known price for {symbol_id}: {price}")
                return price
                
        return None

    def on_tick_or_base_candle(self, market_data: Dict):
        """
        Process a real-time TICK or a base 1-minute CANDLE from the stream.
        Routes it to all configured timeframes for resampling.
        
        Args:
            market_data (Dict): OHLCV data or Tick data.
        """
        inst_id = market_data.get('i', market_data.get('instrument_id'))
        
        # Update global market time if available
        ts = market_data.get('t', market_data.get('timestamp'))
        if ts is not None:
            if self.latest_market_time is None or ts > self.latest_market_time:
                self.latest_market_time = ts
                
        # In Backtest mode, we use the configured price source (Open or Close)
        # In Live/Socket mode (ticks), we use 'p' (LTP)
        is_candle = any(k in market_data for k in ['c', 'close', 'o', 'open'])
        is_spot = (inst_id == 26000) or getattr(self, 'spot_instrument_id', 26000) == inst_id

        if self.is_backtest and is_candle:
            if self.price_source == "open":
                price = market_data.get('o', market_data.get('open'))
            else:
                price = market_data.get('c', market_data.get('close'))
        else:
            price = market_data.get('c', market_data.get('close', market_data.get('p')))
        
        if price is None:
            return

        # 0. Tick Normalization: If this is a raw tick (no OHLC), populate OHLC for downstream compatibility
        if 'p' in market_data and any(k not in market_data for k in ['o', 'h', 'l', 'c']):
            market_data.update({
                'o': price,
                'h': price,
                'l': price,
                'c': price
            })
        
        if inst_id:
            self.latest_tick_prices[int(inst_id)] = price

        is_spot = (inst_id == 26000) or getattr(self, 'spot_instrument_id', 26000) == inst_id
        
        # 1.a Drift Check (Only when we get Spot)
        if is_spot and ts:
            self._check_and_update_monitored_instruments(price, ts)

        # 2. Update Position Manager immediately for Stop Loss / Target Checks
        if self.position_manager.current_position:
            # Only update position if the tick belongs to the active traded instrument
            if str(inst_id) == self.position_manager.current_position.symbol:
                nifty_price = self.latest_tick_prices.get(26000)
                
                mapped = self._get_mapped_indicators()
                # In Backtest Mode, if we receive a 1-minute Candle, we explode it into 
                # 4 virtual ticks (O, H, L, C) to match Socket/Live granularity.
                if self.is_backtest and is_candle:
                    o = market_data.get('o', market_data.get('open', price))
                    h = market_data.get('h', market_data.get('high', price))
                    l = market_data.get('l', market_data.get('low', price))
                    c = price
                    
                    base_t = ts
                    start_t = base_t - 59

                    # Sequence: Open (0s) -> High (15s) -> Low (30s) -> Close (59s)
                    # (Matching SocketDataProvider's fidelity)
                    for p_val, t_val in [(o, start_t), (h, start_t+15), (l, start_t+30), (c, base_t)]:
                        if not self.position_manager.current_position:
                            break
                        v_tick = {'i': inst_id, 'p': p_val, 't': t_val}
                        self.position_manager.update_tick(v_tick, nifty_price=nifty_price, indicators=mapped)
                else:
                    self.position_manager.update_tick(market_data, nifty_price=nifty_price, indicators=mapped)

        # 3. Route to Resamplers based on Category
        category = None
        # Check if it's one of the primary monitored instruments (Spot, current ATM CE/PE)
        for cat, active_id in self.active_instruments.items():
            if active_id == int(inst_id):
                category = cat
                break
        
        # If not primary but currently being traded, it's still CE or PE
        if not category and self.position_manager.current_position:
            if str(inst_id) == self.position_manager.current_position.symbol:
                # It's a traded instrument that drifted. We still need to resample it!
                # We can heuristic the category based on intent (LONG=CE, SHORT=PE for options)
                if self.trade_instrument_type == "OPTIONS":
                    category = "CE" if self.position_manager.current_position.intent == MarketIntentType.LONG else "PE"
                else:
                    category = "SPOT" # Fallback for futures/cash

        if not category:
            return # Data for instrument not actively monitored
            
        # Ensure resampler exists (especially for drifted/traded instruments)
        self._ensure_resampler(int(inst_id), InstrumentCategoryType(category))

        resampler = self.resamplers.get(int(inst_id))
        if resampler:
            resampler.add_candle(market_data)

    def _on_resampled_candle_closed(self, candle: Dict, category: InstrumentCategoryType):
        """
        Callback triggered when a specific Category Resampler finalizes a candle.
        For Triple-Lock, we evaluate the unified state ONLY when the SPOT candle closes.
        """
        ts = candle.get('t', candle.get('timestamp'))

        # Update indicators (Python strategy receives them in on_resampled_candle_closed)
        inst_id = candle.get('instrument_id', candle.get('i'))
        self.indicator_calculator.add_candle(candle, instrument_category=category, instrument_id=inst_id)
        
        # Refresh the flat state for logging and heartbeats
        # We pull the fully mapped (active/inverse) indicators so logs match strategy view
        self.latest_indicators_state = self._get_mapped_indicators()
        
        # 0. Synchronize other resamplers (CE/PE/Traded) to current SPOT timestamp
        # This ensures that if Option ticks arrived slightly late, they are still 
        # processed into the current or previous candle before we run indicators.
        for r_id, r in self.resamplers.items():
            if r_id != 26000: # Not Spot
                # If resampler is lagging behind current SPOT timestamp, flush it
                if r.last_period_start is not None and r.last_period_start < ts:
                    r.add_candle({'t': ts, 'is_flush': True}) # Dummy tick to force close if needed
                    # Note: add_candle logic handles period jumps internally

        if self.log_heartbeat and not self.is_warming_up and category == InstrumentCategoryType.SPOT:
            ind_str = ", ".join([f"{k}: {v:.2f}" if isinstance(v, (int, float)) else f"{k}: {v}" for k, v in self.latest_indicators_state.items()])
            
            # Format candle start and end times for clarity
            if ts:
                start_str = DateUtils.market_timestamp_to_datetime(ts).strftime('%H:%M:%S')
                end_str = DateUtils.market_timestamp_to_datetime(ts + self.global_timeframe).strftime('%H:%M:%S')
                time_display = f"{start_str} - {end_str}"
            else:
                time_display = "N/A"
                
            logger.info(TradeFormatter.format_heartbeat(time_display, category.value, self.latest_indicators_state))

        # ONLY execute strategy decision synchronously when the SPOT candle acts as the anchor
        if category != InstrumentCategoryType.SPOT:
            return
        # Determine current intent for strategy evaluation
        current_intent_str = None
        intent_enum = None
        if self.position_manager.current_position:
            current_intent_str = "LONG" if self.position_manager.current_position.intent == MarketIntentType.LONG else "SHORT"
            intent_enum = self.position_manager.current_position.intent

        # Execute Strategy (Python script)
        mapped_indicators = self._get_mapped_indicators()
        signal, reason, confidence = self.strategy.on_resampled_candle_closed(
            candle, mapped_indicators, current_position_intent=intent_enum
        )
        
        if signal != SignalType.NEUTRAL:
            if self.is_warming_up:
                # No signals/trades during warmup!
                return
            
            # 0. Stale SignalType Protection (Max 30 minutes)
            # This prevents the bot from acting on "catch-up" data using the latest known market time
            if ts and self.latest_market_time and (self.latest_market_time - ts) > 1800:
                 logger.warning(f"⚠️ SignalType ignored: Triggered by stale data from {ts} (>{1800}s behind latest market time {self.latest_market_time})")
                 return

            # Use period end for signal/entry time (signal is finalized at end of candle)
            signal_ts = ts + self.global_timeframe
            spot_price = candle.get('c', candle.get('close'))

            # 1. Handle SignalTypes for existing positions
            if self.position_manager.current_position:
                if signal == SignalType.EXIT:
                    # Fallback to market time if signal_ts is missing
                    ts_dt = (DateUtils.market_timestamp_to_datetime(signal_ts) 
                             if isinstance(signal_ts, (int, float)) 
                             else DateUtils.market_timestamp_to_datetime(self.latest_market_time) 
                             if self.latest_market_time 
                             else datetime.now(DateUtils.MARKET_TZ))
                    ts_str = ts_dt.strftime('%d-%b %H:%M')
                    logger.info(TradeFormatter.format_signal("EXIT", reason, ts_str, self.global_timeframe, self.latest_indicators_state))
                    
                    pos = self.position_manager.current_position
                    opt_price = self._get_fallback_option_price(int(pos.symbol), signal_ts)
                    if not opt_price:
                        logger.error(f"Cannot exit {pos.symbol}, ALL fallbacks failed. Using entry price as last resort.")
                        opt_price = pos.entry_price if pos.entry_price else spot_price # Extremely rare
                    self.position_manager._close_position(opt_price, ts_dt, "STRATEGY_EXIT", reason_desc=reason, nifty_price=spot_price)
                    return
            
                intent = MarketIntentType.LONG if signal == SignalType.LONG else MarketIntentType.SHORT
                
                # If current intent matches signal, do nothing (already in position)
                if self.position_manager.current_position.intent == intent:
                    return
                
                # SignalType changed (flip) - log it and handle closure
                ts_dt = (DateUtils.market_timestamp_to_datetime(signal_ts) 
                         if isinstance(signal_ts, (int, float)) 
                         else DateUtils.market_timestamp_to_datetime(self.latest_market_time) 
                         if self.latest_market_time 
                         else datetime.now(DateUtils.MARKET_TZ))
                ts_str = ts_dt.strftime('%d-%b %H:%M')
                logger.info(TradeFormatter.format_signal(signal.name, reason, ts_str, self.global_timeframe, self.latest_indicators_state))
                
                pos = self.position_manager.current_position
                opt_price = self._get_fallback_option_price(int(pos.symbol), signal_ts)
                if not opt_price: 
                    logger.error(f"Cannot exit {pos.symbol}, ALL fallbacks failed. Using entry price as last resort.")
                    opt_price = pos.entry_price if pos.entry_price else spot_price
                
                self.position_manager._close_position(opt_price, ts_dt, "SIGNAL_FLIP", reason_desc=reason, nifty_price=spot_price)
            else:
                if signal == SignalType.EXIT:
                    return # Ignore lone exit signals when not in position
                
                intent = MarketIntentType.LONG if signal == SignalType.LONG else MarketIntentType.SHORT
                
                # No existing position - log new entry signal
                ts_dt = (DateUtils.market_timestamp_to_datetime(signal_ts) 
                         if isinstance(signal_ts, (int, float)) 
                         else DateUtils.market_timestamp_to_datetime(self.latest_market_time) 
                         if self.latest_market_time 
                         else datetime.now(DateUtils.MARKET_TZ))
                ts_str = ts_dt.strftime('%d-%b %H:%M')
                logger.info(TradeFormatter.format_signal(signal.name, reason, ts_str, self.global_timeframe, self.latest_indicators_state))
                
            # 2. Handle Entries
            target_symbol = "26000" # default spot
            target_display_symbol = "NIFTY SPOT"
            entry_price = spot_price
            
            if self.trade_instrument_type == "OPTIONS":
                t_cat = "CE" if intent == MarketIntentType.LONG else "PE"
                resolved_id = self.active_instruments.get(t_cat)
                resolved_desc = self.active_instruments.get(f"{t_cat}_DESC")
                
                # We also need the contract description if possible for the Payload.
                # In Triple-Lock, the contract is already resolved and tracked during drift!
                if not resolved_id:
                    logger.error(f"Failed to find active {t_cat} instrument from drift tracker")
                    return
                    
                target_symbol = str(resolved_id)
                target_display_symbol = resolved_desc or f"NIFTY {t_cat} ({target_symbol})" # Use resolved description
                
                # Entry Price Cache check
                entry_price = self._get_fallback_option_price(int(resolved_id), signal_ts, is_entry=True)
                if not entry_price:
                    logger.warning(f"No active tick feed OR DB fallback for option {target_symbol}. Skipping entry.")
                    return
            elif self.trade_instrument_type == "FUTURES":
                target_display_symbol = "NIFTY FUT" # Example, could be more dynamic
            
            # Use on_signal for centralized entry/exit logic
            payload = {
                'signal': intent,
                'confidence': confidence,
                'price': entry_price,
                'symbol': target_symbol,
                'display_symbol': target_display_symbol,
                'timestamp': signal_ts,
                'reason': signal.name,
                'reason_desc': reason,
                'nifty_price': spot_price
            }
            
            # Recalculate quantity based on exact entry price and budget
            from packages.config import settings
            lot_size = settings.NIFTY_LOT_SIZE
            
            # Decide which capital to use (Total Capital vs Initial Budget)
            total_realized_pnl = sum([t.pnl for t in self.position_manager.trades_history])
            current_capital = self.initial_budget + total_realized_pnl
            
            # If compounding, we use current_capital. If fixed, we use initial_budget.
            capital_to_use = current_capital if self.invest_mode == "compound" else self.initial_budget
            
            # Calculate exactly how many lots we can afford
            # capital / (price * lot_size)
            if entry_price > 0:
                new_qty = int(capital_to_use // (entry_price * lot_size))
                if new_qty > 0:
                    self.position_manager.quantity = new_qty
                    if self.invest_mode == "compound":
                        logger.debug(f"📈 [COMPOUND] Recalculated Qty: {new_qty} based on Capital: ₹{current_capital:,.2f} and Price: {entry_price}")
                    else:
                        logger.debug(f"💰 [FIXED] Calculated Qty: {new_qty} based on Budget: ₹{self.initial_budget:,.2f} and Price: {entry_price}")
                else:
                    logger.warning(f"⚠️ Insufficient budget (₹{capital_to_use:,.2f}) for entry at {entry_price}. Qty remains {self.position_manager.quantity}")

            self.position_manager.on_signal(payload)
            
            if self.on_signal:
                payload.update({
                    'indicators': self.latest_indicators_state.copy(),
                    'is_buy': signal == SignalType.LONG
                })
                self.on_signal(payload)

    def handle_eod_settlement(self, timestamp: float):
        """
        Forces closure of any open positions at the end of the trading day.
        
        Args:
            timestamp (float): The UNIX timestamp for the settlement (typically 15:30).
        """
        if not self.position_manager.current_position:
            return

        pos = self.position_manager.current_position
        # Use price from fund_manager's tick cache for the specific instrument
        eod_price = self.latest_tick_prices.get(int(pos.symbol))
        
        # If for some reason tick price isn't in cache, use the last known price
        if not eod_price:
            eod_price = pos.current_price
        
        eod_time = DateUtils.market_timestamp_to_datetime(timestamp)
        nifty_price = self.latest_tick_prices.get(26000)
        
        logger.info(TradeFormatter.format_eod(pos.symbol, eod_price))
        desc = f"End of Day Settlement at {eod_price:.2f}"
        self.position_manager._close_position(eod_price, eod_time, "EOD", reason_desc=desc, nifty_price=nifty_price)

    def _get_mapped_indicators(self) -> Dict[str, float]:
        """
        Builds a unified indicator dictionary for the strategy.
        Explicitly pulls indicators for the current primary instruments (Spot, ATM CE, ATM PE)
        and the currently traded instrument to avoid collision and ensure correctness.
        """
        mapped = {}
        
        # 1. Pull Spot Indicators (Always present)
        mapped.update(self.indicator_calculator.extract_indicators(26000, InstrumentCategoryType.SPOT))
        
        # 2. Pull Current Monitored Contract Indicators
        ce_id = self.active_instruments.get("CE")
        pe_id = self.active_instruments.get("PE")
        
        ce_inds = self.indicator_calculator.extract_indicators(ce_id, InstrumentCategoryType.CE) if ce_id else {}
        pe_inds = self.indicator_calculator.extract_indicators(pe_id, InstrumentCategoryType.PE) if pe_id else {}
        
        mapped.update(ce_inds)
        mapped.update(pe_inds)
            
        # 3. Handle Active/Inverse Mapping
        # If in a position, map CE/PE to Active/Inverse based on ACTUAL trade direction
        # If NOT in a position, map CE -> Active and PE -> Inverse as a default for entry checks
        pos = self.position_manager.current_position
        if pos:
            is_long = pos.intent == MarketIntentType.LONG
            # For logging/strategy context, use indicators from the TRADED instrument for 'active-'
            traded_id = int(pos.symbol)
            t_cat = InstrumentCategoryType.CE if is_long else InstrumentCategoryType.PE
            traded_inds = self.indicator_calculator.extract_indicators(traded_id, t_cat)
            
            # Use ATM for 'inverse-' side
            inv_inds = pe_inds if is_long else ce_inds
            
            self._apply_active_inverse_mapping(mapped, traded_inds, inv_inds, is_long)
        else:
            # Entry Mode: Map ATM CE -> Active, ATM PE -> Inverse
            self._apply_active_inverse_mapping(mapped, ce_inds, pe_inds, True)
        
        return mapped

    def _apply_active_inverse_mapping(self, target: Dict, active_source: Dict, inverse_source: Dict, is_long: bool):
        """Helper to apply active/inverse prefixes to the target dict."""
        active_prefix = "ce-" if is_long else "pe-"
        inverse_prefix = "pe-" if is_long else "ce-"
        
        for k, v in active_source.items():
            if k.startswith(active_prefix):
                target[k.replace(active_prefix, "active-", 1)] = v
        
        for k, v in inverse_source.items():
            if k.startswith(inverse_prefix):
                target[k.replace(inverse_prefix, "inverse-", 1)] = v
