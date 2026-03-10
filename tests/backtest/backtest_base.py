import sys
import os
from datetime import datetime
from abc import ABC, abstractmethod

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from packages.utils.log_utils import setup_logger
from packages.utils.date_utils import DateUtils
from packages.utils.mongo import MongoRepository
from packages.utils.trade_persistence import TradePersistence
from packages.config import settings

logger = setup_logger("BacktestBase")

class BacktestDataFeeder(ABC):
    """
    Abstract interface for feeding data into the BacktestBot.
    Allows for different data sources (MongoDB, Socket simulator, etc.)
    """
    @abstractmethod
    def start(self, bot, fund_manager):
        """Starts the data flow and feeds it to the fund manager."""
        pass

    def setup_backtest(self, bot, fund_manager):
        """
        Common setup for all backtest feeders:
        - Parses start/end dates
        - Identifies trading days (if DB mode)
        - Runs indicator warmup
        """
        from packages.utils.mongo import MongoRepository
        from packages.utils.market_utils import MarketUtils
        
        start_date = bot.args.start
        end_date = bot.args.end
        
        iso_start = DateUtils._parse_keyword(start_date, is_end=False).strftime('%Y-%m-%d')
        iso_end = DateUtils._parse_keyword(end_date, is_end=True).strftime('%Y-%m-%d')
        
        db = MongoRepository.get_db()
        
        # Run Indicator Warmup (Hardcoded to 200)
        MarketUtils.run_indicator_warmup(db, fund_manager, iso_start, settings.GLOBAL_WARMUP_CANDLES, logger)
            
        return iso_start, iso_end, db

