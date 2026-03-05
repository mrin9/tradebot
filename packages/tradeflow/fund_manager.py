from typing import Dict, Callable, Any, List
from packages.utils.date_utils import DateUtils
from datetime import datetime
import logging
from packages.tradeflow.indicator_calculator import IndicatorCalculator
from packages.tradeflow.rule_strategy import RuleStrategy
from packages.tradeflow.ml_strategy import MLStrategy
from packages.tradeflow.python_strategy_loader import PythonStrategy
from packages.utils.log_utils import setup_logger
from packages.tradeflow.types import SignalType, MarketIntentType, InstrumentKindType, InstrumentCategoryType

from packages.tradeflow.position_manager import PositionManager
from packages.tradeflow.order_manager import PaperTradingOrderManager
from packages.tradeflow.candle_resampler import CandleResampler
from packages.utils.mongo import MongoRepository

logger = setup_logger(__name__)

class FundManager:
    """
    The Orchestrator (Brain) for Multi-Timeframe Analysis (MTFA).
    Coordinates data flow between Market Data, multiple Timeframe Resamplers, Indicators, and Strategy Logic.
    """
    def __init__(self, strategy_config: Dict[str, Any], position_config: Dict[str, Any] | None = None, log_heartbeat: bool = False, is_backtest: bool = False):
        """
        Args:
            strategy_config (Dict): The full JSON-DSL strategy rule document from the database.
            position_config (Dict, optional): Configuration for PositionManager (quantity, stop_loss, target).
            log_heartbeat (bool): If True, logs indicator state on every candle close (useful for live).
        """
        from packages.config import settings
        self.config = strategy_config
        self.indicators_config = self.config.get('indicators', [])
        self.log_heartbeat = log_heartbeat
        self.is_backtest = is_backtest
        self.pos_config = position_config or {}
        
        # 1. Initialize Indicator Calculator (managing multiple timeframes)
        self.indicator_calculator = IndicatorCalculator(indicators_config=self.indicators_config)
        
        # 2. Initialize Strategy Logic (Hybrid: Rule or ML)
        self.strategy_mode = self.pos_config.get("strategy_mode", "rule")
        
        if self.strategy_mode == "ml":
            self.strategy = MLStrategy(
                model_path=self.pos_config.get("ml_model_path"),
                confidence_threshold=self.pos_config.get("ml_confidence", 0.65)
            )
            logger.info(f"🤖 Strategy Mode: ML (self-contained features)")
        elif self.strategy_mode == "python_code":
            self.strategy = PythonStrategy(script_path=self.pos_config.get("python_strategy_path"))
            logger.info(f"🐍 Strategy Mode: Python Code ({self.pos_config.get('python_strategy_path')})")
        else:
            self.strategy = RuleStrategy(strategy_config=self.config)
            logger.info(f"📏 Strategy Mode: Rule (RuleStrategy)")
        
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
        self.use_break_even = self.pos_config.get('use_break_even', True)
        self.record_papertrade_db = self.pos_config.get('record_papertrade_db', True)
        
        self.trade_instrument_type = self.pos_config.get("instrument_type", "CASH").upper() # CASH, OPTIONS, FUTURES
        self.trade_option_type = self.pos_config.get("option_type", "ATM").upper() # ATM, ITM, OTM
        
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
            price_source=self.pos_config.get("price_source", settings.BACKTEST_PRICE_SOURCE)
        )
        self.order_manager = PaperTradingOrderManager()
        self.position_manager.set_order_manager(self.order_manager)
        
        self.price_source = self.pos_config.get("price_source", settings.BACKTEST_PRICE_SOURCE).lower() # "open" or "close"
        
        self.on_signal: Callable[[Dict], None] | None = None
        self.db = MongoRepository.get_db()
        self.latest_tick_prices: Dict[int, float] = {}
        
        # 4. Global Timeframe and Multi-Instrument Streams
        from packages.config import settings
        self.global_timeframe = self.config.get('timeframe', settings.DEFAULT_TIMEFRAME)
        
        # Track active instruments being monitored {category: instrument_id}
        self.active_instruments: Dict[str, int] = {"SPOT": 26000}
        self.selection_spot_price: float | None = None
        
        # Initialize Resamplers per category
        self.resamplers: Dict[str, CandleResampler] = {}
        for category in [InstrumentCategoryType.SPOT, InstrumentCategoryType.CE, InstrumentCategoryType.PE]:
            cat_val = category.value
            self.resamplers[cat_val] = CandleResampler(
                instrument_id=0, # Will be set dynamically during data ingestion
                interval_seconds=self.global_timeframe,
                on_candle_closed=lambda c, cat=category: self._on_resampled_candle_closed(c, cat)
            )
            
        # 5. Global cache 
        self.latest_indicators_state: Dict[str, float] = {}
        self.is_warming_up = False
        
    def _resolve_option_contract(self, strike: float, is_ce: bool, current_ts: float) -> tuple[int | None, str | None]:
        """Resolves the nearest expiry option contract ID and description for NIFTY from DB given a strike."""
        # Convert timestamp to ISO string for comparison with contractExpiration
        dt_iso = datetime.fromtimestamp(current_ts).strftime("%Y-%m-%dT%H:%M:%S")
        
        opt_type_num = 3 if is_ce else 4 # CE=3, PE=4 in XTS
        
        # Simplification: Sort by contractExpiration and get the first one (nearest expiry)
        from packages.config import settings
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
        atm_strike = round(current_spot / 50) * 50
        
        needs_update = False
        if self.selection_spot_price is None:
            needs_update = True
        elif abs(current_spot - self.selection_spot_price) > 25:
            # Price drifted significantly, recalculate ATM and re-map
            logger.debug(f"🔄 Spot drifted to {current_spot} (prev {self.selection_spot_price}). Recalculating Active Options.")
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
                    self.resamplers["CE"].current_candle = None # Reset partial candle on switch
                    if self.is_backtest:
                        self._warmup_instrument("CE", new_ce_id, current_ts)
            
            # Resolve PE
            pe_id, pe_desc = self._resolve_option_contract(atm_strike, False, current_ts)
            if pe_id:
                new_pe_id = int(pe_id)
                if self.active_instruments.get("PE") != new_pe_id:
                    self.active_instruments["PE"] = new_pe_id
                    self.active_instruments["PE_DESC"] = pe_desc
                    self.resamplers["PE"].current_candle = None # Reset partial candle on switch
                    if self.is_backtest:
                        self._warmup_instrument("PE", new_pe_id, current_ts)

    def _warmup_instrument(self, category: str, instrument_id: int, current_ts: float):
        """
        Fetches historical 1m candles for the new instrument and warms up the resampler/indicators.
        """
        logger.debug(f"🔥 Warming up {category} instrument: {instrument_id} at {DateUtils.from_timestamp(current_ts)}")
        
        from packages.config import settings
        # Fetch last 100 1-minute candles before current_ts
        # Use $lt current_ts to avoid "look-ahead" leakage and ensure we get 
        # previous day's data if market just opened at 09:15.
        history = list(self.db[settings.OPTIONS_CANDLE_COLLECTION].find(
            {"i": instrument_id, "t": {"$lte": current_ts}}
        ).sort("t", -1).limit(100))
        
        if not history:
            logger.warning(f"⚠️ No history found for {category} ({instrument_id}) warmup.")
            return
            
        # Sort chronologically
        history.reverse()
        
        resampler = self.resamplers.get(category)
        if resampler:
            # Temporarily disable the normal callback to avoid triggering strategy logic during warmup 
            # (though resampled candles are pushed to indicator_calculator via the callback)
            # Actually, the callback _on_resampled_candle_closed is safe because it only 
            # updates indicators if category != "SPOT".
            saved_on_closed = resampler.on_candle_closed
            
            # We want indicators updated during warmup, so we keep the callback.
            # But we must ensure it doesn't trigger strategy evaluation.
            # Luckily, _on_resampled_candle_closed already check category != "SPOT"
            
            resampler.instrument_id = int(instrument_id)
            for candle in history:
                resampler.add_candle(candle)
            
            logger.debug(f"✅ Warmup complete for {category} ({instrument_id}) with {len(history)} candles.")

    def _get_fallback_option_price(self, symbol_id: int, current_ts: float | None, is_entry: bool = False) -> float | None:
        """
        Attempts to find a reliable price for an option when the live tick is missing.
        Priority:
        1. Tick Cache
        2. DB Fallback (nearest candle before or at current_ts)
        3. Position Manager's current_price (only for exits)
        """
        # 1. Tick Cache
        price = self.latest_tick_prices.get(symbol_id)
        if price:
            return price
            
        # 2. DB Fallback
        logger.info(f"🔍 No live tick for {symbol_id}. Checking DB fallback...")
        query = {"i": symbol_id}
        if current_ts:
            query["t"] = {"$lte": current_ts}
            
        fallback = self.db['options_candle'].find_one(query, sort=[("t", -1)])
        if fallback:
            price = fallback.get('c', fallback.get('p'))
            if price is not None:
                logger.info(f"✅ Found DB fallback price for {symbol_id}: {price}")
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
        ts = market_data.get('t', market_data.get('timestamp'))
        if is_spot and ts:
            self._check_and_update_monitored_instruments(price, ts)

        # 2. Update Position Manager immediately for Stop Loss / Target Checks
        if self.position_manager.current_position:
            # Only update position if the tick belongs to the active traded instrument
            if str(inst_id) == self.position_manager.current_position.symbol:
                nifty_price = self.latest_tick_prices.get(26000)
                
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
                        self.position_manager.update_tick(v_tick, nifty_price=nifty_price)
                else:
                    self.position_manager.update_tick(market_data, nifty_price=nifty_price)

        # 3. Route to Resamplers based on Category
        category = None
        for cat, active_id in self.active_instruments.items():
            if active_id == int(inst_id):
                category = cat
                break
                
        if not category:
            return # Data for instrument not actively monitored

        resampler = self.resamplers.get(category)
        if resampler:
            resampler.instrument_id = int(inst_id)
            resampler.add_candle(market_data)

    def _on_resampled_candle_closed(self, candle: Dict, category: InstrumentCategoryType):
        """
        Callback triggered when a specific Category Resampler finalizes a candle.
        For Triple-Lock, we evaluate the unified state ONLY when the SPOT candle closes.
        """
        ts = candle.get('t', candle.get('timestamp'))

        # Both MLStrategy and RuleStrategy now implement on_resampled_candle_closed
        # Update indicators for all strategy modes
        inst_id = candle.get('instrument_id', candle.get('i'))
        new_indicators = self.indicator_calculator.add_candle(candle, instrument_category=category, instrument_id=inst_id)
        if new_indicators:
            self.latest_indicators_state.update(new_indicators)
        
        if self.log_heartbeat and new_indicators:
            ind_str = ", ".join([f"{k}: {v:.2f}" if isinstance(v, (int, float)) else f"{k}: {v}" for k, v in new_indicators.items()])
            
            # Format candle start and end times for clarity
            if ts:
                start_str = DateUtils.from_timestamp(ts).strftime('%H:%M:%S')
                end_str = DateUtils.from_timestamp(ts + self.global_timeframe).strftime('%H:%M:%S')
                time_display = f"{start_str} - {end_str}"
            else:
                time_display = "N/A"
                
            logger.info(f"💚 HEARTBEAT [Candle: {time_display}] 💚| Category: {category} | Indicators: {ind_str}")

        # ONLY execute strategy decision synchronously when the SPOT candle acts as the anchor
        if category != InstrumentCategoryType.SPOT:
            return
            
        # 0. Synchronize other resamplers (CE/PE) to current SPOT timestamp
        # This ensures that if Option ticks arrived slightly late, they are still 
        # processed into the current or previous candle before we run indicators.
        for cat_val, r in self.resamplers.items():
            if cat_val != InstrumentCategoryType.SPOT.value:
                # If resampler is lagging behind current SPOT timestamp, flush it
                if r.last_period_start is not None and r.last_period_start < ts:
                    r.add_candle({'t': ts, 'is_flush': True}) # Dummy tick to force close if needed
                    # Note: add_candle logic handles period jumps internally

            
        # Pass the current position intent to explicitly evaluate Exit Rules if configured
        # Determine current intent for strategy evaluation
        current_intent_str = None
        intent_enum = None
        if self.position_manager.current_position:
            current_intent_str = "LONG" if self.position_manager.current_position.intent == MarketIntentType.LONG else "SHORT"
            intent_enum = self.position_manager.current_position.intent

        # Execute Strategy
        if self.strategy_mode == "ml":
            signal, reason, confidence = self.strategy.on_resampled_candle_closed(
                candle, self.latest_indicators_state, current_position_intent=intent_enum
            )
        elif self.strategy_mode == "python_code":
            mapped_indicators = self.latest_indicators_state.copy()
            # Default ACTIVE/INVERSE mapping based on current position
            # This is a helper for strategies that want to be instrument-agnostic
            effective_intent_str = current_intent_str or "LONG" 
            if effective_intent_str == "LONG":
                for k, v in self.latest_indicators_state.items():
                    if k.startswith("CE_"): mapped_indicators[k.replace("CE_", "ACTIVE_", 1)] = v
                    if k.startswith("PE_"): mapped_indicators[k.replace("PE_", "INVERSE_", 1)] = v
            elif effective_intent_str == "SHORT":
                for k, v in self.latest_indicators_state.items():
                    if k.startswith("PE_"): mapped_indicators[k.replace("PE_", "ACTIVE_", 1)] = v
                    if k.startswith("CE_"): mapped_indicators[k.replace("CE_", "INVERSE_", 1)] = v
                    
            signal, reason, confidence = self.strategy.on_resampled_candle_closed(
                candle, mapped_indicators, current_position_intent=intent_enum
            )
        else:
            signal, reason, confidence = self.strategy.on_resampled_candle_closed(
                candle, self.latest_indicators_state, current_position_intent=intent_enum
            )
        
        if signal != SignalType.NEUTRAL:
            if self.is_warming_up:
                # No signals/trades during warmup!
                return
            
            # 0. Stale SignalType Protection (Max 30 minutes)
            # This prevents the bot from acting on "catch-up" data right after startup
            import time
            if not self.is_backtest and ts and time.time() - ts > 1800:
                 logger.warning(f"⚠️ SignalType ignored: Triggered by stale data from {ts} (>{1800}s old)")
                 return

            # SignalType Correction: Use period end for backtest logging & entry time
            signal_ts = ts + self.global_timeframe if self.is_backtest else ts
            spot_price = candle.get('c', candle.get('close'))

            # 1. Handle SignalTypes for existing positions
            if self.position_manager.current_position:
                if signal == SignalType.EXIT:
                    ts_dt = DateUtils.from_timestamp(signal_ts) if isinstance(signal_ts, (int, float)) else datetime.now()
                    ts_str = ts_dt.strftime('%d-%b %H:%M')
                    formatted_ind = {k: round(v, 2) if isinstance(v, (int, float)) else v for k, v in self.latest_indicators_state.items()}
                    logger.debug(f"SignalType: EXIT ({reason}) | Time: {ts_str} | BaseTimeframe: {self.global_timeframe}s | State: {formatted_ind}")
                    
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
                ts_dt = DateUtils.from_timestamp(signal_ts) if isinstance(signal_ts, (int, float)) else datetime.now()
                ts_str = ts_dt.strftime('%d-%b %H:%M')
                formatted_ind = {k: round(v, 2) if isinstance(v, (int, float)) else v for k, v in self.latest_indicators_state.items()}
                logger.info(f"SignalType: {signal.name} ({reason}) | Time: {ts_str} | BaseTimeframe: {self.global_timeframe}s | State: {formatted_ind}")
                
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
                ts_dt = DateUtils.from_timestamp(signal_ts) if isinstance(signal_ts, (int, float)) else datetime.now()
                ts_str = ts_dt.strftime('%d-%b %H:%M')
                formatted_ind = {k: round(v, 2) if isinstance(v, (int, float)) else v for k, v in self.latest_indicators_state.items()}
                logger.debug(f"SignalType: {signal.name} ({reason}) | Time: {ts_str} | BaseTimeframe: {self.global_timeframe}s | State: {formatted_ind}")
                
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
        
        eod_time = datetime.fromtimestamp(timestamp)
        nifty_price = self.latest_tick_prices.get(26000)
        
        logger.info(f"🌙 FundManager: EOD Settlement for {pos.symbol} at {eod_price}")
        desc = f"End of Day Settlement at {eod_price:.2f}"
        self.position_manager._close_position(eod_price, eod_time, "EOD", reason_desc=desc, nifty_price=nifty_price)
