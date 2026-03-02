# VPS Setup Guide

Guide to deploying Trade Bot on a Linux VPS (Ubuntu 22.04+).

## 1. Initial Server Setup

```bash
# Update System
sudo apt update && sudo apt upgrade -y

# Install Docker & Compose
sudo apt install -y docker.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
sudo usermod -aG docker $USER
```

## 2. Pre-deployment (Local Machine)

Before deploying to the VPS, you should build and push your images to a registry like Docker Hub.

### 1. Login to Docker Hub
```bash
docker login
```

### 2. Build and Tag Images
> [!IMPORTANT]
> You **must** set your Docker Hub username for the commands below to work. If you see an `invalid reference format` error, it means this variable is empty.

```bash
# Replace "yourusername" with your actual Docker Hub ID
export DOCKER_USER="yourusername"

# Build Backend
docker build -t $DOCKER_USER/trade-bot-api:latest .

# Build Frontend
cd apps/ui
docker build -t $DOCKER_USER/trade-bot-web:latest .
cd ../..
```

### 3. Push to Docker Hub
```bash
docker push $DOCKER_USER/trade-bot-api:latest
docker push $DOCKER_USER/trade-bot-web:latest
```

## 3. VPS Project Setup

> [!IMPORTANT]
> GitHub no longer supports account passwords for Git operations. You must use a **Personal Access Token (PAT)** or **SSH Keys**.

```bash
# Clone Repository (Replace <TOKEN> and <USERNAME> or use SSH)
# Option A: HTTPS with PAT
git clone https://<USERNAME>:<TOKEN>@github.com/mrin9/tradebot.git

# Option B: SSH (Recommended if SSH keys are setup)
git clone git@github.com:mrin9/tradebot.git

cd tradebot

# Create Environment File
cp .env.example .env
nano .env
# Fill in your XTS Credentials and Mongo URI (if external)
```

## 4. Deployment (using Images)

Instead of building on the VPS, use the production compose file which pulls pre-built images.

```bash
# 1. Transfer docker-compose.prod.yml to VPS
# 2. Rename it to docker-compose.yml on VPS
# 3. Run:
docker compose up -d
```

docker compose up -d --build
```

## 5. Verification (Running Tests)

Once the containers are running, you should verify the installation by running the automated tests inside the container.

```bash
# Run all tests
docker compose exec api pytest tests/

# Run specific XTS Socket test
docker compose exec api pytest tests/backtest/test_xts_socket.py
```

### Running Standalone Scripts
If you want to run a one-off script (like a connection test) without a full compose stack:

```bash
# Using docker run (requires .env file)
docker run --rm --env-file .env yourusername/trade-bot-api:latest python tests/backtest/test_xts_socket.py --events 1501-partial
```

### Running the CLI (Interactive)
To run data collection or other interactive CLI commands:

```bash
# Enter the container shell
docker compose exec -it api bash

python apps/cli/main.py --help
python apps/cli/main.py historical fetch --days 5
```

### Seeding Test Data
If you need mock data for backtesting:

```bash
# Docker
docker compose exec api python scripts/seed_test_data.py

# Manual
python scripts/seed_test_data.py
```

## 6. Database Access (MongoDB Compass)

To connect MongoDB Compass to the database running in Docker:

### Local Machine (Docker Desktop)
- **Connection String**: `mongodb://localhost:27017/`
- **Username/Password**: None (unless you configured them in compose)

### VPS (Remote Access)
1. **SSH Tunnel (Recommended)**:
   - In Compass, go to **Advanced Connection Options** -> **SSH Tunnel**.
   - Set **SSH Host** to your VPS IP.
   - Set **SSH Username** to your VPS user (e.g., `ubuntu`).
   - Use your SSH Key.
   - **Connection String**: `mongodb://localhost:27017/` (Compass will tunnel this to the VPS).
2. **Direct Connection (Not Recommended)**:
   - Ensure port `27017` is open in UFW.
   - **Connection String**: `mongodb://YOUR_VPS_IP:27017/`

## 7. Security (Optional but Recommended)

### Setup UFW Firewall
```bash
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw allow 4321/tcp # Dashboard
sudo ufw enable
```

## 8. Manual Setup (Non-Docker)

If you chose to run the app directly on the host (not recommended compared to Docker), you may encounter the `externally-managed-environment` error. 

### To Fix:
You **must** use a virtual environment. Modern Linux prohibits `pip install` globally.

```bash
# 1. Install venv if missing
sudo apt update && sudo apt install -y python3-venv

# 2. Create the environment
python3 -m venv .venv

# 3. Activate it
source .venv/bin/activate

# 4. NOW install requirements
pip install -r requirements.txt
```

### Troubleshooting: "Command insert requires authentication"
If you see this error, it means your MongoDB instance has security enabled. You need to provide a username and password in your `MONGODB_URI`.

**Update your `.env` file**:
```bash
# Format: mongodb://username:password@host:port/database
MONGODB_URI=mongodb://admin:yourpassword@localhost:27017/trade_bot?authSource=admin
```

---

## 9. Security (Optional but Recommended)
