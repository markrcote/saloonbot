# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

SaloonBot is a Discord bot that generates Old West names and provides a blackjack card game. It consists of two main components that communicate via Redis pub/sub:
- **bot.py** - Discord bot client using nextcord
- **server.py** - Backend game server handling game logic
- MySQL database stores user information (SQLite supported for local development)

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

**Run both components locally (Redis only in Docker, SQLite for DB):**
```bash
./dev-redis.sh
# Then in separate terminals:
export REDIS_HOST=localhost REDIS_PORT=6379 SALOONBOT_DEBUG=1
export DISCORD_TOKEN="..." DISCORD_GUILDS="..."
python bot.py

export REDIS_HOST=localhost REDIS_PORT=6379 USE_SQLITE=1 SALOONBOT_DEBUG=1
python server.py
```

**Run bot locally (server in Docker):** `./dev-bot.sh`

**Run server locally (bot in Docker):** `./dev-server.sh`

**Production:** `docker compose -f compose-production.yml up -d`
**Staging:** `docker compose -f compose.staging.yml up -d`

If you always run the same environment on a host, symlink `compose.yml` for convenience:
```bash
ln -s compose-production.yml compose.yml  # then: docker compose up -d
```

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
|   DB    |  User persistence (MySQL in prod, SQLite locally)
+---------+
```

### Redis Pub/Sub Topics
- **"casino"** - Bot publishes game actions, server subscribes
- **"casino_update"** - Server publishes game creation and list_games responses, bot subscribes
- **"game_updates_{game_id}"** - Server publishes game state changes

### Casino Protocol (published to "casino")

**Casino actions** (`event_type: "casino_action"`):
- `new_game` - Create a new game; optional `guild_id`/`channel_id` for bot recovery, optional `num_bots` (0–4) to spawn bot players (AI-powered if an API key is configured, otherwise simple strategy), optional `deck` list to inject a specific card order (testing only)
- `list_games` - Request list of all active games (used by bot on startup for recovery)
- `get_usage` - Request 7-day LLM usage summary (admin; bot sends with `request_id`, server responds via `usage_stats`)
- `get_debug` - Request full internal state dump (admin; bot sends with `request_id`, server responds via `debug_state`)
- `get_stats` - Request a player's statistics; bot sends with `request_id` and `player`, server responds via `player_stats`
- `get_wallet` - Request a player's wallet balance; bot sends with `request_id` and `player`, server responds via `player_wallet`
- `lookup_wallet {target}` - Admin wallet lookup by name; searches users first then NPCs (case-insensitive); bot sends with `request_id`, server responds via `wallet_info`
- `set_wallet {target, mode:'set'|'adjust', amount}` - Admin wallet edit; resolves target via `_resolve_wallet_target`; rejects set < 0 and adjusts that would go negative; responds via `wallet_set`
- `npc_limits {min?, max?}` - Admin; no args = view current limits; with args = validate, persist via `set_setting`, update `Casino.npc_min/max`, respond via `npc_limits` event
- `stop_game` - Terminate a game immediately (admin; requires `game_id`); unresolved bets are not returned
- `quit_game` - Terminate a game and return all unresolved bets to players (admin; requires `game_id`)

**Player actions** (`event_type: "player_action"`):
- `join`, `leave`, `bet` (with `amount`), `hit`, `stand` (see `Action` in `blackjack.py`; double-down and split are not implemented)

**NPC actions** (`event_type: "npc_action"`, requires `game_id`):
- `add_npc` - Add roster NPC(s) to a game; optional `count` (default 1); capped at `MAX_NPCS_PER_TABLE`
- `remove_npc` - Remove an NPC; optional `npc_name` (omit to remove any NPC, preferring `players_waiting`)

### Casino Update Protocol (published to "casino_update")

- `new_game` response - includes `game_id`, `request_id`, and optional channel info
- `list_games` response - includes `request_id` and `games` list (each entry: `game_id`, `state`, `guild_id`, `channel_id`)
- `usage_stats` response - includes `request_id` and `rows` list (each entry: `purpose`, `model`, `total_input`, `total_output`, `call_count`)
- `debug_state` response - includes `request_id`, a `games` list (per-game state, players, pending bots, dirty flag), the `npcs` roster, and the `dirty_games` list (admin diagnostics)
- `player_stats` response - includes `request_id`, `player`, and `stats` (games/hands played, totals, biggest win, last seen) or null if no record
- `player_wallet` response - includes `request_id`, `player`, and `balance` (float or null if no record)
- `wallet_info` response - includes `request_id`, `target`, `kind` (`'player'`|`'npc'`|`None`), and `balance` (float or null)
- `wallet_set` response - includes `request_id`, `target`, `kind`, `new_balance`, `ok` (bool), and `message`
- `npc_limits` response - includes `request_id`, `min`, `max`, `ok` (bool), and `message`

### Key Modules

**cardgames/**
- `blackjack.py` - Main game logic with states: WAITING → BETTING → PLAYING → DEALER_TURN → RESOLVING → BETWEEN_HANDS; supports `to_dict()`/`from_dict()` for persistence
- `casino.py` - Redis pub/sub coordinator, manages game instances; loads persisted games on startup; handles bot-recovery/admin requests (`list_games`, `get_usage`, `get_debug`, `get_stats`, `get_wallet`), game termination (`stop_game`, `quit_game`), and `npc_action` add/remove; spawns NPC players via `num_bots` param (LLM-backed if API key available, otherwise simple strategy); reads saloon config from env; generates NPC backstories via LLM on first creation; logs LLM usage to DB
- `card_game.py` - Base class for card games (deck, shuffle, deal)
- `player.py` - Base player class
- `npc_player.py` - NPC base class; `simple_npc.py` uses basic strategy; `llm_npc.py` wraps LLM client for AI-driven play
- `llm_client.py` - LLM provider abstraction (Claude / OpenAI); `complete()` returns `(text, input_tokens, output_tokens)` tuple; falls back to basic strategy on timeout
- `personalities.py` - 15 archetype + 4 historical-figure personality definitions; `PersonalityRegistry` with `get_random(exclude_names)` and `get_all_names()`
- `database.py` - MySQL connection with auto-reconnect; manages schema via `MIGRATIONS` list; wallet helpers come in delta (`update_wallet`/`update_npc_wallet`) and absolute (`set_user_wallet`/`set_npc_wallet`) forms, plus `find_npc_by_name` (case-insensitive) and a `get_setting`/`set_setting` runtime config store
- `sqlite_database.py` - SQLite alternative to `database.py`; same interface (including the wallet/settings helpers above), used when `USE_SQLITE=1`; own `MIGRATIONS` list with SQLite-compatible SQL

**Database tables:**
- `schema_version` - Single-row table tracking the last applied migration index
- `users` - Stores player usernames and wallet balances (default $200)
- `games` - Persists game state (deck, hands, bets, timers) for server restart recovery
- `game_channels` - Maps game IDs to Discord guild/channel for bot restart recovery
- `npcs` - Persistent NPC roster: name, personality, backstory (LLM-generated), wallet, current_game_id
- `llm_usage` - Per-call LLM token tracking: purpose, model, input/output tokens, npc_id, game_id
- `settings` - Runtime key/value config store (`setting_key`/`setting_value`); accessed via `get_setting`/`set_setting`

**wwnames/**
- `wwnames.py` - Random name generator using data files in `names/`

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| REDIS_HOST | localhost | Redis server host |
| REDIS_PORT | 6379 | Redis server port |
| USE_SQLITE | - | Set to use SQLite instead of MySQL (local dev) |
| SQLITE_PATH | saloonbot.db | Path to SQLite database file |
| MYSQL_HOST | localhost | MySQL server host |
| MYSQL_PORT | 3306 | MySQL server port |
| MYSQL_USER | saloonbot | MySQL username |
| MYSQL_PASSWORD | (empty) | MySQL password |
| MYSQL_DATABASE | saloonbot | MySQL database name |
| DISCORD_TOKEN | - | Bot token; see secret resolution below |
| DISCORD_GUILDS | - | Comma-separated guild IDs; see secret resolution below |
| SALOONBOT_DEBUG | - | Set to enable debug logging |
| BLACKJACK_MIN_BET | 5 | Minimum bet amount in dollars |
| BLACKJACK_MAX_BET | 100 | Maximum bet amount in dollars |
| BLACKJACK_TIME_FOR_BETTING | 30 | Seconds allowed for placing bets |
| BLACKJACK_TIME_BETWEEN_HANDS | 10 | Seconds between hands |
| BLACKJACK_REMINDER_PERIOD | 30 | Seconds before reminding player of their turn |
| LLM_PROVIDER | claude | LLM provider for bot players: `claude` or `openai` |
| ANTHROPIC_API_KEY | - | API key for Claude; if unset, bot players use simple strategy; see secret resolution below |
| OPENAI_API_KEY | - | API key for OpenAI; if unset, bot players use simple strategy; see secret resolution below |
| LLM_MODEL | provider default | Override LLM model (default: claude-haiku-4-5 / gpt-4o-mini) |
| LLM_TIMEOUT | 5 | Seconds before bot player falls back to basic strategy |
| SALOON_NAME | The Rusty Spur | Name of the saloon (shown in Discord and injected into LLM context) |
| SALOON_TOWN | Redemption, Texas | Town/location of the saloon |
| SALOON_DETAIL_LEVEL | medium | Controls LLM context richness: `low` (names only, no backstory), `medium` (2-sentence backstory, archetypes), `high` (4-sentence backstory, full context) |

### Secret resolution

For `DISCORD_TOKEN`, `DISCORD_GUILDS`, `ANTHROPIC_API_KEY`, and `OPENAI_API_KEY`, the value is resolved in priority order:
1. Direct env var (e.g. `DISCORD_TOKEN=...`)
2. Path given by `<VAR>_FILE` env var (e.g. `DISCORD_TOKEN_FILE=/custom/path`)
3. Default file at `/run/secrets/<lowercase_var>` (e.g. `/run/secrets/discord_token`)
4. Unset — may be a fatal error depending on the variable

This means Docker secrets work automatically when mounted at `/run/secrets/` without any `_FILE` env var needed.

## E2E Testing Best Practices

- **`docker compose up --wait` is self-sufficient.** Never add `time.sleep()` after it — healthchecks are the correct signal that services are ready.
- **Capture server logs.** Redirect server subprocess output to a temp file; print the last 50 lines on failure — this is the primary debugging tool when an E2E test breaks.
- **Clean all stateful tables in every test's setUp**: `DELETE FROM game_channels`, `DELETE FROM games`, `DELETE FROM users`, plus `redis.flushall()`.
- **Prefer structured event assertions** (`data.get('event_type') == 'game_over'`) over text substring checks — more robust if wording changes.
- **Use injectable decks for game-flow tests**: pass `deck=[...]` in the `new_game` message to control card order and prevent flaky failures from bad deals (e.g., unexpected dealer blackjack).

## Key Patterns

- Bot uses asyncio with `@tasks.loop(seconds=3.0)` for polling Redis
- Server uses synchronous Redis in blocking game loop
- Both implement exponential backoff for Redis reconnection
- Custom exceptions: `CardGameError`, `NotPlayerTurnError`, `PlayerNotFoundError`, `InvalidBetError`, `InsufficientFundsError`
- Blackjack `tick()` handles auto-advance between hands and player turn reminders
- **Schema migrations**: `_init_database()` runs on startup and applies any pending migrations from the `MIGRATIONS` list in order, each committed atomically; `schema_version` tracks the last applied index. To add a schema change, append a new entry to `MIGRATIONS` — never edit existing entries. Migrations run automatically on server restart, so no manual SQL is needed for staging/production deployments.
- **Dirty-flag write-behind**: Each `Blackjack` instance sets its own `_dirty` flag when its state changes; on each tick the Casino moves dirty games into `_dirty_games`, then batches and flushes DB writes only when that set is non-empty, reducing unnecessary writes on each tick.
- **MySQL deadlock retry**: `database.py` wraps writes in a retry helper that catches InnoDB deadlock errors (errno 1213) and retries automatically; callers don't need retry logic.
- **Game persistence**: Casino saves game state to the database (MySQL or SQLite) after each action; restores all active games on startup via `load_all_active_games()`
- **Bot recovery**: On `on_ready`, bot sends `list_games` request, then reconnects to all active games (subscribes to topics, announces reconnection in channel)
- **NPC autofill**: `Casino.npc_min/npc_max` (default 0/4) control per-table NPC counts; `_autofill_npcs` runs on every tick (throttled to `AUTOFILL_INTERVAL=15s` per game), acts only in WAITING/BETWEEN_HANDS states. With `npc_min > 0`, games stay populated and `EMPTY_GAME_TIMEOUT` won't reap them — enabling NPC-only ambient play. Limits are persisted in `settings` as `npc_autofill_min`/`npc_autofill_max` and loaded at startup.
- `new_game` requests should include `guild_id`/`channel_id` so bot recovery can find the right channel after restart

## Testing
- ALWAYS activate the virtualenv before running tests or scripts (e.g., `source .venv/bin/activate`)
- ALWAYS run tests (unit + e2e where relevant) after code changes, before committing
- After fixing a bug, run the full test suite to catch regressions in adjacent modules
- **Flaky test hunting**: `hunt_flaky.py` re-uses a single Docker stack across N runs per test (~100× faster than re-spinning docker each time). Usage: `python hunt_flaky.py [--runs N] [--output FILE] [--class ClassName]`

## Planning Docs
- `VISION.md` — high-level product vision: the atmospheric frontier casino simulator and its goals
- `DESIGN-VISION.md` — design decisions and refinements that shaped VISION.md
- `ROADMAP.md` — milestone-by-milestone implementation plan for achieving VISION.md; includes dependency order and cross-cutting concerns (LLM usage tracking, detail level config)

Completed milestone/review docs (architecture decisions, admin-controls roadmap, code review findings) are deleted once fully implemented/fixed rather than kept around as historical records — git history retains them if ever needed.

## Documentation Updates
When implementing a feature or fix, update ALL relevant docs in the same change: README.md, CLAUDE.md, QA.md, ROADMAP.md, and any other active plan docs. Do a final grep for the changed concept across `*.md` before declaring done.

## Commits
- Make small, focused commits — one logical change per commit
- Run tests before every commit; do not commit failing code

## Bug Triage Workflow
When working from a review doc / tech debt list: (1) check if the issue is already fixed before making changes, (2) fix one issue per commit unless explicitly told otherwise, (3) update that doc's status after each fix, (4) delete the doc once every issue is resolved.

Before starting work, restate the exact scope back to me as a numbered list. Do not add adjacent improvements unless I explicitly approve. If you spot something extra worth doing, note it at the end as a 'follow-ups' suggestion.

After 3–5 tool calls of pure exploration, stop and summarize findings before continuing. Before and after any command that takes >30s, print a status line.
