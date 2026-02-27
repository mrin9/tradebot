import sys
import os
from abc import ABC, abstractmethod

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from packages.utils.log_utils import setup_logger
from packages.utils.date_utils import DateUtils
from packages.utils.mongo import MongoRepository

logger = setup_logger("BacktestBase")

class BacktestDataFeeder(ABC):
    """
    Abstract interface for feeding data into the BacktestBot.
    Allows for different data sources (MongoDB, Socket simulator, etc.)
    """
    @abstractmethod
    def start(self, bot, fund_manager, warmup_candles: int = 0):
        """Starts the data flow and feeds it to the fund manager."""
        pass

    def setup_backtest(self, bot, fund_manager, warmup_candles: int):
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
        
        # Run Indicator Warmup
        if warmup_candles > 0:
            MarketUtils.run_indicator_warmup(db, fund_manager, iso_start, warmup_candles, logger)
            
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
        logger.info(f"📊 Recorded Daily PnL for {day_str}: ₹{daily_increment:,.2f} | Total: ₹{current_total_pnl:,.2f}")

    def _log_config(self, start, end, trading_days):
        logger.info(f"\n{'='*20} BACKTEST CONFIGURATION {'='*20}")
        if trading_days:
            logger.info(f"{'Period:':<16} {trading_days[0]} to {trading_days[-1]}")
        else:
            logger.info(f"{'Period:':<16} {start} to {end}")
            
        logger.info(f"{'Budget:':<16} ₹{self.args.budget:,.2f} ({self.args.invest_mode})")
        logger.info(f"{'Strategy:':<16} {self.args.rule_id or 'ML (self-contained)'}")
        logger.info(f"{'Stop Loss:':<16} {self.args.sl} pts")
        logger.info(f"{'Target Steps:':<16} {self.args.target_steps}")
        logger.info(f"{'Trailing SL:':<16} {self.args.trailing_sl}")
        logger.info(f"{'Break Even:':<16} {'Enabled' if not self.args.no_break_even else 'Disabled'}")
        logger.info(f"{'Instrument:':<16} {self.args.instrument_type}")
        if getattr(self.args, 'instrument_type', 'CASH') == "OPTIONS":
            logger.info(f"{'Option Type:':<16} {self.args.option_type}")
        logger.info(f"{'='*60}\n")

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
        """Saves backtest results to MongoDB"""
        try:
            import random
            import string
            
            db = MongoRepository.get_db()

            strategy_id = (self.args.rule_id or "ml-model")
            prefix = strategy_id.split('-')[0][:10].lower()
            
            # Formulate date range
            start_dt = DateUtils._parse_keyword(self.args.start, is_end=False)
            end_dt = DateUtils._parse_keyword(self.args.end, is_end=True)
            start_str = start_dt.strftime("%d%b").upper()
            end_str = end_dt.strftime("%d%b").upper()
            
            if start_str == end_str:
                date_range = start_str
            else:
                date_range = f"{start_str}-{end_str}"
            
            short_id = ''.join(random.choices(string.ascii_lowercase + string.digits, k=3))
            result_id = f"{prefix}-{date_range}-{short_id}"

            # Format trades for UI consumption
            # ... (rest of the mapping logic)
            # 1. Collect all unique instrument IDs
            instrument_ids = list(set([str(getattr(t, "symbol", "")) for t in self.trades if getattr(t, "symbol", "")]))
            
            # 2. Lookup descriptions and metadata from instrument_master
            instrument_map = {}
            if instrument_ids:
                from packages.config import settings
                cursor = db[settings.INSTRUMENT_MASTER_COLLECTION].find(
                    {"exchangeInstrumentID": {"$in": [int(i) if i.isdigit() else i for i in instrument_ids]}},
                    {"exchangeInstrumentID": 1, "description": 1, "series": 1, "optionType": 1}
                )
                for doc in cursor:
                    # Determine Trade Type
                    trade_type = "CASH"
                    series = doc.get("series", "")
                    opt_type = doc.get("optionType", 0)
                    
                    if series in ["FUTIDX", "FUTSTK"]:
                        trade_type = "FUTURES"
                    elif opt_type == 3:
                        trade_type = "CALL"
                    elif opt_type == 4:
                        trade_type = "PUT"
                    
                    instrument_map[str(doc["exchangeInstrumentID"])] = {
                        "symbol": doc.get("description", str(doc["exchangeInstrumentID"])),
                        "type": trade_type
                    }

            # Group trades by trade cycle
            cycle_groups = {}
            for t in self.trades:
                cycle_id = getattr(t, 'trade_cycle', 'N/A')
                if cycle_id not in cycle_groups:
                    cycle_groups[cycle_id] = []
                cycle_groups[cycle_id].append(t)

            trade_cycles = []
            for cycle_id, chunks in cycle_groups.items():
                # Sort chunks by exit_time to identify entry, targets, and exit
                # Entry is the first chunk based on entry_time (they all have same entry_time usually, but let's be safe)
                # But wait, targets are recorded as separate chunks when they hit.
                
                # Determine cycle-wide PnL
                cycle_pnl = sum([getattr(ch, 'pnl', 0) for ch in chunks])
                
                # Find Entry (first chunk)
                entry_chunk = chunks[0]
                
                # Find Target chunks (status starts with TARGET_)
                target_chunks = [ch for ch in chunks if str(getattr(ch, 'status', '')).startswith('TARGET_')]
                
                # Find Exit chunk (the one with status NOT TARGET_ and usually last)
                # If there are no targets, the first chunk might be the only chunk (entry and exit same if stopped out?)
                # Actually, our PositionManager records each exit event as a chunk.
                # If it's a full exit (STOP_LOSS, SIGNAL_EXIT, etc.), there's only one chunk.
                # If it's multi-target, there's TARGET_1, TARGET_2... and then a final EXIT.
                
                exit_chunk = None
                for ch in chunks:
                    status = str(getattr(ch, 'status', ''))
                    if not status.startswith('TARGET_'):
                        exit_chunk = ch
                        break
                
                # Fallback: if all are targets (unlikely but safe), last one is exit
                if not exit_chunk and chunks:
                    exit_chunk = chunks[-1]

                # Resolve Option Type from instrument_map or default
                raw_symbol = str(getattr(entry_chunk, "symbol", "INSTR_X"))
                meta = instrument_map.get(raw_symbol, {"symbol": raw_symbol, "type": "PE | CE"})
                # meta["type"] might be CALL/PUT or PE/CE depending on how we mapped it.
                # Let's ensure it looks like PE | CE for the UI if possible.
                opt_type = meta["type"]
                if opt_type == "CALL": opt_type = "CE"
                elif opt_type == "PUT": opt_type = "PE"

                cycle_obj = {
                    "cycleId": cycle_id,
                    "cyclePnL": cycle_pnl,
                    "entry": {
                        "time": getattr(entry_chunk, 'formatted_entry_time', ''),
                        "exchangeInstrumentId": raw_symbol,
                        "optionType": opt_type,
                        "transaction": getattr(entry_chunk, 'entry_transaction_desc', ''),
                        "totalPrice": getattr(entry_chunk, 'initial_quantity', 0) * settings.NIFTY_LOT_SIZE * getattr(entry_chunk, 'entry_price', 0),
                        "signal": f"{getattr(entry_chunk, 'entry_signal', 'N/A')} ({getattr(entry_chunk, 'entry_reason_description', '')})"
                    }
                }

                # Add Targets
                for i, tch in enumerate(target_chunks, 1):
                    cycle_obj[f"target{i}"] = {
                        "time": getattr(tch, 'formatted_exit_time', ''),
                        "actionPnL": getattr(tch, 'pnl', 0),
                        "transaction": getattr(tch, 'exit_transaction_desc', ''),
                        "totalPrice": getattr(tch, 'quantity', 0) * settings.NIFTY_LOT_SIZE * getattr(tch, 'exit_price', 0)
                    }

                # Add Exit
                if exit_chunk:
                    cycle_obj["exit"] = {
                        "time": getattr(exit_chunk, 'formatted_exit_time', ''),
                        "transaction": getattr(exit_chunk, 'exit_transaction_desc', ''),
                        "reason": getattr(exit_chunk, 'status', 'N/A'),
                        "totalPrice": getattr(exit_chunk, 'quantity', 0) * settings.NIFTY_LOT_SIZE * getattr(exit_chunk, 'exit_price', 0)
                    }

                trade_cycles.append(cycle_obj)

            result_doc = {
                "resultId": result_id,
                "timestamp": DateUtils.to_utc(DateUtils.get_market_time()).replace(tzinfo=None).isoformat(timespec='seconds'),
                "config": {
                    "strategy": self.args.rule_id or "ml-model",
                    "startDate": start_dt.strftime("%Y-%m-%d"),
                    "endDate": end_dt.strftime("%Y-%m-%d"),
                    "timeframe": getattr(self.fm, 'global_timeframe', 300),
                    "indicators": getattr(self.fm, 'indicators_config', []),
                    "budget": self.args.budget,
                    "stopLoss": self.args.sl,
                    "targets": self.args.target_steps,
                    "trailingSl": getattr(self.args, 'trailing_sl', 0),
                    "breakEven": not getattr(self.args, 'no_break_even', False),
                    "instrumentType": getattr(self.args, 'instrument_type', 'CASH'),
                    "selectionBasis": getattr(self.args, 'option_type', 'ATM'),
                    "investMode": getattr(self.args, 'invest_mode', 'compound'),
                    "mlModelPath": getattr(self.args, 'ml_model_path', None)
                },
                "summary": {
                    "initialCapital": self.args.budget,
                    "finalCapital": final_capital,
                    "pnl": total_pnl,
                    "roi": roi,
                    "tradeCount": len(self.trades)
                },
                "tradeCycles": trade_cycles,
                "dailyPnl": self.daily_pnl
            }

            db["backtest_results"].insert_one(result_doc)
            logger.info(f"📊 Backtest '{result_id}' saved to backtest_results ({len(trade_cycles)} cycles)")
            # Return result_id so runner can potentially show it
            return result_id
        except Exception as e:
            logger.error(f"Failed to save backtest results: {e}")
            import traceback
            logger.error(traceback.format_exc())
