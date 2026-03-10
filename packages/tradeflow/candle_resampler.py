from datetime import datetime
from typing import Dict, Callable
from packages.utils.date_utils import DateUtils

class CandleResampler:
    """
    Resamples smaller timeframe candles (e.g., 1-minute) into larger timeframe candles (e.g., 5-minute).
    """
    def __init__(self, instrument_id: int, interval_seconds: int = 60, on_candle_closed: Callable[[Dict], None] | None = None):
        """
        Args:
            instrument_id (int): Instrument ID to filter/track.
            interval_seconds (int): Target candle interval in seconds (e.g., 300 for 5-min).
            on_candle_closed (callable, optional): Callback for closed candles.
        """
        self.instrument_id = instrument_id
        self.interval_seconds = interval_seconds
        self.on_candle_closed = on_candle_closed
        
        self.current_candle: Dict | None = None
        self.last_period_start: int | None = None

    def reset(self):
        """Resets the resampler state for a clean start."""
        self.current_candle = None
        self.last_period_start = None

    def add_candle(self, candle: Dict) -> Dict | None:
        """
        Aggregates a smaller timeframe candle into the current larger timeframe candle.
        
        Args:
            candle (Dict): Source candle (Open, High, Low, Close, Volume, Timestamp).
                           Expected keys: 'o', 'h', 'l', 'c', 'v', 't' (or 'open', 'high'...)
        
        Returns:
            Dict | None: The *closed* candle if this source candle finalized a period, else None.
        """
        # Normalize input keys if necessary (handle both 'o' and 'open')
        timestamp = candle.get('t', candle.get('timestamp'))
        if timestamp is None:
            return None
            
        # Determine Period Start
        # e.g. timestamp 09:01:00 (541 min) // 5min = 108. 
        # But wait, we need standard period alignment (9:15, 9:20 etc)
        # Using simple epoch division aligns to 00:00:00 UTC naturally.
        
        period_start = (timestamp // self.interval_seconds) * self.interval_seconds
        
        closed_candle = None
        
        # Check if we moved to a new period
        if self.last_period_start is not None and period_start != self.last_period_start:
            if self.current_candle:
                # Close the previous candle
                closed_candle = self.current_candle
                closed_candle['is_final'] = True
                
                if self.on_candle_closed:
                    self.on_candle_closed(closed_candle)
                    
                # Reset for new
                self.current_candle = None
                
        self.last_period_start = period_start
        
        # Extract values with safe fallbacks and explicit casting to float
        c = candle.get('c', candle.get('close', candle.get('p', candle.get('ltp'))))
        o = candle.get('o', candle.get('open', c))
        h = candle.get('h', candle.get('high', c))
        l = candle.get('l', candle.get('low', c))
        v = candle.get('v', candle.get('volume', 0))

        # Enforce float types for price columns to prevent Polars schema mismatches
        o = float(o) if o is not None else None
        h = float(h) if h is not None else None
        l = float(l) if l is not None else None
        c = float(c) if c is not None else None
        v = float(v) if v is not None else 0.0

        # Initialize or Update
        if not self.current_candle:
            self.current_candle = {
                'instrument_id': self.instrument_id,
                'timestamp': period_start,
                'open': o,
                'high': h,
                'low': l,
                'close': c,
                'volume': v,
                'is_final': False 
            }
        else:
            can = self.current_candle
            if h is not None:
                can['high'] = max(can['high'], h) if can['high'] is not None else h
            if l is not None:
                can['low'] = min(can['low'], l) if can['low'] is not None else l
            can['close'] = c # Close is always the latest close
            can['volume'] += v
            
        return closed_candle
