# External Integrations

**Analysis Date:** 2026-04-19

## APIs & External Services

**Discord:**
- Discord Gateway API - Real-time bot event stream (guilds, messages, interactions)
  - SDK/Client: nextcord 3.1.1 (`import nextcord`, `from nextcord.ext import commands, tasks`)
  - Auth: `DISCORD_TOKEN` env var or `DISCORD_TOKEN_FILE` pointing to a secrets file
  - Guild scoping: `DISCORD_GUILDS` / `DISCORD_GUILDS_FILE` restricts slash commands to specific guild IDs
  - Intents: `nextcord.Intents.default()` with `message_content = True`
  - Entry point: `bot.py`

## Data Storage

**Databases:**
- MySQL 8.0 - Primary persistence for user wallets and game state
  - Connection env vars: `MYSQL_HOST`, `MYSQL_PORT`, `MYSQL_USER`, `MYSQL_PASSWORD`, `MYSQL_DATABASE`
  - Client: `mysql-connector-python` 9.5.0 (raw connector, no ORM)
  - Implementation: `cardgames/database.py` (`Database` class)
  - Schema managed at startup via `_init_database()` with `CREATE TABLE IF NOT EXISTS`
  - Tables: `users` (wallet balances), `games` (serialized game state JSON), `game_channels` (game-to-Discord channel mapping)
  - Auto-reconnect: `_connect()` checks `is_connected()` before every operation

**File Storage:**
- Local filesystem only - name data files in `wwnames/names/` (read-only at runtime)

**Caching:**
- Redis (Alpine image) - Used as message broker, not a cache
  - Connection env vars: `REDIS_HOST`, `REDIS_PORT`
  - Client: `redis` 7.4.0 — sync `redis.Redis` in `cardgames/casino.py`, async `redis.asyncio.Redis` in `bot.py`
  - Pub/sub topics: `casino` (bot → server actions), `casino_update` (server → bot responses), `game_updates_{game_id}` (per-game state changes)
  - No data persistence configured in Redis; all durable state lives in MySQL

## Authentication & Identity

**Auth Provider:**
- Discord OAuth / Bot Token (no third-party auth provider)
  - Implementation: Token provided via `DISCORD_TOKEN` env var or Docker secret file
  - No user authentication layer in the application; Discord user identity (`interaction.user`) used directly
  - No session management; stateless per-interaction model

## Monitoring & Observability

**Error Tracking:**
- None - No Sentry, Datadog, or similar service integrated

**Logs:**
- Python stdlib `logging` module
- Format: `%(asctime)s - %(levelname)s - %(message)s`
- Level: `INFO` by default; `DEBUG` when `SALOONBOT_DEBUG` env var is set
- Output: stdout/stderr (captured by Docker)

## CI/CD & Deployment

**Hosting:**
- Docker Compose on self-hosted infrastructure
- Container images published to GitHub Container Registry (`ghcr.io/markrcote/saloonbot-server:main`, `ghcr.io/markrcote/saloonbot-bot:main`)

**CI Pipeline:**
- Not detected in repository (no `.github/workflows/` or similar)

**Legacy/Alternative:**
- `Procfile` present suggests prior or possible Heroku deployment (`worker: python bot.py`)

## Environment Configuration

**Required env vars:**
- `DISCORD_TOKEN` or `DISCORD_TOKEN_FILE` - Bot cannot start without this (`sys.exit(1)` if missing)
- `REDIS_HOST` / `REDIS_PORT` - Defaults to `localhost:6379`
- `MYSQL_HOST`, `MYSQL_PORT`, `MYSQL_USER`, `MYSQL_PASSWORD`, `MYSQL_DATABASE` - Defaults to `localhost:3306` / `saloonbot`

**Secrets location:**
- Production: Docker secrets (`discord_token.txt`, `discord_guilds.txt`) mounted into bot container at `/run/secrets/`
- Read via `read_env_file()` helper in `bot.py`

## Webhooks & Callbacks

**Incoming:**
- None - Bot uses Discord Gateway (WebSocket), not webhooks

**Outgoing:**
- None - All external communication is initiated by the bot via Discord API calls through nextcord

## Inter-Process Communication

**Redis Pub/Sub (internal):**
- Not an external integration but the sole IPC mechanism between `bot.py` and `server.py`
- Bot publishes JSON to `casino` topic; server subscribes synchronously via blocking `pubsub.listen()`
- Server publishes to `casino_update` and `game_updates_{game_id}`; bot polls via `@tasks.loop(seconds=3.0)`
- Both sides implement exponential backoff for Redis reconnection

---

*Integration audit: 2026-04-19*
