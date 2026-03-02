# DevOps Guide

Instructions for building, maintaining, and troubleshooting the Dockerized application.

## 1. Docker Structure

- **Backend Container (`trade-bot-api`)**:
    - Base Image: `python:3.11-slim`
    - Runs: `uvicorn` server for API and Socket.IO.
    - Health Check: Verifies health via `/api/status`.
    - Volumes: Maps project root for code access (in dev).

- **Frontend Container (`trade-bot-web`)**:
    - Build Stage: `node:18-alpine` (Nuxt `generate`).
    - Final Image: `nginx:alpine` serving static assets.
    - Configuration: `nginx.conf` handles routing and API proxying.

- **Database Container (`trade-bot-mongo`)**:
    - Image: `mongo:latest`
    - Health Check: Verifies health via `mongosh --eval`.
    - Volume: `mongo_data` persists data.

## 2. Build Instructions

### Rebuild specific service
```bash
docker compose build api
docker compose up -d api
```

### Full Rebuild (No Cache)
```bash
docker compose build --no-cache
docker compose up -d --build
```

## 3. Logging & Monitoring

### View Logs
```bash
# Stream logs for all services
docker compose logs -f

# Stream logs for API only
docker compose logs -f api
```

## 4. Running Tests
You can run automated tests directly inside the backend container:

```bash
# Run all tests
docker compose exec api pytest tests/

# Run a specific test
docker compose exec api pytest tests/backtest/test_xts_socket.py
```

### Running One-off Scripts
You can run any script from the project root inside a temporary container:

```bash
# General Pattern
docker run --rm --env-file .env <image-name> python <path/to/script.py> [args]

# Example: Run XTS Socket Tester
docker run --rm --env-file .env trade-bot-api:latest python tests/backtest/test_xts_socket.py --events all
```

### Seeding Data
To populate the `tradebot_frozen_test` database with mock data:
```bash
docker compose exec api python scripts/seed_test_data.py
```

## 5. Shell Access
To debug or run manual scripts inside a running container:
```bash
docker compose exec -it api bash
```

## 6. Database Access
- **Service Name**: `mongo` (Use this when connecting from the `api` container).
- **External Port**: `27017` (Mapped to host for Compass access).
- **Connection URI**: `mongodb://localhost:27017/`

## 7. Registry Workflow

To maintain a clean production environment, images are built locally and pushed to a registry.

### Tagging Strategy
- `latest`: Always points to the most recent stable build.
- `vX.Y.Z`: Semantic versioning for production releases.

### Publishing Images
```bash
# API
docker build -t yourusername/trade-bot-api:latest .
docker push yourusername/trade-bot-api:latest

# UI
cd apps/ui
docker build -t yourusername/trade-bot-web:latest .
docker push yourusername/trade-bot-web:latest
```

## 8. Maintenance & Cleanup

```bash
# Remove all stopped containers
docker container prune

# Remove all unused images (not just dangling ones)
docker image prune -a

# Remove all unused networks
docker network prune

# Full System Cleanup (removes stopped containers, unused networks, and dangling images/build cache)
docker system prune

# Full System Cleanup (including unused images)
docker system prune -a --volumes
```
