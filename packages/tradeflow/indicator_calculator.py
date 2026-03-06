import polars as pl
import numpy as np
from typing import Dict, List, Any
from collections import deque
from enum import Enum
from packages.tradeflow.types import InstrumentCategoryType
from packages.utils.trade_formatter import TradeFormatter
import logging

logger = logging.getLogger(__name__)

# InstrumentCategory Enum removed - now imported as InstrumentCategoryType from tradeflow.types

class IndicatorCalculator:
    """
    Calculates technical indicators dynamically based on strategy rules.
    Maintains separate rolling windows of historical candles per instrument category (SPOT, CE, PE).
    """
    def __init__(self, indicators_config: List[Dict[str, Any]], max_window_size: int = 200):
        """
        Args:
            indicators_config (List[Dict]): The 'indicators' array from strategy_rules DB.
                Example: [{'indicatorId': 'fast_ema', 'type': 'EMA', 'params': {'period': 5}, 'instrumentData': 'SPOT'}, ...]
            max_window_size (int): Max candles to keep per category.
        """
        self.config = indicators_config
        self.max_window_size = max_window_size
        
        # Dictionary of deques, keyed by instrument_category (e.g., InstrumentCategoryType.SPOT)
        self.category_candles: Dict[InstrumentCategoryType, deque] = {}
        # Track last instrument ID per category to detect switches
        self.category_instrument_ids: Dict[InstrumentCategoryType, int | None] = {}
        
        # Initialize deques for each unique instrument category
        for ind in self.config:
            cat_str = ind.get('InstrumentType', 'SPOT')
            try:
                cat = InstrumentCategoryType(cat_str)
            except ValueError:
                logger.warning(f"Unrecognized InstrumentType '{cat_str}' in config, defaulting to SPOT")
                # InstrumentCategoryType Enum removed - now imported as InstrumentCategoryTypeType from tradeflow.types
                cat = InstrumentCategoryType.SPOT

            if cat not in self.category_candles:
                self.category_candles[cat] = deque(maxlen=self.max_window_size)
                self.category_instrument_ids[cat] = None
                
    def add_candle(self, candle: Dict, instrument_category: InstrumentCategoryType = InstrumentCategoryType.SPOT, instrument_id: int | None = None) -> Dict[str, float | str | None]:
        """
        Ingests a new candle for a specific instrument category, and recalculates those indicators.
        """
        if isinstance(instrument_category, str):
            try:
                instrument_category = InstrumentCategoryType(instrument_category)
            except ValueError:
                logger.warning(f"Unrecognized instrument category string '{instrument_category}', defaulting to SPOT")
                instrument_category = InstrumentCategoryType.SPOT

        if instrument_category not in self.category_candles:
            self.category_candles[instrument_category] = deque(maxlen=self.max_window_size)
            self.category_instrument_ids[instrument_category] = None
            
        # Detect Instrument Switch
        if instrument_id is not None:
            last_id = self.category_instrument_ids.get(instrument_category)
            if last_id is not None and last_id != instrument_id:
                logger.info(TradeFormatter.format_instrument_switch(instrument_category.value, last_id, instrument_id))
                self.category_candles[instrument_category].clear()
            
            self.category_instrument_ids[instrument_category] = instrument_id
            
        ts = candle.get('timestamp', candle.get('t'))
        
        # Deduplication
        if self.category_candles[instrument_category] and self.category_candles[instrument_category][-1]['timestamp'] == ts:
            return {}

        c = {
            'open': candle.get('open', candle.get('o')),
            'high': candle.get('high', candle.get('h')),
            'low': candle.get('low', candle.get('l')),
            'close': candle.get('close', candle.get('c')),
            'volume': candle.get('volume', candle.get('v', 0)),
            'timestamp': ts
        }
        self.category_candles[instrument_category].append(c)
        
        if len(self.category_candles[instrument_category]) < 1:
            return {}
            
        # Create DataFrame with explicit schema to avoid inference errors (e.g., Int64 vs Float64)
        schema = {
            'open': pl.Float64,
            'high': pl.Float64,
            'low': pl.Float64,
            'close': pl.Float64,
            'volume': pl.Float64,
            'timestamp': pl.Int64
        }
        df = pl.DataFrame(list(self.category_candles[instrument_category]), schema=schema)
        
        # Calculate indicators for this specific category
        indicators_to_calc = []
        for ind in self.config:
            itype_str = ind.get('InstrumentType', 'SPOT')
            try:
                itype = InstrumentCategoryType(itype_str)
            except ValueError:
                itype = InstrumentCategoryType.SPOT

            if itype == instrument_category:
                indicators_to_calc.append(ind)
            elif itype == InstrumentCategoryType.OPTIONS_BOTH and instrument_category in [InstrumentCategoryType.CE, InstrumentCategoryType.PE]:
                indicators_to_calc.append(ind)
        
        try:
            for ind in indicators_to_calc:
                df = self.calculate_indicator(df, ind['type'], ind['params'], ind['indicatorId'])

            # Extract latest values
            result = {}
            last_row = df.row(-1, named=True)
            prev_row = df.row(-2, named=True) if df.height >= 2 else None
            
            cat_val = instrument_category.value if hasattr(instrument_category, "value") else str(instrument_category)
            prefix = "NIFTY_" if instrument_category == InstrumentCategoryType.SPOT else f"{cat_val}_"
            
            for ind in indicators_to_calc:
                orig_key = ind['indicatorId']
                ind_type = ind.get('type')
                
                keys_to_extract = [orig_key]
                if ind_type == 'SUPERTREND':
                    keys_to_extract.append(f"{orig_key}_dir")
                elif ind_type == 'MACD':
                    keys_to_extract.extend([f"{orig_key}_signal", f"{orig_key}_hist"])
                    
                for k in keys_to_extract:
                    prefixed_key = f"{prefix}{k}"
                    if k in last_row:
                        result[prefixed_key] = last_row[k]
                    if prev_row and k in prev_row:
                        result[f"{prefixed_key}_prev"] = prev_row[k]
            
            return result
        except Exception as e:
            logger.error(f"Error calculating indicators for category {instrument_category}: {e}", exc_info=True)
            return {}

    @staticmethod
    def calculate_indicator(df: pl.DataFrame, ind_type: str, params: Dict[str, Any], result_key: str) -> pl.DataFrame:
        """
        Centralized logic for indicator calculations on a Polars DataFrame.
        """
        if ind_type == 'EMA':
            period = params.get('period', 14)
            return df.with_columns(
                pl.col("close").ewm_mean(span=period, adjust=False).alias(result_key)
            )
            
        elif ind_type == 'RSI':
            period = params.get('period', 14)
            delta = df.select(pl.col("close").diff()).to_series()
            gain = delta.clip(lower_bound=0)
            loss = delta.clip(upper_bound=0).abs()
            
            avg_gain = gain.ewm_mean(alpha=1/period, adjust=False, min_samples=period)
            avg_loss = loss.ewm_mean(alpha=1/period, adjust=False, min_samples=period)
            
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))
            return df.with_columns(pl.Series(name=result_key, values=rsi))

        elif ind_type == 'ATR':
            period = params.get('period', 14)
            # tr = max(h-l, abs(h-c_prev), abs(l-c_prev))
            prev_close = df.select(pl.col("close").shift(1)).to_series()
            tr = pl.max_horizontal([
                pl.col("high") - pl.col("low"),
                (pl.col("high") - prev_close).abs(),
                (pl.col("low") - prev_close).abs()
            ])
            atr = tr.ewm_mean(span=period, adjust=False)
            return df.with_columns(atr.alias(result_key))

        elif ind_type == 'SUPERTREND':
            period = params.get('period', 10)
            multiplier = params.get('multiplier', 3.0)
            return IndicatorCalculator._calc_supertrend(df, period, multiplier, result_key)
            
        elif ind_type == 'MACD':
            fast = params.get('fastPeriod', 12)
            slow = params.get('slowPeriod', 26)
            signal = params.get('signalPeriod', 9)
            
            ema_fast = df.select(pl.col("close").ewm_mean(span=fast, adjust=False)).to_series()
            ema_slow = df.select(pl.col("close").ewm_mean(span=slow, adjust=False)).to_series()
            macd_line = ema_fast - ema_slow
            macd_signal = macd_line.ewm_mean(span=signal, adjust=False)
            macd_hist = macd_line - macd_signal
            
            return df.with_columns([
                macd_line.alias(f"{result_key}"),
                macd_signal.alias(f"{result_key}_signal"),
                macd_hist.alias(f"{result_key}_hist")
            ])

        else:
            logger.warning(f"Unknown indicator type: {ind_type}")
            return df

    @staticmethod
    def _calc_supertrend(df: pl.DataFrame, period: int, multiplier: float, result_key: str) -> pl.DataFrame:
        """
        Implementation of Supertrend using Polars and a small recursive loop for final bands.
        """
        # 1. Calculate ATR
        prev_close = df.select(pl.col("close").shift(1)).to_series()
        tr_expr = pl.max_horizontal([
            pl.col("high") - pl.col("low"),
            (pl.col("high") - prev_close).abs(),
            (pl.col("low") - prev_close).abs()
        ]).fill_null(strategy="zero")
        atr_expr = tr_expr.ewm_mean(span=period, adjust=False)
        atr = df.select(atr_expr).to_series().to_numpy()
        
        # 2. Basic Bands
        hl2 = ((df["high"] + df["low"]) / 2).to_numpy()
        upper_basic = hl2 + (multiplier * atr)
        lower_basic = hl2 - (multiplier * atr)
        
        closes = df["close"].to_numpy()
        n = len(closes)
        
        upper_final = np.zeros(n)
        lower_final = np.zeros(n)
        supertrend = np.zeros(n)
        direction = np.zeros(n) # 1 for Bullish, -1 for Bearish
        
        for i in range(n):
            if i == 0:
                upper_final[i] = upper_basic[i]
                lower_final[i] = lower_basic[i]
                direction[i] = 1
                supertrend[i] = lower_final[i]
            else:
                # Upper Final
                if upper_basic[i] < upper_final[i-1] or closes[i-1] > upper_final[i-1]:
                    upper_final[i] = upper_basic[i]
                else:
                    upper_final[i] = upper_final[i-1]
                    
                # Lower Final
                if lower_basic[i] > lower_final[i-1] or closes[i-1] < lower_final[i-1]:
                    lower_final[i] = lower_basic[i]
                else:
                    lower_final[i] = lower_final[i-1]
                
                # Direction and Supertrend
                if direction[i-1] == 1:
                    if closes[i] <= lower_final[i]:
                        direction[i] = -1
                        supertrend[i] = upper_final[i]
                    else:
                        direction[i] = 1
                        supertrend[i] = lower_final[i]
                else:
                    if closes[i] >= upper_final[i]:
                        direction[i] = 1
                        supertrend[i] = lower_final[i]
                    else:
                        direction[i] = -1
                        supertrend[i] = upper_final[i]
        
        return df.with_columns([
            pl.Series(name=result_key, values=supertrend),
            pl.Series(name=f"{result_key}_dir", values=direction)
        ])
