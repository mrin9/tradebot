### Trade Bot V2 – Simplification & Consolidation Plan

This document captures a **pragmatic refactor plan** focused on:

- Reducing **duplicate logic**
- Shrinking **god classes** (`FundManager`, `PositionManager`, `LiveTradeEngine`)
- Making the system **easier to reason about and extend**, without exploding the number of concepts

The idea is to introduce a **small set of services**, each of which *replaces multiple scattered implementations*.

---

### Overview of Planned Services

Each service below is intentionally small in scope and designed to **consolidate existing duplicate / overlapping code**, not to add new behavior.

1. `InstrumentService` – option/contract & strike-window logic  
2. `MarketDataService` – warmup & historical/replay data access  
3. `BacktestService` – production backtest orchestration  
4. `XtsStreamService` – unified live XTS/socket stream handling  
5. `TradeEventService` (or `TradePersistenceService`) – events, persistence, and reporting  
6. `DataMaintenanceService` – data jobs & ops consolidation  
7. `StrategyConfigService` – strategy rules normalization & validation  

You do **not** need to implement all of these at once. A reasonable order is:

- **Phase 1**: `InstrumentService`, `MarketDataService`
- **Phase 2**: `BacktestService`, `DataMaintenanceService`
- **Phase 3**: `XtsStreamService`, `TradeEventService`, `StrategyConfigService`

---

### 1. InstrumentService – consolidate option/contract & strike-window logic

**Responsibility**

- Given date/time + underlying + config, answer: **“Which instruments/strikes should we care about?”**
- Provide a single API for:
  - Resolving CE/PE instruments for a given strike and timestamp
  - Deriving ATM±N contracts for a date or timestamp
  - Maintaining “active window” / “rolling strikes” (e.g. ATM ± N strikes)

**Code it consolidates**

- `FundManager._resolve_option_contract`  
  - `packages/tradeflow/fund_manager.py`
- `ContractManager._identify_contracts` and `refresh_active_contracts`  
  - `packages/data/managers/contracts.py`
- `MarketUtils.derive_target_contracts`  
  - `packages/utils/market_utils.py`
- `LiveTradeEngine._resync_strike_chain`, `_update_rolling_strikes`, `_resolve_strike_ids`  
  - `packages/livetrade/live_trader.py`

**Net effect**

- 1 new small module replaces **4 different implementations** of “which options to use”.
- Live trading, backtests, and data jobs all pull strikes from the **same logic**.

---

### 2. MarketDataService – consolidate warmup & historical/replay data access

**Responsibility**

- Single abstraction to:
  - Fetch historical candles / ticks for an instrument or set of instruments
  - Run **warmup** for indicators and engine state
  - Replay historical data into the engine (for backtests or simulations)
- Should have pluggable backends:
  - Mongo / DB
  - XTS REST
  - Simulator / socket

**Code it consolidates**

- Warmup and history logic inside `FundManager`:
  - `_warmup_instrument`, `_fetch_historical_candles`, `_fetch_fallback_quote`, `_get_fallback_option_price`  
  - `packages/tradeflow/fund_manager.py`
- Indicator warmup helper:
  - `MarketUtils.run_indicator_warmup`  
  - `packages/utils/market_utils.py`
- Live warmup orchestration:
  - `LiveTradeEngine._warm_up`  
  - `packages/livetrade/live_trader.py`
- Historical replay paths:
  - `SocketDataProvider.stream_data` (replays Mongo as XTS-like events)  
    - `packages/simulator/socket_data_provider.py`
  - Parts of `DBFeeder` and `SocketFeeder` that fetch/replay candles  
    - `tests/backtest/db_mode.py`, `tests/backtest/socket_mode.py`

**Net effect**

- One place defines “how we warm up and replay history”.
- Live, backtest, and simulator **share the same behavior** instead of re‑implementing it.

---

### 3. BacktestService – move backtest orchestration out of `tests/`

**Responsibility**

- Library-style entrypoint: **“Given a backtest config, run it and persist results.”**
- Encapsulate:
  - Construction of `FundManager`, `BacktestBot`, feeders, and persistence wiring
  - Core backtest loop and result summarization

**Code it consolidates**

- Backtest driver currently under `tests`:
  - `tests/backtest/backtest_runner.py`
  - `tests/backtest/backtest_base.py` (BacktestBot, abstract feeder)
- CLI backtest command that shells out to `python -m tests.backtest.backtest_runner ...`:
  - `apps/cli/main.py`

**Net effect**

- Backtest logic lives under `packages/backtest/` and is imported by:
  - CLI
  - Tests
  - (Optionally) API or automation
- The `tests/` folder becomes a true **consumer** of library code, not a home for production logic.

---

### 4. XtsStreamService – unify live XTS/socket stream handling

**Responsibility**

