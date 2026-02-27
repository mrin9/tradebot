# Cheat Sheet

Quick reference for common commands.

## CLI Commands (`apps/cli/main.py`)

| Action | Command |
|--------|---------|
| **Launch Interactive** | `python apps/cli/main.py interactive` |
| **Fetch Master** | `python apps/cli/main.py master sync` |
| **Fetch History** | `python apps/cli/main.py historical fetch --days 5` |
| **Run Backtest**  | `python -m packages.backtest.backtest_runner --mode db --rule-id [RULE_ID] --start [DATE] --end [DATE]` |
| **Check Data Gaps** | `python apps/cli/main.py maintenance check-gaps` |
| **Prune Old Data** | `python apps/cli/main.py maintenance prune --days-to-keep 30` |

## Docker Commands

| Action | Command |
|--------|---------|
| **Start All** | `docker-compose up -d` |
| **Stop All** | `docker-compose down` |
| **Rebuild** | `docker-compose up --build -d` |
| **View API Logs** | `docker-compose logs -f api` |

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/status` | Check System Health |
| GET | `/api/instruments` | List all instruments |
| GET | `/api/ticks?id=NIFTY` | Get Candle/Tick Data |
| POST | `/api/simulation/start` | Start Simulation |

## Python Snippets

**Run a Quick Backtest Script:**
```python
from packages.tradeflow.fund_manager import FundManager
fm = FundManager()
# ... feed candles manually ...
```
