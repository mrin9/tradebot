"""
Feature Builder for ML Model Training.

Reads NIFTY Spot 1-min candles from MongoDB, resamples to the desired timeframe,
engineers features, and labels data for supervised learning.

Feature Groups:
  - BASE: RSI, EMA, ATR, returns, time-of-day
  - INDICATORS: MACD, Bollinger Bands, Stochastic, VWAP, OBV, Williams %R
  - CANDLES: Doji, Hammer, Engulfing, Marubozu, Spinning Top, Morning/Evening Star
"""

import polars as pl
import numpy as np
from datetime import datetime
from typing import Optional, List
import logging

from packages.utils.mongo import MongoRepository
from packages.utils.date_utils import DateUtils
from packages.config import settings

logger = logging.getLogger(__name__)

# ── Feature Groups ─────────────────────────────────────────────────────────
# Each group is independently toggleable via the `feature_sets` parameter.

BASE_FEATURES = [
    "rsi_14", "ema_fast", "ema_slow", "ema_diff",
    "atr_14", "return_1", "return_3",
    "hour", "minute_bucket",
]

INDICATOR_FEATURES = [
    "macd", "macd_signal", "macd_histogram",
    "bb_upper", "bb_lower", "bb_width", "bb_position",
    "stoch_k", "stoch_d",
    "vwap", "vwap_diff",
    "obv_slope",
    "williams_r",
    "rsi_7",
    "return_5", "return_10",
    "volatility_5", "volatility_14",
]

CANDLE_FEATURES = [
    "body_ratio",          # |close - open| / (high - low)
    "upper_shadow_ratio",  # upper wick / range
    "lower_shadow_ratio",  # lower wick / range
    "is_bullish",          # close > open
    "doji",                # tiny body relative to range
    "hammer",              # long lower wick, small body at top
    "inverted_hammer",     # long upper wick, small body at bottom
    "bullish_engulfing",   # current bullish body > previous bearish body
    "bearish_engulfing",   # current bearish body > previous bullish body
    "marubozu",            # full body, almost no wicks
    "spinning_top",        # small body, long equal wicks
    "morning_star",        # 3-bar reversal (down, small, up)
    "evening_star",        # 3-bar reversal (up, small, down)
]

# Map group names to their feature lists
FEATURE_GROUPS = {
    "base": BASE_FEATURES,
    "indicators": INDICATOR_FEATURES,
    "candles": CANDLE_FEATURES,
}

ALL_FEATURE_GROUPS = ["base", "indicators", "candles"]


def get_feature_columns(feature_sets: List[str] = None) -> List[str]:
    """Return the combined list of feature columns for the given feature sets."""
    if feature_sets is None:
        feature_sets = ALL_FEATURE_GROUPS
    columns = []
    for group in feature_sets:
        columns.extend(FEATURE_GROUPS.get(group, []))
    return columns


# Backward compatibility — defaults to ALL features
FEATURE_COLUMNS = get_feature_columns(ALL_FEATURE_GROUPS)


