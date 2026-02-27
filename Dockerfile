# Backend Dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy Project
COPY . .

# Set Python Path
ENV PYTHONPATH=/app

# Expose API Port
EXPOSE 8000

# Default Command (Overridden in Compose)
CMD ["python", "apps/api/run.py"]
