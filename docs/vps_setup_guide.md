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

```bash
# Clone Repository
git clone https://github.com/your-repo/trade-bot-v2.git
cd trade-bot-v2

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

## 6. Security (Optional but Recommended)

### Setup UFW Firewall
```bash
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw allow 4321/tcp # Dashboard
sudo ufw enable
```

### SSL with Nginx Proxy Manager
For production, it is recommended to run Nginx Proxy Manager or simple Nginx with Certbot to serve the UI over HTTPS.