class FeatureBuilder:
    """
    Builds a labeled feature DataFrame from historical NIFTY Spot candles.

    Pipeline:
        MongoDB (nifty_candle) → 1-min candles → resample to N-sec bars
        → compute features → add labels → drop NaN → return DataFrame
    """

    def __init__(
        self,
        resample_seconds: int = 300,
        forward_bars: int = 6,
        threshold_pct: float = 0.15,
        feature_sets: List[str] = None,
    ):
        self.resample_seconds = resample_seconds
        self.forward_bars = forward_bars
        self.threshold_pct = threshold_pct
        self.feature_sets = feature_sets or ALL_FEATURE_GROUPS
        self.feature_columns = get_feature_columns(self.feature_sets)

    # ── Public API ──────────────────────────────────────────────────────────

    def build(self, start_date: str, end_date: str) -> pl.DataFrame:
        """End-to-end: fetch → resample → features → labels."""
        logger.info(f"📊 Building features: {start_date} → {end_date}, "
                     f"resample={self.resample_seconds}s, "
                     f"forward={self.forward_bars} bars, "
                     f"threshold={self.threshold_pct}%")
        logger.info(f"   Feature sets: {self.feature_sets} ({len(self.feature_columns)} features)")

        raw = self._fetch_candles(start_date, end_date)
        logger.info(f"  Fetched {len(raw)} raw 1-min candles")

        if raw.is_empty():
            logger.warning("No candles found. Returning empty DataFrame.")
            return pl.DataFrame()

        resampled = self._resample(raw)
        logger.info(f"  Resampled to {len(resampled)} bars ({self.resample_seconds}s)")

        featured = self._add_all_features(resampled)
        labeled = self._add_labels(featured)

        clean = labeled.drop_nulls()
        logger.info(f"  Final dataset: {len(clean)} rows, "
                     f"{len(self.feature_columns)} features + label")

        return clean

    def build_from_dataframe(self, df: pl.DataFrame) -> pl.DataFrame:
        """Build features from an already-loaded DataFrame (for testing)."""
        resampled = self._resample(df)
        featured = self._add_all_features(resampled)
        labeled = self._add_labels(featured)
        return labeled.drop_nulls()

    # ── Private: Data Fetch ─────────────────────────────────────────────────

    def _fetch_candles(self, start_date: str, end_date: str) -> pl.DataFrame:
        """Fetch 1-min NIFTY candles from MongoDB."""
        db = MongoRepository.get_db()
        start_dt = DateUtils.parse_iso(start_date).replace(hour=9, minute=15, second=0)
        end_dt = DateUtils.parse_iso(end_date).replace(hour=15, minute=30, second=0)
        start_ts = int(start_dt.timestamp())
        end_ts = int(end_dt.timestamp())

        cursor = db[settings.NIFTY_CANDLE_COLLECTION].find(
            {"i": settings.NIFTY_EXCHANGE_INSTRUMENT_ID,
             "t": {"$gte": start_ts, "$lte": end_ts}},
            {"_id": 0, "o": 1, "h": 1, "l": 1, "c": 1, "v": 1, "t": 1}
        ).sort("t", 1)

        rows = list(cursor)
        if not rows:
            return pl.DataFrame()

        return pl.DataFrame(rows).rename({
            "o": "open", "h": "high", "l": "low", "c": "close", "v": "volume", "t": "timestamp"
        })

    # ── Private: Resample ───────────────────────────────────────────────────

    def _resample(self, df: pl.DataFrame) -> pl.DataFrame:
        """Group 1-min candles into N-second OHLCV bars."""
        interval = self.resample_seconds
        return (
            df
            .with_columns((pl.col("timestamp") // interval * interval).alias("bar_ts"))
            .group_by("bar_ts")
            .agg([
                pl.col("open").first().alias("open"),
                pl.col("high").max().alias("high"),
                pl.col("low").min().alias("low"),
                pl.col("close").last().alias("close"),
                pl.col("volume").sum().alias("volume"),
            ])
            .sort("bar_ts")
            .rename({"bar_ts": "timestamp"})
        )

    # ── Feature Dispatcher ──────────────────────────────────────────────────

    def _add_all_features(self, df: pl.DataFrame) -> pl.DataFrame:
        """Dispatch to feature group builders based on self.feature_sets."""
        result = df.clone()

        if "base" in self.feature_sets:
            result = self._add_base_features(result)
        if "indicators" in self.feature_sets:
            result = self._add_indicator_features(result)
        if "candles" in self.feature_sets:
            result = self._add_candle_features(result)

        return result

    # ── BASE Features ───────────────────────────────────────────────────────

    def _add_base_features(self, df: pl.DataFrame) -> pl.DataFrame:
        """RSI(14), EMA fast/slow, ATR, returns, time."""
        result = df

        # EMA fast (5) / slow (20)
        result = result.with_columns([
            pl.col("close").ewm_mean(span=5, adjust=False).alias("ema_fast"),
            pl.col("close").ewm_mean(span=20, adjust=False).alias("ema_slow"),
        ])
        result = result.with_columns(
            (pl.col("ema_fast") - pl.col("ema_slow")).alias("ema_diff")
        )

        # RSI(14)
        delta = result.select(pl.col("close").diff()).to_series()
        gain = delta.clip(lower_bound=0)
        loss = delta.clip(upper_bound=0).abs()
        avg_gain = gain.ewm_mean(alpha=1 / 14, adjust=False, min_samples=14)
        avg_loss = loss.ewm_mean(alpha=1 / 14, adjust=False, min_samples=14)
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        result = result.with_columns(pl.Series("rsi_14", rsi))

        # ATR(14)
        high_low = result["high"] - result["low"]
        high_prev = (result["high"] - result["close"].shift(1)).abs()
        low_prev = (result["low"] - result["close"].shift(1)).abs()
        tr = pl.DataFrame({"hl": high_low, "hp": high_prev, "lp": low_prev}).select(
            pl.max_horizontal("hl", "hp", "lp").alias("tr")
        ).to_series()
        atr = tr.ewm_mean(span=14, adjust=False)
        result = result.with_columns(pl.Series("atr_14", atr))

        # Returns
        result = result.with_columns([
            (pl.col("close").pct_change(1) * 100).alias("return_1"),
            (pl.col("close").pct_change(3) * 100).alias("return_3"),
        ])

        # Time features
        result = result.with_columns([
            pl.col("timestamp")
              .map_elements(lambda ts: datetime.fromtimestamp(ts).hour, return_dtype=pl.Int32)
              .alias("hour"),
            pl.col("timestamp")
              .map_elements(lambda ts: datetime.fromtimestamp(ts).minute // 15, return_dtype=pl.Int32)
              .alias("minute_bucket"),
        ])

        return result

    # ── INDICATOR Features ──────────────────────────────────────────────────

    def _add_indicator_features(self, df: pl.DataFrame) -> pl.DataFrame:
        """MACD, Bollinger Bands, Stochastic, VWAP, OBV, Williams %R."""
        result = df

        # ── MACD (12, 26, 9) ──
        ema12 = result.select(pl.col("close").ewm_mean(span=12, adjust=False)).to_series()
        ema26 = result.select(pl.col("close").ewm_mean(span=26, adjust=False)).to_series()
        macd_line = ema12 - ema26
        macd_signal = macd_line.ewm_mean(span=9, adjust=False)
        macd_hist = macd_line - macd_signal
        result = result.with_columns([
            pl.Series("macd", macd_line),
            pl.Series("macd_signal", macd_signal),
            pl.Series("macd_histogram", macd_hist),
        ])

        # ── Bollinger Bands (20, 2σ) ──
        sma20 = result.select(pl.col("close").rolling_mean(20)).to_series()
        std20 = result.select(pl.col("close").rolling_std(20)).to_series()
        bb_upper = sma20 + 2 * std20
        bb_lower = sma20 - 2 * std20
        bb_width = (bb_upper - bb_lower) / sma20 * 100  # as % of SMA
        # Position within the bands (0 = at lower, 1 = at upper)
        bb_pos = (result["close"] - bb_lower) / (bb_upper - bb_lower)
        result = result.with_columns([
            pl.Series("bb_upper", bb_upper),
            pl.Series("bb_lower", bb_lower),
            pl.Series("bb_width", bb_width),
            pl.Series("bb_position", bb_pos),
        ])

        # ── Stochastic Oscillator (14, 3) ──
        low14 = result.select(pl.col("low").rolling_min(14)).to_series()
        high14 = result.select(pl.col("high").rolling_max(14)).to_series()
        stoch_k = ((result["close"] - low14) / (high14 - low14)) * 100
        stoch_d = stoch_k.rolling_mean(3)
        result = result.with_columns([
            pl.Series("stoch_k", stoch_k),
            pl.Series("stoch_d", stoch_d),
        ])

        # ── VWAP ──
        cum_vol = result.select(pl.col("volume").cum_sum()).to_series()
        cum_tp_vol = (result["close"] * result["volume"]).cum_sum()
        vwap = cum_tp_vol / cum_vol
        vwap_diff = ((result["close"] - vwap) / vwap) * 100  # % diff from VWAP
        result = result.with_columns([
            pl.Series("vwap", vwap),
            pl.Series("vwap_diff", vwap_diff),
        ])

        # ── OBV (On-Balance Volume) slope ──
        close_diff = result.select(pl.col("close").diff()).to_series().fill_null(0)
        obv_direction = close_diff.map_elements(
            lambda x: 1 if x > 0 else (-1 if x < 0 else 0), return_dtype=pl.Int32
        )
        obv = (result["volume"] * obv_direction).cum_sum()
        # Use slope of last 5 bars (normalized)
        obv_series = obv.to_list()
        obv_slope = [None] * min(5, len(obv_series))
        for i in range(5, len(obv_series)):
            w0 = obv_series[i-5]
            w4 = obv_series[i]
            if w0 is not None and w4 is not None and w0 != 0:
                obv_slope.append((w4 - w0) / abs(w0) * 100)
            else:
                obv_slope.append(0.0)
        result = result.with_columns(pl.Series("obv_slope", obv_slope, dtype=pl.Float64))

        # ── Williams %R (14) ──
        williams_r = ((high14 - result["close"]) / (high14 - low14)) * -100
        result = result.with_columns(pl.Series("williams_r", williams_r))

        # ── RSI(7) — faster RSI ──
        delta7 = result.select(pl.col("close").diff()).to_series()
        gain7 = delta7.clip(lower_bound=0)
        loss7 = delta7.clip(upper_bound=0).abs()
        avg_gain7 = gain7.ewm_mean(alpha=1 / 7, adjust=False, min_samples=7)
        avg_loss7 = loss7.ewm_mean(alpha=1 / 7, adjust=False, min_samples=7)
        rs7 = avg_gain7 / avg_loss7
        rsi7 = 100 - (100 / (1 + rs7))
        result = result.with_columns(pl.Series("rsi_7", rsi7))

        # ── Additional returns ──
        result = result.with_columns([
            (pl.col("close").pct_change(5) * 100).alias("return_5"),
            (pl.col("close").pct_change(10) * 100).alias("return_10"),
        ])

        # ── Volatility (rolling std of returns) ──
        ret_pct = result.select(pl.col("close").pct_change(1) * 100).to_series()
        vol5 = ret_pct.rolling_std(5)
        vol14 = ret_pct.rolling_std(14)
        result = result.with_columns([
            pl.Series("volatility_5", vol5),
            pl.Series("volatility_14", vol14),
        ])

        return result

    # ── CANDLE Pattern Features ─────────────────────────────────────────────

    def _add_candle_features(self, df: pl.DataFrame) -> pl.DataFrame:
        """Candlestick pattern recognition from raw OHLCV."""
        opens = df["open"].to_numpy().astype(np.float64)
        highs = df["high"].to_numpy().astype(np.float64)
        lows = df["low"].to_numpy().astype(np.float64)
        closes = df["close"].to_numpy().astype(np.float64)
        n = len(opens)

        body = np.abs(closes - opens)
        rng = highs - lows
        rng_safe = np.where(rng == 0, 1e-10, rng)  # avoid division by zero
        upper_shadow = highs - np.maximum(opens, closes)
        lower_shadow = np.minimum(opens, closes) - lows

        # Body ratio (0 = doji, 1 = marubozu)
        body_ratio = body / rng_safe

        # Shadow ratios
        upper_shadow_ratio = upper_shadow / rng_safe
        lower_shadow_ratio = lower_shadow / rng_safe

        # Bullish candle
        is_bullish = (closes > opens).astype(np.float64)

        # ── Patterns ──

        # Doji: body < 10% of range
        doji = (body_ratio < 0.10).astype(np.float64)

        # Hammer: lower shadow > 2x body, upper shadow < 30% of range, body at top
        hammer = np.zeros(n)
        for i in range(n):
            if body[i] > 0 and lower_shadow[i] > 2 * body[i] and upper_shadow_ratio[i] < 0.3:
                hammer[i] = 1.0

        # Inverted Hammer: upper shadow > 2x body, lower shadow < 30%
        inv_hammer = np.zeros(n)
        for i in range(n):
            if body[i] > 0 and upper_shadow[i] > 2 * body[i] and lower_shadow_ratio[i] < 0.3:
                inv_hammer[i] = 1.0

        # Bullish Engulfing: prev bearish, curr bullish, curr body covers prev body
        bull_engulf = np.zeros(n)
        for i in range(1, n):
            if closes[i-1] < opens[i-1] and closes[i] > opens[i]:  # prev bear, curr bull
                if opens[i] <= closes[i-1] and closes[i] >= opens[i-1]:
                    bull_engulf[i] = 1.0

        # Bearish Engulfing: prev bullish, curr bearish, curr body covers prev body
        bear_engulf = np.zeros(n)
        for i in range(1, n):
            if closes[i-1] > opens[i-1] and closes[i] < opens[i]:  # prev bull, curr bear
                if opens[i] >= closes[i-1] and closes[i] <= opens[i-1]:
                    bear_engulf[i] = 1.0

        # Marubozu: body > 90% of range (almost no wicks)
        marubozu = (body_ratio > 0.90).astype(np.float64)

        # Spinning Top: small body (< 30%), long equal-ish wicks
        spinning_top = np.zeros(n)
        for i in range(n):
            if body_ratio[i] < 0.30 and rng[i] > 0:
                shadow_balance = min(upper_shadow[i], lower_shadow[i]) / max(upper_shadow[i], lower_shadow[i]) if max(upper_shadow[i], lower_shadow[i]) > 0 else 0
                if shadow_balance > 0.5:  # wicks roughly equal
                    spinning_top[i] = 1.0

        # Morning Star (3-bar bullish reversal)
        morning_star = np.zeros(n)
        for i in range(2, n):
            bar1_bearish = closes[i-2] < opens[i-2] and body_ratio[i-2] > 0.5
            bar2_small = body_ratio[i-1] < 0.25  # small/indecision
            bar3_bullish = closes[i] > opens[i] and body_ratio[i] > 0.5
            bar3_above_midpoint = closes[i] > (opens[i-2] + closes[i-2]) / 2
            if bar1_bearish and bar2_small and bar3_bullish and bar3_above_midpoint:
                morning_star[i] = 1.0

        # Evening Star (3-bar bearish reversal)
        evening_star = np.zeros(n)
        for i in range(2, n):
            bar1_bullish = closes[i-2] > opens[i-2] and body_ratio[i-2] > 0.5
            bar2_small = body_ratio[i-1] < 0.25
            bar3_bearish = closes[i] < opens[i] and body_ratio[i] > 0.5
            bar3_below_midpoint = closes[i] < (opens[i-2] + closes[i-2]) / 2
            if bar1_bullish and bar2_small and bar3_bearish and bar3_below_midpoint:
                evening_star[i] = 1.0

        # ── Add all to DataFrame ──
        result = df.with_columns([
            pl.Series("body_ratio", body_ratio),
            pl.Series("upper_shadow_ratio", upper_shadow_ratio),
            pl.Series("lower_shadow_ratio", lower_shadow_ratio),
            pl.Series("is_bullish", is_bullish),
            pl.Series("doji", doji),
            pl.Series("hammer", hammer),
            pl.Series("inverted_hammer", inv_hammer),
            pl.Series("bullish_engulfing", bull_engulf),
            pl.Series("bearish_engulfing", bear_engulf),
            pl.Series("marubozu", marubozu),
            pl.Series("spinning_top", spinning_top),
            pl.Series("morning_star", morning_star),
            pl.Series("evening_star", evening_star),
        ])

        return result

    # ── Labels ──────────────────────────────────────────────────────────────

    def _add_labels(self, df: pl.DataFrame) -> pl.DataFrame:
        """Label each row based on forward-looking returns."""
        closes = df["close"].to_list()
        n = len(closes)
        labels = []

        for i in range(n):
            end = min(i + self.forward_bars + 1, n)
            future_closes = closes[i + 1 : end]

            if not future_closes:
                labels.append(None)
                continue

            current = closes[i]
            max_ret = ((max(future_closes) - current) / current) * 100
            min_ret = ((min(future_closes) - current) / current) * 100

            long_hit = max_ret > self.threshold_pct
            short_hit = min_ret < -self.threshold_pct

            if long_hit and short_hit:
                labels.append(1 if abs(max_ret) >= abs(min_ret) else -1)
            elif long_hit:
                labels.append(1)
            elif short_hit:
                labels.append(-1)
            else:
                labels.append(0)

        return df.with_columns(pl.Series("label", labels, dtype=pl.Int32))
