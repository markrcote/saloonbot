# discord_wwnames

[![Lint and test](https://github.com/markrcote/discord_wwnames/actions/workflows/lint-and-test.yml/badge.svg)](https://github.com/markrcote/discord_wwnames/actions/workflows/lint-and-test.yml)

Discord bot originally built for randomly generating Old West names and now wandering off into card games.

Names were scraped from [Mithril and Mages](https://www.mithrilandmages.com/utilities/WesternBrowse.php).

## Commands

### Names

* `/wwname [gender] [number]`: Generates `number` Old West names by choosing a random first name of the given `gender` and a random surname.  The `gender` argument accepts any string starting with `f` or `m`.  If no `gender` is given, a random one is chosen. If not provided, `number` defaults to 1. The output is a newline-joined list of names in the form of `<gender emoji> first_name last_name`.

### Cards

* `/newgame` starts a new game of blackjack.  Commands (hit, stand, etc.) are read
  from messages.

### Metadata

* `/version`: Outputs the current git sha.

## Database Setup

SaloonBot uses PostgreSQL to persist game state and user data across server restarts. This ensures that active games can continue even after the bot or server restarts.

### Environment Variables

Configure the database connection using either a full connection string or individual parameters:

**Option 1: Full connection string**
```bash
DATABASE_URL=postgresql://user:pass@host:port/dbname
```

**Option 2: Individual parameters** (used if `DATABASE_URL` is not set)
```bash
POSTGRES_HOST=localhost      # Default: localhost
POSTGRES_PORT=5432           # Default: 5432
POSTGRES_DB=saloonbot        # Default: saloonbot
POSTGRES_USER=saloonbot      # Default: saloonbot
POSTGRES_PASSWORD=saloonbot  # Default: saloonbot
```

**Disable database** (run in memory-only mode)
```bash
USE_DATABASE=false
```

### Running Migrations

The database schema is automatically created on server startup using SQLAlchemy models. No manual migration is needed for the initial setup.

For manual migration management using Alembic:

```bash
# Create a new migration
alembic revision --autogenerate -m "Description of changes"

# Apply migrations
alembic upgrade head

# Rollback one migration
alembic downgrade -1

# View migration history
alembic history
```

### Backup and Restore

**Backup the database:**
```bash
# Using Docker
docker compose exec postgres pg_dump -U saloonbot saloonbot > backup.sql

# Using local PostgreSQL
pg_dump -h localhost -U saloonbot saloonbot > backup.sql
```

**Restore from backup:**
```bash
# Using Docker
docker compose exec -T postgres psql -U saloonbot saloonbot < backup.sql

# Using local PostgreSQL
psql -h localhost -U saloonbot saloonbot < backup.sql
```

**Backup just the game state data:**
```bash
pg_dump -h localhost -U saloonbot -t users -t games -t game_players --data-only saloonbot > game_data.sql
```

## Development

SaloonBot provides flexible development workflows using Docker Compose configurations. The bot consists of three main components: the Discord bot (`bot.py`), the server component (`server.py`), and PostgreSQL for persistence, all communicating through Redis.

### Development Scenarios

There are three development compose files, each designed for a different workflow:

1. **`compose.dev-bot-local.yml`** - Runs server + redis + postgres in Docker, allowing you to run `bot.py` locally
2. **`compose.dev-server-local.yml`** - Runs bot + redis + postgres in Docker, allowing you to run `server.py` locally
3. **`compose.dev-redis-only.yml`** - Runs redis + postgres in Docker, allowing you to run both components locally

### Using Helper Scripts

For convenience, helper scripts are provided for each scenario:

#### Run bot locally (server in Docker)
```bash
./dev-bot.sh
```
This starts the server, redis, and postgres containers, then runs the bot locally. Requires `DISCORD_TOKEN` and `DISCORD_GUILDS` environment variables.

#### Run server locally (bot in Docker)
```bash
./dev-server.sh
```
This starts the bot, redis, and postgres containers, then runs the server locally. Requires `discord_token.txt` and `discord_guilds.txt` files for the bot container.

#### Run both components locally (redis + postgres in Docker)
```bash
./dev-redis.sh
```
This starts redis and postgres. You can then run `bot.py` and `server.py` separately in different terminals:
```bash
# Terminal 1
export REDIS_HOST=localhost REDIS_PORT=6379 SALOONBOT_DEBUG=1
export POSTGRES_HOST=localhost POSTGRES_PORT=5432
export POSTGRES_DB=saloonbot POSTGRES_USER=saloonbot POSTGRES_PASSWORD=saloonbot
export DISCORD_TOKEN="your-token" DISCORD_GUILDS="your-guild-ids"
python bot.py

# Terminal 2
export REDIS_HOST=localhost REDIS_PORT=6379 SALOONBOT_DEBUG=1
export POSTGRES_HOST=localhost POSTGRES_PORT=5432
export POSTGRES_DB=saloonbot POSTGRES_USER=saloonbot POSTGRES_PASSWORD=saloonbot
python server.py
```

### Manual Usage

You can also use Docker Compose directly without the helper scripts:

```bash
# Start services
docker compose -f compose.dev-bot-local.yml up -d

# View logs
docker compose -f compose.dev-bot-local.yml logs -f

# Stop services
docker compose -f compose.dev-bot-local.yml down
```

### Production/Staging Deployment

For production and staging deployments, continue to use the standard `compose.yml` file:

```bash
docker compose up -d
```

This runs all components (bot, server, and redis) in Docker containers.

## Tests

To run tests, run `python test.py`.
