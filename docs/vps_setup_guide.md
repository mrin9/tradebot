# VPS Setup Guide

Guide to deploying Trade Bot on a Linux VPS (Ubuntu 22.04+).

## 1. Initial Server Setup

```bash
# Update System
sudo apt update && sudo apt upgrade -y

# Install Docker & Compose
sudo apt install -y docker.io docker-compose
sudo systemctl enable --now docker
sudo usermod -aG docker $USER
```

## 2. Project Setup

```bash
# Clone Repository
git clone https://github.com/your-repo/trade-bot-v2.git
cd trade-bot-v2

# Create Environment File
cp .env.example .env
nano .env
# Fill in your XTS Credentials and Mongo URI (if external)
```

## 3. Deployment

```bash
# Build and Run Containers
docker-compose up --build -d

# Verify Running Containers
docker ps
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
