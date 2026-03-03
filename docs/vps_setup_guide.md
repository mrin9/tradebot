# VPS Setup Guide

Guide to deploying Trade Bot on a Linux VPS (Ubuntu 22.04+).

## 1. Initial Server Setup

```bash
# Update System
sudo apt update && sudo apt upgrade -y

# Install Docker & Compose
sudo apt install -y docker.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker

# 1. Grant Permission (Fix: "permission denied while trying to connect to the docker API")
# Note: If your user doesn't have sudo rights for usermod, run this as root:
# usermod -aG docker pradeep
sudo usermod -aG docker $USER

# 2. LOG OUT and Log in again for the group change to take effect!
# If you don't want to log out, you can run:
newgrp docker
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

## 5. Using the App (The Docker Way) 🚀

It is **highly recommended** to run all commands inside the Docker environment. This ensures you have the correct Python version, dependencies, and database access without installing anything on your host machine.

### 1. Run the CLI (One-off)
Use `docker compose exec` to run commands without leaving your shell:
```bash
# Check CLI Help
docker compose exec api python apps/cli/main.py --help

# Sync History (Example)
docker compose exec api python apps/cli/main.py sync-history --days 5
```

### 2. Enter Interactive Shell
If you need to run many commands, you can "log in" to the container:
```bash
docker compose exec -it api bash

# Now you are inside the container
python apps/cli/main.py --help
exit
```

### 3. Running Tests & Scripts
```bash
# Run all tests
docker compose exec api pytest tests/

# Run Seed script
docker compose exec api python scripts/seed_test_data.py
```

## 6. Managing Configuration (.env)

Your environment variables are stored in the `.env` file. 

### How to Edit
The `.env` file is mounted as a volume, so changes made on the VPS will be seen by the container. However, **Python processes only read environment variables on startup.**

1.  **Edit the file on the VPS**:
    ```bash
    nano .env
    ```
2.  **Restart the containers to apply changes**:
    ```bash
    docker compose up -d
    ```

> [!WARNING]
> Editing the `.env` file *inside* the container via `bash` is possible but **not recommended**. Always maintain the `.env` file on your VPS host disk as the source of truth.

## 7. Applying Code Changes

Thanks to Docker volumes (`.:/app`), your changes to Python or Javascript files on the VPS disk are instantly reflected inside the container.

### For CLI & Scripts (Immediate)
When you run commands via `docker compose exec`, they **always** use the latest version of your code on the disk. **No rebuild or restart is needed.**

### For API & Web Services (Restart Required)
The background services load code into memory. If you modify the API logic or Nuxt components, you must restart the service to see the changes:
```bash
# Quick restart (takes < 2 seconds)
docker compose restart api web
```

### When to Rebuild?
You only need to run `docker compose up -d --build` if:
1.  You changed `requirements.txt` or `package.json` (new dependencies).
2.  You modified a `Dockerfile`.

## 8. Database Access (MongoDB Compass)

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

### Troubleshooting: "XTS_ROOT_URL is not set"
If you see warnings about unset variables when running `docker compose`:
1.  Ensure you have a `.env` file in the same directory as `docker-compose.yml`.
2.  Check that the variable is correctly defined (it must match exactly).
3.  If running via `docker run`, make sure to pass `--env-file .env`.

### Troubleshooting: "Command insert requires authentication"
If you see this error, it means your MongoDB instance has security enabled. You need to provide a username and password in your `MONGODB_URI`.

**Update your `.env` file**:
```bash
# Format: mongodb://username:password@host:port/database
MONGODB_URI=mongodb://admin:yourpassword@localhost:27017/trade_bot?authSource=admin
```

---

## 9. Security (Optional but Recommended)
