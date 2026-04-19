# Coding Conventions

**Analysis Date:** 2026-04-19

## Naming Patterns

**Files:**
- `snake_case.py` for all Python files: `card_game.py`, `npc_player.py`, `simple_npc.py`
- Test files prefixed with `test_`: `test.py` (unit), `test_e2e.py` (end-to-end)
- Module directories use `snake_case`: `cardgames/`, `wwnames/`

**Classes:**
- `PascalCase`: `CardGame`, `BlackJack`, `WildWestNames`, `NPCPlayer`, `SimpleBlackjackNPC`
- Exceptions end in `Error`: `CardGameError`, `NotPlayerTurnError`, `InvalidBetError`, `InsufficientFundsError`
- Enums use `PascalCase` for class names, `ALL_CAPS` for members: `HandState.WAITING`, `HandState.BETTING`

**Methods:**
- `snake_case` for all methods: `new_hand()`, `start_betting()`, `dealer_turn()`
- Private methods prefixed with `_`: `_check_turn()`, `_tick_waiting()`, `_load_games_from_db()`
- Private helper tick dispatchers prefixed with `_tick_`: `_tick_waiting()`, `_tick_betting()`, `_tick_playing()`
- Boolean-returning methods prefixed with `is_` or `has_`: `is_dealer_turn()`, `has_card()`

**Variables:**
- `snake_case` throughout: `game_id`, `player_name`, `time_betting_started`
- Constants in `ALL_CAPS`: `MIN_BET`, `MAX_BET`, `TIME_FOR_BETTING`, `VALID_ACTIONS`
- Class-level env-configured constants read with `os.getenv()`: `MIN_BET = int(os.getenv('BLACKJACK_MIN_BET', '5'))`

**Constants:**
- Action strings centralized in `Action` class (not an Enum, just a class with string constants): `Action.JOIN`, `Action.HIT`
- State enums use `HandState(Enum)` with string values matching lowercase names: `HandState.WAITING = "waiting"`

## Code Style

**Formatting:**
- No automated formatter configured (no `.prettierrc`, `pyproject.toml` formatter, or `black` config)
- Line length: max 120 characters (enforced by flake8, see `.flake8`)
- f-strings used throughout for string interpolation: `f"Game {game_id} not found"`, `f"{player} {result} 💰 Wallet: ${balance:.2f}"`

**Linting:**
- Tool: `flake8`
- Config: `.flake8` — `max-line-length = 120`, `exclude = venv`
- Run: `flake8 .`

## Import Organization

**Order:**
1. Standard library: `import json`, `import logging`, `import os`, `import time`
2. Third-party packages: `import mysql.connector`, `import redis`, `import nextcord`
3. Local imports: `from .card_game import Card, CardGame`, `from cardgames.blackjack import Blackjack`

**Style:**
- `from X import Y` preferred for commonly used names
- Relative imports used inside `cardgames/` package: `from .card_game import Card`
- Absolute imports used from top-level scripts: `from cardgames.blackjack import Blackjack`

## Error Handling

**Exception Hierarchy:**
- `CardGameError(Exception)` is the base game exception in `cardgames/card_game.py`
- All game errors subclass `CardGameError`: `NotPlayerTurnError`, `InvalidActionError`, `InsufficientFundsError`, `InvalidBetError`
- Each exception class implements `user_message()` returning a human-friendly string for Discord output
- `PlayerNotFoundError` in `cardgames/player.py` does NOT subclass `CardGameError` (standalone)

**Exception Pattern:**
```python
class NotPlayerTurnError(CardGameError):
    def __init__(self, player):
        self.player = player

    def __str__(self):
        return f"It is not {self.player}'s turn"

    def user_message(self):
        return "It's not your turn."
```

**Catching:**
- External errors (MySQL, Redis) caught with library-specific exceptions: `mysql.connector.Error`, `redis.exceptions.ConnectionError`
- Game errors caught at the `Casino.listen()` boundary: `except CardGameError as e: ... game_output(game_id, e.user_message())`
- Infrastructure errors (DB, Redis) caught with broad `except Exception as e: logging.error(...)` — don't re-raise, just log
- `assert` used in `CardGame.deal()` for internal invariants (not for user-facing validation)

## Logging

**Framework:** Python standard `logging` module

**Setup:**
```python
logging.basicConfig(
    level=LOG_LEVEL,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
```

**Levels:**
- `logging.debug()` — high-frequency internal events: tick calls, Redis message receipt, publish events
- `logging.info()` — state changes, connections, user joins: `"Casino online."`, `"Restored game {game_id}"`
- `logging.warning()` — game errors surfaced to user: `f"Game error: {e}"`
- `logging.error()` — infrastructure failures: DB connection errors, save failures

**Debug mode:** Enabled via `SALOONBOT_DEBUG` env var, switches log level to `DEBUG`

## Comments

**Docstrings:**
- Used on public methods in `cardgames/`: one-line for simple methods, multi-line with `Args:` / `Returns:` / `Raises:` for complex ones
- Example from `casino.py`:
  ```python
  def add_npc(self, game_id, npc_name, npc_type='simple'):
      """Add an NPC player to a game.

      Args:
          game_id: The game to add the NPC to.
          npc_name: Name for the NPC player.
          npc_type: NPC strategy type (key in NPC_TYPES).

      Returns:
          The created NPCPlayer instance.

      Raises:
          CardGameError: If game_id is invalid or npc_type is unknown.
      """
  ```
- Not used on simple private helpers or data class methods

**Inline Comments:**
- Used to explain non-obvious logic, especially deck ordering in tests
- Short comments on constants: `# must be unique` on `Player.name`
- State machine transitions documented inline: `# WAITING -> BETTING`

## Function Design

**Size:** Methods kept focused; complex logic broken into private `_tick_*` helpers called from public `tick()`

**Parameters:** Positional args for required data, keyword args with defaults for optional: `def random_name(self, gender=None, number=1)`

**Return Values:**
- Return `True`/`False` for DB operations indicating rows affected: `add_user()`, `update_wallet()`
- Return `None` implicitly for output-only methods
- Return created objects for factory methods: `Casino.new_game()` returns `game_id`, `Casino.add_npc()` returns NPC instance

## Module Design

**Exports:**
- `cardgames/__init__.py` is empty — consumers import directly from submodules
- Module-level singleton in `cardgames/player.py`: `registry = PlayerRegistry()`
- `NPC_TYPES` dict in `cardgames/casino.py` serves as a plugin registry for NPC strategies

**Class Constants:**
- Game configuration read from env at class definition time: `MIN_BET = int(os.getenv('BLACKJACK_MIN_BET', '5'))`
- State machine tables defined as class-level dicts: `VALID_ACTIONS = {HandState.WAITING: {...}, ...}`

## Async vs Sync

- `bot.py` uses `asyncio` with `nextcord` and `redis.asyncio`
- `server.py`, `cardgames/` are fully synchronous
- No mixing of sync/async within a module

---

*Convention analysis: 2026-04-19*
