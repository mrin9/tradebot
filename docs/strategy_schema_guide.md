# TradeFlow Strategy Rules Definition Guide

This guide explains how to define trading strategies for the TradeFlow engine using the internal JSON schema. The system uses a flattened, condition-based evaluation engine that supports multi-instrument "Triple-Lock" alignment automatically.

---

## The Core Concept: The "Active" Focus
The TradeFlow rule engine always evaluates rules from the perspective of the **Active Option** you are trying to buy (or the Option you currently hold).

When you say "I want to buy when an EMA crosses over," the engine assumes you mean: *"I want to buy a CALL when the CALL's EMA crosses over, and I want to buy a PUT when the PUT's EMA crosses over."*

You do not need to write separate rules for Calls and Puts. You define the "Bullish/Entry" scenario once, and the engine automatically figures out the "Bearish/Put" mirror scenario.

---

## 1. Schema Structure Overview

```json
{
  "ruleId": "example-strategy-id",
  "name": "Human Readable Strategy Name",
  "category": "TREND",
  "timeframe": 300,
  "indicators": [ ... ],
  "entry": { ... },
  "exit": { ... },
  "restrictions": { ... }
}
```

### `timeframe` (Integer)
The base timeframe in seconds for the strategy (e.g., `300` for 5-minute candles, `60` for 1-minute). All indicators are calculated on this base interval.

---

## 2. Defining Indicators
The `indicators` array defines the technical indicators the engine needs to calculate. You do not need to prefix these with specific instrument identifiers (like `SPOT_` or `ACTIVE_`); just give them a clean, simple ID.

```json
"indicators": [
  {"indicatorId": "fast_ema", "type": "EMA", "params": {"period": 5}},
  {"indicatorId": "slow_ema", "type": "EMA", "params": {"period": 13}},
  {"indicatorId": "rsi", "type": "RSI", "params": {"period": 7}}
]
```

---

## 3. Entry and Exit Blocks
The `entry` and `exit` blocks strictly define a *flat array* of conditions governed by a single logical operator.

```json
"entry": {
  "evaluateSpot": boolean,
  "evaluateInverse": boolean,
  "operator": "AND" | "OR",
  "intent": "LONG" | "SHORT" | "AUTO",
  "conditions": [ ... ]
}
```

### The Magic Flags: `evaluateSpot` & `evaluateInverse`
These two flags are the secret to the TradeFlow architecture. By default, the engine only evaluates the Active Option chart. By setting these flags, you force the engine to perfectly clone and apply your conditions to the other data streams simultaneously.

*   `evaluateSpot: true`: "Also apply my conditions to the underlying Nifty Spot chart."
*   `evaluateInverse: true`: "Also apply my conditions to the opposite Option chart (flips logic automatically)."

### The `intent` Flag
*   `"AUTO"`: The engine will evaluate the conditions twice on every candle close: once assuming you want to buy a CALL, and once assuming you want to buy a PUT. **This is highly recommended for standard trend strategies.**
*   `"LONG"`: The engine only evaluates the rules to buy a CALL.
*   `"SHORT"`: The engine only evaluates the rules to buy a PUT.

### The `conditions` Array
A flat list of dictionary objects. No nesting is allowed.

**Type 1: `crossover` / `crossunder`**
```json
{"type": "crossover", "fastIndicatorId": "fast_ema", "slowIndicatorId": "slow_ema"}
```

**Type 2: `threshold` (Static Value)**
```json
{"type": "threshold", "indicatorId": "rsi", "op": ">", "value": 60}
```

**Type 3: `threshold` (Dynamic Indicator Comparison)**
```json
{"type": "threshold", "indicatorId": "fast_ema", "op": ">", "valueIndicatorId": "slow_ema"}
```

---

## 4. Examples

### Example A: The Single-Instrument Legacy Rule (Spot Only)
If you want to trade purely based on the Nifty Spot chart, and simply buy ATM Options whenever the Spot index breaks out:

