### Trade Bot V2 – Simplification & Consolidation Plan (Final)

This document captures a **pragmatic refactor plan** focused on reducing duplicate logic and making the system easier to reason about and extend.

---

### Core Services

1. **`ContractDiscoveryService`** – Consolidate option/contract & strike-window logic.
2. **`MarketHistoryService`** – Consolidate warmup & historical/replay data access.
3. **Backtest Verification:** Confirmed full backtest execution (3-Mar data) with successful results storage.
4. **CLI Method Typo:** Fixed `'HistoricalDataCollector' object has no attribute 'sync_nifty_and_options'` in `apps/cli/main.py` by using `sync_nifty_and_options_history` and providing correct datetime arguments.
4. **`LiveMarketService`** – Unified live XTS/socket stream handling.
5. **`TradeEventService`** – Events, persistence, and summary PnL performance reporting.
6. **`DataMaintenanceService`** – Centralized data jobs & ops.
7. **`TradeConfigService`** – Normalize, validate, and build session configurations.

---

### Phase 1: Core Logic & Foundation (Current)

**Responsibility**: Establish the "Source of Truth" for data and configuration.

- **`TradeConfigService`**: Standardize how engines start up. Build `position_config` and `strategy_config`.
- **`ContractDiscoveryService`**: Single place for resolving strikes (ATM±N). Replaces scattered logic in `FundManager` and `LiveTradeEngine`.
- **`MarketHistoryService`**: Unified warmup and historical replay.
- **Refactor**: Update `FundManager` and `LiveTradeEngine` to use these services.

### Phase 2: Orchestration & Performance

**Responsibility**: Align the apps (Backtest/Live) with the library.

- **`BacktestEngine`**: Move orchestration out of `tests/`.
- **`PerformanceService`**: Consolidated reporting (PnL, ROI, Win-Rate) inside `TradeEventService`.
- **`DataMaintenanceService`**: Wire CLI/API ops to centralized library code.

### Phase 3: Live Connectivity & Cleanup

**Responsibility**: Deep cleanup of streaming and events.

- **`LiveMarketService`**: Clean abstraction for Socket events.
- **`TradeEventService (Event Bus)`**: Fully migrate to an event-driven model for internal updates.
- **Cleanup**: Remove old utility shims and redundant handlers.
