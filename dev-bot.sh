#!/bin/bash
# Start server + redis, run bot locally

echo "Starting server and redis..."
docker compose -f compose.dev-bot-local.yml up -d

echo "Waiting for services..."
sleep 2

echo "Starting bot locally..."
export REDIS_HOST=localhost
export REDIS_PORT=6379
export DISCORD_TOKEN="${DISCORD_TOKEN}"
export DISCORD_GUILDS="${DISCORD_GUILDS}"
export SALOONBOT_DEBUG=1

python bot.py

# Cleanup on exit
echo "Stopping background services..."
docker compose -f compose.dev-bot-local.yml down
