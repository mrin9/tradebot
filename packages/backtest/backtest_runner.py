import argparse
import sys
import os

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from packages.utils.log_utils import setup_logger
from packages.utils.mongo import MongoRepository
from packages.tradeflow.fund_manager import FundManager
from packages.backtest.backtest_base import BacktestBot
from packages.config import settings

logger = setup_logger("BacktestRunner")

def get_parser():
    parser = argparse.ArgumentParser(description="Backtest Runner")
    parser.add_argument("--mode", type=str, choices=["db", "socket"], default="db", help="Backtest mode: db or socket")
    parser.add_argument("--start", type=str, default="2026-02-02", help="Start Date (YYYY-MM-DD)")
    parser.add_argument("--end", type=str, default=None, help="End Date (YYYY-MM-DD). Defaults to --start if omitted.")
    parser.add_argument("--rule-id", type=str, default=None, help="Strategy Rule ID (from DB). Optional for ML mode.")
    parser.add_argument("--budget", type=float, default=200000.0, help="Initial Capital")
    parser.add_argument("--sl", type=float, default=settings.BACKTEST_STOP_LOSS, help="Stop Loss Points")
    parser.add_argument("--target-steps", type=str, default=settings.BACKTEST_TARGET_STEPS, help="Comma separated target points")
    parser.add_argument("--trailing-sl", type=float, default=0.0, help="Trailing Stop Loss Points (0 to disable)")
    parser.add_argument("--no-break-even", action="store_true", help="Disable Break-Even trailing on first target")
    parser.add_argument("--instrument-type", type=str, choices=["CASH", "OPTIONS"], default="OPTIONS", help="Instrument to trade")
    parser.add_argument("--option-type", type=str, choices=["ITM", "ATM", "OTM"], default="ATM", help="Option Strike selection")
    parser.add_argument("--invest-mode", type=str, choices=["compound", "fixed"], default=settings.BACKTEST_INVEST_MODE)
    parser.add_argument("--socket-event", type=str, choices=["1505-json-full", "1501-json-full", "1501-json-partial"], default="1505-json-full", help="Event to listen to on socket mode")
    # Hybrid Strategy & Pyramiding
    parser.add_argument("--strategy-mode", type=str, choices=["rule", "ml", "python_code"], default="rule", help="Strategy engine: rule (JSON-DSL), ml, or python_code")
    parser.add_argument("--python-strategy-path", type=str, default=None, help="Path to custom python strategy file")
    parser.add_argument("--ml-model-path", type=str, default=None, help="Path to trained ML model file (.joblib/.onnx)")
    parser.add_argument("--ml-confidence", type=float, default=0.65, help="Minimum confidence threshold for ML signals")
    parser.add_argument("--pyramid-steps", type=str, default="100", help="Comma-separated entry percentages (e.g., 25,50,25 or 100 for all-in)")
    parser.add_argument("--pyramid-confirm-pts", type=float, default=10.0, help="Points price must move in our favor before next pyramid step")
    parser.add_argument("--warmup-candles", type=int, default=settings.BACKTEST_WARMUP_CANDLES, help="Number of candles to use for indicator warmup")
    return parser

def fetch_strategy_rule(rule_id: str, strategy_mode: str = "rule"):
    if not rule_id:
        if strategy_mode == "ml":
            # ML mode doesn't need a rule — provide a minimal stub
            logger.info("No --rule-id provided. ML mode uses self-contained features.")
            return {"ruleId": "ML_SELF_CONTAINED", "name": "ML Self-Contained", "indicators": [], "entry": {}}
        elif strategy_mode == "python_code":
            logger.info("No --rule-id provided for Python mode. Using dummy rule with default standard indicators.")
            return {
                "ruleId": "PYTHON_DUMMY", 
                "name": "Python Strategy Stub", 
                "indicators": [
                    { "indicatorId": "fast_ema", "type": "EMA", "params": { "period": 9 }, "InstrumentType": "SPOT" },
                    { "indicatorId": "slow_ema", "type": "EMA", "params": { "period": 21 }, "InstrumentType": "SPOT" },
                    { "indicatorId": "opt_fast_ema", "type": "EMA", "params": { "period": 9 }, "InstrumentType": "OPTIONS_BOTH" },
                    { "indicatorId": "opt_slow_ema", "type": "EMA", "params": { "period": 21 }, "InstrumentType": "OPTIONS_BOTH" },
                    { "indicatorId": "macd", "type": "MACD", "params": { "fast": 12, "slow": 26, "signal": 9 }, "InstrumentType": "SPOT" },
                    { "indicatorId": "opt_macd", "type": "MACD", "params": { "fast": 12, "slow": 26, "signal": 9 }, "InstrumentType": "OPTIONS_BOTH" }
                ], 
                "entry": {}
            }
        else:
            logger.error("--rule-id is required in Rule mode.")
            sys.exit(1)
    db = MongoRepository.get_db()
    rule = db['strategy_rules'].find_one({"ruleId": rule_id})
    if not rule:
        logger.error(f"Rule ID '{rule_id}' not found in DB.")
        sys.exit(1)
    return rule

def setup_fund_manager(args, rule_config):
    pos_config = {
        "symbol": "NIFTY",
        "quantity": 1, # Default placeholder, will be recalculated by FundManager
        "stop_loss_points": args.sl,
        "target_points": args.target_steps,
        "trailing_sl_points": args.trailing_sl,
        "use_break_even": not args.no_break_even,
        "instrument_type": args.instrument_type,
        "option_type": args.option_type,
        "invest_mode": args.invest_mode,
        "budget": args.budget,
        # Hybrid Strategy
        "strategy_mode": args.strategy_mode,
        "python_strategy_path": args.python_strategy_path,
        "ml_model_path": args.ml_model_path,
        "ml_confidence": args.ml_confidence,
        # Pyramiding
        "pyramid_steps": args.pyramid_steps,
        "pyramid_confirm_pts": args.pyramid_confirm_pts
    }
    
    logger.info(f"Initializing FundManager with Rule: {args.rule_id} and Position Config: {pos_config}")
    fm = FundManager(strategy_config=rule_config, position_config=pos_config, is_backtest=True)
    return fm

def main():
    parser = get_parser()
    args = parser.parse_args()
    
    if args.end is None:
        args.end = args.start
        
    rule_config = fetch_strategy_rule(args.rule_id, args.strategy_mode)
    fm = setup_fund_manager(args, rule_config)
    bot = BacktestBot(fm, args=args)
    
    if args.mode == "db":
        try:
            from packages.backtest.db_mode import DBFeeder
            feeder = DBFeeder()
        except ImportError:
            logger.error("DBFeeder not implemented yet.")
            sys.exit(1)
    else:
        try:
            from packages.backtest.socket_mode import SocketFeeder
            feeder = SocketFeeder(socket_event=args.socket_event)
        except ImportError:
            logger.error("SocketFeeder not implemented yet.")
            sys.exit(1)
            
    try:
        feeder.start(bot, fm, warmup_candles=args.warmup_candles)
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
