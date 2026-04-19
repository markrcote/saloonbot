# Technology Stack

**Analysis Date:** 2026-04-19

## Languages

**Primary:**
- Python 3.13 - All application code (bot, server, game logic, utilities)

## Runtime

**Environment:**
- Python 3.13 (specified in `runtime.txt`)
- CPython (standard interpreter, no special runtime)

**Package Manager:**
- pip with `requirements.txt`
- Lockfile: `requirements.txt` is fully pinned (all packages at exact versions)

## Frameworks

**Core:**
- nextcord 3.1.1 - Discord bot framework (async, slash commands via `@bot.slash_command`)
- redis 7.4.0 - Redis client; used both sync (`redis.Redis`) in server and async (`redis.asyncio.Redis`) in bot

**Testing:**
- unittest (stdlib) - Test runner and assertion library; used in `test.py` and `test_e2e.py`
- unittest.mock (stdlib) - Mocking via `MagicMock`, `patch`

**Build/Dev:**
- flake8 7.3.0 - Linting (max-line-length 120, see `.flake8`)
- Docker / Docker Compose - Container build and orchestration

## Key Dependencies

**Critical:**
- nextcord 3.1.1 - Entire Discord integration; slash commands, intents, interactions (`bot.py`)
- redis 7.4.0 - Inter-process communication; pub/sub between bot and server (`bot.py`, `cardgames/casino.py`)
- mysql-connector-python 9.5.0 - MySQL ORM-less direct connector (`cardgames/database.py`)

**Infrastructure:**
- aiohttp 3.13.5 - Async HTTP, pulled in as nextcord dependency
- aioconsole 0.8.2 - Used by `cli.py` for async stdin input
- requests 2.33.1 - Sync HTTP client (minor utility use)
- typing_extensions 4.15.0 - Backport type hints

## Configuration

**Environment:**
- All configuration via environment variables (no `.env` file used at runtime)
- Key vars: `REDIS_HOST`, `REDIS_PORT`, `MYSQL_HOST`, `MYSQL_PORT`, `MYSQL_USER`, `MYSQL_PASSWORD`, `MYSQL_DATABASE`, `DISCORD_TOKEN` (or `DISCORD_TOKEN_FILE`), `DISCORD_GUILDS` (or `DISCORD_GUILDS_FILE`), `SALOONBOT_DEBUG`
- Game tuning vars: `BLACKJACK_MIN_BET`, `BLACKJACK_MAX_BET`, `BLACKJACK_TIME_FOR_BETTING`, `BLACKJACK_TIME_BETWEEN_HANDS`, `BLACKJACK_REMINDER_PERIOD`
- Secrets in production passed via Docker secrets files (`discord_token.txt`, `discord_guilds.txt`) mounted at `/run/secrets/`

**Build:**
- `Dockerfile.bot` - Builds bot image from `python:3.13-slim`
- `Dockerfile.server` - Builds server image from `python:3.13-slim`
- `compose.yml` - Production Docker Compose (references `ghcr.io/markrcote/saloonbot-*:main`)
- `compose.test.yml` - Test infrastructure (Redis + MySQL only; server runs natively)
- `compose.dev-redis-only.yml`, `compose.dev-bot-local.yml`, `compose.dev-server-local.yml` - Dev variants
- `GIT_SHA` build arg embedded into `.version` file for runtime version reporting

## Platform Requirements

**Development:**
- Python 3.13
- Docker + Docker Compose (for Redis/MySQL infrastructure)
- Redis and MySQL instances (via Docker or external)

**Production:**
- Docker Compose deployment
- Container registry: `ghcr.io/markrcote/`
- Heroku-compatible `Procfile` present (`worker: python bot.py`) suggesting possible Heroku deployment history

---

*Stack analysis: 2026-04-19*
