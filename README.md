# saloonbot

[![Lint and test](https://github.com/markrcote/discord_wwnames/actions/workflows/lint-and-test.yml/badge.svg)](https://github.com/markrcote/discord_wwnames/actions/workflows/lint-and-test.yml)

Discord bot originally built for randomly generating Old West names and now wandering off into card games.

See [DISCORD_SETUP.md](DISCORD_SETUP.md) for instructions on creating and configuring a Discord bot for this app.

Names were scraped from [Mithril and Mages](https://www.mithrilandmages.com/utilities/WesternBrowse.php).

## Commands

### Names

* `/wwname [gender] [number]`: Generates `number` Old West names by choosing a random first name of the given `gender` and a random surname.  The `gender` argument accepts any string starting with `f` or `m`.  If no `gender` is given, a random one is chosen. If not provided, `number` defaults to 1. The output is a newline-joined list of names in the form of `<gender emoji> first_name last_name`.

### Cards

* `/newgame` starts a new game of blackjack. Commands (hit, stand, etc.) are read
  from messages.

### Metadata

* `/version`: Outputs the current git sha.

## LLM Bot Players

SaloonBot supports AI-powered bot players with Wild West personalities. Bots use an LLM to make real gameplay decisions (hit/stand/bet) and deliver in-character quips during the game.

### Personalities

Bots are drawn from a pool of archetypes (The Grizzled Prospector, The Drunk Cowboy) and occasional historical figures (Doc Holliday), each with a distinct voice and betting temperament.

### Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_PROVIDER` | `claude` | LLM provider: `claude` or `openai` |
| `ANTHROPIC_API_KEY` | — | Required when `LLM_PROVIDER=claude` |
| `OPENAI_API_KEY` | — | Required when `LLM_PROVIDER=openai` |
| `LLM_MODEL` | provider default | Override model (`claude-haiku-4-5` / `gpt-4o-mini`) |
| `LLM_TIMEOUT` | `5` | Seconds before falling back to basic strategy |

If no API key is configured, the server starts normally but LLM bots are disabled.

## CLI

A standalone CLI client (`cli.py`) lets you play and test the game locally without Discord.

```bash
export REDIS_HOST=localhost REDIS_PORT=6379
export ANTHROPIC_API_KEY=<key>   # optional, enables LLM bots
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

SaloonBot provides flexible development workflows using Docker Compose configurations. The bot consists of two main components: the Discord bot (`bot.py`) and the server component (`server.py`), both communicating through Redis. The server also connects to a MySQL database to store user information.

### Development Scenarios

There are three development compose files, each designed for a different workflow:

1. **`compose.dev-bot-local.yml`** - Runs server + redis + mysql in Docker, allowing you to run `bot.py` locally
2. **`compose.dev-server-local.yml`** - Runs bot + redis + mysql in Docker, allowing you to run `server.py` locally
3. **`compose.dev-redis-only.yml`** - Runs redis + mysql in Docker, allowing you to run both components locally

### Using Helper Scripts

For convenience, helper scripts are provided for each scenario:

#### Run bot locally (server in Docker)
```bash
./dev-bot.sh
```
This starts the server and redis containers, then runs the bot locally. Requires `DISCORD_TOKEN` and `DISCORD_GUILDS` environment variables.

#### Run server locally (bot in Docker)
```bash
./dev-server.sh
```
This starts the bot, redis, and mysql containers, then runs the server locally. Requires `discord_token.txt` and `discord_guilds.txt` files for the bot container.

The server will connect to MySQL using these default values:
- Host: `localhost`
- Port: `3306`
- User: `saloonbot`
- Password: `saloonbot_password`
- Database: `saloonbot`

#### Run both components locally (redis and mysql only in Docker)
```bash
./dev-redis.sh
```
This starts redis and mysql in Docker. You can then run `bot.py` and `server.py` separately in different terminals:
```bash
# Terminal 1
export REDIS_HOST=localhost REDIS_PORT=6379 SALOONBOT_DEBUG=1
export DISCORD_TOKEN="your-token" DISCORD_GUILDS="your-guild-ids"
python bot.py

# Terminal 2
export REDIS_HOST=localhost REDIS_PORT=6379 SALOONBOT_DEBUG=1
export MYSQL_HOST=localhost MYSQL_PORT=3306
export MYSQL_USER=saloonbot MYSQL_PASSWORD=saloonbot_password
export MYSQL_DATABASE=saloonbot
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
