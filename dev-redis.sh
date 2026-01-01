#!/bin/bash
# Start only redis

# Cleanup function
cleanup() {
    echo "Stopping redis..."
    docker compose -f compose.dev-redis-only.yml down
}

# Set trap to ensure cleanup happens on exit, interrupt, or error
trap cleanup EXIT INT TERM

echo "Starting redis..."
docker compose -f compose.dev-redis-only.yml up -d
echo "Redis running on localhost:6379"
echo "Press Ctrl+C to stop redis and exit"

# Wait indefinitely until interrupted
wait