- Provide a single abstraction for **market data streaming**:
  - Connect to XTS
  - Manage subscriptions (including rolling updates)
  - Normalize incoming events into a single internal tick/candle format
  - Handle reconnect/health logic and call user-provided callbacks

**Code it consolidates**

- XTS socket wiring and callbacks:
  - `MarketDataListener`  
    - `packages/data/stream/listener.py`
  - Socket-handling parts of `LiveTradeEngine`  
    - `packages/livetrade/live_trader.py`
- XTS-like event encoding/decoding used by simulator/backtest:
  - `SocketServer` and `SocketDataProvider`  
    - `packages/simulator/socket_server.py`  
    - `packages/simulator/socket_data_provider.py`
  - Event normalization helpers like `MarketUtils.normalize_xts_event`  
    - `packages/utils/market_utils.py`

**Net effect**

- One clear abstraction for “XTS-style stream → internal tick events”.
- Live engine, listeners, and simulator **all go through the same interface**.

---

### 5. TradeEventService (or TradePersistenceService) – unify events, persistence, and reporting

**Responsibility**

- Define and handle **trade domain events**:
  - Position opened/added/reduced/closed
  - SL/target hits, TSL moves
  - Session summaries (PnL, win/loss stats, etc.)
- Provide:
  - A single place to format events for logs
  - A single place to persist events and summaries
  - Utilities for reconstructing trade cycles from stored events

**Code it consolidates**

- Trade event/log formatting:
  - Use of `TradeFormatter` scattered in:
    - `packages/tradeflow/position_manager.py`
    - `packages/utils/trade_formatter.py`
- Persistence and trade-cycle reconstruction:
  - `TradePersistence` logic (inferring cycles from status strings, session IDs, etc.)  
    - `packages/utils/trade_persistence.py`
- Backtest vs live reporting:
  - Similar PnL/session summary code in:
    - `tests/backtest/backtest_base.py` (BacktestBot)
    - `packages/livetrade/live_trader.py`

**Net effect**

- `PositionManager` and the engine emit **simple domain events**.
- `TradeEventService` decides how to **log, persist, and summarize** them, for both live and backtest.

---

### 6. DataMaintenanceService – centralize data jobs & ops

**Responsibility**

- Provide a single entrypoint to run **data maintenance jobs**:
  - Sync instrument master
  - Sync history
  - Age-out old data
  - Fix gaps
  - Refresh contracts / active windows

**Code it consolidates**

- Job orchestration in CLI:
  - Commands that wrap:
    - `MasterDataCollector` (`sync_master.py`)
    - `HistoricalDataCollector` (`sync_history.py`)
    - Age-out manager (`age_out.py`)
    - Gap-fixing logic (`fix_data_gaps.py`)
  - `apps/cli/main.py`
- Individual job managers (which remain, but are orchestrated in one place):
  - `packages/data/managers/sync_master.py`
  - `packages/data/managers/sync_history.py`
  - `packages/data/managers/age_out.py`
  - `packages/data/managers/fix_data_gaps.py`
- API ops router (can finally call real code instead of returning 501):
  - `apps/api/routers/ops.py`

**Net effect**

- One API like `DataMaintenanceService.run_job(job_name, params)` used by:
  - CLI
  - API
  - Scripts/automation

---

### 7. StrategyConfigService – normalize & validate strategy rules

**Responsibility**

- Provide a canonical way to:
  - Normalize raw strategy rule documents from DB/UI into the **internal** config shape
  - Validate that required fields are present and correctly typed
  - Handle backward-compat casing and naming differences

**Code it consolidates**

- Compatibility shims and ad‑hoc normalization in:
  - `FundManager` (e.g. supporting `'Indicators'` vs `'indicators'`)  
    - `packages/tradeflow/fund_manager.py`
- Pydantic models & shape assumptions in the API:
  - `StrategyIndicator`, `StrategyRule`, etc.  
    - `apps/api/routers/strategy.py`
- Any seeding/migration scripts that hand‑roll normalization logic.

**Net effect**

- A single function like `normalize_strategy_config(raw_doc)` becomes the **one source of truth**.
- Engine, API, CLI, and seeding scripts all rely on the same normalization + validation rules.

---

### Suggested Refactor Order

- **Phase 1 – Max impact / least disruption**
  - Implement `InstrumentService` and `MarketDataService`.
  - Refactor `FundManager` and `LiveTradeEngine` to depend on these services.

- **Phase 2 – Clarify “library vs apps”**
  - Introduce `BacktestService` and `DataMaintenanceService`.
  - Thin out CLI commands and wire API ops endpoints to these services.

- **Phase 3 – Deep cleanup**
  - Add `XtsStreamService`, `TradeEventService`, and `StrategyConfigService`.
  - Gradually migrate callers, keeping old paths as shims where necessary.

