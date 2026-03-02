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

### maintenance
```bash
# Prune old images
docker system prune -a
```
