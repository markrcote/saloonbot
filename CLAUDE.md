# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

SaloonBot is a Discord bot that generates Old West names and provides a blackjack card game. It consists of two main components that communicate via Redis pub/sub:
- **bot.py** - Discord bot client using nextcord
- **server.py** - Backend game server handling game logic
- MySQL database stores user information

## Commands

### Testing
```bash
python test.py
```

### Linting
```bash
flake8 .
```
Configuration: max-line-length = 120 (see .flake8)

### Development Options

**Run both components locally (Redis/MySQL in Docker):**
```bash
./dev-redis.sh
# Then in separate terminals:
export REDIS_HOST=localhost REDIS_PORT=6379 SALOONBOT_DEBUG=1
export DISCORD_TOKEN="..." DISCORD_GUILDS="..."
python bot.py

export REDIS_HOST=localhost REDIS_PORT=6379 SALOONBOT_DEBUG=1
export MYSQL_HOST=localhost MYSQL_PORT=3306
export MYSQL_USER=saloonbot MYSQL_PASSWORD=saloonbot_password MYSQL_DATABASE=saloonbot
python server.py
```

**Run bot locally (server in Docker):** `./dev-bot.sh`

**Run server locally (bot in Docker):** `./dev-server.sh`

**Production:** `docker compose up -d`

### CLI Testing
```bash
python cli.py
```
Standalone async client for testing game logic without Discord.

## Architecture

```
Discord Users
     |
+----v----+
|   BOT   |  bot.py - Slash commands, Redis subscriber
+----+----+
     | JSON via Redis pub/sub
+----v----+
|  REDIS  |  Message broker
+----+----+
     |
+----v----+
|  SERVER |  server.py - Casino orchestrator, game logic
+----+----+
     |
+----v----+
|  MySQL  |  User persistence
+---------+
```

### Redis Pub/Sub Topics
- **"casino"** - Bot publishes game actions, server subscribes
- **"casino_update"** - Server publishes game creation, bot subscribes
- **"game_updates_{game_id}"** - Server publishes game state changes

### Key Modules

**cardgames/**
- `blackjack.py` - Main game logic with states: WAITING → ACTIVE → FINISHED
- `casino.py` - Redis pub/sub coordinator, manages game instances
- `card_game.py` - Base class for card games (deck, shuffle, deal)
- `database.py` - MySQL connection with auto-reconnect

**wwnames/**
- `wwnames.py` - Random name generator using data files in `names/`

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| REDIS_HOST | localhost | Redis server host |
| REDIS_PORT | 6379 | Redis server port |
| MYSQL_HOST | localhost | MySQL server host |
| MYSQL_PORT | 3306 | MySQL server port |
| MYSQL_USER | saloonbot | MySQL username |
| MYSQL_PASSWORD | (empty) | MySQL password |
| MYSQL_DATABASE | saloonbot | MySQL database name |
| DISCORD_TOKEN | - | Bot token (or use DISCORD_TOKEN_FILE) |
| DISCORD_GUILDS | - | Comma-separated guild IDs (or use DISCORD_GUILDS_FILE) |
| SALOONBOT_DEBUG | - | Set to enable debug logging |

## Key Patterns

- Bot uses asyncio with `@tasks.loop(seconds=3.0)` for polling Redis
- Server uses synchronous Redis in blocking game loop
- Both implement exponential backoff for Redis reconnection
- Custom exceptions: `CardGameError`, `NotPlayerTurnError`, `PlayerNotFoundError`
- Blackjack `tick()` handles auto-advance between hands and player turn reminders
