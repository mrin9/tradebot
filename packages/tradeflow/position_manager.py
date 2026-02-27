from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import Dict, List
from packages.utils.date_utils import DateUtils
from packages.utils.log_utils import setup_logger
import logging

logger = setup_logger(__name__)

class MarketIntent(Enum):
    LONG = auto()
    SHORT = auto()

class InstrumentType(Enum):
    CASH = auto()
    FUTURES = auto()
    OPTIONS = auto()

class OrderStatus(Enum):
    PENDING = auto()
    FILLED = auto()
    REJECTED = auto()
    CANCELLED = auto()

@dataclass
class Position:
    symbol: str
    display_symbol: str
    intent: MarketIntent
    entry_price: float
    initial_quantity: int
    entry_time: datetime
    stop_loss: float
    targets: list[float]
    current_price: float = 0.0
    status: str = "OPEN"
    pnl: float = 0.0
    total_realized_pnl: float = 0.0 # Tracking cumulative PnL for multi-target trades
    
    # Nifty Underlying Tracking
    nifty_price_at_entry: float = 0.0
    nifty_price_at_exit: float = 0.0
    nifty_price_at_break_even: float = 0.0

    # Advanced Execution Tracking
    remaining_quantity: int = field(init=False)
    achieved_targets: int = 0
    highest_price: float = field(init=False)
    lowest_price: float = field(init=False)
    exit_price: float | None = None
    exit_time: datetime | None = None
    trade_cycle: str = "N/A"
    entry_signal: str = "N/A"
    entry_reason_description: str = ""
    exit_reason_description: str = ""
    
    # Enriched Fields for UI/Reporting
    formatted_entry_time: str = ""
    formatted_exit_time: str = ""
    entry_transaction_desc: str = ""
    exit_transaction_desc: str = ""

    # Pyramiding
    pyramid_step: int = 0      # Current pyramid step index (0 = first entry)
    total_intended_quantity: int = 0  # Full quantity before splitting into pyramid steps

    def __post_init__(self):
        self.remaining_quantity = self.initial_quantity
        self.highest_price = self.entry_price
        self.lowest_price = self.entry_price

