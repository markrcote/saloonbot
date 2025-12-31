#!/bin/bash
# Start bot + redis, run server locally

echo "Starting bot and redis..."
docker compose -f compose.dev-server-local.yml up -d

echo "Waiting for services..."
sleep 2

echo "Starting server locally..."
export REDIS_HOST=localhost
export REDIS_PORT=6379
export SALOONBOT_DEBUG=1

python server.py

# Cleanup on exit
echo "Stopping background services..."
docker compose -f compose.dev-server-local.yml down
