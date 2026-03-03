# ML Training & Integration Guide (Phase 2)

Train an XGBoost classifier on historical NIFTY Spot candles from MongoDB, then run real model inference inside the Tradeflow pipeline.

> **Phase 1 (Done)**: Strategy abstraction (`BaseStrategy` Protocol), `DummyMLStrategy`, Pyramiding, CLI updates.
> **Phase 2 (This Doc)**: Feature engineering, model training, real inference, CLI `train-model` command.

---

## Architecture Overview

```
                      TRAINING (Offline)
MongoDB (nifty_candle) ──► FeatureBuilder ──► train.py (XGBoost) ──► models/*.joblib

                      INFERENCE (Online / Backtest)
Ticks ──► CandleResampler ──► MLStrategy.on_candle() ──► Signal
                                    │
                                    ├── Internal rolling candle window
                                    ├── Computes RSI, EMA, ATR, returns, time
                                    └── model.predict_proba() → LONG / SHORT / NEUTRAL
```

- **Training**: `FeatureBuilder` reads raw 1-min candles → resamples → computes features → labels them → `train.py` trains XGBoost with Walk-Forward validation → saves `.joblib`.
- **Inference**: `MLStrategy` is **fully self-contained**. It maintains its own rolling candle window, computes all features internally (no `IndicatorCalculator` or `--rule-id` needed), and runs prediction.

---

## Feature Set (40 features in 3 groups)

### BASE (9 features) — price action & time

| Feature | Computation |
|---------|-------------|
| `rsi_14` | RSI(14) on close |
| `ema_fast` | EMA(5) on close |
| `ema_slow` | EMA(20) on close |
| `ema_diff` | `ema_fast − ema_slow` (crossover proxy) |
| `atr_14` | Average True Range(14) |
| `return_1` | 1-bar % return |
| `return_3` | 3-bar % return |
| `hour` | Hour of day (9–15) |
| `minute_bucket` | Minute / 15 (0–3 within the hour) |

### INDICATORS (18 features) — technical analysis

| Feature | Computation |
|---------|-------------|
| `macd` | MACD Line (EMA12 − EMA26) |
| `macd_signal` | MACD Signal (EMA9 of MACD) |
| `macd_histogram` | MACD − Signal |
| `bb_upper` / `bb_lower` | Bollinger Bands (20, 2σ) |
| `bb_width` | Band width as % of SMA |
| `bb_position` | Position within bands (0=lower, 1=upper) |
| `stoch_k` / `stoch_d` | Stochastic Oscillator (14, 3) |
| `vwap` / `vwap_diff` | VWAP and % distance from it |
| `obv_slope` | On-Balance Volume slope (5-bar) |
| `williams_r` | Williams %R (14) |
| `rsi_7` | Fast RSI(7) |
| `return_5` / `return_10` | 5 and 10-bar returns |
| `volatility_5` / `volatility_14` | Rolling return std dev |

### CANDLES (13 features) — candlestick patterns

| Feature | What it detects |
|---------|-----------------|
| `body_ratio` | Body size relative to range (0=doji, 1=marubozu) |
| `upper_shadow_ratio` | Upper wick / total range |
| `lower_shadow_ratio` | Lower wick / total range |
| `is_bullish` | Close > Open (1.0 / 0.0) |
| `doji` | Tiny body (< 10% of range) |
| `hammer` | Long lower wick, small body at top |
| `inverted_hammer` | Long upper wick, small body at bottom |
| `bullish_engulfing` | Current bullish body covers previous bearish body |
| `bearish_engulfing` | Current bearish body covers previous bullish body |
| `marubozu` | Full body candle (> 90% of range) |
| `spinning_top` | Small body with equal-length wicks |
| `morning_star` | 3-bar bullish reversal pattern |
| `evening_star` | 3-bar bearish reversal pattern |

> Features are computed identically during training (`feature_builder.py`) and inference (`ml_strategy.py`). Both use pure math on raw OHLCV candles — no external indicator config required.

---

## Model Algorithms

The trainer supports two primary algorithms:

1. **XGBoost** (`--model-type xgboost`): Gradient Boosting Decision Trees. Excellent at capturing non-linear relationships. Handles large feature sets well.
2. **Random Forest** (`--model-type random_forest`): Bagging approach. Often more robust to outliers and noise. Good baseline.

Common parameters are mapped to each algorithm:
- `--trees` → `n_estimators` (XGB/RF)
- `--depth` → `max_depth` (XGB/RF)
- `--lr` → `learning_rate` (XGB only)
- `--min-child` → `min_child_weight` (XGB) or `min_samples_leaf` (RF)

---

## Labeling Logic

