# Project Layout

This document describes the structure of the `trade-bot-v2` project and the role of key components.

## Directory Structure

```
trade-bot-v2/
├── apps/                   # Application Entry Points
│   ├── api/                # FastAPI Backend
│   │   ├── routers/        # API Endpoints (Instruments, Ticks, Backtests)
│   │   └── main.py         # API Application Entry
│   ├── cli/                # Command Line Interface
│   │   └── main.py         # CLI Entry Point
│   └── ui/                 # Frontend Dashboard (HTML/JS/Vue)
│       └── ...
├── packages/               # Core Logic & Shared Libraries
│   ├── backtest/           # Backtest Engine (Runner, DB Mode, Socket Mode)
│   ├── config.py           # Configuration Settings
│   ├── tradeflow/          # Trading Engine Core
│   │   ├── candle_resampler.py # Candle Aggregation logic
│   │   ├── indicator_calculator.py # Indicators
│   │   ├── strategy.py     # Strategy Logic
│   │   ├── order_manager.py # Order Management
│   │   ├── position_manager.py # Position Management
│   │   ├── tick_to_candle.py # Tick aggregation
│   │   └── fund_manager.py # Main Orchestrator
│   ├── data/               # Data Layer
│   │   ├── connectors/     # XTS API & Socket Wrappers
│   │   └── maintenance.py  # Data Cleanup
│   └── utils/              # Utilities (Mongo, Date, Log)
├── tests/                  # Automated Tests
├── Dockerfile              # Backend Container Config
├── docker-compose.yml      # Orchestration Config
└── requirements.txt        # Python Dependencies
```

## Key Components

### Apps
- **CLI (`apps/cli`)**: The primary interface for managing the bot, fetching data, and running maintenance tasks.
- **API (`apps/api`)**: Provides REST endpoints and Socket.IO streams for the Dashboard.
- **UI (`apps/ui`)**: A web-based dashboard for monitoring strategy performance and backtest results.

### Packages
- **`packages.data`**: Handles all interactions with the XTS Market Data API and MongoDB.
- **`packages.tradeflow`**: Contains the trading logic (`Strategy` class), indicator calculations (`IndicatorCalculator`), position management (`PositionManager`), and order execution (`OrderManager`).

### Tests
- **`tests/test_strategy_integration.py`**: Integration test ensuring Strategy Output matches between Database and Socket Feed.
- **`tests/test_fund_manager.py`**: End-to-end verification of the trading workflow (Signal -> Order).
