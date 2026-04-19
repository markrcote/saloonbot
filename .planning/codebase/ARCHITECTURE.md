# Architecture

**Analysis Date:** 2026-04-19

## Pattern Overview

**Overall:** Event-Driven Microservices via Redis Pub/Sub

**Key Characteristics:**
- Two independent processes (`bot.py`, `server.py`) communicate exclusively through Redis pub/sub — no direct function calls or shared memory
- Bot is async (asyncio + nextcord); server is synchronous with a blocking event loop
- Game state is fully serializable to MySQL for crash recovery and restart resilience
- One-way command flow: bot publishes actions → server executes → server publishes updates → bot renders to Discord

## Layers

**Discord Interface Layer:**
- Purpose: Translate Discord events (slash commands, messages) into Redis messages and render game updates back to Discord
- Location: `bot.py`
- Contains: `BlackjackGame` (client-side wrapper), `BlackjackCog` (nextcord Cog with slash commands and pubsub listener), `WildWestNames` integration
- Depends on: `redis.asyncio`, `nextcord`, `wwnames/wwnames.py`
- Used by: Discord users only

**Casino Orchestrator Layer:**
- Purpose: Receive game commands from Redis, route to correct game instance, manage game lifecycle, publish state updates
- Location: `cardgames/casino.py` → `Casino` class
- Contains: Game registry (`self.games` dict), pub/sub listener loop, persistence calls, NPC management
- Depends on: `cardgames/blackjack.py`, `cardgames/database.py`, `cardgames/simple_npc.py`
- Used by: `server.py` entry point only

**Game Logic Layer:**
- Purpose: Implement blackjack rules, state machine, player actions, and bet management
- Location: `cardgames/blackjack.py` → `Blackjack` class
- Contains: `HandState` enum, `Action` constants, `Blackjack` game class, serialization helpers
- Depends on: `cardgames/card_game.py`, `cardgames/player.py`
- Used by: `Casino` only (never called directly from outside `cardgames/`)

**Card Game Base Layer:**
- Purpose: Generic deck management — creation, shuffling, dealing, discarding
- Location: `cardgames/card_game.py` → `CardGame` base class, `Card` class, `CardGameError`
- Contains: Deck logic, card representation, base exception
- Depends on: nothing (no imports from this codebase)
- Used by: `Blackjack` (subclasses `CardGame`)

**Player Layer:**
- Purpose: Player identity, hand tracking, and NPC abstraction
- Location: `cardgames/player.py` → `Player`, `PlayerRegistry`; `cardgames/npc_player.py` → `NPCPlayer` (abstract); `cardgames/simple_npc.py` → `SimpleBlackjackNPC`
- Contains: Module-level `registry` singleton in `player.py` used across the server process
- Depends on: nothing external
- Used by: `Blackjack`, `Casino`

**Persistence Layer:**
- Purpose: MySQL operations for user wallets and game state; schema auto-initialization on startup
- Location: `cardgames/database.py` → `Database` class
- Contains: Connection management with auto-reconnect, CRUD for `users`, `games`, `game_channels` tables
- Depends on: `mysql.connector`
- Used by: `Casino` and `Blackjack` (via `self.casino.db`)

**Name Generation Layer:**
- Purpose: Standalone Wild West name generator; no game dependency
- Location: `wwnames/wwnames.py` → `WildWestNames`; data in `wwnames/names/`
- Contains: `M.txt`, `F.txt`, `S.txt` name lists
- Depends on: nothing
- Used by: `bot.py` `/wwname` command only

## Data Flow

**New Game Creation:**

1. Discord user runs `/newgame` in a channel
2. `BlackjackCog.new_game()` publishes `{"event_type": "casino_action", "action": "new_game", "request_id": ..., "guild_id": ..., "channel_id": ...}` to Redis topic `"casino"`
3. `Casino.listen()` receives message, calls `Casino.new_game()`, creates `Blackjack` instance, saves to MySQL
4. Casino publishes `{"event_type": "new_game", "request_id": ..., "game_id": ...}` to Redis topic `"casino_update"`
5. Bot's `listen` task receives message, matches `request_id` to pending `BlackjackGame`, subscribes to `game_updates_{game_id}`, sends Discord embed

**Player Action Flow:**

1. Discord user sends message (e.g. `bet 25`) or uses slash command in active game channel
2. `BlackjackCog.send_command()` publishes `{"event_type": "player_action", "game_id": ..., "player": ..., "action": ..., [amount: ...]}` to `"casino"`
3. `Casino.listen()` routes to `self.games[game_id].action(data)`
4. `Blackjack.action()` validates state, resolves player from `player_registry`, executes game method
5. Game method calls `self.output(text)` → `Casino.game_output()` → Redis `game_updates_{game_id}`
6. Bot receives update on that topic, renders text (plain or embed) to Discord channel
7. After action, `Casino._save_game()` persists updated state to MySQL

**Game State Tick:**