- Look at the **max/min close** in the next `N` bars (default N=6 = 30 min on 5-min candles).
- `LONG (1)`: forward return > +threshold (default 0.15%)
- `SHORT (-1)`: forward return < -threshold
- `NEUTRAL (0)`: price stays flat within ±threshold

---

## Walk-Forward Validation

Standard random train/test splits cause **look-ahead bias** in time-series data.

**Walk-Forward approach**:
1. Train on months 1–3, test on month 4.
2. Train on months 1–4, test on month 5.
3. Repeat until the last month.

Each fold produces accuracy/precision/recall metrics. The final model is trained on all available data.

---

## File Layout

```
packages/ml/
├── __init__.py
├── feature_builder.py    # Feature engineering + labeling
└── train.py              # Walk-forward training script

models/
├── .gitkeep
└── nifty_xgb_YYYYMMDD.joblib   # Trained models (gitignored)

packages/tradeflow/
└── ml_strategy.py        # MLStrategy (self-contained features + model inference)
```

---

## CLI Commands

### Train a Model (with defaults)

```bash
python apps/cli/main.py train-model --start 2025-08-01 --end 2026-02-20
```

Or via interactive menu:

```bash
python apps/cli/main.py menu
# → Select "Train ML Model"
```

### Train with All Parameters (copy-paste and edit)

```bash
python apps/cli/main.py train-model \
  --start 2025-08-01 \
  --end 2026-02-20 \
  --threshold 0.15 \
  --forward-bars 6 \
  --folds 3 \
  --trees 300 \
  --depth 4 \
  --lr 0.05 \
  --min-child 5 \
  --features base,indicators,candles \
  --model-type xgboost \
  --output-dir models \
  --model-name my_v1 
```

> [!IMPORTANT]
> **New Naming Convention**:
> - The trainer **always** attaches a prefix based on the model type: `xgb_` or `rf_`.
> - If you omit `--model-name`, it defaults to the current date `YYYYMMDD`.
> - If you provide `--model-name my_v1`, it will be saved as `xgb_my_v1.joblib` (for XGBoost).

> [!TIP]
> **Saving vs Loading**:
> - During **Training** (`train-model`), use `--output-dir` and `--model-name` to define where the model file is **created**.
> - During **Backtesting** (`backtest_runner`), use `--ml-model-path` (e.g. `models/xgb_my_v1.joblib`) to define which file to **load**.

### Preset: XGBoost Default

```bash
python apps/cli/main.py train-model \
  --start 2025-08-01 --end 2026-02-20 \
  --model-name xgb_v1 \
  --model-type xgboost
```

### Preset: Random Forest Default

```bash
python apps/cli/main.py train-model \
  --start 2025-08-01 --end 2026-02-20 \
  --model-name rf_v1 \
  --model-type random_forest
```

### Preset: Aggressive (more signals, lower bar)

```bash
python apps/cli/main.py train-model \
  --start 2025-08-01 --end 2026-02-20 \
  --model-name aggressive_v1 \
  --threshold 0.10 --forward-bars 4 \
  --depth 5 --trees 400
```

### Preset: Conservative (fewer, higher-quality signals)

```bash
python apps/cli/main.py train-model \
  --start 2025-08-01 --end 2026-02-20 \
  --model-name conservative_v1 \
  --threshold 0.25 --forward-bars 12 \
  --depth 3 --min-child 10
```

### Preset: Base + Candle Patterns Only (no indicators)

```bash
python apps/cli/main.py train-model \
  --start 2025-08-01 --end 2026-02-20 \
  --model-name candle_only_v1 \
  --features base,candles
```

### Preset: Base + Indicators Only (no candle patterns)

```bash
python apps/cli/main.py train-model \
  --start 2025-08-01 --end 2026-02-20 \
  --model-name indicators_only_v1 \
  --features base,indicators
```

### Preset: Without Class Balancing

```bash
python apps/cli/main.py train-model \
  --start 2025-08-01 --end 2026-02-20 \
  --model-name raw_accuracy_v1 \
  --no-balance
```

### See All Available Options

```bash
python apps/cli/main.py train-model --help
```

---

## Training Parameters Reference

### Data & Labeling

