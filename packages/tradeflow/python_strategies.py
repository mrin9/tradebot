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
        spot_fast = indicators.get("nifty-ema-5")
        spot_slow = indicators.get("nifty-ema-21")

        # active/inverse mapping provided by FundManager
        active_fast = indicators.get("active-ema-5")
        active_slow = indicators.get("active-ema-21")
        inverse_fast = indicators.get("inverse-ema-5")
        inverse_slow = indicators.get("inverse-ema-21")

        # 1. Gather Required Data
        ce_fast = indicators.get("ce-ema-5")
        ce_slow = indicators.get("ce-ema-21")
        ce_f_prev = indicators.get("ce-ema-5-prev")
        ce_s_prev = indicators.get("ce-ema-21-prev")

        pe_fast = indicators.get("pe-ema-5")
        pe_slow = indicators.get("pe-ema-21")
        pe_f_prev = indicators.get("pe-ema-5-prev")
        pe_s_prev = indicators.get("pe-ema-21-prev")

        # Wait for history and ensure all indicators are non-None
        required_indicators = [
            ce_fast, ce_slow, ce_f_prev, ce_s_prev,
            pe_fast, pe_slow, pe_f_prev, pe_s_prev,
            spot_fast, spot_slow
        ]
        if any(v is None for v in required_indicators):
            return SignalType.NEUTRAL, "PYTHON: WAITING FOR INDICATOR WARMUP", 0.0

        if "nifty-ema-5" in indicators: # Just a heartbeat to know we reached logic
             pass # print(f"--- TRIPLE LOCK EVAL --- CE: {ce_fast:.2f}/{ce_slow:.2f} PE: {pe_fast:.2f}/{pe_slow:.2f} SPOT: {spot_fast:.2f}/{spot_slow:.2f}")

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
        # Use explicit ce and pe prefixes
        ce_hist = indicators.get("ce-macd-hist")
        pe_hist = indicators.get("pe-macd-hist")

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

class EmaCrossStrategy:
    """
    Example Strategy utilizing the new Indicator-Based TSL.
    Entry: EMA-3 crossing EMA-21
    Exit: Delegated to PositionManager (EMA-5 TSL)
    """
    def on_resampled_candle_closed(
        self, 
        candle: CandleType, 
        indicators: Dict[str, Any], 
        current_position_intent: Optional[MarketIntentType] = None
    ) -> Tuple[SignalType, str, float]:
        
        # active/inverse mapping provided by FundManager
        active_f = indicators.get("active-ema-3")
        active_s = indicators.get("active-ema-21")
        active_f_prev = indicators.get("active-ema-3-prev")
        active_s_prev = indicators.get("active-ema-21-prev")

        # ce/pe specific indicators for initial entry
        ce_f = indicators.get("ce-ema-3")
        ce_s = indicators.get("ce-ema-21")
        ce_f_prev = indicators.get("ce-ema-3-prev")
        ce_s_prev = indicators.get("ce-ema-21-prev")

        pe_f = indicators.get("pe-ema-3")
        pe_s = indicators.get("pe-ema-21")
        pe_f_prev = indicators.get("pe-ema-3-prev")
        pe_s_prev = indicators.get("pe-ema-21-prev")

        # 1. Warmup Check
        if any(v is None for v in [ce_f, ce_s, ce_f_prev, ce_s_prev, pe_f, pe_s, pe_f_prev, pe_s_prev]):
            return SignalType.NEUTRAL, "PYTHON: WARMING UP", 0.0

        # 2. Entry Logic
        if current_position_intent is None:
            # Check CE Crossover
            if ce_f_prev <= ce_s_prev and ce_f > ce_s:
                return SignalType.LONG, "EMA-3 Crosses EMA-21 (CE)", 1.0
            
            # Check PE Crossover
            if pe_f_prev <= pe_s_prev and pe_f > pe_s:
                return SignalType.SHORT, "EMA-3 Crosses EMA-21 (PE)", 1.0

        # 3. Exit Logic
        # NOTE: We do NOT implement EMA-5 crossunder exit here. 
        # By providing active-ema-5 as 'tsl_indicator_id' in your strategy config,
        # the PositionManager handles that automatically on every tick!
        
        return SignalType.NEUTRAL, "No entry signal", 0.0
