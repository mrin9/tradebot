"""
ML Strategy — fully self-contained ML inference.

Maintains its own rolling candle window, computes all features internally
(base + indicators + candle patterns), and runs XGBoost prediction.
Uses IndicatorCalculator for centralized indicator logic.
"""

import os
from typing import Dict, List
from collections import deque
from datetime import datetime
import logging
import numpy as np
import polars as pl

from packages.tradeflow.rule_strategy import Signal
from packages.utils.log_utils import setup_logger
from packages.tradeflow.indicator_calculator import IndicatorCalculator

logger = setup_logger(__name__)

# Label mapping (must match train.py)
CLASS_TO_LABEL = {0: -1, 1: 0, 2: 1}   # 0=SHORT, 1=NEUTRAL, 2=LONG
LABEL_TO_SIGNAL = {1: Signal.LONG, -1: Signal.SHORT, 0: Signal.NEUTRAL}

# Minimum candles needed before prediction
MIN_CANDLE_WINDOW = 30


class MLStrategy:
    """
    ML Strategy.
    Loads a .joblib model, maintains a rolling candle window, 
    computes features, and runs prediction.
    """

    def __init__(self, model_path: str | None = None, confidence_threshold: float = 0.65):
        self.model_path = model_path
        self.confidence_threshold = confidence_threshold
        self.model = None

        # Rolling candle window for feature computation
        self._candles: deque = deque(maxlen=200)
        self._feature_columns = None

        if model_path:
            try:
                import joblib
                self.model = joblib.load(model_path)
                from packages.ml.feature_builder import FEATURE_COLUMNS
                self._feature_columns = FEATURE_COLUMNS
                logger.info(f"🧠 MLStrategy loaded model from: {model_path}")
                logger.info(f"   {len(self._feature_columns)} features expected")
            except Exception as e:
                logger.error(f"Failed to load model from {model_path}: {e}")
                self.model = None
        else:
            logger.warning("MLStrategy initialized without a model path!")

    # ── Public API ──────────────────────────────────────────────────────

    def on_resampled_candle_closed(self, candle: Dict, indicators: Dict | None = None) -> tuple[Signal, str, float]:
        """
        Standardized interface for processing a resampled candle.
        """
        c = {
            'open': candle.get('open', candle.get('o')),
            'high': candle.get('high', candle.get('h')),
            'low': candle.get('low', candle.get('l')),
            'close': candle.get('close', candle.get('c')),
            'volume': candle.get('volume', candle.get('v', 0)),
            'timestamp': candle.get('timestamp', candle.get('t')),
        }
        self._candles.append(c)

        if len(self._candles) < MIN_CANDLE_WINDOW:
            return Signal.NEUTRAL, "ML_WARMING_UP", 0.0

        if self.model is None:
             return Signal.NEUTRAL, "ML_NO_MODEL", 0.0

        return self._predict_from_candles()

    # ── Internal Prediction ─────────────────────────────────────────────

    def _predict_from_candles(self) -> tuple[Signal, str, float]:
        """Compute features from internal candle window, run model prediction."""
        try:
            feature_vec = self._compute_features()
            if feature_vec is None:
                return Signal.NEUTRAL, "ML_FEATURE_ERROR", 0.0

            proba = self.model.predict_proba(feature_vec.reshape(1, -1))[0]
            best_class = int(np.argmax(proba))
            best_prob = float(proba[best_class])
            label = CLASS_TO_LABEL[best_class]
            signal = LABEL_TO_SIGNAL[label]

            logger.debug(f"🔮 ML Proba: SHORT={proba[0]:.3f}, NEUTRAL={proba[1]:.3f}, LONG={proba[2]:.3f} | Best: {CLASS_TO_LABEL[best_class]} ({best_prob:.3f})")

            if best_prob < self.confidence_threshold:
                return Signal.NEUTRAL, "ML_LOW_CONFIDENCE", best_prob

            reason = f"ML_PREDICTION ({os.path.basename(self.model_path)})" if self.model_path else "ML_PREDICTION"
            return signal, reason, best_prob

        except Exception as e:
            logger.error(f"ML prediction error: {e}")
            return Signal.NEUTRAL, "ML_ERROR", 0.0

    def _compute_features(self) -> np.ndarray | None:
        """
        Compute the full feature vector from the internal candle window.
        """
        candles = list(self._candles)
        if len(candles) < MIN_CANDLE_WINDOW:
            return None

        df = pl.DataFrame(candles)
        features = {}

        # ── Modularized Feature Groups ──
        self._add_momentum_features(df, features)
        self._add_volatility_features(df, features)
        self._add_candle_features(df, features)
        self._add_time_features(df, features)

        # ── Build feature vector in canonical order ──
        if self._feature_columns:
            vec = []
            for col in self._feature_columns:
                vec.append(features.get(col, 0.0))
            return np.array(vec, dtype=np.float64)

        return None

    # ── Feature Helpers ─────────────────────────────────────────────────

    def _add_momentum_features(self, df: pl.DataFrame, features: Dict):
        """Adds RSI, EMA, MACD, Stochastic, etc."""
        # RSI
        df_rsi14 = IndicatorCalculator.calculate_indicator(df, 'RSI', {'period': 14}, 'rsi_14')
        df_rsi7 = IndicatorCalculator.calculate_indicator(df, 'RSI', {'period': 7}, 'rsi_7')
        features['rsi_14'] = df_rsi14['rsi_14'].tail(1)[0]
        features['rsi_7'] = df_rsi7['rsi_7'].tail(1)[0]

        # EMAs
        df_ema5 = IndicatorCalculator.calculate_indicator(df, 'EMA', {'period': 5}, 'ema_fast')
        df_ema20 = IndicatorCalculator.calculate_indicator(df, 'EMA', {'period': 20}, 'ema_slow')
        e_fast = df_ema5['ema_fast'].tail(1)[0]
        e_slow = df_ema20['ema_slow'].tail(1)[0]
        features['ema_fast'] = e_fast
        features['ema_slow'] = e_slow
        features['ema_diff'] = e_fast - e_slow

        # MACD
        df_macd = IndicatorCalculator.calculate_indicator(df, 'MACD', {'fastPeriod': 12, 'slowPeriod': 26, 'signalPeriod': 9}, 'macd')
        features['macd'] = df_macd['macd'].tail(1)[0]
        features['macd_signal'] = df_macd['macd_signal'].tail(1)[0]
        features['macd_histogram'] = df_macd['macd_hist'].tail(1)[0]

        # Williams %R (Manual since it's simple)
        high14 = df['high'].tail(14).max()
        low14 = df['low'].tail(14).min()
        close = df['close'].tail(1)[0]
        features['williams_r'] = ((high14 - close) / (high14 - low14)) * -100 if (high14 - low14) > 0 else -50

    def _add_volatility_features(self, df: pl.DataFrame, features: Dict):
        """Adds ATR, Bollinger Bands, Returns, Volatility."""
        # ATR
        df_atr = IndicatorCalculator.calculate_indicator(df, 'ATR', {'period': 14}, 'atr_14')
        features['atr_14'] = df_atr['atr_14'].tail(1)[0]

        # Bollinger Bands (Custom calculation as not in IndicatorCalculator yet)
        period = 20
        multiplier = 2.0
        closes = df['close'].tail(period)
        sma = closes.mean()
        std = closes.std()
        features['bb_upper'] = sma + multiplier * std
        features['bb_lower'] = sma - multiplier * std
        features['bb_width'] = (features['bb_upper'] - features['bb_lower']) / sma * 100 if sma else 0
        features['bb_position'] = (df['close'].tail(1)[0] - features['bb_lower']) / (features['bb_upper'] - features['bb_lower']) if (features['bb_upper'] - features['bb_lower']) > 0 else 0.5

        # Returns
        close = df['close'].to_numpy()
        features['return_1'] = (close[-1] / close[-2] - 1) * 100 if len(close) >= 2 else 0.0
        features['return_3'] = (close[-1] / close[-4] - 1) * 100 if len(close) >= 4 else 0.0
        features['return_5'] = (close[-1] / close[-6] - 1) * 100 if len(close) >= 6 else 0.0
        features['return_10'] = (close[-1] / close[-11] - 1) * 100 if len(close) >= 11 else 0.0

        # Hist Volatility
        rets = np.diff(close) / close[:-1] * 100
        features['volatility_5'] = np.std(rets[-5:]) if len(rets) >= 5 else 0.0
        features['volatility_14'] = np.std(rets[-14:]) if len(rets) >= 14 else 0.0

    def _add_candle_features(self, df: pl.DataFrame, features: Dict):
        """Adds OHLC relationships, Doji, Engulfing, etc."""
        last = df.tail(1).to_dicts()[0]
        o, h, l, c = last['open'], last['high'], last['low'], last['close']
        
        body = abs(c - o)
        rng = h - l
        rng_safe = rng if rng > 0 else 1e-10
        upper_shadow = h - max(o, c)
        lower_shadow = min(o, c) - l

        features['body_ratio'] = body / rng_safe
        features['upper_shadow_ratio'] = upper_shadow / rng_safe
        features['lower_shadow_ratio'] = lower_shadow / rng_safe
        features['is_bullish'] = 1.0 if c > o else 0.0
        features['doji'] = 1.0 if features['body_ratio'] < 0.10 else 0.0
        
        # Engulfing
        if df.height >= 2:
            prev = df.tail(2).to_dicts()[0]
            po, pc = prev['open'], prev['close']
            features['bullish_engulfing'] = 1.0 if (pc < po and c > o and o <= pc and c >= po) else 0.0
            features['bearish_engulfing'] = 1.0 if (pc > po and c < o and o >= pc and c <= po) else 0.0
        else:
            features['bullish_engulfing'] = 0.0
            features['bearish_engulfing'] = 0.0

    def _add_time_features(self, df: pl.DataFrame, features: Dict):
        """Adds Hour/Minute features."""
        ts = df['timestamp'].tail(1)[0]
        dt = datetime.fromtimestamp(ts) if ts else datetime.now()
        features['hour'] = dt.hour
        features['minute_bucket'] = dt.minute // 15


# Backward compatibility alias
DummyMLStrategy = MLStrategy