1. `Casino.listen()` loop calls `game.tick()` for every active game after each Redis poll iteration (timeout=2.0s)
2. `Blackjack.tick()` dispatches to `_tick_{state}()` methods
3. Tick methods handle: auto-advancing states, NPC auto-play, betting timeout, reminders, hand transitions
4. If state changed during tick, `Casino._save_game()` is called

**Bot Recovery on Restart:**

1. `BlackjackCog.on_ready()` publishes `list_games` casino action
2. Server responds with all active game IDs + guild/channel info (from `game_channels` DB table)
3. Bot creates `BlackjackGame` wrappers, subscribes to each game's topic, announces reconnection in channel

**Server Recovery on Restart:**

1. `Casino.__init__()` calls `_load_games_from_db()`
2. All rows from `games` table are deserialized via `Blackjack.from_dict()` with time offset correction
3. Games resume from their persisted state

**State Management:**
- Server-side: `HandState` enum on each `Blackjack` instance; `Casino.games` dict is the authoritative in-memory registry
- Bot-side: `GameState` enum on each `BlackjackGame` wrapper; `BlackjackCog.games` list tracks per-channel games
- Persistence: MySQL `games` table (full state as JSON columns), `game_channels` table (guild/channel mapping)

## Key Abstractions

**Casino (Orchestrator):**
- Purpose: Decouples Redis messaging from game logic; single choke point for all game lifecycle events
- Examples: `cardgames/casino.py`
- Pattern: Command dispatcher — receives JSON messages, routes to game methods, publishes results

**Blackjack (State Machine):**
- Purpose: Self-contained game rules with explicit state: `WAITING → BETTING → PLAYING → DEALER_TURN → RESOLVING → BETWEEN_HANDS`
- Examples: `cardgames/blackjack.py`
- Pattern: State machine with `tick()` for time-driven transitions and `action()` for player-driven transitions; `VALID_ACTIONS` dict enforces per-state action rules

**PlayerRegistry (Singleton):**
- Purpose: Resolve player names to `Player` objects across the server process lifetime
- Examples: `cardgames/player.py` — module-level `registry = PlayerRegistry()`
- Pattern: Module-level singleton accessed via `player_registry.get_player(name, add=True)`

**NPCPlayer (Strategy Pattern):**
- Purpose: Abstract base for automated players; concrete strategies implement `decide_bet()` and `decide_action()`
- Examples: `cardgames/npc_player.py`, `cardgames/simple_npc.py`
- Pattern: Abstract class / strategy; `NPC_TYPES` dict in `casino.py` maps string keys to classes

**Game Serialization:**
- Purpose: Full game state snapshot for persistence and recovery
- Examples: `Blackjack.to_dict()`, `Blackjack.from_dict()`, serialization helpers in `cardgames/blackjack.py`
- Pattern: `to_dict()` / `from_dict()` with time offset correction on restore

## Entry Points

**Bot Process:**
- Location: `bot.py` (run directly: `python bot.py`)
- Triggers: Discord events via nextcord, `@tasks.loop(seconds=3.0)` for Redis polling
- Responsibilities: Discord auth, slash command registration, Redis pub/sub subscription, rendering game output

**Server Process:**
- Location: `server.py` (run directly: `python server.py`)
- Triggers: `Casino.listen()` blocks forever on Redis
- Responsibilities: Instantiate `Database` and `Casino`, start blocking event loop

**CLI Client:**
- Location: `cli.py`
- Triggers: Manual invocation (`python cli.py`)
- Responsibilities: Async REPL for testing game logic without Discord; publishes same Redis protocol as bot

## Error Handling

**Strategy:** Catch-and-log at layer boundaries; user-facing errors are translated to human-readable messages via `user_message()` on exception classes

**Patterns:**
- `CardGameError` and subclasses (`NotPlayerTurnError`, `InvalidActionError`, `InsufficientFundsError`, `InvalidBetError`) carry both a developer `__str__` and a `user_message()` for Discord output
- `Casino.listen()` catches `CardGameError` and calls `self.game_output(game_id, e.user_message())` to send error to Discord channel
- Redis connection errors: both bot and server use exponential backoff loops (`backoff = min(backoff * 2, 60)`)
- MySQL errors: `Database._connect()` auto-reconnects on each call; most DB errors are caught and re-raised after logging
- Bot Redis errors: `BlackjackCog.listen` catches all exceptions, clears `subscribed` event, triggers `try_subscribe()` background task

## Cross-Cutting Concerns

**Logging:** Python `logging` module throughout; `LOG_LEVEL` set from `SALOONBOT_DEBUG` env var; format: `'%(asctime)s - %(levelname)s - %(message)s'`

**Validation:** Game state validation in `Blackjack._validate_action()` using `VALID_ACTIONS` dict; bet validation in `Blackjack.bet()` checks min/max and wallet balance

**Authentication:** No app-level auth; Discord user identity is the `interaction.user.name` / `message.author.name` string, which becomes the `Player` name and MySQL `users.username`

---

*Architecture analysis: 2026-04-19*
