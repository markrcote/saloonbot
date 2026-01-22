#!/bin/bash
# Start bot + redis, run server locally

# Cleanup function
cleanup() {
    echo "Stopping background services..."
    docker compose -f compose.dev-server-local.yml down
}

# Set trap to ensure cleanup happens on exit, interrupt, or error
trap cleanup EXIT INT TERM

echo "Starting bot and redis..."
docker compose -f compose.dev-server-local.yml up -d

echo "Waiting for services..."
sleep 2

echo "Starting server locally..."
export REDIS_HOST=localhost
export REDIS_PORT=6379
export MYSQL_HOST=localhost
export MYSQL_PORT=3306
export MYSQL_USER=saloonbot
export MYSQL_PASSWORD=saloonbot_password
export MYSQL_DATABASE=saloonbot
export SALOONBOT_DEBUG=1

python server.py
