# Operational Guide

This guide provides instructions for running the Trade Bot in various modes.

## 1. Development (Local)

### Prerequisites
- Python 3.11+
- Node.js 18+
- MongoDB

### Setup
```bash
# 1. Install Python Dependencies
pip install -r requirements.txt

# 2. Setup Frontend
cd apps/ui
npm install
```

### Running the API
```bash
python apps/api/run.py
```
*API will run at http://localhost:8000*

### Running the UI
```bash
cd apps/ui
npm run dev
```
*UI will run at http://localhost:4321*

### Running the CLI
```bash
python apps/cli/main.py interactive
```

## 2. Production (Docker)

### Build & Run
```bash
docker compose up -d --build
```

### Access Points
- **Dashboard**: http://YOUR_VPS_IP:4321
- **API**: http://YOUR_VPS_IP:8000
- **Database**: Port 27017 (only if exposed in compose)

## 3. Common Tasks

### Fetching Historical Data
Use the CLI to populate your database.
```bash
python apps/cli/main.py historical fetch --days 5
```

### Running a Backtest
1. Ensure you have data in `nifty_candle`.
2. Use the CLI to run a backtest:
   ```bash
   python apps/cli/main.py backtest --rule-id triple-lock-momentum --start 2026-03-02
   ```
3. View results in the Dashboard -> Backtest Results.

### Checking System Health
```bash
curl http://localhost:8000/api/status
```
