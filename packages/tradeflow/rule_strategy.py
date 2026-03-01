from typing import Dict, Any, List, Optional, Tuple
from packages.tradeflow.types import CandleType, SignalType, MarketIntentType, SignalReturnType
import logging

logger = logging.getLogger(__name__)

# SignalType Enum moved to tradeflow.types as SignalType
# SignalTypeReturnType moved to tradeflow.types

class RuleStrategy:
    """
    Stateless Rule Engine.
    Evaluates market conditions dynamically based on JSON-DSL strategy rules from DB.
    """
    def __init__(self, strategy_config: Dict[str, Any]):
        """
        Args:
            strategy_config (Dict): The full strategy rule document from DB.
        """
        self.config = strategy_config
        self.entry_config = self.config.get('entry', {})
        self.exit_config = self.config.get('exit', {})
        
    def on_resampled_candle_closed(
        self, 
        candle: CandleType, 
        indicators: Dict[str, Any], 
        current_position_intent: Optional[MarketIntentType] = None
    ) -> SignalTypeReturnType:
        """
        Evaluates the dynamic Rule Engine against the latest market data.
        
        Args:
            candle: The finalized resampled candle.
            indicators: Dictionary containing all required indicators for all timeframes
                                produced by IndicatorCalculator. Example: {'NIFTY_fast_ema': 15000, 'CE_rsi': 60}
            current_position_intent: The intent of the currently open position (MarketIntentType.LONG or MarketIntentType.SHORT).
            
        Returns:
            SignalTypeReturnType: A tuple of (SignalType, Reason, Confidence).
        """
        if not indicators:
            return SignalType.NEUTRAL, "N/A", 0.0
            
        # 1. Check Explicit Exits if we are in a position
        if current_position_intent and self.exit_config:
            is_pos_short = (current_position_intent == MarketIntentType.SHORT)
            match_exit, reason_exit = self._evaluate_flat_config(self.exit_config, indicators, is_short=is_pos_short)
            if match_exit:
                return SignalType.EXIT, reason_exit, 1.0
                
        # 2. Evaluate Entries
        intent = self.entry_config.get('intent', 'AUTO')
        
        match_long, reason_long = False, "N/A"
        match_short, reason_short = False, "N/A"
        
        if intent in ["AUTO", "LONG"]:
            match_long, reason_long = self._evaluate_flat_config(self.entry_config, indicators, is_short=False)
            
        if intent in ["AUTO", "SHORT"]:
            match_short, reason_short = self._evaluate_flat_config(self.entry_config, indicators, is_short=True)
            
        if match_long:
            return SignalType.LONG, reason_long, 1.0
        elif match_short:
            return SignalType.SHORT, reason_short, 1.0
            
        return SignalType.NEUTRAL, "N/A", 0.0

    def _evaluate_flat_config(self, config_block: Dict[str, Any], indicators: Dict[str, float], is_short: bool = False, parent_evaluate_spot: bool = True, parent_evaluate_inverse: bool = True) -> tuple[bool, str]:
        """
        Evaluates a flat condition block handling ACTIVE_, INVERSE_ mapping, and Spot inversion.
        Returns (match_status, reason)
        """
        if not config_block:
            return False, "N/A"
            
        operator = config_block.get('operator', 'AND')
        conditions = config_block.get('conditions', [])
        evaluate_spot = config_block.get('evaluateSpot', parent_evaluate_spot)
        evaluate_inverse = config_block.get('evaluateInverse', parent_evaluate_inverse)
        
        if not conditions:
            return False, "N/A"
            
        # Determine actual prefixes based on intent direction
        active_prefix = "PE_" if is_short else "CE_"
        inverse_prefix = "CE_" if is_short else "PE_"
        
        results = []
        
        for base_cond in conditions:
            # Handle recursive nested condition blocks (e.g. an OR block inside an AND block)
            if "conditions" in base_cond:
                match, reason = self._evaluate_flat_config(
                    base_cond, indicators, is_short=is_short,
                    parent_evaluate_spot=evaluate_spot, parent_evaluate_inverse=evaluate_inverse
                )
                results.append((match, f"[{reason}]"))
                continue
                
            # Check what type of condition this is by its prefix
            is_active = False
            is_inverse = False
            
            for v in base_cond.values():
                if isinstance(v, str):
                    if "ACTIVE_" in v: is_active = True
                    if "INVERSE_" in v: is_inverse = True
            
            is_spot = not (is_active or is_inverse)
            
            # Filter out conditions we don't want to evaluate based on config flags
            if is_inverse and not evaluate_inverse:
                continue
            if is_spot and not evaluate_spot:
                continue
                
            # Prepare the condition mapping
            eval_cond = base_cond.copy()
            for key in ['indicatorId', 'fastIndicatorId', 'slowIndicatorId', 'valueIndicatorId']:
                if isinstance(eval_cond.get(key), str):
                    val = eval_cond[key]
                    if val.startswith("ACTIVE_"):
                        val = val.replace("ACTIVE_", active_prefix, 1)
                    elif val.startswith("INVERSE_"):
                        val = val.replace("INVERSE_", inverse_prefix, 1)
                    elif not val.startswith(("CE_", "PE_", "NIFTY_")):
                        # Auto-apply NIFTY_ prefix for spot indicators
                        val = f"NIFTY_{val}"
                    eval_cond[key] = val
                    
            # Options (ACTIVE/INVERSE) cross the SAME way for both Calls and Puts (price goes up = good)
            # Spot must be inverted if we are shorting (Put)
            should_invert = True if (is_spot and is_short) else False
            
            match, reason = self._evaluate_condition(eval_cond, indicators, invert=should_invert)
            results.append((match, reason))
            
        if not results:
            return False, "N/A"
            
        if operator == 'AND':
            # All evaluated conditions must be true
            for match, reason in results:
                if not match:
                    return False, "N/A"
            return True, results[0][1] if results else "N/A"
            
        elif operator == 'OR':
            # Any evaluated condition can be true
            for match, reason in results:
                if match:
                    return True, reason
            return False, "N/A"
            
        return False, "N/A"
        
    def _evaluate_condition(self, condition: Dict[str, Any], indicators: Dict[str, float], invert: bool = False) -> tuple[bool, str]:
        """
        Evaluates a single primitive condition.
        Returns (match_status, reason)
        """
        cond_type = condition.get('type')
        reason = cond_type.upper() if cond_type else "N/A"
        
        if cond_type == 'crossover':
            fast_id = condition.get('fastIndicatorId')
            slow_id = condition.get('slowIndicatorId')
            
            fast_curr = indicators.get(fast_id)
            slow_curr = indicators.get(slow_id)
            fast_prev = indicators.get(f"{fast_id}_prev")
            slow_prev = indicators.get(f"{slow_id}_prev")
            
            if fast_curr is None or slow_curr is None:
                return False, "N/A"
            
            if fast_prev is not None and slow_prev is not None:
                if not invert:
                    match = (fast_prev <= slow_prev) and (fast_curr > slow_curr)
                    desc = f"{fast_id} ({fast_curr:.2f}) crossed over {slow_id} ({slow_curr:.2f})" if match else ""
                    return match, desc
                else:
                    match = (fast_prev >= slow_prev) and (fast_curr < slow_curr)
                    desc = f"{fast_id} ({fast_curr:.2f}) crossed under {slow_id} ({slow_curr:.2f})" if match else ""
                    return match, desc
            else:
                # Fallback for first candle
                if not invert:
                    match = fast_curr > slow_curr
                    desc = f"{fast_id} ({fast_curr:.2f}) is above {slow_id} ({slow_curr:.2f})" if match else ""
                    return match, desc
                else:
                    match = fast_curr < slow_curr
                    desc = f"{fast_id} ({fast_curr:.2f}) is below {slow_id} ({slow_curr:.2f})" if match else ""
                    return match, desc
                
        elif cond_type == 'crossunder':
            fast_id = condition.get('fastIndicatorId')
            slow_id = condition.get('slowIndicatorId')
            
            fast_curr = indicators.get(fast_id)
            slow_curr = indicators.get(slow_id)
            fast_prev = indicators.get(f"{fast_id}_prev")
            slow_prev = indicators.get(f"{slow_id}_prev")
            
            if fast_curr is None or slow_curr is None:
                return False, "N/A"
                
            if fast_prev is not None and slow_prev is not None:
                if not invert:
                    match = (fast_prev >= slow_prev) and (fast_curr < slow_curr)
                    desc = f"{fast_id} ({fast_curr:.2f}) crossed under {slow_id} ({slow_curr:.2f})" if match else ""
                    return match, desc
                else:
                    match = (fast_prev <= slow_prev) and (fast_curr > slow_curr)
                    desc = f"{fast_id} ({fast_curr:.2f}) crossed over {slow_id} ({slow_curr:.2f})" if match else ""
                    return match, desc
            else:
                # Fallback for first candle
                if not invert:
                    match = fast_curr < slow_curr
                    desc = f"{fast_id} ({fast_curr:.2f}) is below {slow_id} ({slow_curr:.2f})" if match else ""
                    return match, desc
                else:
                    match = fast_curr > slow_curr
                    desc = f"{fast_id} ({fast_curr:.2f}) is above {slow_id} ({slow_curr:.2f})" if match else ""
                    return match, desc
                
        elif cond_type == 'threshold':
            ind_val = indicators.get(condition.get('indicatorId'))
            op = condition.get('op')
            
            value = condition.get('value')
            value_indicator_id = condition.get('valueIndicatorId')
            
            if value_indicator_id:
                value = indicators.get(value_indicator_id)
            
            if ind_val is None or value is None or op is None:
                return False, "N/A"
                
            # Invert threshold operations for SELL side equivalent
            if invert:
                if op == '>': op = '<'
                elif op == '>=': op = '<='
                elif op == '<': op = '>'
                elif op == '<=': op = '>='
            
            match = False
            if op == '>': match = ind_val > value
            elif op == '<': match = ind_val < value
            elif op == '>=': match = ind_val >= value
            elif op == '<=': match = ind_val <= value
            elif op == '==': match = ind_val == value
            
            desc_val = f"{value_indicator_id} ({value:.2f})" if value_indicator_id else str(value)
            desc = f"{condition.get('indicatorId')} ({ind_val:.2f}) {op} {desc_val}" if match else ""
            return match, desc
            
        elif cond_type == 'direction_match':
            ind_val = indicators.get(condition.get('indicatorId'))
            value = condition.get('value')
            
            if ind_val is None or value is None:
                return False, "N/A"
                
            if invert:
                value = -value # Assuming binary 1/-1 flags
                
            return ind_val == value, reason

        return False, "N/A"