```json
{
  "ruleId": "ema-5x13+rsi-7",
  "name": "Spot EMA Scalp",
  "category": "SCALP",
  "timeframe": 300,
  "indicators": [
    {"indicatorId": "fast_ema", "type": "EMA", "params": {"period": 5}},
    {"indicatorId": "slow_ema", "type": "EMA", "params": {"period": 13}},
    {"indicatorId": "rsi", "type": "RSI", "params": {"period": 7}}
  ],
  "entry": {
    "intent": "AUTO",          // Check both Call and Put scenarios
    "evaluateSpot": true,      // Look at Spot!
    "evaluateInverse": false,  // Ignore options charts entirely
    "operator": "AND",
    "conditions": [
        {"type": "crossover", "fastIndicatorId": "fast_ema", "slowIndicatorId": "slow_ema"},
        {"type": "threshold", "indicatorId": "rsi", "op": ">", "value": 60}
    ]
  },
  "exit": {
    "evaluateSpot": true,      // Look at Spot for the exit!
    "evaluateInverse": false,
    "operator": "AND",
    "conditions": [
        {"type": "crossunder", "fastIndicatorId": "fast_ema", "slowIndicatorId": "slow_ema"}
    ]
  }
}
```

### Example B: The Triple-Lock Strategy (Multi-Instrument Alignment)
You want to buy a CALL *only* when the CALL is breaking out, the PUT is breaking down, and the SPOT index is trending up. 

Because of `intent: "AUTO"`, this entirely handles the PUT entry scenario automatically as well!

```json
{
  "ruleId": "triple-lock-ema",
  "name": "Triple-Lock Options Momentum",
  "category": "TREND",
  "timeframe": 300,
  "indicators": [
    {"indicatorId": "fast_ema", "type": "EMA", "params": {"period": 5}},
    {"indicatorId": "slow_ema", "type": "EMA", "params": {"period": 13}}
  ],
  "entry": {
    "intent": "AUTO",
    "evaluateSpot": true,      // Confirm the Spot trend
    "evaluateInverse": true,   // Confirm the opposite option is crashing
    "operator": "AND",         // ALL conditions must map perfectly
    "conditions": [
        {"type": "crossover", "fastIndicatorId": "fast_ema", "slowIndicatorId": "slow_ema"}
    ]
  },
  "exit": {
    "evaluateSpot": false,     
    "evaluateInverse": false,  
    "operator": "AND",         // Simple Active-Only exit
    "conditions": [
        {"type": "crossunder", "fastIndicatorId": "fast_ema", "slowIndicatorId": "slow_ema"}
    ]
  }
}
```

### Example C: The "Emergency Ripcord" Exit
You are holding a CALL option and waiting for it to cross under to exit. However, you want to bolt for the door if the *PUT* option suddenly rockets upwards before your CALL officially crosses under. 

Notice the use of `"operator": "OR"` paired with `evaluateInverse: true`!

```json
"exit": {
  "evaluateSpot": false,
  "evaluateInverse": true, // Monitor the inverse option!
  "operator": "OR",        // If ACTIVE crosses under OR INVERSE crosses over -> EXIT
  "conditions": [
      {"type": "crossunder", "fastIndicatorId": "fast_ema", "slowIndicatorId": "slow_ema"}
  ]
}
```

---

## 5. Technical Architecture: FundManager ↔ RuleStrategy API Contract

For developers working on the Python codebase, here is how the parsed JSON schema interacts with the execution flow.

### Synchronization
Signals are evaluated **only** when the base timeframe candle (e.g., 5-min NIFTY Spot) closes. The `FundManager` waits for the base candle to close, aggregates the latest indicator values for all tracked instruments (Spot, CE, PE), and passes the entire state to the Rule Engine simultaneously.

### The Input Contract
`RuleStrategy.on_resampled_candle_closed(candle, indicators_state)`

