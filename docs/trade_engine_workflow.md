# Trade Engine Workflow (Multi-Timeframe Architecture - MTFA)

This document outlines the flow of data and execution within the Trade Bot V2 engine, which has been refactored to natively support Multi-Timeframe Analysis (MTFA) based on strategy configuration from the database.

## 1. Workflow Diagram (MTFA)

The engine has shifted from a linear "Single Candle -> Strategy" pipeline to a concurrent "Multi-Candle -> Synchronized Strategy Evaluation" model.

### High-Level Data Flow

```mermaid
graph TD
    DB[(MongoDB: strategy_indicators)] -->|Loads Config| FundMgr[FundManager]
    
    Stream[Base Data Stream <br> Tick or 1-Min] --> FundMgr
    Stream -->|Update real-time Price| PosMgr[Position Manager]
    
    subgraph "Indicator Calculation (FundManager Routing)"
    FundMgr -->|Route to| IndCalc[IndicatorCalculator]
    IndCalc -->|Shorthand Parser| Polars[Polars Vectorized Calcs]
    Polars -->|Updated State| State((Global Indicator State Cache))
    end
    
    subgraph "Python Strategy Evaluator"
    State -->|All Indicators Context| Strat[PythonStrategy.on_resampled_candle_closed]
    DB -->|Fetch via strategy_id| Strat
    Strat -->|Signal: LONG/SHORT/EXIT| PosMgr
    end
    
    subgraph Execution Engine
    PosMgr -->|Open/Close Trade| G[Order Manager]
    G -->|Place Order| H[Exchange / Paper]
    end
```

### Business Process Model and Notation (BPMN)

This detailed process model illustrates the exact sequencing logic and the parallel multiple-instance execution spawned by the `FundManager` upon receiving a new market data tick.

```mermaid
graph TD
    %% BPMN Nodes
    StartEvent((fa:fa-bolt Receive <br>Tick / 1-Min Candle))
    UpdatePos[fa:fa-cog Update Position<br>SL & Target]
    SplitGateway{fa:fa-plus Parallel Split<br>per Timeframe}
    
    %% Multi-Instance Subprocess
    subgraph "Multi-Instance Resampler [For each TF ∈ Active_Timeframes]"
        direction TB
        Resample[Resample Data to TF]
        CheckClosed{Is TF Candle<br>Closed?}
        CalcInd[Calculate TF Indicators]
        Resample --> CheckClosed
        CheckClosed -->|Yes| CalcInd
    end
    
    MergeState[fa:fa-database Merge to Global<br>Indicator State Cache]
    EvalStrategy[fa:fa-code Evaluate Python<br>Strategy Script]
    SignalGateway{Signal<br>Generated?}
    
    CheckPos[Check Position Status]
    ExecOrder[Execute Order via OrderManager]
    
    EndHold((fa:fa-stop End: Hold <br>Wait for Tick))
    EndComplete((fa:fa-check End: Traded))

    %% Sequence / Flow
    StartEvent --> UpdatePos
    UpdatePos --> SplitGateway
    
    SplitGateway -->|Spawn Parallel| Resample
    
    CheckClosed -->|No| EndHold
    CalcInd --> MergeState
    MergeState --> EvalStrategy
    EvalStrategy --> SignalGateway
    
    SignalGateway -->|HOLD| EndHold
    SignalGateway -->|BUY / SELL| CheckPos
    
    CheckPos --> ExecOrder
    ExecOrder --> EndComplete
    
    classDef Event fill:#f9f,stroke:#333,stroke-width:2px;
    classDef Task fill:#bbf,stroke:#333,stroke-width:1px;
    classDef Gateway fill:#ff9,stroke:#333,stroke-width:2px;
    
    class StartEvent,EndHold,EndComplete Event;
    class UpdatePos,Resample,CalcInd,MergeState,EvalStrategy,CheckPos,ExecOrder Task;
    class SplitGateway,CheckClosed,SignalGateway Gateway;
```


## 2. Component Roles

### 2.1. Market Data Source
- **Live**: XTS WebSocket (`1501` Ticks or BarData).
- **Simulation**: Backtest runner replaying historical MongoDB data natively.

### 2.2. Fund Manager (`packages/tradeflow/fund_manager.py`)
- The **Active Orchestrator Engine**.
- Initializes sub-components based on a `strategy_indicators` DB document.
- **Tick Normalization**: Natively handles both raw ticks (price-only) and base 1-minute candles. If a raw tick is received, it automatically populates standard OHLC keys (`o`, `h`, `l`, `c`) to ensure compatibility with downstream resamplers and ML strategy windows.
- Dynamically spawns `CandleResampler` instances for every unique timeframe required by the active strategy indicators.
- Routes incoming ticks/base candles into all active resamplers.
- Maintains a `Global Indicator State Cache` merging finalized indicators across timeframes.
- **Derivative Resolution**: When trading options, evaluating conditions based on Spot Data (e.g. NIFTY Nifty 50), the engine will automatically resolve the correct Option Strike (ITM/ATM/OTM) or Futures contract from MongoDB's `instrument_master` upon signal confirmation.

### 2.3. Candle Resampler (`packages/tradeflow/candle_resampler.py`)
- Aggregates raw ticks or base 1-minute candles into higher timeframes (e.g., 5-minute candles).
- Emits a "Finalized Candle" event specifically tagged with its timeframe when a candle closes.

### 2.4. Strategy Engine (`packages/tradeflow/python_strategy_loader.py` & `indicator_calculator.py`)
- **Indicator Calculator**: 
  - Maintains separate memory `deques` for each instrument category and ID.
  - Dynamically calculates specific technical indicators (RSI, EMA, etc.) using `Polars` based on shorthand strings (e.g. `ema-9`, `rsi-14`) in the `strategy_indicators` collection.
  - Fully vectorized Polars expressions ensure high performance.
- **Python Strategy Logic (`python_strategy_loader.py`)**: 
  - A dynamic loader for pure Python strategy files.
  - Evaluates the global indicator state within the strategy's `on_resampled_candle_closed` method to generate `LONG`, `SHORT`, or `EXIT` signals.
  - This replaces the old JSON-DSL engine, allowing for unlimited logic complexity.

### 2.5. Execution Engine (`packages/tradeflow/position_manager.py` & `order_manager.py`)
- **Position Manager**: 
    - Tracks current trade orientation (Flat, Long, Short).
    - Checks incoming Strategy Signals against the current position.
    - Operates iteratively: updates internal **Stop Loss** and **Targets** conditions *on every tick* directly from the data stream.
    - **Multiple Targets**: Exits specific quantity sizes natively as the positions reach parameterized profit tiers.
    - **Break Even**: Automatically trails the Stop Loss to the original Entry Price after realizing the first partial target.
    - **Trailing SL**: Supports trailing the stop-loss behind the highest/lowest trade price for unbounded captures.
- **Order Manager**: 
    - Executes the actual trade payload.
    - Default: `PaperTradingOrderManager` for simulations.

## 3. Testing Process

Due to the complex routing of the engine, rigorous testing is mandated.

- **Unit Tests (`tests/no_db/test_indicator_calculator.py`)**: Validates shorthand parsing and Polars-based indicator accuracy.
- **Integration Tests (`tests/frozen_db/test_e2e_strategies.py`)**: Spans the entire pipeline. A strategy from `strategy_indicators` is fed into `FundManager` or the backtest runner, verifying signals and trade execution across historical data.
