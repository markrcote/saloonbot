# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

SaloonBot is a Discord bot that generates Old West names and provides a blackjack card game. It consists of two main components that communicate via Redis pub/sub:
- **bot.py** - Discord bot client using nextcord
- **server.py** - Backend game server handling game logic
- MySQL database stores user information

## Commands

### Unit Testing
```bash
python test.py
```

### End-to-End Testing
```bash
./run-e2e-tests.sh
```
Starts Redis and MySQL via `compose.test.yml`, runs the actual server, and tests the complete system integration. Tests live in `test_e2e.py`.

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
- **"casino_update"** - Server publishes game creation and list_games responses, bot subscribes
- **"game_updates_{game_id}"** - Server publishes game state changes

### Casino Protocol (published to "casino")

**Casino actions** (`event_type: "casino_action"`):
- `new_game` - Create a new game; optional `guild_id`/`channel_id` for bot recovery
- `list_games` - Request list of all active games (used by bot on startup for recovery)

**Player actions** (`event_type: "player_action"`):
- `join`, `bet` (with `amount`), `hit`, `stand`, `double_down`, `split`

### Casino Update Protocol (published to "casino_update")

- `new_game` response - includes `game_id`, `request_id`, and optional channel info
- `list_games` response - includes `request_id` and `games` list (each entry: `game_id`, `state`, `guild_id`, `channel_id`)

### Key Modules

**cardgames/**
- `blackjack.py` - Main game logic with states: WAITING → BETTING → PLAYING → DEALER_TURN → RESOLVING → BETWEEN_HANDS; supports `to_dict()`/`from_dict()` for persistence
- `casino.py` - Redis pub/sub coordinator, manages game instances; loads persisted games on startup; handles `list_games` for bot recovery
- `card_game.py` - Base class for card games (deck, shuffle, deal)
- `database.py` - MySQL connection with auto-reconnect; manages `users`, `games`, and `game_channels` tables

**Database tables:**
- `users` - Stores player usernames and wallet balances (default $200)
- `games` - Persists game state (deck, hands, bets, timers) for server restart recovery
- `game_channels` - Maps game IDs to Discord guild/channel for bot restart recovery

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
| BLACKJACK_MIN_BET | 5 | Minimum bet amount in dollars |
| BLACKJACK_MAX_BET | 100 | Maximum bet amount in dollars |
| BLACKJACK_TIME_FOR_BETTING | 30 | Seconds allowed for placing bets |
| BLACKJACK_TIME_BETWEEN_HANDS | 10 | Seconds between hands |
| BLACKJACK_REMINDER_PERIOD | 30 | Seconds before reminding player of their turn |

## Key Patterns

- Bot uses asyncio with `@tasks.loop(seconds=3.0)` for polling Redis
- Server uses synchronous Redis in blocking game loop
- Both implement exponential backoff for Redis reconnection
- Custom exceptions: `CardGameError`, `NotPlayerTurnError`, `PlayerNotFoundError`, `InvalidBetError`, `InsufficientFundsError`
- Blackjack `tick()` handles auto-advance between hands and player turn reminders
- **Game persistence**: Casino saves game state to MySQL after each action; restores all active games on startup via `load_all_active_games()`
- **Bot recovery**: On `on_ready`, bot sends `list_games` request, then reconnects to all active games (subscribes to topics, announces reconnection in channel)
- `new_game` requests should include `guild_id`/`channel_id` so bot recovery can find the right channel after restart
