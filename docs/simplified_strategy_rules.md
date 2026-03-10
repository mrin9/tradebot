# Simplified Strategy Rules Structure

Since the ML and DSL-based strategies have been removed and the system now relies exclusively on Python code-based strategies, the `strategy_rules` collection in MongoDB can be significantly simplified.

The complex `entry`, `exit`, and `restrictions` JSON blocks are no longer needed because all trading logic is now handled internally by the Python strategy class (e.g., `TripleLockStrategy`). The database document only needs to provide metadata, the required timeframe, and the list of indicators to calculate.

## Final Implemented Schema

Here is the finalized structure for a document in the `strategy_indicators` collection:

```json
{
  "strategyId": "triple-confirmation",
  "name": "Triple Confirmation Momentum",
  "enabled": true,
  "timeframe_seconds": 180,
  "pythonStrategyPath": "packages/tradeflow/python_strategies.py:TripleLockStrategy",
  "Indicators": [
    { "indicatorId": "fast_ema", "indicator": "ema-5", "InstrumentType": "SPOT" },
    { "indicatorId": "slow_ema", "indicator": "ema-21", "InstrumentType": "SPOT" },
    { "indicatorId": "opt_fast_ema", "indicator": "ema-5", "InstrumentType": "OPTIONS_BOTH" },
    { "indicatorId": "opt_slow_ema", "indicator": "ema-21", "InstrumentType": "OPTIONS_BOTH" },
    { "indicatorId": "nifty_price", "indicator": "price", "InstrumentType": "SPOT" }
  ]
}
```

### Supported Indicator String Formats
A parser will translate the `indicator` field into the underlying calculations. Here are some of the standard indicators that can be supported, alongside their short-hand naming convention:

| Indicator Type | Short-hand Format | Example | Explanation |
| :--- | :--- | :--- | :--- |
| **PRICE** | `price` | `price` | Extracts purely the 'close' price object itself (bypassing technical calculation) to use in strategy comparisons. |
| **EMA** (Exponential Moving Average) | `ema-<period>` | `ema-9` | Calculates a 9-period EMA. |
| **SMA** (Simple Moving Average) | `sma-<period>` | `sma-50` | Calculates a 50-period SMA. |
| **RSI** (Relative Strength Index) | `rsi-<period>` | `rsi-14` | Calculates a 14-period RSI. |
| **ATR** (Average True Range) | `atr-<period>` | `atr-14` | Calculates a 14-period ATR. |
| **MACD** (Moving Average Convergence/Divergence) | `macd-<fast>-<slow>-<signal>` | `macd-12-26-9` | Calculates MACD where Fast EMA is 12, Slow EMA is 26, and Signal is 9. |
| **SUPERTREND** | `supertrend-<period>-<multiplier>` | `supertrend-10-3` | Calculates a Supertrend with a 10-period ATR and 3x multiplier. |
| **BBANDS** (Bollinger Bands) | `bbands-<period>-<stddev>` | `bbands-20-2` | Calculates 20-period Bollinger Bands with 2 Standard Deviations. |
| **VWAP** (Volume Weighted Average Price) | `vwap` | `vwap` | Calculates rolling VWAP (usually anchors daily). |
| **OBV** (On-Balance Volume) | `obv` | `obv` | Calculates On-Balance Volume using price and volume deltas. |

### How the Parser will work
When initializing the `IndicatorCalculator`, if an indicator comes in with the short-hand `indicator: "supertrend-10-3"`, we will parse it effectively tracking:
```python
parts = "supertrend-10-3".split("-")
type = parts[0].upper() # SUPERTREND
params = { "period": int(parts[1]), "multiplier": float(parts[2]) }
```

In the special case of `price`, `IndicatorCalculator._extract_results_from_df` will simply forward `df.row(-1, named=True)['close']` to the `indicators` dictionary passed down into the `PythonStrategy`.

### What was removed:
- **`entry`**: The JSON logic for entry conditions (signals, operators, crossover checks) is removed. The python script's `on_resampled_candle_closed` method now handles this.
- **`exit`**: The JSON logic for exit conditions is removed. Handled by the python script.
- **`restrictions`**: Execution constraints like `avoidWindows` and `maxTradesPerDay` can be managed within the python script itself (or handled gracefully at the `FundManager` or `OrderManager` level if needed globally).
