# saloonbot

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

To run tests, run `python test.py`.
