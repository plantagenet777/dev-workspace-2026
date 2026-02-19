#!/bin/bash

echo "🚢 Starting Pump Predictive Maintenance Deployment..."

# 1. Build Docker image
docker build -t pump-predictive-maintenance:v1.0 .

# 2. Stop and remove old container if present
docker stop pump_monitor || true
docker rm pump_monitor || true

# 3. Run new container with certificates mounted
# --restart always for resilience
docker run -d \
  --name pump_monitor \
  --restart always \
  -v /etc/pump-monitor/certs:/app/certs:ro \
  -v ./logs:/app/logs \
  --env-file .env \
  pump-predictive-maintenance:v1.0

echo "✅ Deployment finished. System is running in background."
