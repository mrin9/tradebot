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
```bash
# Set your Docker Hub username
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

### Manual Build on VPS (Alternative)
If you prefer building directly on the VPS:
```bash
docker compose up -d --build
```

## 4. Security (Optional but Recommended)

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