*   **`candle`**: The latest raw Nifty Spot OHLCV dictionary for the closed timeframe.
*   **`indicators_state`**: A unified, flattened dictionary mapping string keys to numerical values (e.g., `{"SPOT_fast_ema": 22100.5, "CE_rsi": 62.1, "PE_macd": -15.2}`). 
    *   *Context Mapping*: If evaluating an `exit`, the `FundManager` dynamically injects `ACTIVE_` aliases for the currently owned position's indicators before passing this state array into the strategy.

### The Output Contract
The strategy evaluates the indicators against the configured rules and returns a tuple: `(Signal, reason_string, confidence_float)`.

How `FundManager` interprets the signals:
*   **`Signal.LONG`**: Executes a Market Buy for the currently tracked ATM CALL (CE) instrument.
*   **`Signal.SHORT`**: Executes a Market Buy for the currently tracked ATM PUT (PE) instrument.
*   **`Signal.NEUTRAL`**: No action taken. If returned during an active trade, the position continues to be held.

*Note: The `RuleStrategy` class itself has no concept of "Call" or "Put". It only knows that its `entry` conditions mapped to `intent: "LONG"` passed (yielding a LONG signal), or its `intent: "SHORT"` conditions passed (yielding a SHORT signal).*

## 6. Real-World Strategy Rule Examples

To make it easy to manage configurations directly in MongoDB without typing complex logic from scratch, here are 12 common strategy entry and exit setups. You can copy/paste these directly into the `conditions` block of your database entries.

### Example 1: Basic Option EMA Crossover
The most fundamental strategy. Buy a Call/Put the moment its fast EMA crosses its slow EMA.
```json
"evaluateSpot": false,
"evaluateInverse": false,
"operator": "AND",
"conditions": [
    {"type": "crossover", "fastIndicatorId": "ACTIVE_ema5", "slowIndicatorId": "ACTIVE_ema21"}
]
```

### Example 2: EMA Crossover + RSI Filter
Wait for a crossover, but only enter the trade if the RSI is above a certain strength threshold (e.g., bullish momentum).
```json
"evaluateSpot": false,
"evaluateInverse": false,
"operator": "AND",
"conditions": [
    {"type": "crossover", "fastIndicatorId": "ACTIVE_ema5", "slowIndicatorId": "ACTIVE_ema21"},
    {"type": "threshold", "indicatorId": "ACTIVE_rsi", "op": ">", "value": 55}
]
```

### Example 3: Triple-Lock State Machine Entry
Enter the trade *only* when the Active option, Nifty Spot, and Inverse option all directionally align. The crossover acts as a trigger, while the thresholds act as state confirmations. Requires Nifty Spot, CE, and PE.
```json
"evaluateSpot": true,
"evaluateInverse": true,
"operator": "AND",
"conditions": [
    {
        "operator": "OR",
        "conditions": [
            {"type": "crossover", "fastIndicatorId": "ACTIVE_ema5", "slowIndicatorId": "ACTIVE_ema21"},
            {"type": "crossover", "fastIndicatorId": "SPOT_ema5", "slowIndicatorId": "SPOT_ema21"},
            {"type": "crossunder", "fastIndicatorId": "INVERSE_ema5", "slowIndicatorId": "INVERSE_ema21"}
        ]
    },
    {"type": "threshold", "indicatorId": "ACTIVE_ema5", "op": ">", "valueIndicatorId": "ACTIVE_ema21"},
    {"type": "threshold", "indicatorId": "SPOT_ema5", "op": ">", "valueIndicatorId": "SPOT_ema21"},
    {"type": "threshold", "indicatorId": "INVERSE_ema5", "op": "<", "valueIndicatorId": "INVERSE_ema21"}
]
```

### Example 4: MACD Zero-Line Squeeze
Enter when the MACD Histogram crosses above zero, but only if the broader trend (EMA) also confirms upward momentum.
```json
"evaluateSpot": false,
"evaluateInverse": false,
"operator": "AND",
"conditions": [
    {"type": "threshold", "indicatorId": "ACTIVE_macd_hist", "op": ">", "value": 0},
    {"type": "threshold", "indicatorId": "ACTIVE_ema9", "op": ">", "valueIndicatorId": "ACTIVE_ema21"}
]
```

