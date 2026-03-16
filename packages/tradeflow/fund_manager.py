import time
from collections.abc import Callable
from datetime import datetime
from typing import Any

from packages.services.contract_discovery import ContractDiscoveryService
from packages.services.market_history import MarketHistoryService
from packages.services.trade_config_service import TradeConfigService
from packages.tradeflow.candle_resampler import CandleResampler
from packages.tradeflow.drift_manager import DriftManager
from packages.tradeflow.indicator_calculator import IndicatorCalculator
from packages.tradeflow.order_manager import PaperTradingOrderManager
from packages.tradeflow.position_manager import PositionManager
from concurrent.futures import ThreadPoolExecutor
from packages.tradeflow.python_strategy_loader import PythonStrategy
from packages.tradeflow.types import InstrumentCategoryType, InstrumentKindType, MarketIntentType, SignalType
from packages.utils.date_utils import DateUtils
from packages.utils.log_utils import setup_logger
from packages.utils.trade_formatter import TradeFormatter

logger = setup_logger(__name__)


class FundManager:
    """
    The Orchestrator (Brain) for Multi-Timeframe Analysis (MTFA).
    Coordinates data flow between Market Data, Resamplers, Indicators, and Strategy Logic.
    """

    def __init__(
        self,
        strategy_config: dict[str, Any],
        position_config: dict[str, Any] | None = None,
        log_heartbeat: bool = False,
        is_backtest: bool = False,
        config_service: TradeConfigService | None = None,
        discovery_service: ContractDiscoveryService | None = None,
        history_service: MarketHistoryService | None = None,
        fetch_ohlc_fn: Callable | None = None,  # Legacy injection
        fetch_quote_fn: Callable | None = None,  # Legacy injection
        drift_manager: DriftManager | None = None,
    ):
        # 1. Initialize Services
        self.config_service = config_service or TradeConfigService()
        self.discovery_service = discovery_service or ContractDiscoveryService()
        self.history_service = history_service or MarketHistoryService(fetch_ohlc_api_fn=fetch_ohlc_fn)

        # 2. Normalize and Build Configs
        self.config = self.config_service.normalize_strategy_config(strategy_config)
        self.position_config = self.config_service.build_position_config(**(position_config or {}))

        self.indicators_config = self.config.get("indicators", [])
        self.log_heartbeat = log_heartbeat
        self.is_backtest = is_backtest

        self.indicator_calculator = IndicatorCalculator(indicators_config=self.indicators_config)

        # 3. Load Strategy
        python_path = self.position_config.get("python_strategy_path") or self.config.get("pythonStrategyPath")
        if not python_path:
            raise ValueError("No 'python_strategy_path' found in position_config or strategy_config.")

        self.strategy = PythonStrategy(script_path=python_path)
        logger.info(f"🐍 Strategy: {python_path}")

        # 4. Core Parameters
        self.initial_budget = self.position_config["budget"]
        self.invest_mode = self.position_config["invest_mode"]
        self.sl_points = self.position_config["sl_points"]
        self.target_points = self.position_config["target_points"]
        self.tsl_points = self.position_config["tsl_points"]
        self.tsl_id = self.position_config.get("tsl_id")
        self.use_be = self.position_config["use_be"]

        self.trade_instrument_type = self.position_config["instrument_type"]
        self.strike_selection = self.position_config["strike_selection"]
        self.price_source = self.position_config["price_source"]
        self.record_papertrade_db = self.position_config.get("record_papertrade_db", False)

        enum_map = {
            "CASH": InstrumentKindType.CASH,
            "OPTIONS": InstrumentKindType.OPTIONS,
            "FUTURES": InstrumentKindType.FUTURES,
        }
        instr_enum = enum_map.get(self.trade_instrument_type, InstrumentKindType.CASH)

        self.position_manager = PositionManager(
            symbol=self.position_config["symbol"],
            quantity=self.position_config.get("quantity", 50),
            sl_points=self.sl_points,
            target_points=self.target_points,
            instrument_type=instr_enum,
            tsl_points=self.tsl_points,
            use_be=self.use_be,
            pyramid_steps=self.position_config["pyramid_steps"],
            pyramid_confirm_pts=self.position_config["pyramid_confirm_pts"],
            price_source=self.position_config["price_source"],
            tsl_id=self.tsl_id,
        )
        self.order_manager = PaperTradingOrderManager()
        self.position_manager.set_order_manager(self.order_manager)

        self.on_signal: Callable[[dict], None] | None = None
        self.latest_tick_prices: dict[int, float] = {}

        self.global_timeframe = self.config["timeframe_seconds"]

        # Track active instruments being monitored {category: instrument_id}
        self.drift_manager = drift_manager or DriftManager(
            self.discovery_service, instrument_type=self.trade_instrument_type
        )
        self.active_instruments = self.drift_manager.active_instruments
        self.drift_manager.on_instruments_changed = self._on_drift_instruments_changed

        # Initialize Resamplers per instrument_id
        self.resamplers: dict[int, CandleResampler] = {}
        self._ensure_resampler(26000, InstrumentCategoryType.SPOT)

        # Global cache
        self.latest_indicators_state: dict[str, float] = {}
        self._cached_mapped_indicators: dict[str, float] = {}
        self._needs_mapping_update = True

        self.is_warming_up = False
        self.latest_market_time: float | None = None

        # Position Events also invalidate the mapping cache (due to direction-based Active/Inverse mapping)
        def invalidate_mapping_cache(event):
            self._needs_mapping_update = True

        self.position_manager.on_trade_event = invalidate_mapping_cache

    def _ensure_resampler(self, instrument_id: int, category: InstrumentCategoryType) -> None:
        """Ensures a resampler exists for the given instrument ID."""
        if instrument_id not in self.resamplers:
            self.resamplers[instrument_id] = CandleResampler(
                instrument_id=instrument_id,
                interval_seconds=self.global_timeframe,
                on_candle_closed=lambda c, cat=category: self._on_resampled_candle_closed(c, cat),
            )
            logger.debug(f"🛠️ Created resampler for {category.value} ({instrument_id})")

    def _on_drift_instruments_changed(self, changed_info: dict[str, Any]) -> None:
        """
        Callback triggered when DriftManager resolves new instruments.
        Handles resampler management and initial warmup.
        """
        if self.is_warming_up:
            return

        self._needs_mapping_update = True  # Invalidate cache

        current_ts = changed_info.get("current_ts")
        instruments = changed_info.get("instruments", {})

        new_instruments_to_warmup = []
        for cat, info in instruments.items():
            if info["is_new"]:
                new_instruments_to_warmup.append((cat, info["id"], info["desc"]))

        if not new_instruments_to_warmup:
            return

        # 1. Sequential Setup (Thread-Unsafe Parts)
        warmup_anchor = current_ts or self.latest_market_time or time.time()
        use_api = not self.is_backtest

        for cat, new_id, new_desc in new_instruments_to_warmup:
            logger.info(f"🔄 Component Drift Update: {cat} -> {new_desc} ({new_id})")

            # Sync description to FundManager's local copy (used for logs)
            self.active_instruments[f"{cat}_DESC"] = new_desc

            # Ensure Resampler and Reset it
            self._ensure_resampler(new_id, InstrumentCategoryType(cat))
            self.resamplers[new_id].reset()

            # Pre-initialize Indicator Calculator deques sequentially to ensure thread-safety
            if new_id not in self.indicator_calculator.instrument_candles:
                from collections import deque
                self.indicator_calculator.instrument_candles[new_id] = deque(
                    maxlen=self.indicator_calculator.max_window_size
                )

            # Extract cached indicators immediately to avoid stale data
            cached_indicators = self.indicator_calculator.extract_indicators(new_id, InstrumentCategoryType(cat))
            if cached_indicators:
                self.latest_indicators_state.update(cached_indicators)

        # 2. Parallel Warmup (Thread-Safe Parts)
        # We manage is_warming_up flag here to prevent premature resets in nested run_warmup calls
        self.is_warming_up = True
        try:

            def do_warmup(warmup_args):
                cat_target, id_target = warmup_args
                self.history_service.run_warmup(
                    self, id_target, warmup_anchor, cat_target, use_api=use_api, save_to_db=use_api
                )

            with ThreadPoolExecutor(max_workers=len(new_instruments_to_warmup)) as executor:
                executor.map(do_warmup, [(cat, nid) for cat, nid, _ in new_instruments_to_warmup])
        finally:
            self.is_warming_up = False

    def _get_fallback_option_price(
        self, symbol_id: int, current_ts: float | None, is_entry: bool = False
    ) -> float | None:
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

        # Try fetching from history service (which handles API/DB)
        history = self.history_service.fetch_historical_candles(
            symbol_id, start_ts=0, end_ts=current_ts or 0, limit=1, use_api=not self.is_backtest
        )
        if history:
            price = history[0].get("c", history[0].get("p"))
            if price is not None:
                logger.info(f"✅ Found history service fallback price for {symbol_id}: {price}")
                return price

        # 3. Position Manager Fallback (Exits Only)
        if (
            not is_entry
            and self.position_manager.current_position
            and str(symbol_id) == self.position_manager.current_position.symbol
        ):
            price = self.position_manager.current_position.current_price
            if price is not None and price > 0:
                logger.info(f"⚠️ Using PositionManager last known price for {symbol_id}: {price}")
                return price

        return None

    def on_tick_or_base_candle(self, market_data: dict[str, Any]) -> None:
        """
        Process a real-time TICK or a base 1-minute CANDLE from the stream.
        Routes it to all configured timeframes for resampling and updates
        the PositionManager for real-time stop loss/target monitoring.

        Indicators:
            Before updating the PositionManager, this method fetches 'mapped'
            indicators (active-*, inverse-*, etc.) which are used for
            Indicator-based Trailing SL (e.g. EMA-5 exit).

        Args:
            market_data (Dict): OHLCV data or Tick data containing instrument ID ('i'),
                               price ('p' or 'c'), and timestamp ('t').
        """
        inst_id = market_data.get("i", market_data.get("instrument_id"))

        # Update global market time if available
        ts = market_data.get("t", market_data.get("timestamp"))
        if ts is not None:
            if self.latest_market_time is None or ts > self.latest_market_time:
                self.latest_market_time = ts

        # In Backtest mode, we use the configured price source (Open or Close)
        # In Live/Socket mode (ticks), we use 'p' (LTP)
        is_candle = any(k in market_data for k in ["c", "close", "o", "open"])
        is_spot = (inst_id == 26000) or getattr(self, "spot_instrument_id", 26000) == inst_id

        if self.is_backtest and is_candle:
            if self.price_source == "open":
                price = market_data.get("o", market_data.get("open"))
            else:
                price = market_data.get("c", market_data.get("close"))
        else:
            price = market_data.get("c", market_data.get("close", market_data.get("p")))

        if price is None:
            return

        # 0. Tick Normalization: If this is a raw tick (no OHLC), populate OHLC for downstream compatibility
        if "p" in market_data and any(k not in market_data for k in ["o", "h", "l", "c"]):
            market_data.update({"o": price, "h": price, "l": price, "c": price})

        if inst_id:
            self.latest_tick_prices[int(inst_id)] = price

        is_spot = (inst_id == 26000) or getattr(self, "spot_instrument_id", 26000) == inst_id

        # 1.a Drift Check (Only when we get Spot)
        if is_spot and ts:
            self.drift_manager.check_drift(price, ts)

        # 2. Update Position Manager immediately for Stop Loss / Target Checks
        if self.position_manager.current_position:
            # Only update position if the tick belongs to the active traded instrument
            if str(inst_id) == self.position_manager.current_position.symbol:
                nifty_price = self.latest_tick_prices.get(26000)

                mapped = self._get_mapped_indicators()
                # In Backtest Mode, if we receive a 1-minute Candle, we explode it into
                # 4 virtual ticks (O, H, L, C) to match Socket/Live granularity.
                if self.is_backtest and is_candle:
                    from packages.utils.replay_utils import ReplayUtils

                    virtual_ticks = ReplayUtils.explode_bar_to_ticks(
                        int(inst_id) if inst_id else 0, market_data, ts, default_price=price
                    )
                    for v_tick in virtual_ticks:
                        if not self.position_manager.current_position:
                            break
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
                    category = "SPOT"  # Fallback for futures/cash

        if not category:
            return  # Data for instrument not actively monitored

        # Ensure resampler exists (especially for drifted/traded instruments)
        self._ensure_resampler(int(inst_id), InstrumentCategoryType(category))

        resampler = self.resamplers.get(int(inst_id))
        if resampler:
            resampler.add_candle(market_data)

    def _on_resampled_candle_closed(self, candle: dict[str, Any], category: InstrumentCategoryType) -> None:
        """
        Callback triggered when a specific Category Resampler finalizes a candle.
        For Triple-Lock, we evaluate the unified state ONLY when the SPOT candle closes.
        """
        ts = candle.get("t", candle.get("timestamp"))

        # Update indicators (Python strategy receives them in on_resampled_candle_closed)
        inst_id = candle.get("instrument_id", candle.get("i"))
        self.indicator_calculator.add_candle(candle, instrument_category=category, instrument_id=inst_id)

        # Invalidate mapping cache as raw indicator values just changed
        self._needs_mapping_update = True

        # Refresh the flat state for logging and heartbeats
        # We pull the fully mapped (active/inverse) indicators so logs match strategy view
        self.latest_indicators_state = self._get_mapped_indicators()

        # 0. Synchronize other resamplers (CE/PE/Traded) to current SPOT timestamp
        # This ensures that if Option ticks arrived slightly late, they are still
        # processed into the current or previous candle before we run indicators.
        for r_id, r in self.resamplers.items():
            if r_id != 26000:  # Not Spot
                # If resampler is lagging behind current SPOT timestamp, flush it
                if r.last_period_start is not None and r.last_period_start < ts:
                    r.add_candle({"t": ts, "is_flush": True})  # Dummy tick to force close if needed
                    # Note: add_candle logic handles period jumps internally

        if self.log_heartbeat and not self.is_warming_up and category == InstrumentCategoryType.SPOT:
            ", ".join(
                [
                    f"{k}: {v:.2f}" if isinstance(v, (int, float)) else f"{k}: {v}"
                    for k, v in self.latest_indicators_state.items()
                ]
            )

            # Format candle start and end times for clarity
            if ts:
                start_str = DateUtils.market_timestamp_to_datetime(ts).strftime("%H:%M:%S")
                end_str = DateUtils.market_timestamp_to_datetime(ts + self.global_timeframe).strftime("%H:%M:%S")
                time_display = f"{start_str} - {end_str}"
            else:
                time_display = "N/A"

            logger.info(TradeFormatter.format_heartbeat(time_display, category.value, self.latest_indicators_state))

        # ONLY execute strategy decision synchronously when the SPOT candle acts as the anchor
        if category != InstrumentCategoryType.SPOT:
            return
        # Determine current intent for strategy evaluation
        intent_enum = None
        if self.position_manager.current_position:
            intent_enum = self.position_manager.current_position.intent

        # Execute Strategy (Python script)
        mapped_indicators = self._get_mapped_indicators()
        mapped_indicators["meta-is-warming-up"] = self.is_warming_up

        signal, reason, confidence = self.strategy.on_resampled_candle_closed(
            candle, mapped_indicators, current_position_intent=intent_enum
        )

        is_cont = "(Continuity)" in reason

        if signal != SignalType.NEUTRAL:
            if self.is_warming_up:
                # No signals/trades during warmup!
                return

            # 0. Stale SignalType Protection (Max 30 minutes)
            if ts and self.latest_market_time and (self.latest_market_time - ts) > 1800:
                logger.warning(f"⚠️ SignalType ignored: Triggered by stale data from {ts}")
                return

            # Use period end for signal/entry time (signal is finalized at end of candle)
            signal_ts = ts + self.global_timeframe
            spot_price = candle.get("c", candle.get("close"))

            # 1. Handle SignalTypes for existing positions
            if self.position_manager.current_position:
                if signal == SignalType.EXIT:
                    # Fallback to market time if signal_ts is missing
                    ts_dt = self._resolve_signal_time(signal_ts)
                    ts_str = ts_dt.strftime("%d-%b %H:%M")
                    logger.info(
                        TradeFormatter.format_signal(
                            "EXIT",
                            reason,
                            ts_str,
                            self.global_timeframe,
                            self.latest_indicators_state,
                            is_continuity=is_cont,
                        )
                    )

                    pos = self.position_manager.current_position
                    opt_price = self._get_fallback_option_price(int(pos.symbol), signal_ts)
                    if not opt_price:
                        logger.error(
                            f"Cannot exit {pos.symbol}, ALL fallbacks failed. Using entry price as last resort."
                        )
                        opt_price = pos.entry_price if pos.entry_price else spot_price  # Extremely rare
                    self.position_manager._close_position(
                        opt_price, ts_dt, "STRATEGY_EXIT", reason_desc=reason, nifty_price=spot_price
                    )
                    return

                intent = MarketIntentType.LONG if signal == SignalType.LONG else MarketIntentType.SHORT

                # If current intent matches signal, do nothing (already in position)
                if self.position_manager.current_position.intent == intent:
                    return

                # SignalType changed (flip) - log it and handle closure
                ts_dt = self._resolve_signal_time(signal_ts)
                ts_str = ts_dt.strftime("%d-%b %H:%M")
                logger.info(
                    TradeFormatter.format_signal(
                        signal.name,
                        reason,
                        ts_str,
                        self.global_timeframe,
                        self.latest_indicators_state,
                        is_continuity=is_cont,
                    )
                )

                pos = self.position_manager.current_position
                opt_price = self._get_fallback_option_price(int(pos.symbol), signal_ts)
                if not opt_price:
                    logger.error(f"Cannot exit {pos.symbol}, ALL fallbacks failed. Using entry price as last resort.")
                    opt_price = pos.entry_price if pos.entry_price else spot_price

                self.position_manager._close_position(
                    opt_price, ts_dt, "SIGNAL_FLIP", reason_desc=reason, nifty_price=spot_price
                )
            else:
                if signal == SignalType.EXIT:
                    return  # Ignore lone exit signals when not in position

                intent = MarketIntentType.LONG if signal == SignalType.LONG else MarketIntentType.SHORT

                # No existing position - log new entry signal
                ts_dt = self._resolve_signal_time(signal_ts)
                ts_str = ts_dt.strftime("%d-%b %H:%M")
                logger.info(
                    TradeFormatter.format_signal(
                        signal.name,
                        reason,
                        ts_str,
                        self.global_timeframe,
                        self.latest_indicators_state,
                        is_continuity=is_cont,
                    )
                )

            # 2. Handle Entries
            target_symbol = "26000"  # default spot
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
                target_display_symbol = resolved_desc or f"NIFTY {t_cat} ({target_symbol})"  # Use resolved description

                # Entry Price Cache check
                entry_price = self._get_fallback_option_price(int(resolved_id), signal_ts, is_entry=True)
                if not entry_price:
                    logger.warning(f"No active tick feed OR DB fallback for option {target_symbol}. Skipping entry.")
                    return
            elif self.trade_instrument_type == "FUTURES":
                target_display_symbol = "NIFTY FUT"  # Example, could be more dynamic

            # Use on_signal for centralized entry/exit logic
            payload = {
                "signal": intent,
                "confidence": confidence,
                "price": entry_price,
                "symbol": target_symbol,
                "display_symbol": target_display_symbol,
                "timestamp": signal_ts,
                "reason": reason,
                "reason_desc": signal.name,
                "nifty_price": spot_price,
                "is_continuity": is_cont,
            }

            # Recalculate quantity based on exact entry price and budget
            from packages.settings import settings

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
                        logger.debug(
                            f"📈 [COMPOUND] Recalculated Qty: {new_qty} based on Capital: ₹{current_capital:,.2f} and Price: {entry_price}"
                        )
                    else:
                        logger.debug(
                            f"💰 [FIXED] Calculated Qty: {new_qty} based on Budget: ₹{self.initial_budget:,.2f} and Price: {entry_price}"
                        )
                else:
                    logger.warning(
                        f"⚠️ Insufficient budget (₹{capital_to_use:,.2f}) for entry at {entry_price}. Qty remains {self.position_manager.quantity}"
                    )

            self.position_manager.on_signal(payload)

            if self.on_signal:
                payload.update({"indicators": self.latest_indicators_state.copy(), "is_buy": signal == SignalType.LONG})
                self.on_signal(payload)

    def handle_eod_settlement(self, timestamp: float) -> None:
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

    def _get_mapped_indicators(self) -> dict[str, float]:
        """
        Builds a unified indicator dictionary for the strategy.
        Caches the result to avoid redundant mapping on every tick.
        """
        if not self._needs_mapping_update:
            return self._cached_mapped_indicators

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
        pos = self.position_manager.current_position
        if pos:
            is_long = pos.intent == MarketIntentType.LONG
            traded_id = int(pos.symbol)
            t_cat = InstrumentCategoryType.CE if is_long else InstrumentCategoryType.PE
            traded_inds = self.indicator_calculator.extract_indicators(traded_id, t_cat)
            inv_inds = pe_inds if is_long else ce_inds
            self._apply_active_inverse_mapping(mapped, traded_inds, inv_inds, is_long)
        else:
            self._apply_active_inverse_mapping(mapped, ce_inds, pe_inds, True)

        self._cached_mapped_indicators = mapped
        self._needs_mapping_update = False
        return mapped

    def _apply_active_inverse_mapping(
        self, target: dict[str, Any], active_source: dict[str, Any], inverse_source: dict[str, Any], is_long: bool
    ) -> None:
        """Helper to apply active/inverse prefixes to the target dict."""
        active_prefix = "ce-" if is_long else "pe-"
        inverse_prefix = "pe-" if is_long else "ce-"

        for k, v in active_source.items():
            if k.startswith(active_prefix):
                target[k.replace(active_prefix, "active-", 1)] = v

        for k, v in inverse_source.items():
            if k.startswith(inverse_prefix):
                target[k.replace(inverse_prefix, "inverse-", 1)] = v

    def _resolve_signal_time(self, signal_ts: float | None) -> datetime:
        """Centralized helper to resolve a signal timestamp to a market-aware datetime."""
        if isinstance(signal_ts, (int, float)):
            return DateUtils.market_timestamp_to_datetime(signal_ts)
        if self.latest_market_time:
            return DateUtils.market_timestamp_to_datetime(self.latest_market_time)
        return datetime.now(DateUtils.MARKET_TZ)
