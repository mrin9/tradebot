from collections.abc import Callable


class CandleResampler:
    """
    Resamples smaller timeframe candles (e.g., 1-minute) into larger timeframe candles (e.g., 5-minute).
    """

    def __init__(
        self, instrument_id: int, interval_seconds: int = 60, on_candle_closed: Callable[[dict], None] | None = None
    ):
        """
        Args:
            instrument_id (int): Instrument ID to filter/track.
            interval_seconds (int): Target candle interval in seconds (e.g., 300 for 5-min).
            on_candle_closed (callable, optional): Callback for closed candles.
        """
        self.instrument_id = instrument_id
        self.interval_seconds = interval_seconds
        self.on_candle_closed = on_candle_closed

        self.current_candle: dict | None = None
        self.last_period_start: int | None = None
        self.source_candle_count = 0
        self.suppress_logs = False

    def reset(self):
        """Resets the resampler state for a clean start."""
        self.current_candle = None
        self.last_period_start = None

    def add_candle(self, candle: dict) -> dict | None:
        """
        Aggregates a smaller timeframe candle into the current larger timeframe candle.

        Args:
            candle (Dict): Source candle (Open, High, Low, Close, Volume, Timestamp).
                           Expected keys: 'o', 'h', 'l', 'c', 'v', 't' (or 'open', 'high'...)

        Returns:
            Dict | None: The *closed* candle if this source candle finalized a period, else None.
        """
        # Normalize input keys if necessary (handle both 'o' and 'open')
        timestamp = candle.get("t", candle.get("timestamp"))
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
                closed_candle["is_final"] = True

                if self.on_candle_closed:
                    if not self.suppress_logs:
                        import logging
                        logger = logging.getLogger(__name__)
                        from datetime import datetime
                        pretty_ts = datetime.fromtimestamp(self.last_period_start).strftime('%H:%M:%S')
                        logger.info(f"💡 [CR] Finalizing {self.interval_seconds // 60}m Candle for {self.instrument_id} @ {pretty_ts} | Source: {self.source_candle_count}m | Close: {closed_candle['close']}")
                    self.on_candle_closed(closed_candle)

                # Reset for new
                self.current_candle = None
                self.source_candle_count = 0

        self.last_period_start = period_start

        # Extract values with safe fallbacks and explicit casting to float
        close_ = candle.get("c", candle.get("close", candle.get("p", candle.get("ltp"))))
        open_ = candle.get("o", candle.get("open", close_))
        high_ = candle.get("h", candle.get("high", close_))
        low_ = candle.get("l", candle.get("low", close_))
        volume_ = candle.get("v", candle.get("volume", 0))

         # Enforce float types for price columns to prevent Polars schema mismatches
        open_ = float(open_) if open_ is not None else None
        high_ = float(high_) if high_ is not None else None
        low_ = float(low_) if low_ is not None else None

        close_ = float(close_) if close_ is not None else None
        volume_ = float(volume_) if volume_ is not None else 0.0

        # Initialize or Update
        if not self.current_candle:
            self.current_candle = {
                "instrument_id": self.instrument_id,
                # MATCH JAVA: Use period START as the candle timestamp
                "timestamp": period_start,
                "open": open_,
                "high": high_,
                "low": low_,
                "close": close_,
                "volume": volume_,
                "is_final": False,
            }
        else:
            can = self.current_candle
            if high_ is not None:
                can["high"] = max(can["high"], high_) if can["high"] is not None else high_
            if low_ is not None:
                can["low"] = min(can["low"], low_) if can["low"] is not None else low_
            if close_ is not None:
                can["close"] = close_  # Only update close if we have a valid price
            
            can["volume"] += volume_
        
        self.source_candle_count += 1

        return closed_candle
