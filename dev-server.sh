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

echo "Starting server locally (SQLite)..."
export REDIS_HOST=localhost
export REDIS_PORT=6379
export USE_SQLITE=1
export SALOONBOT_DEBUG=1
# Default local runs to the deterministic fake LLM provider so testing never
# hits a real (billed) API by accident. Export LLM_PROVIDER=openai/claude
# yourself beforehand if you specifically want to exercise the real client.
export LLM_PROVIDER="${LLM_PROVIDER:-fake}"

python server.py
