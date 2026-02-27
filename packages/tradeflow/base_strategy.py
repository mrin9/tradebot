from typing import Dict, Protocol, runtime_checkable
from packages.tradeflow.rule_strategy import Signal


@runtime_checkable
class BaseStrategy(Protocol):
    """
    Protocol defining the contract for all Strategy implementations.
    Both RuleStrategy and MLModelStrategy must implement this interface.
    """
    def evaluate(self, indicators: Dict[str, float]) -> tuple[Signal, str, float]:
        """
        Evaluates the current market state and returns a trading signal.

        Args:
            indicators (Dict): Dictionary of indicator values from IndicatorCalculator.

        Returns:
            tuple[Signal, str, float]: 
                - Signal: LONG, SHORT, or NEUTRAL.
                - str: Reason string (e.g., "CROSSOVER", "ML_PREDICTION").
                - float: Confidence score between 0.0 and 1.0.
        """
        ...
