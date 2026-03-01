from typing import TypedDict, Any, Tuple
from enum import Enum, auto

class SignalType(Enum):
    LONG = 1
    SHORT = -1
    NEUTRAL = 0
    EXIT = 2

class MarketIntentType(Enum):
    LONG = auto()
    SHORT = auto()

class InstrumentKindType(Enum):
    CASH = auto()
    FUTURES = auto()
    OPTIONS = auto()

class InstrumentCategoryType(Enum):
    SPOT = "SPOT"
    CE = "CE"
    PE = "PE"
    OPTIONS_BOTH = "OPTIONS_BOTH" # Pseudo-category for Rule seeding

class CandleType(TypedDict):
    """
    Represents a finalized resampled candle.
    Used across all strategy types (Rule, ML, Python).
    """
    instrument_id: int
    timestamp: int  # Unix epoch seconds (period start)
    open: float
    high: float
    low: float
    close: float
    volume: int
    is_final: bool

# Type Aliases for cleaner signatures
SignalReturnType = Tuple[SignalType, str, float]
