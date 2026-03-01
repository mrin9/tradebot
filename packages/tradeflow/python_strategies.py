from typing import Dict, Any, Tuple, Optional
from packages.tradeflow.types import CandleType, SignalType, MarketIntentType, SignalReturnType

class TripleLockStrategy:
    """Target this via CLI: --python-strategy-path packages/tradeflow/python_strategies.py:TripleLockStrategy"""
    
    def on_resampled_candle_closed(
        self, 
        candle: CandleType, 
        indicators: Dict[str, Any], 
        current_position_intent: Optional[MarketIntentType] = None
    ) -> Tuple[SignalType, str, float]:
        """
        Processes a finalized candle to determine trading signals.

        Args:
            candle: The finalized OHLCV data for the current timeframe.
            indicators: A dictionary of pre-calculated technical indicators (e.g., NIFTY_fast_ema, CE_fast_ema).
            current_position_intent: The intent of the currently open position, if any (MarketIntentType.LONG or MarketIntentType.SHORT).

        Returns:
            A tuple containing:
                - SignalType: The generated trade signal (LONG, SHORT, EXIT, or NEUTRAL).
                - str: A human-readable reason or log message for the signal.
                - float: Confidence score (usually 1.0 for crossover strategies).
        """
        spot_fast = indicators.get("NIFTY_fast_ema")
        spot_slow = indicators.get("NIFTY_slow_ema")

        # FundManager pre-populates ACTIVE and INVERSE keys for you based on current_position_intent!
        active_fast = indicators.get("ACTIVE_fast_ema")
        active_slow = indicators.get("ACTIVE_slow_ema")
        inverse_fast = indicators.get("INVERSE_fast_ema")
        inverse_slow = indicators.get("INVERSE_slow_ema")

        # Wait for warmup
        # 1. Gather Required Data
        ce_fast = indicators.get("CE_fast_ema")
        ce_slow = indicators.get("CE_slow_ema")
        ce_f_prev = indicators.get("CE_fast_ema_prev")
        ce_s_prev = indicators.get("CE_slow_ema_prev")

        pe_fast = indicators.get("PE_fast_ema")
        pe_slow = indicators.get("PE_slow_ema")
        pe_f_prev = indicators.get("PE_fast_ema_prev")
        pe_s_prev = indicators.get("PE_slow_ema_prev")

        # Wait for history
        if ce_f_prev is None or pe_f_prev is None:
            return SignalType.NEUTRAL, "PYTHON: WAITING FOR PREV DATA", 0.0

        # 2. Entry Logic (Bidirectional)
        if current_position_intent is None:
            # --- CHECK CALL ENTRY ---
            if (ce_f_prev <= ce_s_prev) and (ce_fast > ce_slow): # Crossover
                if spot_fast > spot_slow and pe_fast < pe_slow: # Confirmations
                    return SignalType.LONG, "PYTHON: Triple Lock CALL Entry", 1.0

            # --- CHECK PUT ENTRY ---
            if (pe_f_prev <= pe_s_prev) and (pe_fast > pe_slow): # Crossover
                if spot_fast < spot_slow and ce_fast < ce_slow: # Confirmations
                    return SignalType.SHORT, "PYTHON: Triple Lock PUT Entry", 1.0

        # 3. Exit Logic
        if current_position_intent == MarketIntentType.LONG:
            if (ce_f_prev >= ce_s_prev) and (ce_fast < ce_slow): # Crossunder
                return SignalType.EXIT, "PYTHON: CALL Crossunder Exit", 0.0
        elif current_position_intent == MarketIntentType.SHORT:
            if (pe_f_prev >= pe_s_prev) and (pe_fast < pe_slow): # Crossunder
                return SignalType.EXIT, "PYTHON: PUT Crossunder Exit", 0.0
            
        return SignalType.NEUTRAL, "No signal", 0.0

class SimpleMACDStrategy:
    """Target this via CLI: --python-strategy-path packages/tradeflow/python_strategies.py:SimpleMACDStrategy"""
    
    def __init__(self):
        # Maintain state for both CE and PE histograms
        self.ce_prev_hist = None
        self.pe_prev_hist = None

    def on_resampled_candle_closed(
        self, 
        candle: CandleType, 
        indicators: Dict[str, Any], 
        current_position_intent: Optional[MarketIntentType] = None
    ) -> Tuple[SignalType, str, float]:
        """
        Standard MACD Strategy. Crosses over/under 0 to trigger entries/exits.

        Args:
            candle: The finalized OHLCV data.
            indicators: Dictionary containing calculated indicators (e.g., CE_macd_hist, PE_macd_hist).
            current_position_intent: The current trade direction (MarketIntentType).

        Returns:
            Tuple[SignalType, str, float]: (SignalType, Reason, Confidence)
        """
        # Use explicit CE and PE prefixes
        ce_hist = indicators.get("CE_macd_hist")
        pe_hist = indicators.get("PE_macd_hist")

        # Wait for warmup
        if ce_hist is None or pe_hist is None:
            return SignalType.NEUTRAL, "PYTHON: WARMING UP", 0.0

        signal = SignalType.NEUTRAL
        reason = "No signal"

        # 1. Entry Logic (Bidirectional)
        if current_position_intent is None:
            if self.ce_prev_hist is not None and self.ce_prev_hist <= 0 and ce_hist > 0:
                signal, reason = SignalType.LONG, "PYTHON: CE MACD Crossover"
            elif self.pe_prev_hist is not None and self.pe_prev_hist <= 0 and pe_hist > 0:
                signal, reason = SignalType.SHORT, "PYTHON: PE MACD Crossover"

        # 2. Exit Logic (Bidirectional)
        elif current_position_intent == MarketIntentType.LONG:
            if self.ce_prev_hist is not None and self.ce_prev_hist > 0 and ce_hist <= 0:
                signal, reason = SignalType.EXIT, "PYTHON: CE MACD Crossunder Exit"
        elif current_position_intent == MarketIntentType.SHORT:
            if self.pe_prev_hist is not None and self.pe_prev_hist > 0 and pe_hist <= 0:
                signal, reason = SignalType.EXIT, "PYTHON: PE MACD Crossunder Exit"

        # Update state for the next candle
        self.ce_prev_hist = ce_hist
        self.pe_prev_hist = pe_hist

        return signal, reason, 1.0 if signal in [SignalType.LONG, SignalType.SHORT] else 0.0
