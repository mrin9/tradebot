from packages.tradeflow.rule_strategy import Signal

class TripleLockStrategy:
    """Target this via CLI: --python-strategy-path scripts/my_strategies.py:TripleLockStrategy"""
    def on_resampled_candle_closed(self, candle, indicators, current_position_intent=None):
        spot_fast = indicators.get("fast_ema")
        spot_slow = indicators.get("slow_ema")

        # FundManager pre-populates ACTIVE and INVERSE keys for you based on current_position_intent!
        active_fast = indicators.get("ACTIVE_opt_fast_ema")
        active_slow = indicators.get("ACTIVE_opt_slow_ema")
        inverse_fast = indicators.get("INVERSE_opt_fast_ema")
        inverse_slow = indicators.get("INVERSE_opt_slow_ema")

        # Wait for warmup
        # 1. Gather Required Data
        ce_fast = indicators.get("CE_opt_fast_ema")
        ce_slow = indicators.get("CE_opt_slow_ema")
        ce_f_prev = indicators.get("CE_opt_fast_ema_prev")
        ce_s_prev = indicators.get("CE_opt_slow_ema_prev")

        pe_fast = indicators.get("PE_opt_fast_ema")
        pe_slow = indicators.get("PE_opt_slow_ema")
        pe_f_prev = indicators.get("PE_opt_fast_ema_prev")
        pe_s_prev = indicators.get("PE_opt_slow_ema_prev")

        # Wait for history
        if ce_f_prev is None or pe_f_prev is None:
            return Signal.NEUTRAL, "PYTHON: WAITING FOR PREV DATA", 0.0

        # 2. Entry Logic (Bidirectional)
        if not current_position_intent:
            # --- CHECK CALL ENTRY ---
            if (ce_f_prev <= ce_s_prev) and (ce_fast > ce_slow): # Crossover
                if spot_fast > spot_slow and pe_fast < pe_slow: # Confirmations
                    return Signal.LONG, "Triple Lock CALL Entry (Explicit Style)", 1.0

            # --- CHECK PUT ENTRY ---
            if (pe_f_prev <= pe_s_prev) and (pe_fast > pe_slow): # Crossover
                if spot_fast < spot_slow and ce_fast < ce_slow: # Confirmations
                    return Signal.SHORT, "Triple Lock PUT Entry (Explicit Style)", 1.0

        # 3. Exit Logic
        if current_position_intent == "LONG":
            if (ce_f_prev >= ce_s_prev) and (ce_fast < ce_slow): # Crossunder
                return Signal.EXIT, "CALL Crossunder Exit", 0.0
        elif current_position_intent == "SHORT":
            if (pe_f_prev >= pe_s_prev) and (pe_fast < pe_slow): # Crossunder
                return Signal.EXIT, "PUT Crossunder Exit", 0.0
            
        return Signal.NEUTRAL, "No signal", 0.0

class SimpleMACDStrategy:
    """Target this via CLI: --python-strategy-path scripts/my_strategies.py:SimpleMACDStrategy"""
    
    def __init__(self):
        # Because the class is instantiated once per backtest/live-trade, 
        # you can safely maintain state across candles using 'self'
        self.prev_hist = None

    def on_resampled_candle_closed(self, candle, indicators, current_position_intent=None):
        # FundManager pre-populates ACTIVE and INVERSE keys for you!
        # In this strategy, we only care about the Active Option's MACD
        active_macd = indicators.get("ACTIVE_opt_macd")
        active_macd_signal = indicators.get("ACTIVE_opt_macd_signal")
        active_macd_hist = indicators.get("ACTIVE_opt_macd_hist")

        # Wait for warmup
        if any(v is None for v in [active_macd, active_macd_signal, active_macd_hist]):
            return Signal.NEUTRAL, "PYTHON: WARMING UP", 0.0

        # Exact Crossover Logic: 
        # We want to buy ONLY right when the histogram flips from negative to positive.
        
        signal = Signal.NEUTRAL
        reason = "No signal"

        if self.prev_hist is not None:
             if self.prev_hist <= 0 and active_macd_hist > 0:
                 signal = Signal.LONG
                 reason = f"PYTHON: Exact MACD Crossover for {current_position_intent}"

        # Update our state for the *next* candle
        self.prev_hist = active_macd_hist

        return signal, reason, 1.0 if signal == Signal.LONG else 0.0