class PositionManager:
    """
    Manages the lifecycle of a trade:
    - Entry based on Signals
    - Stop Loss / Target Monitoring
    - Exit Execution
    - PnL Calculation
    """
    def __init__(self, symbol: str, quantity: int, stop_loss_points: float = 0, target_points: List[float] | None = None,
                 instrument_type: InstrumentType = InstrumentType.OPTIONS, 
                 trailing_sl_points: float = 0.0,
                 use_break_even: bool = True,
                 display_symbol: str | None = None,
                 pyramid_steps: List[int] | None = None,
                 pyramid_confirm_pts: float = 10.0):
        self.symbol = symbol
        self.display_symbol = display_symbol or symbol
        self.quantity = quantity
        self.stop_loss_points = stop_loss_points
        self.trailing_sl_points = trailing_sl_points
        self.use_break_even = use_break_even
        self.instrument_type = instrument_type
        
        # Parse Targets
        if isinstance(target_points, str):
            self.target_steps = [float(x.strip()) for x in target_points.split(',')]
        elif isinstance(target_points, (list, tuple)):
            self.target_steps = [float(x) for x in target_points]
        else:
            self.target_steps = [float(target_points)]
        
        self.current_position: Position | None = None
        self.trades_history = []
        
        # Cycle Tracking
        self.cycle_count = 0
        self.last_trade_date = None
        
        # Interface to OrderManager (to be injected)
        self.order_manager = None
        
        # Pyramiding Config
        self.pyramid_steps = pyramid_steps or [100]  # Default: 100% all-in
        self.pyramid_confirm_pts = pyramid_confirm_pts

    def set_order_manager(self, order_manager):
        self.order_manager = order_manager

    def on_signal(self, signal_dict: Dict):
        """
        Processes a New Signal. 
        Accepts: {'signal': MarketIntent.LONG, 'price': 100.0, 'timestamp': datetime, 'symbol': '48215', 'display_symbol': 'NIFTY...'}
        """
        intent = signal_dict['signal']
        price = signal_dict['price']
        timestamp = signal_dict['timestamp']
        
        if isinstance(timestamp, (int, float)):
            timestamp = datetime.fromtimestamp(timestamp)
        symbol = str(signal_dict.get('symbol', self.symbol))
        display_symbol = signal_dict.get('display_symbol', symbol)

        if self.current_position:
            if self.current_position.intent != intent:
                # Signal flip → close current position
                nifty_price = signal_dict.get('nifty_price', 0.0)
                self._close_position(price, timestamp, "SIGNAL_EXIT", nifty_price=nifty_price)
            else:
                # Same-direction signal → attempt pyramid add
                self._try_pyramid_add(price, timestamp, signal_dict)
                return
        else:
            # Check for Entry Signal
            # 1. Handle Daily Cycle Reset
            trade_date = timestamp.date()
            if self.last_trade_date != trade_date:
                self.cycle_count = 1
                self.last_trade_date = trade_date
            else:
                self.cycle_count += 1
            
            # 2. Extract specific trigger name if provided
            entry_reason = signal_dict.get('reason', 'N/A')
            nifty_price = signal_dict.get('nifty_price', 0.0)
            
            self._open_position(intent, price, timestamp, symbol, display_symbol, 
                               cycle_id=f"cycle-{self.cycle_count}", 
                               reason=entry_reason,
                               reason_desc=signal_dict.get('reason_desc', ''),
                               nifty_price=nifty_price)

    def _try_pyramid_add(self, price: float, timestamp: datetime, signal_dict: Dict):
        """
        Attempts to add to an existing position via pyramiding.
        Only adds if:
          1. There are more pyramid steps remaining.
          2. Price has moved >= pyramid_confirm_pts in our favor.
        """
        pos = self.current_position
        if not pos:
            return
        
        # Check if more steps are available
        next_step = pos.pyramid_step + 1
        if next_step >= len(self.pyramid_steps):
            return  # All pyramid steps exhausted
        
        # Check price confirmation
        is_long_dir = (self.instrument_type == InstrumentType.OPTIONS) or (pos.intent == MarketIntent.LONG)
        if is_long_dir:
            price_moved = price - pos.entry_price
        else:
            price_moved = pos.entry_price - price
        
        if price_moved < self.pyramid_confirm_pts:
            return  # Price hasn't moved enough in our favor
        
        # Calculate quantity for this step
        step_pct = self.pyramid_steps[next_step]
        add_qty = max(1, (pos.total_intended_quantity * step_pct) // 100)
        
        # Update position with weighted average entry
        old_total = pos.entry_price * pos.remaining_quantity
        new_total = price * add_qty
        pos.entry_price = (old_total + new_total) / (pos.remaining_quantity + add_qty)
        pos.remaining_quantity += add_qty
        pos.initial_quantity += add_qty
        pos.pyramid_step = next_step
        
        # Recalculate SL and Targets based on new avg entry
        if is_long_dir:
            pos.stop_loss = pos.entry_price - self.stop_loss_points
            pos.targets = [pos.entry_price + t for t in self.target_steps]
        else:
            pos.stop_loss = pos.entry_price + self.stop_loss_points
            pos.targets = [pos.entry_price - t for t in self.target_steps]
        pos.achieved_targets = 0  # Reset targets for recalculated levels
        
        time_str = timestamp.strftime("%d-%b %H:%M").upper()
        logger.info(f"📈 [{time_str}] PYRAMID Step {next_step + 1}/{len(self.pyramid_steps)}: "
                    f"Added {add_qty} lots @ {price} | New Avg: {pos.entry_price:.2f} | "
                    f"Total Qty: {pos.remaining_quantity}")
        
        if self.order_manager:
            self.order_manager.place_order(pos.symbol, "BUY", add_qty)

    def update_tick(self, tick: Dict, nifty_price: float | None = None):
        """
        Updates current position status based on latest price (tick/candle).
        Checks Stop Loss, Targets, and Trailing features.
        """
        if not self.current_position:
            return

        current_price = tick.get('c', tick.get('close', tick.get('ltp')))
        if not current_price:
            return
            
        # Parse realistic exit time from tick if available
        ts = tick.get('t', tick.get('timestamp'))
        if isinstance(ts, (int, float)):
            exit_time = DateUtils.from_timestamp(ts)
        else:
            exit_time = datetime.now()

        pos = self.current_position
        pos.current_price = current_price
        
        # Determine if we are in a 'Long' direction trade (expecting price to go up)
        # 1. Any Option position is 'Long' the contract itself.
        # 2. CASH/FUTURE LONG is 'Long' the underlying.
        # 3. CASH/FUTURE SHORT is 'Short' the underlying.
        is_long_dir = (self.instrument_type == InstrumentType.OPTIONS) or (pos.intent == MarketIntent.LONG)
        
        # PnL Calculation: 
        # Long: (Current - Entry) * Qty
        # Short: (Entry - Current) * Qty
        if is_long_dir:
            pos.pnl = (current_price - pos.entry_price) * pos.remaining_quantity
        else:
            pos.pnl = (pos.entry_price - current_price) * pos.remaining_quantity
        
        # Trailing Extremes and Exit Triggers
        if is_long_dir:
            # LONG direction: Profit when High increases, SL when Low decreases
            if current_price > pos.highest_price:
                pos.highest_price = current_price
                if self.trailing_sl_points > 0:
                    new_sl = pos.highest_price - self.trailing_sl_points
                    if new_sl > pos.stop_loss:
                        pos.stop_loss = new_sl
            
            # Stop Loss execution (price drops below SL)
            if current_price <= pos.stop_loss:
                reason = "TRAILING_SL" if pos.highest_price > pos.entry_price else "STOP_LOSS"
                desc = f"{reason} hit at {current_price:.2f} (SL: {pos.stop_loss:.2f})"
                self._close_position(pos.stop_loss, exit_time, reason, reason_desc=desc, nifty_price=nifty_price)
                return
        else:
            # SHORT direction: Profit when Low decreases, SL when High increases
            if current_price < pos.lowest_price:
                pos.lowest_price = current_price
                if self.trailing_sl_points > 0:
                    new_sl = pos.lowest_price + self.trailing_sl_points
                    if new_sl < pos.stop_loss:
                        pos.stop_loss = new_sl
            
            # Stop Loss execution (price rises above SL)
            if current_price >= pos.stop_loss:
                reason = "TRAILING_SL" if pos.lowest_price < pos.entry_price else "STOP_LOSS"
                desc = f"{reason} hit at {current_price:.2f} (SL: {pos.stop_loss:.2f})"
                self._close_position(pos.stop_loss, exit_time, reason, reason_desc=desc, nifty_price=nifty_price)
                return
            
        # Targets execution
        while pos.achieved_targets < len(pos.targets):
            next_target = pos.targets[pos.achieved_targets]
            hit = (current_price >= next_target) if is_long_dir else (current_price <= next_target)
            
            if hit:
                pos.achieved_targets += 1
                
                # Move SL to Break-Even if first target hit
                if pos.achieved_targets == 1 and self.use_break_even:
                    # For Long: Entry > SL | For Short: Entry < SL
                    is_far = (pos.entry_price > pos.stop_loss) if is_long_dir else (pos.entry_price < pos.stop_loss)
                    if is_far:
                        pos.stop_loss = pos.entry_price
                        pos.nifty_price_at_break_even = nifty_price or 0.0
                        time_str = exit_time.strftime("%d-%b %H:%M").upper()
                        logger.info(f"🤟 [{time_str}] Break-Even Triggered! SL moved to Entry ({pos.stop_loss})")
                
                # fractional exit: close 1/(N+1) of initial quantity per target hit
                # leaving 1/(N+1) for signal/SL exit.
                close_qty = self.quantity // (len(pos.targets) + 1)
                desc = f"Target {pos.achieved_targets} ({next_target:.2f}) hit at {current_price:.2f}"
                self._close_position(next_target, exit_time, f"TARGET_{pos.achieved_targets}", reason_desc=desc, quantity=close_qty, nifty_price=nifty_price)
                
                if not self.current_position:
                    break
            else:
                break

    def _open_position(self, intent: MarketIntent, price: float, timestamp: datetime, 
                      symbol: str | None = None, display_symbol: str | None = None,
                      cycle_id: str = "N/A", reason: str = "N/A", reason_desc: str = "", nifty_price: float = 0.0):
        """
        Logic for entering a trade.
        """
        if symbol: self.symbol = symbol
        if display_symbol: self.display_symbol = display_symbol

        # Disable Shorting for Futures/Cash
        if self.instrument_type in [InstrumentType.CASH, InstrumentType.FUTURES] and intent == MarketIntent.SHORT:
            # logger.info(f"skipping SHORT signal for {self.instrument_type.name}") # Avoid noise
            return

        # Determine direction logic
        is_long_dir = (self.instrument_type == InstrumentType.OPTIONS) or (intent == MarketIntent.LONG)
        
        # Set SL and Targets based on Direction
        if is_long_dir:
            # Profit on increase
            sl = price - self.stop_loss_points
            targets = [price + t for t in self.target_steps]
        else:
            # Profit on decrease (Short Selling - only for Options Put contracts internally)
            sl = price + self.stop_loss_points
            targets = [price - t for t in self.target_steps]

        # Calculate initial pyramid quantity
        step_pct = self.pyramid_steps[0]  # First step percentage
        pyramid_qty = max(1, (self.quantity * step_pct) // 100)
        
        from packages.config import settings
        lot_size = settings.NIFTY_LOT_SIZE
        fmt_time = timestamp.strftime("%d-%b-%Y %H:%M").upper()
        total_price = pyramid_qty * lot_size * price
        trans_desc = f"Purchased {pyramid_qty} lots({lot_size}) @ {price} | Total: ₹{total_price:,.2f}"

        self.current_position = Position(
            symbol=self.symbol,
            display_symbol=self.display_symbol,
            intent=intent,
            entry_price=price,
            initial_quantity=pyramid_qty,
            entry_time=timestamp,
            stop_loss=sl,
            targets=targets,
            current_price=price,
            trade_cycle=cycle_id,
            entry_signal=reason,
            entry_reason_description=reason_desc,
            nifty_price_at_entry=nifty_price,
            pyramid_step=0,
            total_intended_quantity=self.quantity,
            formatted_entry_time=fmt_time,
            entry_transaction_desc=trans_desc
        )
        
        # Place Order: 
        # For OPTIONS: Always BUY
        # For CASH/FUTURES: BUY (Shorts are disabled)
        side = "BUY"
        if self.instrument_type != InstrumentType.OPTIONS and intent == MarketIntent.SHORT:
            side = "SELL" # This part is technically unreachable now due to the lock above
            
        step_label = f" (Pyramid 1/{len(self.pyramid_steps)})" if len(self.pyramid_steps) > 1 else ""
        logger.info(f"🟢 [{fmt_time}] Entry: {self.display_symbol} | {trans_desc}{step_label}")
        
        if self.order_manager:
            self.order_manager.place_order(self.symbol, side, pyramid_qty)

    def _close_position(self, price: float, timestamp: datetime, reason: str, reason_desc: str = "", quantity: int | None = None, nifty_price: float | None = None):
        if not self.current_position:
            return
            
        pos = self.current_position
        close_qty = quantity if quantity is not None else pos.remaining_quantity
        
        if close_qty <= 0:
            return
            
        # Determine exit side
        is_long_dir = (self.instrument_type == InstrumentType.OPTIONS) or (pos.intent == MarketIntent.LONG)
        exit_side = "SELL" if is_long_dir else "BUY"
        
        # PnL is (Exit - Entry) for Long, (Entry - Exit) for Short
        if is_long_dir:
            chunk_pnl = (price - pos.entry_price) * close_qty
        else:
            chunk_pnl = (pos.entry_price - price) * close_qty
        
        pos.total_realized_pnl += chunk_pnl
        
        from packages.config import settings
        lot_size = settings.NIFTY_LOT_SIZE
        fmt_time = timestamp.strftime("%d-%b-%Y %H:%M").upper()
        total_price = close_qty * lot_size * price
        trans_desc = f"Sold {close_qty} lots({lot_size}) @ {price} | Total: ₹{total_price:,.2f}"

        if quantity is not None and reason.startswith("TARGET"):
            logger.info(f"🟠 [{fmt_time}] {reason} Hit: {trans_desc} (Action PnL: +{chunk_pnl:,.2f})")
        else:
            logger.info(f"🔴 [{fmt_time}] Exit {reason}: {self.display_symbol} | {trans_desc} | Action PnL: +{chunk_pnl:,.2f} | Total Trade PnL: ₹{pos.total_realized_pnl:,.2f}")

        closed_chunk = Position(
            symbol=pos.symbol,
            display_symbol=pos.display_symbol,
            intent=pos.intent,
            entry_price=pos.entry_price,
            initial_quantity=close_qty,
            entry_time=pos.entry_time,
            stop_loss=pos.stop_loss,
            targets=pos.targets,
            trade_cycle=pos.trade_cycle,
            entry_signal=pos.entry_signal,
            entry_reason_description=pos.entry_reason_description,
            exit_reason_description=reason_desc,
            nifty_price_at_entry=pos.nifty_price_at_entry,
            formatted_entry_time=pos.formatted_entry_time,
            formatted_exit_time=fmt_time,
            entry_transaction_desc=pos.entry_transaction_desc,
            exit_transaction_desc=trans_desc
        )
        closed_chunk.exit_price = price
        closed_chunk.exit_time = timestamp
        closed_chunk.nifty_price_at_exit = nifty_price or 0.0
        closed_chunk.status = reason
        closed_chunk.pnl = chunk_pnl
        closed_chunk.quantity = close_qty 
        
        self.trades_history.append(closed_chunk)
        pos.remaining_quantity -= close_qty
        
        if self.order_manager:
            self.order_manager.place_order(self.symbol, exit_side, close_qty)

        if pos.remaining_quantity <= 0:
            self.current_position = None
