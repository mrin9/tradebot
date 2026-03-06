from datetime import datetime
from typing import Dict, Optional, List

class TradeFormatter:
    """
    Centralized utility for formatting trade-related logs with consistent colors and emojis.
    Separates presentation logic from trading logic.
    """
    
    # Emojis
    EMOJI_ENTRY = "🟢"
    EMOJI_EXIT_NEUTRAL = "⚪"
    EMOJI_EXIT_LOSS = "🔴"
    EMOJI_TARGET = "🟠"
    EMOJI_BREAKEVEN = "🤟"
    EMOJI_PYRAMID = "📈"
    EMOJI_HEARTBEAT = "💚"
    EMOJI_SIGNAL = "🆔"
    EMOJI_WARNING = "⚠️"
    EMOJI_ERROR = "❌"
    EMOJI_SUCCESS = "✅"
    EMOJI_SYNC = "🔄"
    EMOJI_WARMUP = "🔥"
    EMOJI_ROCKET = "🚀"
    EMOJI_PLUG = "🔌"
    EMOJI_THREAD = "🧵"
    EMOJI_MOON = "🌙"

    @staticmethod
    def format_entry(timestamp: datetime, symbol: str, quantity: int, price: float, total: float, lot_size: int, step: Optional[int] = None, total_steps: Optional[int] = None) -> str:
        fmt_time = timestamp.strftime("%d-%b-%y %H:%M").upper()
        step_suffix = f" (Pyramid {step}/{total_steps})" if step and total_steps else ""
        return f"{TradeFormatter.EMOJI_ENTRY} [{fmt_time}] Entry: [{symbol}] Purchased {quantity} lots({lot_size}) @ {price:,.2f} | Total: ₹{total:,.2f}{step_suffix}"

    @staticmethod
    def format_target(timestamp: datetime, target_num: int, symbol: str, quantity: int, price: float, total: float, lot_size: int, action_pnl: float) -> str:
        fmt_time = timestamp.strftime("%d-%b-%y %H:%M").upper()
        return f"{TradeFormatter.EMOJI_TARGET} [{fmt_time}] TARGET_{target_num} Hit: [{symbol}] Sold {quantity} lots({lot_size}) @ {price:,.2f} | Total: ₹{total:,.2f} (Action PnL: {action_pnl:>+10,.2f})"

    @staticmethod
    def format_exit(timestamp: datetime, reason: str, symbol: str, quantity: int, price: float, total: float, lot_size: int, action_pnl: float, cycle_pnl: float, session_pnl: float) -> str:
        fmt_time = timestamp.strftime("%d-%b-%y %H:%M").upper()
        emoji = TradeFormatter.EMOJI_EXIT_LOSS if action_pnl < 0 else TradeFormatter.EMOJI_EXIT_NEUTRAL
        return (f"{emoji} [{fmt_time}] Exit {reason}: [{symbol}] Sold {quantity} lots({lot_size}) @ {price:,.2f} | "
                f"Total: ₹{total:,.2f} | Action PnL: {action_pnl:>+10,.2f} | "
                f"Cycle PnL: ₹{cycle_pnl:>+10,.2f} | Session PnL: ₹{session_pnl:>+10,.2f}")

    @staticmethod
    def format_breakeven(timestamp: datetime, price: float) -> str:
        fmt_time = timestamp.strftime("%d-%b %H:%M").upper()
        return f"{TradeFormatter.EMOJI_BREAKEVEN} [{fmt_time}] Break-Even Triggered! SL moved to Entry ({price})"

    @staticmethod
    def format_pyramid(timestamp: datetime, step: int, total_steps: int, quantity: int, price: float, avg_price: float, total_qty: int) -> str:
        fmt_time = timestamp.strftime("%d-%b %H:%M").upper()
        return (f"{TradeFormatter.EMOJI_PYRAMID} [{fmt_time}] PYRAMID Step {step}/{total_steps}: "
                f"Added {quantity} lots @ {price} | New Avg: {avg_price:.2f} | "
                f"Total Qty: {total_qty}")

    @staticmethod
    def format_heartbeat(time_display: str, category: str, indicators: Dict[str, float]) -> str:
        ind_str = ", ".join([f"{k}: {v:.2f}" if isinstance(v, (int, float)) else f"{k}: {v}" for k, v in indicators.items()])
        return f"{TradeFormatter.EMOJI_HEARTBEAT} HEARTBEAT [Candle: {time_display}] {TradeFormatter.EMOJI_HEARTBEAT}| Category: {category} | Indicators: {ind_str}"

    @staticmethod
    def format_signal(signal_name: str, reason: str, time_str: str, timeframe: int, indicators: Dict[str, float]) -> str:
        ind_str = ", ".join([f"{k}: {v:.2f}" if isinstance(v, (int, float)) else f"{k}: {v}" for k, v in indicators.items()])
        return f"{TradeFormatter.EMOJI_SIGNAL} Signal: {signal_name} ({reason}) | Time: {time_str} | BaseTimeframe: {timeframe}s | State: {ind_str}"

    @staticmethod
    def format_instrument_switch(category: str, old_id: int, new_id: int) -> str:
        return f"{TradeFormatter.EMOJI_SYNC} Instrument switch detected for {category}: {old_id} -> {new_id}. Clearing indicator window."

    @staticmethod
    def format_warmup(category: str, instrument_id: int, timestamp_str: str, count: int = 0, complete: bool = False) -> str:
        if complete:
            return f"{TradeFormatter.EMOJI_SUCCESS} Warmup complete for {category} ({instrument_id}) with {count} candles."
        return f"{TradeFormatter.EMOJI_WARMUP} Warming up {category} instrument: {instrument_id} at {timestamp_str}"

    @staticmethod
    def format_drift(current_spot: float, prev_spot: float) -> str:
        return f"{TradeFormatter.EMOJI_SYNC} Spot drifted to {current_spot} (prev {prev_spot}). Recalculating Active Options."

    @staticmethod
    def format_session_start(session_id: str, strategy_name: str, strategy_id: str) -> str:
        lines = [
            f"{TradeFormatter.EMOJI_ROCKET} Starting Live Trade Engine | Session: {session_id}",
            f"{TradeFormatter.EMOJI_SIGNAL} Strategy: {strategy_name} ({strategy_id})"
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
