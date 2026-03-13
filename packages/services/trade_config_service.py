from typing import Dict, Any, List, Optional
from packages.utils.mongo import MongoRepository

from packages.config import settings
from packages.utils.log_utils import setup_logger
from packages.tradeflow.types import InstrumentKindType

logger = setup_logger("TradeConfigService")

class TradeConfigService:
    """
    Centralized service for building, validating, and normalizing trade configurations.
    Consolidates logic from CLI, Backtest Runner, and FundManager.
    """

    @staticmethod
    def fetch_strategy_config(strategy_id: str) -> Dict[str, Any]:
        """
        Fetches strategy configuration from MongoDB by strategyId.
        Centralizes logic previously split between BacktestRunner and CLI.
        """
        db = MongoRepository.get_db()
        strategy = db["strategy_indicators"].find_one({"strategyId": strategy_id})
        
        if not strategy:
            raise ValueError(f"Strategy ID '{strategy_id}' not found in 'strategy_indicators' collection.")
            
        # Normalize and return
        return TradeConfigService.normalize_strategy_config(strategy)

    @staticmethod
    def normalize_strategy_config(raw_config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalizes a strategy document (e.g. from DB) into the internal format.
        Handles casing differences like 'Indicators' vs 'indicators'.
        """
        normalized = raw_config.copy()
        
        # 1. Normalize Indicators Key
        if "Indicators" in normalized and "indicators" not in normalized:
            normalized["indicators"] = normalized.pop("Indicators")
        elif "indicators" not in normalized:
            normalized["indicators"] = []
            
        # 2. Normalize basic fields
        if "timeframe" in normalized and "timeframe_seconds" not in normalized:
            normalized["timeframe_seconds"] = normalized.pop("timeframe")
            
        normalized.setdefault("strategyId", "default")
        normalized.setdefault("name", "Unnamed Strategy")
        normalized.setdefault("timeframe_seconds", settings.DEFAULT_TIMEFRAME)
        
        # 3. Normalize individual indicators
        indicators = normalized.get("indicators", [])
        for ind in indicators:
            if "indicator" not in ind and "type" in ind:
                # Construct shorthand like 'rsi-14' or 'ema-20'
                it_type = ind["type"].lower()
                params = ind.get("params", {})
                if it_type in ["rsi", "ema", "sma", "atr", "vwap", "obv"]:
                    period = params.get("period", 14)
                    ind["indicator"] = f"{it_type}-{period}"
                elif it_type == "supertrend":
                    period = params.get("period", 10)
                    mult = params.get("multiplier", 3.0)
                    ind["indicator"] = f"supertrend-{period}-{mult}"
                elif it_type == "macd":
                    fast = params.get("fast", 12)
                    slow = params.get("slow", 26)
                    sig = params.get("signal", 9)
                    ind["indicator"] = f"macd-{fast}-{slow}-{sig}"
                elif it_type == "bbands":
                    period = params.get("period", 20)
                    dev = params.get("stdDev", 2.0)
                    ind["indicator"] = f"bbands-{period}-{dev}"
                else:
                    ind["indicator"] = it_type

        return normalized

    @staticmethod
    def build_position_config(
        budget: float = 200000.0,
        sl_points: float = 15.0,
        target_points: str | List[float] = "15,25,50",
        tsl_points: float = 0.0,
        tsl_id: Optional[str] = None,
        use_be: bool = True,
        instrument_type: str = "OPTIONS",
        strike_selection: str = "ATM",
        invest_mode: str = "fixed",
        python_strategy_path: Optional[str] = None,
        pyramid_steps: str | List[int] = "100",
        pyramid_confirm_pts: float = 10.0,
        price_source: str = "close",
        symbol: str = "NIFTY",
        **kwargs
    ) -> Dict[str, Any]:
        """
        Factory method to build a validated position_config dictionary.
        """
        # Parse target points
        if isinstance(target_points, str):
            targets = [float(x.strip()) for x in target_points.split(',')]
        else:
            targets = target_points

        # Parse pyramid steps
        if isinstance(pyramid_steps, str):
            steps = [int(s.strip()) for s in pyramid_steps.split(',')]
        else:
            steps = pyramid_steps

        config = {
            "budget": budget,
            "sl_points": sl_points,
            "target_points": targets,
            "tsl_points": tsl_points,
            "tsl_id": tsl_id,
            "use_be": use_be,
            "instrument_type": instrument_type.upper(),
            "strike_selection": strike_selection.upper(),
            "invest_mode": invest_mode.lower(),
            "python_strategy_path": python_strategy_path,
            "pyramid_steps": steps,
            "pyramid_confirm_pts": pyramid_confirm_pts,
            "price_source": price_source.lower(),
            "symbol": symbol,
            **kwargs
        }
        
        # Validation
        if config["invest_mode"] not in ["fixed", "compound"]:
            raise ValueError(f"Invalid invest_mode: {invest_mode}. Must be 'fixed' or 'compound'.")
            
        if config["instrument_type"] not in ["CASH", "OPTIONS", "FUTURES"]:
            raise ValueError(f"Invalid instrument_type: {instrument_type}")

        return config

