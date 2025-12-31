#!/bin/bash
# Start only redis

echo "Starting redis..."
docker compose -f compose.dev-redis-only.yml up -d
echo "Redis running on localhost:6379"
