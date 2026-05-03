# saloonbot

[![Lint and test](https://github.com/markrcote/discord_wwnames/actions/workflows/lint-and-test.yml/badge.svg)](https://github.com/markrcote/discord_wwnames/actions/workflows/lint-and-test.yml)

Discord bot originally built for randomly generating Old West names and now wandering off into card games.

See [DISCORD_SETUP.md](DISCORD_SETUP.md) for instructions on creating and configuring a Discord bot for this app.

Names were scraped from [Mithril and Mages](https://www.mithrilandmages.com/utilities/WesternBrowse.php).

## Commands

### Names

* `/wwname [gender] [number]`: Generates `number` Old West names by choosing a random first name of the given `gender` and a random surname.  The `gender` argument accepts any string starting with `f` or `m`.  If no `gender` is given, a random one is chosen. If not provided, `number` defaults to 1. The output is a newline-joined list of names in the form of `<gender emoji> first_name last_name`.

### Cards

* `/newgame [num_bots]` starts a new game of blackjack. `num_bots` (0–4, default 0) spawns bot players with Wild West personalities. Bots use AI-powered decisions if an API key is configured, otherwise they fall back to basic strategy. Commands (hit, stand, etc.) are read from messages.

### Metadata

* `/version`: Outputs the current git sha.

## LLM Bot Players

SaloonBot supports AI-powered bot players with Wild West personalities. Bots use an LLM to make real gameplay decisions (hit/stand/bet) and deliver in-character quips during the game.

### Personalities

Bots are drawn from a pool of 15 archetypes and 4 historical figures, each with a distinct voice and betting temperament. Bot quips appear in sepia-colored embeds to distinguish them from regular game messages.

**Archetypes:** The Grizzled Prospector, The Drunk Cowboy, The Snake Oil Salesman, The Prim Schoolmarm, The Bounty Hunter, The Frontier Preacher, The Railroad Baron, The Half-Broke Drifter, The Card Sharp, The Saloon Singer, The Greenhorn Deputy, The Apache Tracker, The Patent Medicine Widow, The Retired Outlaw, The Railroad Cook

**Historical figures:** Doc Holliday, Calamity Jane, Jesse James, Wild Bill Hickok

### Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_PROVIDER` | `claude` | LLM provider: `claude` or `openai` |
| `ANTHROPIC_API_KEY` | — | API key for Claude; supports `ANTHROPIC_API_KEY_FILE` |
| `OPENAI_API_KEY` | — | API key for OpenAI; supports `OPENAI_API_KEY_FILE` |
| `LLM_MODEL` | provider default | Override model (`claude-haiku-4-5` / `gpt-4o-mini`) |
| `LLM_TIMEOUT` | `5` | Seconds before falling back to basic strategy |

API keys are optional. If unset or invalid, bot players still join the game but use basic blackjack strategy instead of AI decisions.

All four secret variables (`DISCORD_TOKEN`, `DISCORD_GUILDS`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`) resolve in priority order: direct env var → `<VAR>_FILE` path → `/run/secrets/<lowercase_var>` → unset. Docker secrets mounted at `/run/secrets/` are picked up automatically with no extra configuration.

## CLI

A standalone CLI client (`cli.py`) lets you play and test the game locally without Discord.

```bash
export REDIS_HOST=localhost REDIS_PORT=6379
python cli.py
```

At startup you'll be prompted for your name and how many LLM bot players to add (0–4). The CLI auto-joins the game and drops you into the command prompt.

Available commands:

| Command | Description |
|---------|-------------|
| `join` | Sit down at the table (done automatically at startup) |
| `bet <amount>` | Place a bet during the betting phase |
| `hit` | Draw another card |
| `stand` | Hold your current hand |
| `leave` | Leave the game |
| `addnpc <name> [simple\|llm]` | Add a bot player |
| `removenpc <name>` | Remove a bot player |
| `help` | Show command list |
| `quit` | Exit |

## Development

SaloonBot provides flexible development workflows using Docker Compose configurations. The bot consists of two main components: the Discord bot (`bot.py`) and the server component (`server.py`), both communicating through Redis. The server persists state to a database — MySQL in production, SQLite locally.

### SQLite for local development

The server supports SQLite as a drop-in replacement for MySQL, controlled by the `USE_SQLITE` environment variable. All three dev scripts enable this automatically, so no MySQL container is needed for local development.

To use SQLite manually:
```bash
export USE_SQLITE=1          # enables SQLite
export SQLITE_PATH=saloonbot.db  # optional; this is the default
python server.py
```

### Development Scenarios

There are three development compose files, each designed for a different workflow:

1. **`compose.dev-bot-local.yml`** - Runs server + redis in Docker, allowing you to run `bot.py` locally
2. **`compose.dev-server-local.yml`** - Runs bot + redis in Docker, allowing you to run `server.py` locally
3. **`compose.dev-redis-only.yml`** - Runs redis only in Docker, allowing you to run both components locally

### Using Helper Scripts

For convenience, helper scripts are provided for each scenario:

#### Run bot locally (server in Docker)
```bash
./dev-bot.sh
```
This starts the server and redis containers (server uses SQLite), then runs the bot locally. Requires `DISCORD_TOKEN` and `DISCORD_GUILDS` environment variables.

#### Run server locally (bot in Docker)
```bash
./dev-server.sh
```
This starts the bot and redis containers, then runs the server locally with SQLite. Requires `discord_token.txt` and `discord_guilds.txt` files for the bot container.

#### Run both components locally (redis only in Docker)
```bash
./dev-redis.sh
```
This starts redis in Docker. You can then run `bot.py` and `server.py` separately in different terminals:
```bash
# Terminal 1
export REDIS_HOST=localhost REDIS_PORT=6379 SALOONBOT_DEBUG=1
export DISCORD_TOKEN="your-token" DISCORD_GUILDS="your-guild-ids"
python bot.py

# Terminal 2
export REDIS_HOST=localhost REDIS_PORT=6379 USE_SQLITE=1 SALOONBOT_DEBUG=1
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

For production and staging deployments, use the standard `compose.yml` file:

```bash
docker compose up -d
```

This runs all components (bot, server, and redis) in Docker containers.

Schema migrations run automatically on server startup — deploy new code and restart; no manual SQL needed.

#### Secrets setup (one-time per host)

Secrets are sourced from `/etc/saloonbot/secrets/` on the host, which persists across reboots (unlike `/run/secrets`, which is a tmpfs and is wiped on restart). Run this once on each host:

```bash
mkdir -p /etc/saloonbot/secrets
chmod 700 /etc/saloonbot/secrets

# Required
echo -n "your-discord-token"     > /etc/saloonbot/secrets/discord_token
echo -n "guild_id1,guild_id2"    > /etc/saloonbot/secrets/discord_guilds

# Optional — LLM bot players. Create empty files if unused.
echo -n "your-anthropic-key"     > /etc/saloonbot/secrets/anthropic_api_key
echo -n ""                       > /etc/saloonbot/secrets/openai_api_key

chmod 600 /etc/saloonbot/secrets/*
```

All four secret files must exist (Docker Compose requires them even if empty). Docker mounts them into each container at `/run/secrets/<name>`, where SaloonBot picks them up automatically.

## Tests

### Unit Tests

To run unit tests, run:
```bash
python test.py
```

### End-to-End Tests

End-to-end tests validate the complete system integration using the Redis interface with real MySQL and Redis services (no mocking). These tests:
- Start Redis and MySQL via docker-compose
- Run the actual server process
- Simulate client interactions through Redis pub/sub
- Verify game logic, database persistence, and server behavior

To run end-to-end tests:
```bash
python test_e2e.py
```

Or use the helper script:
```bash
./run-e2e-tests.sh
```

**Requirements:**
- Docker and Docker Compose must be installed and running
- The tests will automatically start and stop the necessary services

**Note:** End-to-end tests take longer to run (~2 minutes) as they start/stop Docker containers and wait for game timing events.
