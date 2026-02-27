# Trade Bot V2

**Agentic Python Trading Bot with XTS Connect Integration**

![Dashboard Preview](docs/images/dashboard_preview.png) *Wrapper for visualization*

## 🚀 Quickstart

### 1. Prerequisites
- **Python 3.11+**
- **Docker & Compose** (Recommended)
- **MongoDB**

### 2. Setup
1.  **Clone the Repo**:
    ```bash
    git clone <repo_url>
    cd trade-bot-v2
    ```
2.  **Configure Credentials**:
    ```bash
    cp .env.example .env
    # Edit .env with your XTS API keys
    ```
3.  **Run with Docker** (Easiest):
    ```bash
    docker-compose up --build
    ```
    - **Dashboard**: [http://localhost:4321](http://localhost:4321)
    - **API**: [http://localhost:8000](http://localhost:8000)

### 3. Run Manually (Dev Mode)
See [Operational Guide](docs/operational_guide.md) for detailed local setup.

## 📚 Documentation

Detailed documentation is available in the `docs/` folder:

- **[Project Layout](docs/project_layout.md)**: Understand the folder structure and code organization.
- **[Trade Engine Workflow](docs/trade_engine_workflow.md)**: Logic flow from Market Data to Order Execution.
- **[Operational Guide](docs/operational_guide.md)**: How to run the bot, CLI, and common tasks.
- **[VPS Setup Guide](docs/vps_setup_guide.md)**: Deploying to a Linux Server.
- **[DevOps Guide](docs/devops_guide.md)**: Docker, Build, and Maintenance instructions.
- **[Testing Guide](docs/testing_guide.md)**: How to run and interpret automated tests.
- **[Cheat Sheet](docs/cheat_sheet.md)**: Quick copy-paste commands.

## ✨ Key Features
- **Strategy Engine**: Polars-based indicator calculation with signal generation.
- **Execution Engine**: Automated Entry, Stop-Loss, and Target management.
- **Simulation**: Replay historical MongoDB data as live ticks via Socket.IO.
- **Dashboard**: Real-time visualization of Ticks, Signals, and Strategy performance.
