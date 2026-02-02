# GitHub Copilot Instructions for SaloonBot

This file provides guidance to GitHub Copilot when working with code in this repository.

## Project Overview

SaloonBot is a Discord bot that generates Old West names and provides a blackjack card game. It consists of two main components that communicate via Redis pub/sub:
- **bot.py** - Discord bot client using nextcord library for slash commands and Discord interactions
- **server.py** - Backend game server handling game logic and state management
- **MySQL database** - Stores user information and game data persistence
- **Redis** - Message broker for pub/sub communication between bot and server

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

### Communication Flow
- Bot receives Discord commands, publishes to Redis "casino" topic
- Server subscribes to "casino", processes commands, updates game state
- Server publishes game updates to "casino_update" and "game_updates_{game_id}" topics
- Bot subscribes to updates and sends messages back to Discord users

### Redis Pub/Sub Topics
- **"casino"** - Bot publishes game actions (create, join, bet, hit, stand), server subscribes
- **"casino_update"** - Server publishes game creation events, bot subscribes
- **"game_updates_{game_id}"** - Server publishes game state changes for specific games

## Key Modules

### cardgames/
- **blackjack.py** - Main game logic with state machine:
  - States: WAITING → BETTING → PLAYING → DEALER_TURN → RESOLVING → BETWEEN_HANDS
  - Manages player hands, dealer logic, betting, and game flow
  - Uses `tick()` method for auto-advance between hands and turn reminders
- **casino.py** - Redis pub/sub coordinator, manages game instances lifecycle
- **card_game.py** - Base class for card games (deck management, shuffle, deal)
- **database.py** - MySQL connection handling with auto-reconnect on failure

### wwnames/
- **wwnames.py** - Random Old West name generator
- **names/** - Data files containing first names and surnames

### Root Files
- **bot.py** - Discord client using nextcord, implements slash commands
- **server.py** - Game server with synchronous Redis client in blocking loop
- **cli.py** - Standalone async client for testing game logic without Discord

## Development Commands

### Testing
```bash
# Unit tests
python test.py

# End-to-end tests (requires Docker)
python test_e2e.py
# or use helper script:
./run-e2e-tests.sh
```

### Linting
```bash
flake8 .
```
Configuration: `max-line-length = 120` (see .flake8)

### Development Workflows

**Run both components locally (Redis/MySQL in Docker):**
```bash
./dev-redis.sh
# Then in separate terminals:

# Terminal 1 - Bot
export REDIS_HOST=localhost REDIS_PORT=6379 SALOONBOT_DEBUG=1
export DISCORD_TOKEN="your-token" DISCORD_GUILDS="your-guild-ids"
python bot.py

# Terminal 2 - Server
export REDIS_HOST=localhost REDIS_PORT=6379 SALOONBOT_DEBUG=1
export MYSQL_HOST=localhost MYSQL_PORT=3306
export MYSQL_USER=saloonbot MYSQL_PASSWORD=saloonbot_password MYSQL_DATABASE=saloonbot
python server.py
```

**Run bot locally (server in Docker):**
```bash
./dev-bot.sh
```

**Run server locally (bot in Docker):**
```bash
./dev-server.sh
```

**Production deployment:**
```bash
docker compose up -d
```

### CLI Testing
```bash
python cli.py
```
Standalone async client for testing game logic without Discord integration.

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
| DISCORD_TOKEN | - | Discord bot token (or use DISCORD_TOKEN_FILE) |
| DISCORD_GUILDS | - | Comma-separated guild IDs (or use DISCORD_GUILDS_FILE) |
| SALOONBOT_DEBUG | - | Set to enable debug logging |
| BLACKJACK_MIN_BET | 5 | Minimum bet amount in dollars |
| BLACKJACK_MAX_BET | 100 | Maximum bet amount in dollars |
| BLACKJACK_TIME_FOR_BETTING | 30 | Seconds allowed for placing bets |
| BLACKJACK_TIME_BETWEEN_HANDS | 10 | Seconds between hands |
| BLACKJACK_REMINDER_PERIOD | 30 | Seconds before reminding player of their turn |

## Key Design Patterns

### Async vs Sync
- **bot.py** uses asyncio with `@tasks.loop(seconds=3.0)` for polling Redis
- **server.py** uses synchronous Redis client in blocking game loop
- Both implement exponential backoff for Redis reconnection

### Error Handling
Custom exceptions defined in card_game.py:
- `CardGameError` - Base exception for card game errors
- `NotPlayerTurnError` - Raised when player acts out of turn
- `PlayerNotFoundError` - Raised when player ID not found in game
- `InvalidBetError` - Raised for invalid bet amounts
- `InsufficientFundsError` - Raised when player lacks funds

### Game State Management
- Blackjack uses state machine pattern with explicit state transitions
- `tick()` method handles time-based events (auto-advance, reminders)
- State persisted in memory (server.py), user data persisted in MySQL

## Code Style Guidelines

- Follow PEP 8 with max line length of 120 characters
- Use descriptive variable names following the existing patterns
- Add type hints where appropriate (following existing style)
- Keep functions focused and single-purpose
- Use docstrings for complex logic

## Testing Guidelines

- Unit tests in `test.py` - no external dependencies
- E2E tests in `test_e2e.py` - full system integration with Docker
- Always run linting before committing: `flake8 .`
- Verify tests pass before submitting changes: `python test.py`
- For significant changes, run E2E tests: `python test_e2e.py`

## Common Tasks

### Adding a New Card Game
1. Create new game class in `cardgames/` inheriting from `CardGame`
2. Implement required methods: `deal()`, `get_state()`, etc.
3. Add game registration in `casino.py`
4. Add bot command handler in `bot.py`
5. Add unit tests in `test.py`

### Modifying Game Logic
1. Update relevant class in `cardgames/blackjack.py`
2. Ensure state transitions remain valid
3. Update tests to cover new behavior
4. Test with `cli.py` for quick iteration

### Adding New Environment Variables
1. Add to environment variable table in documentation
2. Add default value in relevant Python file
3. Update Docker Compose files if needed
4. Document in `README.md` and this file