class BacktestBot:
    """
    Base class for Backtesting.
    Contains common reporting, logging, and data serialization logic.
    """
    def __init__(self, fund_manager_instance, args=None):
        self.fm = fund_manager_instance
        self.args = args
        self.daily_pnl = {} # day_str -> pnl
        self.trades = []
        
        # Subscribe to signals/trades from FundManager
        # We need a way to capture completed trades to build the summary.
        # In v2, OrderManager handles executions. 
        # For backtests, PaperTradingOrderManager handles the simulated fills.
        
        # Capture trades from PositionManager
        def _on_trade_closed(trade_details):
            self.trades.append(trade_details)
            logger.debug(f"Captured simulated trade closed: {trade_details}")
            
        # Hook into FundManager's PositionManager. Normally, we'd hook into OrderManager,
        # but the PositionManager natively stores a local trade history.
        # Let's monitor it periodically or at the end.
        self._last_pnl_checkpoint = 0.0

    def get_realized_pnl(self) -> float:
        """Calculates total realized PnL from all completed trades so far."""
        return sum([t.pnl for t in self.fm.position_manager.trades_history])

    def record_daily_pnl(self, day_str: str):
        """
        Calculates and records the PnL increment for the given day.
        Updates the checkpoint for the next call.
        """
        current_total_pnl = self.get_realized_pnl()
        daily_increment = current_total_pnl - self._last_pnl_checkpoint
        self.daily_pnl[day_str] = daily_increment
        self._last_pnl_checkpoint = current_total_pnl
        logger.info(f"Recorded Daily PnL for {day_str}: {int(daily_increment):,} | Total: {int(current_total_pnl):,}")

    def _log_config(self, trading_days: List[str] | None = None):
        """
        Displays the final configuration being used.
        """
        args = self.args
        if not args:
            return
            
        # Extract indicators from FundManager (which are now centralized)
        indicators = self.fm.indicator_calculator.config
        ind_summary = []
        for ind in indicators:
            cat = ind.get('InstrumentType', 'SPOT')
            ind_val = ind.get('indicator', 'N/A')
            ind_id = ind.get('indicatorId', 'N/A')
            ind_summary.append(f"{cat} | {ind_id} ({ind_val})")

        period_str = f"{args.start} to {args.end or args.start}"
        if trading_days:
            period_str = f"{trading_days[0]} to {trading_days[-1]} ({len(trading_days)} days)"

        msg = f"""
========================= BACKTEST CONFIG =========================
Mode: {args.mode.upper()} | Range: {period_str}
Strategy: {getattr(args, 'python_strategy_path', None) or args.strategy_id or 'Python'}
Budget: ₹{args.budget:,.2f} | Invest Mode: {self.fm.invest_mode.upper()}
Stop Loss: {self.fm.stop_loss_points} pts | Targets: {self.fm.target_points} pts
Trailing SL: {self.fm.trailing_sl_points} pts | Break-Even: {self.fm.use_break_even}
Option Selection: {getattr(args, 'strike_selection', 'ATM')} | Price Source: {getattr(args, 'price_source', 'close').upper()}
Warmup Candles: {settings.GLOBAL_WARMUP_CANDLES}

Indicators:
"""
        for s in ind_summary:
            msg += f" - {s}\n"
        msg += "===================================================================="
        
        logger.info(msg)

    def _report(self):
        # Extract trades directly from the Position Manager history (Dataclass objects)
        pm = self.fm.position_manager
        self.trades = pm.trades_history

        # Group trades by day for count
        trades_by_day = {}
        for t in self.trades:
            day_str = t.entry_time.strftime("%Y-%m-%d")
            trades_by_day[day_str] = trades_by_day.get(day_str, 0) + 1

        print(f"\n{'='*25} DAILY BREAKDOWN {'='*25}")
        print(f"{'Date':<12} | {'Trades':<8} | {'Daily PnL':<15}")
        print("-" * 45)
        
        sorted_days = sorted(self.daily_pnl.keys())
        for d in sorted_days:
            p = self.daily_pnl[d]
            count = trades_by_day.get(d, 0)
            color = "\033[92m" if p > 0 else ("\033[91m" if p < 0 else "")
            reset = "\033[0m"
            print(f"{d:<12} | {count:<8} | {color}{p:>+14,.2f}{reset}")
            
        total_pnl = sum(self.daily_pnl.values())
        print("-" * 45)
        color = "\033[92m" if total_pnl > 0 else ("\033[91m" if total_pnl < 0 else "")
        reset = "\033[0m"
        print(f"{'TOTAL':<12} | {len(self.trades):<8} | {color}{total_pnl:>+14,.2f}{reset}")

        print(f"\n{'='*25} BACKTEST SUMMARY {'='*25}")
        
        # In v2, trades are Position dataclasses, so access attributes via dot notation
        total_pnl = sum([t.pnl for t in self.trades])
        final_capital = self.args.budget + total_pnl
        roi = (total_pnl / self.args.budget) * 100 if self.args.budget > 0 else 0
        
        print(f"Final Capital: ₹{final_capital:,.2f} | ROI: {roi:+.2f}%")
        print(f"Total Trades: {len(self.trades)}")
        
        if len(self.trades) == 0:
            logger.warning("No trades were executed during this backtest.")
            
        # Save results if possible
        self._save_results(total_pnl, roi, final_capital)

    def _save_results(self, total_pnl, roi, final_capital):
        """Saves backtest results to MongoDB using centralized persistence."""
        try:
            import random
            import string
            
            if getattr(self.args, "python_strategy_path", None):
                strategy_id = os.path.basename(self.args.python_strategy_path).split(':')[0].split('.')[0]
            else:
                strategy_id = (self.args.strategy_id or "python")
            
            # Prefix: first word (hyphen/underscore) or 10 chars, whichever is smaller
            import re
            first_word = re.split('[-_ ]', strategy_id)[0]
            prefix = first_word[:10].lower()
            
            # Formulate date range
            start_dt = DateUtils._parse_keyword(self.args.start, is_end=False)
            end_dt = DateUtils._parse_keyword(self.args.end, is_end=True)
            start_str = start_dt.strftime("%d%b").upper()
            end_str = end_dt.strftime("%d%b").upper()
            
            date_range = start_str if start_str == end_str else f"{start_str}-{end_str}"
            short_id = ''.join(random.choices(string.ascii_lowercase + string.digits, k=3))
            session_id = f"{prefix}-{date_range}-{short_id}"

            config = {
                "strategyId": strategy_id,
                "python_strategy_path": getattr(self.args, "python_strategy_path", None),
                "timeframe": self.fm.global_timeframe,
                "indicators": [
                    f"{ind.get('InstrumentType', 'SPOT')}|{ind.get('indicator', 'N/A')}|{ind.get('indicatorId', 'N/A')}"
                    for ind in self.fm.indicator_calculator.config
                ],
                "tsl_indicator_id": self.fm.tsl_indicator_id,
                "budget": self.args.budget,
                "invest_mode": self.fm.invest_mode,
                "stop_loss_points": self.fm.stop_loss_points,
                "target_points": self.fm.target_points,
                "trailing_sl_points": self.fm.trailing_sl_points,
                "use_break_even": self.fm.use_break_even,
                "strike_selection": getattr(self.args, 'strike_selection', 'ATM'),
                "price_source": self.fm.price_source,
                "pyramid_steps": getattr(self.args, 'pyramid_steps', None),
                "pyramid_confirm_pts": getattr(self.args, 'pyramid_confirm_pts', None),
            }
            
            # Use centralized persistence
            persistence = TradePersistence()
            persistence.save_session_summary(
                session_id=session_id,
                trades=self.trades, # List[Position]
                config=config,
                daily_pnl=self.daily_pnl,
                is_live=False
            )
            
            logger.info(f"✅ Backtest saved! sessionId: {session_id}")
            return session_id
        except Exception as e:
            logger.error(f"Failed to save backtest results: {e}")
            import traceback
            logger.error(traceback.format_exc())