| Parameter | CLI Flag | Default | Description |
|-----------|----------|---------|-------------|
| **Start Date** | `--start` | *(prompted)* | First day of training data (YYYY-MM-DD). Use the earliest date you have candle data for. |
| **End Date** | `--end` | *(prompted)* | Last day of training data. Should be **before** the dates you want to backtest on (avoid data leakage). |
| **Model Name** | `--model-name` | *(auto)* | Output filename (without `.joblib`). If omitted, auto-generates `nifty_xgb_YYYYMMDD`. Example: `--model-name my_experiment_v1` → saves `models/my_experiment_v1.joblib`. |
| **Threshold** | `--threshold` | `0.15` | **% move required to label a candle as LONG or SHORT.** Lower = more LONG/SHORT labels (more training signals). Higher = only strong moves count. If your model keeps predicting NEUTRAL, try lowering this (e.g. `0.10`). |
| **Forward Bars** | `--forward-bars` | `6` | **How many future bars to look ahead for labeling.** Default 6 × 5min = 30 minutes. Increase for longer-term trades (e.g. `12` = 1 hour). |
| **Output Dir** | `--output-dir` | `models` | Folder to save the `.joblib` model file. |
| **Model Name** | `--model-name` | `20260223` | **Custom filename (without ext).** Defaults to current date (YYYYMMDD). Always prefixed with `xgb_` or `rf_`. |
| **Model Type**| `--model-type`| `xgboost` | `xgboost` or `random_forest`. |
| **Features** | `--features` | `base,indicators,candles` | **Comma-separated feature groups to include.** Options: `base` (9), `indicators` (18), `candles` (13). Default uses all 40 features. Use `base,candles` to exclude indicators, or `base,indicators` to exclude candle patterns. |

> [!TIP]
> **Algorithm Confidence Thresholds**:
> - **XGBoost**: Tends to produce more polarized (confident) probabilities. The default `--ml-confidence 0.65` works well.
> - **Random Forest**: Due to its averaging nature, peak probabilities are often lower (e.g. 0.45 - 0.55). If you see zero trades with Random Forest, try lowering the backtest threshold:
>   `python -m packages.backtest.backtest_runner ... --ml-confidence 0.45`

### Class Balancing

| Parameter | CLI Flag | Default | Description |
|-----------|----------|---------|-------------|
| **Class Balance** | `--no-balance` | OFF *(balancing ON)* | **Inverse-frequency sample weighting.** When ON, rare LONG/SHORT samples get higher weight (e.g. 2–3×) so the model doesn't just predict NEUTRAL. Pass `--no-balance` to disable. |

### XGBoost Hyperparameters

| Parameter | CLI Flag | Default | Description |
|-----------|----------|---------|-------------|
| **Trees** | `--trees` | `300` | **Number of boosting rounds.** More trees = better fit but slower training. Try `200–500`. |
| **Max Depth** | `--depth` | `4` | **Maximum tree depth.** Lower = simpler model, less overfitting. Higher = more complex patterns. Range: `3–6`. |
| **Learning Rate** | `--lr` | `0.05` | **Step size shrinkage.** Lower = slower learning, needs more trees. Range: `0.01–0.1`. |
| **Min Child Weight** | `--min-child` | `5` | **Minimum samples per leaf node.** Higher = more conservative (avoids learning noise). Range: `3–10`. |
| **Folds** | `--folds` | `3` | **Walk-Forward validation folds.** More folds = more robust evaluation but less training data per fold. |

### Tuning Tips

- **Model predicts only NEUTRAL?** → Lower `--threshold` (try `0.10`) or ensure `--no-balance` is NOT set.
- **Too many false signals?** → Raise `--threshold` (try `0.20`), increase `--min-child`, or lower `--depth`.
- **Overfitting (train accuracy >> test accuracy)?** → Lower `--depth`, raise `--min-child`, lower `--trees`.
- **Want longer-term signals?** → Increase `--forward-bars` (e.g. `12` for 1-hour horizon).

---

### Backtest with Trained Model

ML mode is fully self-contained — no `--rule-id` needed:

```bash
python -m tests.backtest.backtest_runner --mode db \
  --start 2026-02-16 --end 2026-02-16 \
  --strategy-mode ml --ml-confidence 0.45 --ml-model-path models/xgb_v1.joblib
```

> You can still pass `--rule-id` if you want, but it's optional in ML mode.

### Live Trading with ML

```bash
python apps/cli/main.py live-trade \
  --strategy-mode ml --ml-model-path models/nifty_xgb_20260223.joblib
```

---

## Key Design Decisions

1. **Self-Contained ML**: The `MLStrategy` computes its own features from raw candle data. No dependency on `IndicatorCalculator` or strategy rules. You don't choose which indicators matter — the model learns that from data.

2. **Train on NIFTY Spot, Trade Options**: The model learns market *direction* from Spot. The `FundManager` resolves Option contracts separately. This avoids noise from Theta/Vega.

3. **Feature Column Order**: `feature_builder.py` defines a canonical `FEATURE_COLUMNS` list. Both training and inference use this exact order.

4. **XGBoost**: Fast, handles tabular data well, no GPU required. Can be swapped for LightGBM or neural nets later.

5. **Confidence Threshold**: Model returns class probabilities. Only emit a signal if the highest probability exceeds `confidence_threshold` (default 0.65). Configurable via `--ml-confidence` in backtest runner.

---

## Dependencies

```
scikit-learn
xgboost
joblib
libomp          # macOS only: brew install libomp
```
