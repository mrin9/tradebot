from packages.utils.mongo import MongoRepository
from packages.utils.log_utils import setup_logger

logger = setup_logger("seed_strategy_rules")

RULES = [
    {
        "ruleId": "ema-5x13+rsi-7",
        "name": "EMA 5/13 Scalp + RSI Filter",
        "category": "SCALP",
        "goal": "Fast momentum scalp with RSI confirmation, bidirectional",
        "explanation": (
            "## EMA 5/13 Scalp + RSI Filter\n\n"
            "### Why These Indicators?\n\n"
            "| Indicator | Role | Rationale |\n"
            "|---|---|---|\n"
            "| **EMA 5** (fast) | Signal line | Ultra-short lookback reacts within 2-3 candles to price shifts — ideal for quick scalps |\n"
            "| **EMA 13** (slow) | Trend anchor | Smooths out noise while still being responsive enough for 5-min scalping |\n"
            "| **RSI 7** | Momentum filter | Short-period RSI confirms that momentum is behind the crossover, filtering out weak signals |\n\n"
            "### Entry Logic (AND — all must be true)\n\n"
            "1. **EMA 5 crosses above EMA 13** — price momentum has shifted bullish\n"
            "2. **RSI > 60** — momentum is strong, not just a weak bounce\n\n"
            "Signal `+1` → **Buy CALL** | Signal `-1` → **Buy PUT** (fully bidirectional)\n\n"
            "### Exit Logic (AND — all must be true)\n\n"
            "1. **EMA 5 crosses below EMA 13** — momentum reversal confirmed\n"
            "2. **RSI < 40** — selling pressure is dominant\n\n"
            "Using AND for exit means we hold through minor pullbacks and only exit on confirmed reversals.\n\n"
            "### Restrictions\n\n"
            "- **Avoid 11:00–13:30 IST**: Lunch-hour chop kills scalping — volume drops 40-60%, spreads widen, and false crosses multiply\n"
            "- **Max 4 trades/day**: Scalps can over-trade; capping at 4 preserves capital on choppy days"
        ),
        "enabled": True,
        "applicableTo": ["NIFTY", "BANKNIFTY"],
        "timeframe": 300,
        "indicators": [
            {"indicatorId": "fast_ema", "displayLabel": "Fast EMA", "type": "EMA", "params": {"period": 5}, "InstrumentType": "SPOT"},
            {"indicatorId": "slow_ema", "displayLabel": "Slow EMA", "type": "EMA", "params": {"period": 13}, "InstrumentType": "SPOT"},
            {"indicatorId": "rsi", "displayLabel": "RSI", "type": "RSI", "params": {"period": 7}, "InstrumentType": "SPOT"}
        ],
        "entry": {
            "intent": "AUTO",
            "evaluateSpot": True,
            "evaluateInverse": False,
            "operator": "AND",
            "conditions": [
                {"type": "crossover", "fastIndicatorId": "fast_ema", "slowIndicatorId": "slow_ema"},
                {"type": "threshold", "indicatorId": "rsi", "op": ">", "value": 60}
            ]
        },
        "exit": {
            "evaluateSpot": True,
            "evaluateInverse": False,
            "operator": "AND",
            "conditions": [
                {"type": "crossunder", "fastIndicatorId": "fast_ema", "slowIndicatorId": "slow_ema"},
                {"type": "threshold", "indicatorId": "rsi", "op": "<", "value": 40}
            ]
        },
        "restrictions": {
            "avoidWindows": [{"from": "11:00", "to": "13:30", "tz": "Asia/Kolkata"}],
            "maxTradesPerDay": 4
        }
    },
    {
        "ruleId": "ema-9x21+rsi-14+st-10-3",
        "name": "EMA 9/21 Trend + Supertrend + RSI",
        "category": "TREND",
        "goal": "High-conviction trend entry with multi-indicator confirmation, bidirectional",
        "explanation": (
            "## EMA 9/21 Trend + Supertrend + RSI\n\n"
            "### Why These Indicators?\n\n"
            "| Indicator | Role | Rationale |\n"
            "|---|---|---|\n"
            "| **EMA 9** (fast) | Trend signal | Balanced between responsiveness and noise rejection — standard institutional short-term MA |\n"
            "| **EMA 21** (slow) | Trend baseline | The 21-period EMA is widely watched by institutional traders; crossovers here carry conviction |\n"
            "| **RSI 14** | Momentum filter | Standard period RSI confirms underlying strength — above 50 means buyers are in control |\n"
            "| **Supertrend (10, 3.0)** | Regime filter | Binary trend direction eliminates counter-trend entries — the single most effective whipsaw filter |\n\n"
            "### Entry Logic (AND — all three must be true)\n\n"
            "1. **EMA 9 crosses above EMA 21** — trend shift detected\n"
            "2. **RSI > 50** — buyers are in control (neutral threshold, not overbought)\n"
            "3. **Supertrend direction == 1** — broader trend regime is bullish\n\n"
            "Signal `+1` → **Buy CALL** | Signal `-1` → **Buy PUT** (fully bidirectional)\n\n"
            "Triple confirmation makes this a *high-conviction, low-frequency* strategy. Expect 1-2 trades/day.\n\n"
            "### Exit Logic (AND — both must be true)\n\n"
            "1. **EMA 9 crosses below EMA 21** — trend has reversed\n"
            "2. **Supertrend direction == -1** — regime confirms the reversal\n\n"
            "AND-based exit means we hold through minor RSI dips as long as the trend structure remains intact.\n\n"
            "### Restrictions\n\n"
            "- **Avoid 11:00–13:30 IST**: Trend strategies suffer most during range-bound lunch hours\n"
            "- **Max 3 trades/day**: This is a conviction strategy — if 3 trades whipsaw, the market isn't trending today"
        ),
        "enabled": True,
        "applicableTo": ["NIFTY", "BANKNIFTY"],
        "timeframe": 300,
        "indicators": [
            {"indicatorId": "fast_ema", "displayLabel": "Fast EMA", "type": "EMA", "params": {"period": 9}, "InstrumentType": "SPOT"},
            {"indicatorId": "slow_ema", "displayLabel": "Slow EMA", "type": "EMA", "params": {"period": 21}, "InstrumentType": "SPOT"},
            {"indicatorId": "rsi", "displayLabel": "RSI", "type": "RSI", "params": {"period": 14}, "InstrumentType": "SPOT"},
            {"indicatorId": "supertrend", "displayLabel": "Supertrend", "type": "SUPERTREND", "params": {"period": 10, "multiplier": 3}, "InstrumentType": "SPOT"}
        ],
        "entry": {
            "signals": {"1": "Buy CALL", "-1": "Buy PUT"},
            "operator": "AND",
            "conditions": [
                {"type": "crossover", "fastIndicatorId": "fast_ema", "slowIndicatorId": "slow_ema"},
                {"type": "threshold", "indicatorId": "rsi", "op": ">", "value": 50},
                {"type": "direction_match", "indicatorId": "supertrend", "op": "==", "value": 1}
            ]
        },
        "exit": {
            "operator": "AND",
            "conditions": [
                {"type": "crossunder", "fastIndicatorId": "fast_ema", "slowIndicatorId": "slow_ema"},
                {"type": "direction_match", "indicatorId": "supertrend", "op": "==", "value": -1}
            ]
        },
        "restrictions": {
            "avoidWindows": [{"from": "11:00", "to": "13:30", "tz": "Asia/Kolkata"}],
            "maxTradesPerDay": 3
        }
    },
    {
        "ruleId": "ema-5x21+rsi-14",
        "name": "Trend-following system",
        "category": "TREND",
        "goal": "Exact replica of crossover_and_rsi.py default params for comparison testing",
        "explanation": (
            "## EMA 5/21 + RSI 14 (Legacy Replica)\n\n"
            "### Purpose\n\n"
            "This rule is a **direct translation** of the hardcoded `crossover_and_rsi.py` strategy into the dynamic rule engine. "
            "It exists for **A/B comparison testing** — verifying that the `DynamicStrategy` engine produces identical signals to the legacy implementation.\n\n"
            "### Why These Indicators?\n\n"
            "| Indicator | Role | Rationale |\n"
            "|---|---|---|\n"
            "| **EMA 5** (fast) | Signal line | Very short lookback for aggressive signal generation on 1-min candles |\n"
            "| **EMA 21** (slow) | Trend anchor | Provides ~20 minutes of smoothing on 1-min candles, capturing short-term trend direction |\n"
            "| **RSI 14** | Momentum filter | Standard Wilder period — confirms that crossover has genuine momentum behind it |\n\n"
            "### Entry Logic (AND)\n\n"
            "1. **EMA 5 crosses above EMA 21** — short-term price is accelerating above medium-term trend\n"
            "2. **RSI >= 55** — mild bullish bias confirmed (slightly above neutral 50)\n\n"
            "Signal `+1` → **Buy CALL** | Signal `-1` → **Buy PUT** (fully bidirectional)\n\n"
            "### Exit Logic (AND)\n\n"
            "1. **EMA 5 crosses below EMA 21** — trend has reversed\n"
            "2. **RSI <= 45** — mild bearish bias confirmed\n\n"
            "### Notes\n\n"
            "- **1-min candles** produce many signals (~10-15/day). This is intentionally aggressive for comparison testing.\n"
            "- **No restrictions** applied — matches the original legacy implementation's behaviour exactly.\n"
            "- Use this rule to validate the dynamic engine against known legacy results before trusting new strategies."
        ),
        "enabled": True,
        "applicableTo": ["NIFTY", "BANKNIFTY"],
        "timeframe": 60,
        "indicators": [
            {"indicatorId": "fast_ema", "displayLabel": "Fast EMA", "type": "EMA", "params": {"period": 5}, "InstrumentType": "SPOT"},
            {"indicatorId": "slow_ema", "displayLabel": "Slow EMA", "type": "EMA", "params": {"period": 21}, "InstrumentType": "SPOT"},
            {"indicatorId": "rsi", "displayLabel": "RSI", "type": "RSI", "params": {"period": 14}, "InstrumentType": "SPOT"}
        ],
        "entry": {
            "intent": "AUTO",
            "evaluateSpot": True,
            "evaluateInverse": False,
            "operator": "AND",
            "conditions": [
                {"type": "crossover", "fastIndicatorId": "fast_ema", "slowIndicatorId": "slow_ema"},
                {"type": "threshold", "indicatorId": "rsi", "op": ">=", "value": 55.0}
            ]
        },
        "exit": {
            "evaluateSpot": True,
            "evaluateInverse": False,
            "operator": "AND",
            "conditions": [
                {"type": "crossunder", "fastIndicatorId": "fast_ema", "slowIndicatorId": "slow_ema"},
                {"type": "threshold", "indicatorId": "rsi", "op": "<=", "value": 45.0}
            ]
        },
        "restrictions": {}
    },
    {
        "ruleId": "gold-macd-st-slope-5m",
        "name": "Gold Standard – MACD + Supertrend + EMA Slope",
        "category": "TREND",
        "goal": "High-conviction intraday trend-following with triple confirmation: MACD momentum, Supertrend regime, and EMA slope. Designed as the single best daily strategy for NIFTY.",
        "explanation": (
            "## Gold Standard – MACD + Supertrend + EMA Slope\n\n"
            "### Why This Combination?\n\n"
            "NIFTY is institution-dominated. Retail edge comes from **riding confirmed trends**, not predicting reversals. "
            "This strategy uses three *uncorrelated* confirmation layers to eliminate false signals:\n\n"
            "| Indicator | Role | Rationale |\n"
            "|---|---|---|\n"
            "| **MACD (12,26,9)** | Primary signal | The classic momentum-meets-trend indicator. Histogram crossing zero catches trend acceleration early. Battle-tested across all major equity indices. |\n"
            "| **Supertrend (10, 3.0)** | Regime filter | Binary trend direction (bullish/bearish). Prevents taking MACD signals against the dominant trend — the #1 cause of whipsaws. |\n"
            "| **EMA 21** | Slope confirmation | `slope > 0` confirms the 21-period trend is actively rising, not flat with a coincidental MACD crossover. Eliminates sideways chop entries. |\n\n"
            "### Why 5-Minute Candles?\n\n"
            "- NIFTY on 1-min is too noisy for MACD — generates ~15-20 crosses/day, most false\n"
            "- 5-min strikes the balance: ~3-5 signals/day, each with higher conviction\n"
            "- Supertrend on 5-min aligns with NIFTY's typical 30-60 min trend legs\n\n"
            "### Entry Logic (AND — all must be true)\n\n"
            "1. **MACD histogram > 0** — momentum has shifted bullish (histogram = MACD line − signal line)\n"
            "2. **Supertrend direction == 1** — price is above the Supertrend band, confirming bullish regime\n"
            "3. **EMA 21 slope > 0** — the trend is actively rising, not consolidating\n\n"
            "Signal `+1` → **Buy CALL** | Signal `-1` → **Buy PUT** (fully bidirectional)\n\n"
            "When all three invert (histogram < 0, Supertrend == -1, slope < 0), the system exits and takes the opposite trade.\n\n"
            "### Exit Logic (OR — any one sufficient)\n\n"
            "1. **MACD histogram < 0** — momentum has faded\n"
            "2. **Supertrend direction == -1** — trend regime has flipped\n\n"
            "**OR-based exit** is intentionally asymmetric: we enter with high conviction (3 confirmations) but exit fast on the first sign of trouble. "
            "This protects capital — the cost of a missed continuation is far less than the cost of riding a reversal.\n\n"
            "### Restrictions\n\n"
            "- **Avoid 09:15–09:30 IST**: Opening 15 minutes have abnormal spreads, gap fills, and fake breakouts. Indicators need time to calibrate.\n"
            "- **Avoid 11:00–13:00 IST**: Lunch-hour chop — volume drops 40-60%, trends stall, and whipsaw risk peaks.\n"
            "- **Max 3 trades/day**: If stopped out 3 times, the day is not trending. Stepping aside preserves capital for better days."
        ),
        "enabled": True,
        "applicableTo": ["NIFTY"],
        "timeframe": 300,
        "indicators": [
            {"indicatorId": "macd", "displayLabel": "MACD", "type": "MACD", "params": {"fastPeriod": 12, "slowPeriod": 26, "signalPeriod": 9}, "InstrumentType": "SPOT"},
            {"indicatorId": "supertrend", "displayLabel": "Supertrend", "type": "SUPERTREND", "params": {"period": 10, "multiplier": 3.0}, "InstrumentType": "SPOT"},
            {"indicatorId": "ema_21", "displayLabel": "EMA 21", "type": "EMA", "params": {"period": 21}, "InstrumentType": "SPOT"}
        ],
        "entry": {
            "intent": "AUTO",
            "evaluateSpot": True,
            "evaluateInverse": False,
            "operator": "AND",
            "conditions": [
                {"type": "threshold", "indicatorId": "macd_hist", "op": ">", "value": 0},
                {"type": "direction_match", "indicatorId": "supertrend", "op": "==", "value": 1},
                {"type": "slope", "indicatorId": "ema_21", "op": ">", "value": 0}
            ]
        },
        "exit": {
            "evaluateSpot": True,
            "evaluateInverse": False,
            "operator": "OR",
            "conditions": [
                {"type": "threshold", "indicatorId": "macd_hist", "op": "<", "value": 0},
                {"type": "direction_match", "indicatorId": "supertrend", "op": "==", "value": -1}
            ]
        },
        "restrictions": {
            "avoidWindows": [
                {"from": "09:15", "to": "09:30", "tz": "Asia/Kolkata"},
                {"from": "11:00", "to": "13:00", "tz": "Asia/Kolkata"}
            ],
            "maxTradesPerDay": 3
        }
    },
    {
        "ruleId": "triple-lock-momentum",
        "name": "Triple-Lock Momentum Strategy",
        "category": "TREND",
        "goal": "Synchronize Option Crossovers with underlying Spot confirmation.",
        "explanation": "Synchronize three independent data streams (Spot, CE, PE) to filter out noise and capture high-velocity momentum.",
        "enabled": True,
        "applicableTo": ["NIFTY"],
        "timeframe": 300,
        "indicators": [
            { "indicatorId": "fast_ema", "displayLabel": "Fast EMA", "type": "EMA", "params": { "period": 9 }, "InstrumentType": "SPOT" },
            { "indicatorId": "slow_ema", "displayLabel": "Slow EMA", "type": "EMA", "params": { "period": 21 }, "InstrumentType": "SPOT" },
            { "indicatorId": "opt_fast_ema", "displayLabel": "Options Fast EMA", "type": "EMA", "params": { "period": 9 }, "InstrumentType": "OPTIONS_BOTH" },
            { "indicatorId": "opt_slow_ema", "displayLabel": "Options Slow EMA", "type": "EMA", "params": { "period": 21 }, "InstrumentType": "OPTIONS_BOTH" }
        ],
        "entry": {
            "intent": "AUTO",
            "evaluateSpot": True,
            "evaluateInverse": True,
            "operator": "AND",
            "conditions": [
                { "type": "crossover", "fastIndicatorId": "ACTIVE_opt_fast_ema", "slowIndicatorId": "ACTIVE_opt_slow_ema" },
                { "type": "threshold", "indicatorId": "INVERSE_opt_fast_ema", "op": "<", "valueIndicatorId": "INVERSE_opt_slow_ema" },
                { "type": "threshold", "indicatorId": "fast_ema", "op": ">", "valueIndicatorId": "slow_ema" }
            ]
        },
        "exit": {
            "evaluateSpot": False,
            "evaluateInverse": False,
            "operator": "AND",
            "conditions": [
                { "type": "crossunder", "fastIndicatorId": "ACTIVE_opt_fast_ema", "slowIndicatorId": "ACTIVE_opt_slow_ema" }
            ]
        },
        "restrictions": {}
    }
]

def seed_strategy_rules():
    col = MongoRepository.get_collection("strategy_rules")
    col.delete_many({})
    col.insert_many(RULES)
    logger.info(f"Seeded {len(RULES)} strategy rules into strategy_rules collection")
    for r in RULES:
        sig = r['entry'].get('signals', {})
        logger.info(f"  → {r['ruleId']}: {r['name']} | signals: {sig}")

if __name__ == "__main__":
    seed_strategy_rules()
