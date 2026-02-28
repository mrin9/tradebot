from packages.tradeflow.rule_strategy import Signal

class TripleLockStrategy:
    """Target this via CLI: --python-strategy-path packages/tradeflow/python_strategies.py:TripleLockStrategy"""
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
                    return Signal.LONG, "PYTHON: Triple Lock CALL Entry", 1.0

            # --- CHECK PUT ENTRY ---
            if (pe_f_prev <= pe_s_prev) and (pe_fast > pe_slow): # Crossover
                if spot_fast < spot_slow and ce_fast < ce_slow: # Confirmations
                    return Signal.SHORT, "PYTHON: Triple Lock PUT Entry", 1.0

        # 3. Exit Logic
        if current_position_intent == "LONG":
            if (ce_f_prev >= ce_s_prev) and (ce_fast < ce_slow): # Crossunder
                return Signal.EXIT, "PYTHON: CALL Crossunder Exit", 0.0
        elif current_position_intent == "SHORT":
            if (pe_f_prev >= pe_s_prev) and (pe_fast < pe_slow): # Crossunder
                return Signal.EXIT, "PYTHON: PUT Crossunder Exit", 0.0
            
        return Signal.NEUTRAL, "No signal", 0.0

class SimpleMACDStrategy:
    """Target this via CLI: --python-strategy-path packages/tradeflow/python_strategies.py:SimpleMACDStrategy"""
    
    def __init__(self):
        # Maintain state for both CE and PE histograms
        self.ce_prev_hist = None
        self.pe_prev_hist = None

    def on_resampled_candle_closed(self, candle, indicators, current_position_intent=None):
        # Use explicit CE and PE prefixes
        ce_hist = indicators.get("CE_opt_macd_hist")
        pe_hist = indicators.get("PE_opt_macd_hist")

        # Wait for warmup
        if ce_hist is None or pe_hist is None:
            return Signal.NEUTRAL, "PYTHON: WARMING UP", 0.0

        signal = Signal.NEUTRAL
        reason = "No signal"

        # 1. Entry Logic (Bidirectional)
        if not current_position_intent:
            if self.ce_prev_hist is not None and self.ce_prev_hist <= 0 and ce_hist > 0:
                signal, reason = Signal.LONG, "PYTHON: CE MACD Crossover"
            elif self.pe_prev_hist is not None and self.pe_prev_hist <= 0 and pe_hist > 0:
                signal, reason = Signal.SHORT, "PYTHON: PE MACD Crossover"

        # 2. Exit Logic (Bidirectional)
        elif current_position_intent == "LONG":
            if self.ce_prev_hist is not None and self.ce_prev_hist > 0 and ce_hist <= 0:
                signal, reason = Signal.EXIT, "PYTHON: CE MACD Crossunder Exit"
        elif current_position_intent == "SHORT":
            if self.pe_prev_hist is not None and self.pe_prev_hist > 0 and pe_hist <= 0:
                signal, reason = Signal.EXIT, "PYTHON: PE MACD Crossunder Exit"

        # Update state for the next candle
        self.ce_prev_hist = ce_hist
        self.pe_prev_hist = pe_hist

        return signal, reason, 1.0 if signal in [Signal.LONG, Signal.SHORT] else 0.0
