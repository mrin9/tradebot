# Data Management

This document details the purpose of the primary data collections in the system and outlines the procedures for updating them.

## Important Data Collections

The system relies on three main collections in MongoDB to power its backtesting and trading engines:

### 1. `nifty_candle`

- **Purpose**: Stores the 1-minute candle data (OHLCV) specifically for the NIFTY 50 index (Instrument ID: `26000`).
- **Usage**: Serves as the foundational market data for evaluating index price action, generating trading signals based on index indicators (e.g., EMA, RSI), and determining overall market direction during backtests.

### 2. `options_candle`

- **Purpose**: Stores the 1-minute candle data for individual NIFTY options contracts (Calls and Puts).
- **Usage**: Used to calculate actual option premium movements, determine precise entry and exit prices for trades during backtesting, and assess strategy profitability based on real options data rather than theoretical pricing models.

### 3. `instrument_master`

- **Purpose**: Acts as the master directory of all tradable instruments provided by the exchange (XTS).
- **Usage**: Crucial for mapping human-readable trading symbols (like `NIFTY26FEB2415000CE`) to their corresponding numerical Exchange Instrument IDs, lot sizes, and strike prices. The system needs this mapping to know which specific instrument IDs to subscribe to or query for data.

---

## Update Procedures

All data updates are managed via the centralized CLI application (`apps/cli/main.py`). You can execute these commands directly or use the interactive menu by running `python3 apps/cli/main.py interactive`.

### 1. How to update `nifty_candle` and `options_candle`

Historical candle data sync relies on fetching the data from the XTS API chunk by chunk. Data updates are handled by the `sync-history` command.

#### For `nifty_candle` (Index Data):
You can synchronize historical NIFTY data by running the `sync-history` command with the NIFTY instrument ID (`26000`).

```bash
python3 apps/cli/main.py sync-history 26000 --start "2dago" --end "now"
```

*(The `--start` and `--end` flags accept date keywords like "2dago", "today", "now", or standard ISO dates).*

#### For `options_candle` (Options Data):
Updating options data requires a two-step approach:

1. **Refresh Active Contracts**: First, identify which option contracts (ITM/ATM/OTM) were active during the desired timeframe based on the historical movement of the NIFTY spot price.
   ```bash
   python3 apps/cli/main.py update-contracts --date-range "today"
   ```

2. **Sync History for Contracts**: Once the active contracts are identified, you must sync the historical data for those specific option contract IDs using the `sync-history` command.
   ```bash
   python3 apps/cli/main.py sync-history <OPTIONS_INSTRUMENT_ID> --start "2dago" --end "now"
   ```

*(Note: The `interactive` menu contains an option to "Sync All Active Contracts (History)", which can be used to coordinate the bulk download if fully implemented in your environment).*

### 2. How to Update `instrument_master`

The master database needs to be updated periodically (e.g., daily before market open) to ensure the system is aware of the latest newly issued contract definitions or expired contracts.

You can download and update the Master Instrument Database from XTS by running the `update-master` command:

```bash
python3 apps/cli/main.py update-master
```

This command connects to the XTS API, downloads the latest master file for the `NSECM` and `NSEFO` segments, parses it, and automatically upserts the active contracts into the `instrument_master` database collection.

---

## XTS Data Schema (Market Data)

The system normalizes incoming XTS socket events and historical candles into a consistent flat format. Below is the mapping of XTS short keys to domain concepts:

| XTS Key | Meaning | Notes |
| :--- | :--- | :--- |
| `i` | Instrument ID | Exchange Instrument ID (e.g., 26000 for NIFTY) |
| `t` | Timestamp | Unix Epoch (seconds or milliseconds) |
| `o` | Open | Opening price of the bar |
| `h` | High | High price of the bar |
| `l` | Low | Low price of the bar |
| `c` | Close | Closing price of the bar (or Last Traded Price in ticks) |
| `v` | Volume | Total traded volume |
| `oi` | Open Interest | Relevant for Futures and Options |
| `v2` | Tick Volume | Volume of the individual tick (in 1501 events) |

### Common Event Codes

- **1505**: OHLC Candle data (1-minute)
- **1501**: Touchline data (Real-time ticks)
- **1510**: Open Interest update
- **1502**: Market Depth (L2 data)
