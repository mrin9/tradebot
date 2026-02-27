# DevOps Guide

Instructions for building, maintaining, and troubleshooting the Dockerized application.

## 1. Docker Structure

- **Backend Container (`trade-bot-api`)**:
    - Base Image: `python:3.11-slim`
    - Runs: `uvicorn` server for API and Socket.IO.
    - Volumes: Maps project root for code access (in dev).

- **Frontend Container (`trade-bot-web`)**:
    - Base Image: `nginx:alpine`
    - Build Stage: `node:18-alpine` builds the Static Assets.
    - Configuration: `nginx.conf` proxies `/api` requests to the Backend.

- **Database Container (`trade-bot-mongo`)**:
    - Image: `mongo:latest`
    - Volume: `mongo_data` persists data across restarts.

## 2. Build Instructions

### Rebuild specific service
```bash
docker-compose build api
docker-compose up -d api
```

### Full Rebuild (No Cache)
```bash
docker-compose build --no-cache
docker-compose up -d
```

## 3. Logging & Monitoring

### View Logs
```bash
# Stream logs for all services
docker-compose logs -f

# Stream logs for API only
docker-compose logs -f api
```

### maintenance
```bash
# Prune old images
docker system prune -a
```
