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
docker-compose up --build -d
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

### Running a Simulation
1. Ensure you have data in `nifty_candle`.
2. Start the API (`docker-compose up`).
3. Open Dashboard -> Tick Monitor.
4. Select Date and Click **Start**.

### Checking System Health
```bash
curl http://localhost:8000/api/status
```
