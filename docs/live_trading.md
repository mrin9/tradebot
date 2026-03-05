# Live Trading Guide

This document explains how to set up and run live trading with the XTS Socket integration in TradeBot V2.

## Prerequisites

1.  **XTS Credentials**: Ensure your `.env` file contains valid XTS API credentials.
    ```env
    XTS_MARKET_KEY=your_key
    XTS_MARKET_SECRET=your_secret
    XTS_INTERACTIVE_KEY=your_key
    XTS_INTERACTIVE_SECRET=your_secret
    ```
2.  **Instrument Master**: Ensure your instrument master data is up to date.
    ```bash
    python3 apps/cli/main.py update-master
    ```

## Starting Live Trading

You can start live trading via the CLI using either the interactive menu or a direct command.

### Direct Command

You can run the live trader directly, bypassing the interactive menu, by specifying parameters. Here is the recommended command sequence for a custom Python strategy:

```bash
python apps/cli/main.py live-trade \
  --strategy-mode python_code \
  --python-strategy-path packages/tradeflow/python_strategies.py:TripleLockStrategy \
  --rule-id triple-lock-momentum \
  --selection-basis ATM \
  --budget 200000 \
  --sl 15 \
  --target 15,25,45 \
  --trailing-sl 15 \
  --break-even \
  --record-papertrade
```

### Configuration Parameters

Values that denote points (like Stop Loss) correspond to absolute price changes in the Option's premium (e.g. 15 points = ₹15 movement in Option price, which is ₹15 * 50 = ₹750/lot for NIFTY).

| Parameter | Default | Valid Options | Description |
| :--- | :--- | :--- | :--- |
| `--strategy-mode` | `python_code` | `rule`, `python_code`, `ml` | The core intelligence engine. `rule` uses the web JSON DSL. `python_code` delegates to your custom script. |
| `--python-strategy-path` | `packages/tradeflow/python_strategies.py:TripleLockStrategy` | Valid Python path | Used only when `strategy-mode` is `python_code`. Points to your custom class. |
| `--rule-id` | `triple-lock-momentum` | Any valid Rule ID from DB | Crucial for `python_code` mode, as it defines *which* indicators the FundManager calculates and feeds to your script. |
| `--selection-basis` | `ATM` | `ATM`, `ITM`, `OTM` | Dictates which Option strike is dynamically tracked and traded. (e.g., if NIFTY is 22000, ATM buys the 22000 CE/PE). |
| `--budget` | `200000.0` | Any positive float | Initial capital (in ₹). Divides by contract (Options lot size * premium) to determine how many lots to buy. |
| `--sl` | `15.0` | Any positive float | **(Points)** Absolute stop-loss points off the premium. E.g., if you buy an option at ₹200, a `--sl 15` triggers if the premium drops to ₹185 (which is only a 7.5% drop, *not* 15%). |
| `--target` | `15,25,45` | Comma-separated floats | **(Points)** Step-wise profit booking points. The bot divides your lots into chunks and sells them progressively at +15pts, +25pts, and +45pts from your entry price. |
| `--trailing-sl` | `15.0` | Any positive float | **(Points)** Locks in profits. If the premium moves +15pts *above* your highest mark, the Stop Loss is dragged up by 15 points. If set to `0`, trailing is disabled. |
| `--break-even` / `--no-break-even` | `--break-even` (True) | Flag | If enabled, the moment your **first target** is hit (e.g., +15pts), the Stop Loss for all remaining lots is instantly moved to your exact Entry Price. |
| `--record-papertrade` / `--no-record-papertrade` | `--record-papertrade` (True) | Flag | Enables high-fidelity logging of every trade event (Entry, Target Bookings, SL hits) into a dedicated `papertrade` collection. |
| `--ml-model-path` | `None` | Path to `.joblib` | Only used if `--strategy-mode ml`. |
| `--debug` / `--no-debug` | `--no-debug` (False) | Flag | Prints raw XTS Socket JSON packets to the console. |

### Interactive Menu

1. Run `python3 apps/cli/main.py menu`.
2. Select **Live Trading**.
3. Follow the prompts for Strategy ID, Budget, and Risk parameters.

## Monitoring

- **Console Logs**: The engine provides detailed logs about socket connection, warm-up, received ticks, and generated signals.
- **UI Dashboard**: Live trades are persisted to the `live_trades` collection and can be visualized in the UI (similar to backtest results).
- **Paper Trading Logs**: Detailed transaction-level events (Entry, Target 1, Exit, etc.) are recorded in the **`papertrade` collection**.
- **MongoDB**: You can inspect the `live_trades` collection for session state or `papertrade` for audit logs.

## Off-Market Hours

If started while the market is closed:
1. The engine will perform a "Warm-up" by processing the last 5 hours of historical data from the database.
2. It will connect to the XTS socket and wait.
3. It will remain idle until the first tick is received when the market opens.

## End of Day

The engine automatically handles EOD settlement at **15:30 IST**, closing all open positions and stopping the session.
