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
echo ""
echo "Run server locally with:"
echo "  export REDIS_HOST=localhost REDIS_PORT=6379 USE_SQLITE=1 SALOONBOT_DEBUG=1"
echo "  python server.py"
echo ""
echo "Press Ctrl+C to stop redis and exit"

# Wait indefinitely until interrupted
sleep infinity
