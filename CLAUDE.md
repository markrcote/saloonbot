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
pytest test.py
```
(`python test.py` still works — it's a plain `unittest` suite — but `pytest` is the standard runner and what the pre-commit hook uses.)

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
- `get_usage` - Request an LLM usage summary; optional `days` (default 7, clamped 1–90) (admin; bot sends with `request_id`, server responds via `usage_stats`)
- `get_debug` - Request full internal state dump (admin; bot sends with `request_id`, server responds via `debug_state`)
- `get_stats` - Request a player's statistics; bot sends with `request_id` and `player`, server responds via `player_stats`
- `get_wallet` - Request a player's wallet balance; bot sends with `request_id` and `player`, server responds via `player_wallet`
- `lookup_wallet {target}` - Admin wallet lookup by name; searches users first then NPCs (case-insensitive); bot sends with `request_id`, server responds via `wallet_info`
- `get_npc_relationships {target}` - Admin NPC relationship lookup by name (case-insensitive); bot sends with `request_id`, server responds via `npc_relationships`
- `set_wallet {target, mode:'set'|'adjust', amount}` - Admin wallet edit; `amount` is in cents; resolves target via `_resolve_wallet_target`; rejects set < 0 and adjusts that would go negative; responds via `wallet_set`
- `npc_limits {min?, max?}` - Admin; no args = view current limits; with args = validate, persist via `set_setting`, update `Casino.npc_min/max`, respond via `npc_limits` event
- `stop_game` - Terminate a game immediately and return all unresolved bets to players (admin; requires `game_id`)

**Player actions** (`event_type: "player_action"`):
- `join`, `leave`, `bet` (with `amount`, in cents), `hit`, `stand` (see `Action` in `blackjack.py`; double-down and split are not implemented)

**NPC actions** (`event_type: "npc_action"`, requires `game_id`):
- `add_npc` - Add roster NPC(s) to a game; optional `count` (default 1); capped at `MAX_NPCS_PER_TABLE`
- `remove_npc` - Remove an NPC; optional `npc_name` (omit to remove any NPC, preferring `players_waiting`)

### Casino Update Protocol (published to "casino_update")

- `new_game` response - includes `game_id`, `request_id`, and optional channel info
- `list_games` response - includes `request_id` and `games` list (each entry: `game_id`, `state`, `guild_id`, `channel_id`)
- `usage_stats` response - includes `request_id`, `days`, and `rows` list (each entry: `purpose`, `model`, `provider`, `total_input`, `total_output`, `call_count`)
- `debug_state` response - includes `request_id`, a `games` list (per-game state, players, pending bots, dirty flag), the `npcs` roster, the `dirty_games` list, `llm_health` (per-provider status/last success/last failure/last error), and `llm_active` (bool — whether NPCs are currently using AI vs. simple fallback strategy) (admin diagnostics)
- `player_stats` response - includes `request_id`, `player`, and `stats` (games/hands played, `total_won_cents`/`total_lost_cents`/`biggest_win_cents`, last seen) or null if no record
- `player_wallet` response - includes `request_id`, `player`, and `balance_cents` (int or null if no record)
- `wallet_info` response - includes `request_id`, `target`, `kind` (`'player'`|`'npc'`|`None`), and `balance_cents` (int or null)
- `wallet_set` response - includes `request_id`, `target`, `kind`, `new_balance_cents`, `ok` (bool), and `message`
- `npc_limits` response - includes `request_id`, `min`, `max`, `ok` (bool), and `message`
- `npc_relationships` response - includes `request_id`, `target`, `npc_name` (resolved name, or null if not found), and `relationships` list (each entry: `partner`, `type`, `strength`, `notes`)

### Key Modules

**cardgames/**
- `blackjack.py` - Main game logic with states: WAITING → BETTING → PLAYING → DEALER_TURN → RESOLVING → BETWEEN_HANDS; supports `to_dict()`/`from_dict()` for persistence; broadcasts short table-event strings (bets, actions, outcomes, quips) to seated players via `_notify_table_event`; rolls the per-hand NPC departure chance on entry to BETWEEN_HANDS
- `casino.py` - Redis pub/sub coordinator, manages game instances; loads persisted games on startup; handles bot-recovery/admin requests (`list_games`, `get_usage`, `get_debug`, `get_stats`, `get_wallet`), game termination (`stop_game`), and `npc_action` add/remove; spawns NPC players via `num_bots` param (LLM-backed if API key available, otherwise simple strategy); reads saloon config from env; generates NPC backstories via LLM on first creation; condenses departing LLM NPCs' sessions into `npc_memories` (fire-and-forget, capped at `MAX_MEMORIES_PER_NPC=20` per NPC) and loads them back at seating via `_load_npc_memories`; manages NPC–NPC relationships (creation-time and organic formation, +5-per-shared-session strength, boundary-crossing note/type refreshes — see M7 in Key Patterns) and loads them at seating via `_load_npc_relationships`; logs LLM usage to DB and Prometheus (`metrics.record_llm_usage`) and tracks per-provider health state (`_llm_health`, updated via `_set_llm_health`) for `/debug` and `/metrics`
- `card_game.py` - Base class for card games (deck, shuffle, deal)
- `player.py` - Base player class
- `npc_player.py` - NPC base class; `simple_npc.py` uses basic strategy; `llm_npc.py` wraps LLM client for AI-driven play, buffers table events per session (`deque(maxlen=40)`), condenses them into a first-person memory on departure (`submit_session_condensation`), and injects seated partners' relationships into its context block (detail-level gated)
- `llm_client.py` - LLM provider abstraction (Claude / OpenAI / deterministic fake for testing); `complete()` returns `(text, input_tokens, output_tokens)` tuple; falls back to basic strategy on timeout; `get_configured_provider()` resolves `LLM_PROVIDER` to exactly one of `openai`/`claude`/`none`/`fake` (default `openai`, no auto-detection from which API keys happen to be set), raising `LLMError` immediately on anything else; `create_llm_client()` builds the corresponding client, or returns `None` for `none`
- `metrics.py` - Prometheus metrics: `saloonbot_llm_calls_total`/`saloonbot_llm_input_tokens_total`/`saloonbot_llm_output_tokens_total` (labeled `purpose`/`model`/`provider`), `saloonbot_llm_provider_up` gauge and `saloonbot_llm_provider_failures_total` counter (labeled `provider`); `record_llm_usage` updates the call/token counters, `set_llm_provider_status` sets the alert-driving gauge, `record_llm_probe_failure` increments the failure counter independently (so a debounced-but-not-yet-alerting failure still shows up in the counter) — all called from `casino.py`; `start_metrics_server(port)` wraps `prometheus_client.start_http_server` (background thread, non-blocking)
- `personalities.py` - 15 archetype + 4 historical-figure personality definitions; `PersonalityRegistry` with `get_random(exclude_names)` and `get_all_names()`
- `database.py` - MySQL connection with auto-reconnect; manages schema via `MIGRATIONS` list; wallet helpers come in delta (`update_wallet`/`update_npc_wallet`) and absolute (`set_user_wallet`/`set_npc_wallet`) forms, plus `find_npc_by_name` (case-insensitive), a `get_setting`/`set_setting` runtime config store, session-memory helpers (`add_npc_memory` insert+prune, `get_npc_memories` newest-first), and relationship helpers (`create_npc_relationship`/`get_npc_relationship` order-insensitive via `ordered_pair`, `get_npc_relationships` strongest-first, `update_npc_relationship` partial updates); `log_llm_usage`/`get_llm_usage_summary` track `provider` alongside purpose/model; every public method runs under an RLock (see thread safety in Key Patterns)
- `sqlite_database.py` - SQLite alternative to `database.py`; same interface (including the wallet/settings helpers above), used when `USE_SQLITE=1`; own `MIGRATIONS` list with SQLite-compatible SQL
- `money.py` - Dollars/cents conversion helpers (`dollars_to_cents`, `cents_to_dollars`, `format_cents`); all wallet/bet/stats values are stored and passed internally as integer cents — dollars only appear at human-facing boundaries (Discord slash command args, plain-text chat commands, CLI input, LLM prompt text)

**Database tables:**
- `schema_version` - Single-row table tracking the last applied migration index
- `users` - Stores player usernames and wallet balances as `wallet_cents` (default 20000, i.e. $200)
- `games` - Persists game state (deck, hands, bets, timers) for server restart recovery
- `game_channels` - Maps game IDs to Discord guild/channel for bot restart recovery
- `npcs` - Persistent NPC roster: name, personality, backstory (LLM-generated), `wallet_cents`, current_game_id
- `npc_memories` - Condensed NPC session summaries: npc_id, game_id (no FK — games rows are deleted at game end), session_summary, created_at; pruned to the 20 most recent per NPC on insert
- `npc_relationships` - NPC–NPC relationships: npc_id_a/npc_id_b (stored low-id-first, unique pair index), relationship_type (`friend`/`rival`/`complicated`), strength (0–100), notes (NOT NULL — template fallback written at creation), created_at/updated_at; absence of a row means strangers
- `llm_usage` - Per-call LLM token tracking: purpose, model, provider, input/output tokens, npc_id
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
| BLACKJACK_MIN_BET | 500 | Minimum bet amount in cents |
| BLACKJACK_MAX_BET | 10000 | Maximum bet amount in cents |
| BLACKJACK_TIME_FOR_BETTING | 30 | Seconds allowed for placing bets |
| BLACKJACK_TIME_BETWEEN_HANDS | 10 | Seconds between hands |
| BLACKJACK_REMINDER_PERIOD | 30 | Seconds before reminding player of their turn |
| BLACKJACK_AMBIENT_SPEED_MULTIPLIER | 2.0 | Multiplier applied to dramatic/dealer-card/result pauses when a table has no human players (NPCs only) |
| BLACKJACK_AMBIENT_TIME_BETWEEN_HANDS_MIN | 120 | Minimum seconds between hands on an all-NPC ambient table |
| BLACKJACK_AMBIENT_TIME_BETWEEN_HANDS_MAX | 300 | Maximum seconds between hands on an all-NPC ambient table (actual delay is randomized within [MIN, MAX]) |
| BLACKJACK_NPC_DEPARTURE_BASE | 0.02 | Baseline per-hand chance an NPC leaves ("calls it a night") |
| BLACKJACK_NPC_DEPARTURE_RAMP | 0.28 | Extra departure chance at a full session event buffer |
| NPC_RELATIONSHIP_CHANCE | 0.70 | Chance a newly created NPC has pre-existing relationships |
| NPC_ORGANIC_RELATIONSHIP_CHANCE | 0.15 | Chance two stranger NPCs bond after a shared session |
| WALLET_REPLENISH_INTERVAL | 300 | Seconds between idle-NPC wallet replenishment passes |
| LLM_PROVIDER | openai | LLM provider for bot players: `openai`, `claude`, `none` (disables the LLM client entirely — always basic strategy), or `fake` (deterministic, no API key; for tests). Optional — unset defaults to `openai`. Exactly one provider is ever active; any other value raises at startup rather than guessing from which API keys are set. |
| ANTHROPIC_API_KEY | - | API key for Claude; if unset, bot players use simple strategy; see secret resolution below |
| OPENAI_API_KEY | - | API key for OpenAI; if unset, bot players use simple strategy; see secret resolution below |
| LLM_MODEL | provider default | Override LLM model (default: claude-haiku-4-5 / gpt-4o-mini) |
| LLM_TIMEOUT | 5 | Seconds before bot player falls back to basic strategy |
| LLM_HEALTHCHECK_INTERVAL | 300 | Seconds between periodic re-probes of the LLM provider, to detect credit exhaustion/outages and recovery without a restart |
| LLM_DOWN_GRACE_PERIOD | 120 | Seconds a provider must keep failing before it's reported down for alerting/metrics (`saloonbot_llm_provider_up`) — absorbs transient blips like boot-time DNS not being ready yet without paging |
| LLM_SESSION_MEMORY_TIMEOUT | 15 | Seconds allowed for the fire-and-forget session-memory call |
| SALOON_NAME | The Rusty Spur | Name of the saloon (shown in Discord and injected into LLM context) |
| SALOON_TOWN | Redemption, Texas | Town/location of the saloon |
| SALOON_DETAIL_LEVEL | medium | Controls LLM context richness: `low` (names only, no backstory, session memory off entirely), `medium` (2-sentence backstory, archetypes, 1 recalled memory), `high` (4-sentence backstory, full context, 3 recalled memories) |
| METRICS_PORT | 9400 | Port for the Prometheus `/metrics` endpoint (LLM usage counters, provider health gauge) |

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
- **Use `LLM_PROVIDER=fake` to e2e the LLM path**: the deterministic fake provider (no API key) makes the real server run LLM NPCs — quips, session memories, usage logging — with canned, valid responses. The fake stands at 16+, bets the minimum, and answers non-game prompts with fixed prose.
- **The base e2e env zeroes the NPC departure roll** (`BLACKJACK_NPC_DEPARTURE_BASE/RAMP = 0`) so NPCs never randomly leave mid-test; tests exercising the roll override via `EXTRA_ENV`. Similarly, `TestNPCRelationships` pins `NPC_RELATIONSHIP_CHANCE=1.0` so creation-time relationship formation is deterministic.
- **The `/metrics` endpoint is reachable at `localhost:METRICS_PORT`** in e2e tests since the server runs as a bare subprocess (no Docker port mapping needed); see `TestMetricsEndpoint` for the pattern (drive a hand with `LLM_PROVIDER=fake`, then poll `requests.get(.../metrics)` for the expected series).

## Key Patterns

- Bot uses asyncio with `@tasks.loop(seconds=3.0)` for polling Redis
- Server uses synchronous Redis in blocking game loop
- Both implement exponential backoff for Redis reconnection
- Custom exceptions: `CardGameError`, `NotPlayerTurnError`, `PlayerNotFoundError`, `InvalidBetError`, `InsufficientFundsError`
- Blackjack `tick()` handles auto-advance between hands and player turn reminders
- **Schema migrations**: `_init_database()` runs on startup and applies any pending migrations from the `MIGRATIONS` list in order, each committed atomically; `schema_version` tracks the last applied index. To add a schema change, append a new entry to `MIGRATIONS` — never edit existing entries. Migrations run automatically on server restart, so no manual SQL is needed for staging/production deployments.
- **Dirty-flag write-behind**: Each `Blackjack` instance sets its own `_dirty` flag when its state changes; on each tick the Casino moves dirty games into `_dirty_games`, then batches and flushes DB writes only when that set is non-empty, reducing unnecessary writes on each tick.
- **MySQL deadlock retry**: `database.py` wraps writes in a retry helper that catches InnoDB deadlock errors (errno 1213) and retries automatically; callers don't need retry logic.
- **MySQL read freshness**: the server's long-lived connection uses REPEATABLE READ, so a read method that SELECTs without first ending the open transaction can return a stale snapshot and never see rows committed by other connections (e.g., the e2e test harness). Read methods in `database.py` call `self.connection.commit()` before their SELECT — include that line in any new read method. SQLite needs no equivalent (its SELECTs don't open transactions).
- **DB thread safety**: the DB object is shared between the main game loop and NPC worker threads (usage logging, session-memory writes), and neither `mysql.connector` nor a shared sqlite3 connection tolerates concurrent use — every public method of both DB classes runs under a per-instance `RLock` via the `@_synchronized` decorator. Add the decorator to any new DB method.
- **NPC session memory (M6)**: one session = one NPC's tenure at a table. `Blackjack` broadcasts templated event strings to seated players; LLM NPCs buffer them (40-event FIFO cap). On any departure path (the shared M4 hook, plus `_delete_game` for stop/quit/reap), the Casino submits a fire-and-forget condensation call (purpose `session_memory`) on the NPC's own executor producing a 2-4 sentence first-person memory in `npc_memories`; skipped for simple NPCs, at `low` detail, and for sessions under `SESSION_MEMORY_MIN_EVENTS=3` events; failures write no row. Memories are loaded once at seating and injected into prompts per detail level. The in-session buffer is deliberately not persisted across restarts. The per-hand departure roll (`0.02 + 0.28 * buffer fill`) gives busy tables natural turnover.
- **NPC–NPC relationships (M7)**: `npc_relationships` rows (pair stored low-id-first, unique index; no row = strangers) form two ways: at NPC creation (70% chance of 1–3 partners from ≤10 sampled roster NPCs; type weights friend 45/rival 30/complicated 25; strength uniform 20–60) and organically (15% roll per still-seated *stranger* NPC when an NPC departs; initial strength 20). A per-type template note is written synchronously so `notes` is never empty; a fire-and-forget LLM call (purpose `relationship_gen`, dedicated single-worker executor on `Casino` — no per-NPC executor exists at creation time) replaces it unless detail level is `low` or no LLM is available. Each shared session awards +5 strength (cap 100) in the M4 departure hook — deduped for free since the hook fires after removal; `_delete_game` bypasses the hook (like M6) and walks seated pairs explicitly. A +5 crossing a 20-point boundary queues an LLM refresh that rewrites the note and may change the type (JSON response; invalid types ignored); it feeds the departing NPC's live session buffer, not `npc_memories`, since M6 condensation is async. Relationships load once at seating (spawn + restore paths) and surface in prompts only for partners present at the table, gated by detail level (low = omit, medium = type + first sentence, high = full note).
- **Game persistence**: Casino saves game state to the database (MySQL or SQLite) after each action; restores all active games on startup via `load_all_active_games()`
- **Bot recovery**: On `on_ready`, bot sends `list_games` request, then reconnects to all active games (subscribes to topics, announces reconnection in channel)
- **NPC autofill**: `Casino.npc_min/npc_max` (default 0/4) control per-table NPC counts; `_autofill_npcs` runs on every tick (throttled to `AUTOFILL_INTERVAL=15s` per game), acts only in WAITING/BETWEEN_HANDS states. With `npc_min > 0`, games stay populated and `EMPTY_GAME_TIMEOUT` won't reap them — enabling NPC-only ambient play. Limits are persisted in `settings` as `npc_autofill_min`/`npc_autofill_max` and loaded at startup.
- `new_game` requests should include `guild_id`/`channel_id` so bot recovery can find the right channel after restart
- **LLM health checks**: `Casino.llm_client` lazily creates and probes the LLM client on first access (logged at startup); if `LLM_PROVIDER=none`, it short-circuits to `None` without ever probing or touching health state (`_llm_provider_disabled` flag). `Casino._check_llm_health`, called from `_tick_games` and throttled to `LLM_HEALTHCHECK_INTERVAL` (default 300s), re-probes a live client to detect outages/exhausted credits (falling back to simple NPC strategy) and, if currently unavailable, retries client creation to detect recovery — all without a server restart; no-ops when the provider is disabled. Every probe/creation outcome (from both the lazy `llm_client` property and the periodic re-check) is recorded via `_set_llm_health` into an in-memory `_llm_health` dict (per-provider status, last success/failure time, last error) — this internal status flips immediately, so `/debug` and the simple-strategy fallback are never delayed. The `saloonbot_llm_provider_up` Prometheus gauge that `LlmProviderDown` alerts on is debounced separately: it's only set to 0 once failures persist past `LLM_DOWN_GRACE_PERIOD` (default 120s), so a single transient failure (e.g. boot-time DNS not ready) never triggers an alert on its own; `saloonbot_llm_provider_failures_total` still counts every failed probe regardless, via `record_llm_probe_failure`. Surfaced via `/debug` (`llm_health`/`llm_active`) and `/metrics`, so a sustained outage (e.g. credits running out) is visible without reading server logs.
- **Prometheus `/metrics` endpoint**: `metrics.start_metrics_server(METRICS_PORT)` (default port 9400) runs a background HTTP server (via `prometheus_client.start_http_server`, non-blocking — doesn't interact with the synchronous game loop) started once in `server.py`'s `main()`. Exposes LLM call/token counters and provider-health gauge/counter, all labeled by `purpose`/`model`/`provider` where applicable; intended to be scraped by an external Prometheus instance (alerting/dashboards live outside this repo).
- **Ambient table slowdown**: `Blackjack._is_ambient()` is true whenever every seated player is an NPC (no humans watching). `Blackjack._pause()` multiplies the dramatic/dealer-card/result pauses by `BLACKJACK_AMBIENT_SPEED_MULTIPLIER` on ambient tables. `end_hand()` also picks the BETWEEN_HANDS wait: a fixed `TIME_BETWEEN_HANDS` for tables with a human player, or a random duration in `[BLACKJACK_AMBIENT_TIME_BETWEEN_HANDS_MIN, BLACKJACK_AMBIENT_TIME_BETWEEN_HANDS_MAX]` for ambient ones — stored in `time_between_hands_duration` (persisted, so a restart mid-wait doesn't reset it).

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
