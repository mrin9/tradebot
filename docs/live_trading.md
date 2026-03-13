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
# Example 1: Standard Python Strategy (Triple Lock)
python3 apps/cli/main.py live-trade \
  --strategy-id triple-confirmation \
  --strike-selection ATM \
  --budget 200000 \
  --sl-points 15 \
  --target-points 15,25,45 \
  --tsl-points 15 \
  --use-be \
  --record-papertrade

# Example 2: Using Indicator-based Trailing SL (EMA-5)
python3 apps/cli/main.py live-trade \
  --strategy-id triple-confirmation \
  --tsl-id active-ema-5 \
  --budget 200000
```

### Configuration Parameters

Values that denote points (like Stop Loss) correspond to absolute price changes in the Option's premium (e.g. 15 points = ₹15 movement in Option price, which is ₹15 * 50 = ₹750/lot for NIFTY).

| Parameter | Short | Default | Description |
| :--- | :--- | :--- | :--- |
| `--strategy-id` | `-s` | `triple-confirmation`| **Required**. Strategy ID from database. Used to load indicators and python path. |
| `--strike-selection`| `-S` | `ATM` | Strike selection: `ATM`, `ITM`, or `OTM`. |
| `--budget` | `-b` | `200000.0` | Initial capital for the session. |
| `--sl-points`| `-l` | `15.0` | Absolute stop loss points off premium. |
| `--target-points` | `-t` | `15,25,45` | Comma-separated profit booking levels. |
| `--tsl-points`| `-L` | `0.0` | Trailing SL increment. |
| `--use-be` | `-e` | `True` | Move SL to entry after Target 1. |
| `--record-papertrade`| n/a | `True` | Record high-fidelity events in `paper_trades` collection. |
| `--tsl-id`| `-T` | `active-ema-5` | Indicator ID for Trailing SL (e.g. `active-ema-5`). |
| `--debug` | n/a | `False` | Enable raw socket debug logs. |

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