### Example 5: SuperTrend Reversal
A pure momentum strategy. Buy immediately when the SuperTrend flips from Bearish (-1) to Bullish (+1).
```json
"evaluateSpot": false,
"evaluateInverse": false,
"operator": "AND",
"conditions": [
    {"type": "direction_match", "indicatorId": "ACTIVE_st_dir", "op": "==", "value": 1}
]
```

### Example 6: Spot Breakout with Option Alignment
Execute a trade strictly based on the Nifty Spot Index breaking out, but require the purchased option to be moving favorably.
```json
"evaluateSpot": true,
"evaluateInverse": false,
"operator": "AND",
"conditions": [
    {"type": "crossover", "fastIndicatorId": "SPOT_ema9", "slowIndicatorId": "SPOT_ema21"},
    {"type": "threshold", "indicatorId": "ACTIVE_ema9", "op": ">", "valueIndicatorId": "ACTIVE_ema21"}
]
```

### Example 7: RSI Oversold Bounce
Enter a trade when an instrument becomes extremely oversold, indicating a high probability of a reversal bounce.
```json
"evaluateSpot": false,
"evaluateInverse": false,
"operator": "AND",
"conditions": [
    {"type": "threshold", "indicatorId": "ACTIVE_rsi", "op": "<", "value": 30}
]
```

### Example 8: Standard Trailing Exit
A very common exit strategy. Exit the trade the moment the fast EMA dips below the slow EMA.
```json
"exit": {
    "evaluateSpot": false,
    "evaluateInverse": false,
    "operator": "AND",
    "conditions": [
        {"type": "crossunder", "fastIndicatorId": "ACTIVE_ema5", "slowIndicatorId": "ACTIVE_ema21"}
    ]
}
```

### Example 9: Take-Profit Target Exit (RSI)
Exit the trade when the RSI reaches "overbought" territory, indicating the momentum wave might be exhausted.
```json
"exit": {
    "evaluateSpot": false,
    "evaluateInverse": false,
    "operator": "AND",
    "conditions": [
        {"type": "threshold", "indicatorId": "ACTIVE_rsi", "op": ">", "value": 75}
    ]
}
```

### Example 10: Inverse Panic Ripcord Exit
Exit your trade if the *opposite* side of the market suddenly surges upward, breaking its own trend (indicating your active option is about to collapse).
```json
"exit": {
    "evaluateSpot": false,
    "evaluateInverse": true,
    "operator": "OR",
    "conditions": [
        {"type": "crossover", "fastIndicatorId": "INVERSE_ema5", "slowIndicatorId": "INVERSE_ema21"}
    ]
}
```

### Example 11: MACD Exhaustion Exit
Exit the trade when the MACD momentum starts to fade (histogram begins shrinking downwards), even if it hasn't crossed below zero yet.
```json
"exit": {
    "evaluateSpot": false,
    "evaluateInverse": false,
    "operator": "AND",
    "conditions": [
        {"type": "crossunder", "fastIndicatorId": "ACTIVE_macd_hist", "slowIndicatorId": "ACTIVE_macd_hist_prev"}
    ]
}
```

### Example 12: Dual Confidence Exit (Spot & Active)
Wait for both the active option AND the broader Nifty Index to lose momentum before closing the trade, preventing premature shakeouts on temporary option premiums dips.
```json
"exit": {
    "evaluateSpot": true,
    "evaluateInverse": false,
    "operator": "AND",
    "conditions": [
        {"type": "crossunder", "fastIndicatorId": "ACTIVE_ema5", "slowIndicatorId": "ACTIVE_ema21"},
        {"type": "crossunder", "fastIndicatorId": "SPOT_ema5", "slowIndicatorId": "SPOT_ema21"}
    ]
}
```
