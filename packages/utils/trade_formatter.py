from datetime import datetime


class TradeFormatter:
    """
    Centralized utility for formatting trade-related logs with consistent colors and emojis.
    Separates presentation logic from trading logic.
    """

    # Emojis
    EMOJI_ENTRY = "🔵"
    EMOJI_EXIT_PROFIT = "🟢"
    EMOJI_EXIT_NEUTRAL = "⚪"
    EMOJI_EXIT_LOSS = "🔴"
    EMOJI_TARGET = "🟠"
    EMOJI_BREAKEVEN = "🤟"
    EMOJI_PYRAMID = "📈"
    EMOJI_HEARTBEAT = "💚"
    EMOJI_SIGNAL = "⭕"
    EMOJI_WARNING = "⚠️"
    EMOJI_ERROR = "❌"
    EMOJI_SUCCESS = "✅"
    EMOJI_SYNC = "🔄"
    EMOJI_WARMUP = "🔥"
    EMOJI_ROCKET = "🚀"
    EMOJI_PLUG = "🔌"
    EMOJI_THREAD = "🧵"
    EMOJI_MOON = "🌙"
    EMOJI_CONTINUITY = "🔁"

    @staticmethod
    def format_entry(
        timestamp: datetime,
        symbol: str,
        quantity: int,
        price: float,
        total: float,
        lot_size: int,
        step: int | None = None,
        total_steps: int | None = None,
    ) -> str:
        fmt_time = timestamp.strftime("%d-%b-%y %H:%M").upper()
        step_suffix = f" (Pyramid {step}/{total_steps})" if step and total_steps else ""
        return f"{TradeFormatter.EMOJI_ENTRY} [{fmt_time}] Entry: [{symbol}] Purchased {quantity} lots({lot_size}) @ {price:,.2f} | Total: {int(total):,}{step_suffix}"

    @staticmethod
    def format_target(
        timestamp: datetime,
        target_num: int,
        symbol: str,
        quantity: int,
        price: float,
        total: float,
        lot_size: int,
        action_pnl: float,
    ) -> str:
        fmt_time = timestamp.strftime("%d-%b-%y %H:%M").upper()
        return f"{TradeFormatter.EMOJI_TARGET} [{fmt_time}] TARGET_{target_num} Hit: [{symbol}] Sold {quantity} lots({lot_size}) @ {price:,.2f} | Total: {int(total):,} (Action PnL: {int(action_pnl):>+7,})"

    @staticmethod
    def format_exit(
        timestamp: datetime,
        reason: str,
        symbol: str,
        quantity: int,
        price: float,
        total: float,
        lot_size: int,
        action_pnl: float,
        cycle_pnl: float,
        session_pnl: float,
    ) -> str:
        fmt_time = timestamp.strftime("%d-%b-%y %H:%M").upper()
        if cycle_pnl > 0:
            emoji = TradeFormatter.EMOJI_EXIT_PROFIT
        elif cycle_pnl < 0:
            emoji = TradeFormatter.EMOJI_EXIT_LOSS
        else:
            emoji = TradeFormatter.EMOJI_EXIT_NEUTRAL
        return (
            f"{emoji} [{fmt_time}] Exit {reason}: [{symbol}] Sold {quantity} lots({lot_size}) @ {price:,.2f} | "
            f"Total: {int(total):,} | Action PnL: {int(action_pnl):>+7,} | "
            f"Cycle PnL: {int(cycle_pnl):>+7,} | Session PnL: {int(session_pnl):>+7,}"
        )

    @staticmethod
    def format_breakeven(timestamp: datetime, price: float) -> str:
        fmt_time = timestamp.strftime("%d-%b %H:%M").upper()
        return f"{TradeFormatter.EMOJI_BREAKEVEN} [{fmt_time}] Break-Even Triggered! SL moved to Entry ({price})"

    @staticmethod
    def format_pyramid(
        timestamp: datetime, step: int, total_steps: int, quantity: int, price: float, avg_price: float, total_qty: int
    ) -> str:
        fmt_time = timestamp.strftime("%d-%b %H:%M").upper()
        return (
            f"{TradeFormatter.EMOJI_PYRAMID} [{fmt_time}] PYRAMID Step {step}/{total_steps}: "
            f"Added {quantity} lots @ {price} | New Avg: {avg_price:.2f} | "
            f"Total Qty: {total_qty}"
        )

    @staticmethod
    def format_heartbeat(time_display: str, category: str, indicators: dict[str, float]) -> str:
        state_str = TradeFormatter._format_indicator_state(indicators)
        return f"{TradeFormatter.EMOJI_HEARTBEAT} HEARTBEAT [Candle: {time_display}] {TradeFormatter.EMOJI_HEARTBEAT}| Category: {category} | Indicators: {state_str}"

    @staticmethod
    def _format_indicator_state(indicators: dict[str, float]) -> str:
        """
        Generic helper to format indicator states with comparison arrows and pipe grouping.
        Automatically detects pairs like fast/slow, macd/signal, etc.
        """
        if not indicators:
            return "N/A"

        keys = sorted(indicators.keys())
        formatted_parts = []
        seen_keys = set()

        # 1. Look for common indicator pairs
        # Patterns:
        # - prefix_fast_ema vs prefix_slow_ema
        # - prefix_macd vs prefix_macd_signal
        # - prefix_close vs prefix_supertrend (if available)

        # We'll scan for everything that ends in _fast_xxx and look for _slow_xxx
        for k in keys:
            if k in seen_keys:
                continue

            # Check for fast/slow pairs
            if "_fast_" in k:
                slow_key = k.replace("_fast_", "_slow_")
                if slow_key in indicators:
                    f_val = indicators[k]
                    s_val = indicators[slow_key]
                    arrow = "🔼" if f_val > s_val else "🔻"
                    formatted_parts.append(f"{k}: {f_val:.2f} {arrow} {slow_key}: {s_val:.2f}")
                    seen_keys.update([k, slow_key])
                    continue

            # Check for macd/signal pairs
            if k.endswith("_macd") or k.endswith("_macd_prev"):
                signal_key = k + "_signal"
                if signal_key in indicators:
                    m_val = indicators[k]
                    si_val = indicators[signal_key]
                    arrow = "🔼" if m_val > si_val else "🔻"
                    formatted_parts.append(f"{k}: {m_val:.2f} {arrow} {signal_key}: {si_val:.2f}")
                    seen_keys.update([k, signal_key])
                    continue

        # 2. Add remaining individual indicators
        others = []
        for k in keys:
            if k not in seen_keys:
                v = indicators[k]
                val_str = f"{v:.2f}" if isinstance(v, (int, float)) else str(v)
                others.append(f"{k}: {val_str}")

        if others:
            formatted_parts.append(", ".join(others))

        return " | ".join(formatted_parts)

    @staticmethod
    def format_signal(
        signal_name: str,
        reason: str,
        time_str: str,
        timeframe: int,
        indicators: dict[str, float],
        is_continuity: bool = False,
    ) -> str:
        state_str = TradeFormatter._format_indicator_state(indicators)
        emoji = TradeFormatter.EMOJI_CONTINUITY if is_continuity else TradeFormatter.EMOJI_SIGNAL
        prefix = "Continuity " if is_continuity else ""
        return f"{emoji} {prefix}Signal: {signal_name} ({reason}) | Time: {time_str} | Timeframe: {timeframe}s | State: {state_str}"

    @staticmethod
    def format_instrument_switch(category: str, old_id: int, new_id: int) -> str:
        return f"{TradeFormatter.EMOJI_SYNC} Instrument switch detected for {category}: {old_id} -> {new_id}. Clearing indicator window."

    @staticmethod
    def format_warmup(
        category: str, instrument_id: int, timestamp_str: str, count: int = 0, complete: bool = False
    ) -> str:
        if complete:
            return f"Warmup complete for {category} ({instrument_id}) with {count} candles."
        return f"{TradeFormatter.EMOJI_WARMUP} Warming up {category} instrument: {instrument_id} at {timestamp_str}"

    @staticmethod
    def format_drift(current_spot: float, prev_spot: float) -> str:
        return f"{TradeFormatter.EMOJI_SYNC} Spot drifted to {current_spot} (prev {prev_spot}). Recalculating Active Options."

    @staticmethod
    def format_session_start(session_id: str, strategy_name: str, strategy_id: str) -> str:
        lines = [
            f"{TradeFormatter.EMOJI_ROCKET} Starting Live Trade Engine | Session: {session_id}",
            f"{TradeFormatter.EMOJI_SIGNAL} Strategy: {strategy_name} ({strategy_id})",
        ]
        return "\n".join(lines)

    @staticmethod
    def format_connection(status: str, detail: str = "") -> str:
        if status.lower() == "connecting":
            return f"{TradeFormatter.EMOJI_PLUG} {detail}"
        elif status.lower() == "connected":
            return f"{TradeFormatter.EMOJI_SUCCESS} {detail}"
        elif status.lower() == "disconnected":
            return f"{TradeFormatter.EMOJI_WARNING} {detail}"
        return f"{TradeFormatter.EMOJI_PLUG} {status}: {detail}"

    @staticmethod
    def format_eod(symbol: str, price: float) -> str:
        return f"{TradeFormatter.EMOJI_MOON} FundManager: EOD Settlement for {symbol} at {price}"
