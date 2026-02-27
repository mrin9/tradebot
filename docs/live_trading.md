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
3.  **Active Contracts**: Refresh the session's active contracts.
    ```bash
    python3 apps/cli/main.py refresh-contracts --date-range today
    ```

## Starting Live Trading

You can start live trading via the CLI using either the interactive menu or a direct command.

### Direct Command

```bash
python3 apps/cli/main.py live-trade --rule-id R001 --budget 200000 --sl 20 --target 40 --subscribe-to Full
```

**Arguments:**
- `--rule-id`: The ID of the strategy rule (e.g., `EMACROSS_01`).
- `--budget`: Initial capital assigned to this session.
- `--sl`: Stop loss points for each trade.
- `--target`: Target points for each trade.
- `--selection-basis`: Option selection (ATM, ITM, OTM).
- `--subscribe-to`: XTS broadcast mode. `Full` provides more fields, `Partial` is lighter.
- `--trailing-sl`: Points for trailing stop loss (0 to disable).
- `--break-even`: Enable moving SL to cost when first target is hit (default: True).

### Interactive Menu

1. Run `python3 apps/cli/main.py menu`.
2. Select **Live Trading**.
3. Follow the prompts for Strategy ID, Budget, and Risk parameters.

## Monitoring

- **Console Logs**: The engine provides detailed logs about socket connection, warm-up, received ticks, and generated signals.
- **UI Dashboard**: Live trades are persisted to the `live_trades` collection and can be visualized in the UI (similar to backtest results).
- **MongoDB**: You can inspect the `live_trades` collection directly for the latest session state.

## Off-Market Hours

If started while the market is closed:
1. The engine will perform a "Warm-up" by processing the last 5 hours of historical data from the database.
2. It will connect to the XTS socket and wait.
3. It will remain idle until the first tick is received when the market opens.

## End of Day

The engine automatically handles EOD settlement at **15:30 IST**, closing all open positions and stopping the session.
