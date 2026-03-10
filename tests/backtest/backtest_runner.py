import argparse
import sys
import os

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from packages.utils.log_utils import setup_logger
from packages.utils.mongo import MongoRepository
from packages.tradeflow.fund_manager import FundManager
from tests.backtest.backtest_base import BacktestBot
from packages.config import settings

logger = setup_logger("BacktestRunner")

def get_parser():
    parser = argparse.ArgumentParser(description="Backtest Runner")
    parser.add_argument("--mode", type=str, choices=["db", "socket"], default="db", help="Backtest mode: db or socket")
    parser.add_argument("--start", type=str, default="2026-02-02", help="Start Date (YYYY-MM-DD)")
    parser.add_argument("--end", type=str, default=None, help="End Date (YYYY-MM-DD). Defaults to --start if omitted.")
    parser.add_argument("--strategy-id", "-I", type=str, default=None, help="Strategy Indicator ID (from DB).")
    parser.add_argument("--budget", "-b", type=float, default=200000.0, help="Initial Capital")
    parser.add_argument("--stop-loss-points", "-s", type=float, default=settings.BACKTEST_STOP_LOSS, help="Stop Loss Points")
    parser.add_argument("--target-points", "-t", type=str, default=settings.BACKTEST_TARGET_STEPS, help="Comma separated target points")
    parser.add_argument("--trailing-sl-points", "-L", type=float, default=0.0, help="Trailing Stop Loss Points (0 to disable)")
    parser.add_argument("--use-break-even", "-e", action="store_true", help="Enable Break-Even trailing on first target")
    parser.add_argument("--instrument-type", type=str, choices=["CASH", "OPTIONS"], default="OPTIONS", help="Instrument to trade")
    parser.add_argument("--strike-selection", "-S", type=str, choices=["ITM", "ATM", "OTM"], default="ATM", help="Option Strike selection")
    parser.add_argument("--invest-mode", "-i", type=str, choices=["compound", "fixed"], default=settings.BACKTEST_INVEST_MODE)
    # Hybrid Strategy & Pyramiding
    parser.add_argument("--python-strategy-path", type=str, default=None, help="Path to python strategy (e.g. packages/tradeflow/python_strategies.py:TripleLockStrategy)")
    parser.add_argument("--pyramid-steps", type=str, default="100", help="Comma-separated entry percentages (e.g., 25,50,25 or 100 for all-in)")
    parser.add_argument("--pyramid-confirm-pts", type=float, default=10.0, help="Points price must move in our favor before next pyramid step")
    parser.add_argument("--price-source", "-p", type=str, choices=["open", "close"], default=settings.BACKTEST_PRICE_SOURCE, help="Price source for backtest entry/exit (open or close)")
    parser.add_argument("--tsl-indicator-id", type=str, default=None, help="Indicator ID for Trailing Stop Loss (e.g. active-ema-5)")
    return parser

def fetch_strategy_config(strategy_id: str | None, python_strategy_path: str | None):
    """Build strategy_config for FundManager. Optional strategy_id loads indicators from DB."""
    if strategy_id:
        db = MongoRepository.get_db()
        strategy = db["strategy_indicators"].find_one({"strategyId": strategy_id})
        if strategy:
            return strategy
        logger.warning(f"Strategy ID '{strategy_id}' not found; using default indicators.")
    
    default_indicators = [
        {"indicator": "ema-9", "InstrumentType": "SPOT"},
        {"indicator": "ema-21", "InstrumentType": "SPOT"},
        {"indicator": "ema-9", "InstrumentType": "OPTIONS_BOTH"},
        {"indicator": "ema-21", "InstrumentType": "OPTIONS_BOTH"},
    ]
    return {
        "strategyId": "python_default",
        "name": "Python Strategy",
        "indicators": default_indicators,
    }

def setup_fund_manager(args, rule_config):
    pos_config = {
        "symbol": "NIFTY",
        "quantity": 1, # Default placeholder, will be recalculated by FundManager
        "stop_loss_points": args.stop_loss_points,
        "target_points": args.target_points,
        "trailing_sl_points": args.trailing_sl_points,
        "tsl_indicator_id": args.tsl_indicator_id,
        "use_break_even": args.use_break_even,
        "instrument_type": args.instrument_type,
        "strike_selection": args.strike_selection,
        "invest_mode": args.invest_mode,
        "budget": args.budget,
        "python_strategy_path": args.python_strategy_path,
        # Pyramiding
        "pyramid_steps": args.pyramid_steps,
        "pyramid_confirm_pts": args.pyramid_confirm_pts,
        "price_source": args.price_source
    }
    
    logger.info(f"Initializing FundManager with Strategy: {args.strategy_id} and Position Config: {pos_config}")
    fm = FundManager(strategy_config=rule_config, position_config=pos_config, is_backtest=True)
    return fm

def main():
    parser = get_parser()
    args = parser.parse_args()
    
    if args.end is None:
        args.end = args.start
        
    rule_config = fetch_strategy_config(args.strategy_id, args.python_strategy_path)
    
    # Priority: CLI Argument > DB Configuration
    strategy_path = args.python_strategy_path or rule_config.get("pythonStrategyPath")
    
    if not strategy_path:
        logger.error("--python-strategy-path is required if not defined in the strategy document (e.g. packages/tradeflow/python_strategies.py:TripleLockStrategy)")
        sys.exit(1)
        
    # Inject back into args for consistency if loaded from DB
    args.python_strategy_path = strategy_path
    
    fm = setup_fund_manager(args, rule_config)
    bot = BacktestBot(fm, args=args)
    
    if args.mode == "db":
        try:
            from tests.backtest.db_mode import DBFeeder
            feeder = DBFeeder()
        except ImportError:
            logger.error("DBFeeder not implemented yet.")
            sys.exit(1)
    else:
        try:
            from tests.backtest.socket_mode import SocketFeeder
            feeder = SocketFeeder()
        except ImportError:
            logger.error("SocketFeeder not implemented yet.")
            sys.exit(1)
            
    try:
        feeder.start(bot, fm)
    except KeyboardInterrupt:
        logger.info("Backtest Interrupted.")
    except Exception as e:
        logger.error(f"Backtest failed with error: {e}")
        import traceback
        logger.error(traceback.format_exc())
    finally:
        logger.info("Generating Backtest Report...")
        bot._report()

if __name__ == "__main__":
    main()
