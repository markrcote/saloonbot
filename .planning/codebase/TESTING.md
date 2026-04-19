# Testing Patterns

**Analysis Date:** 2026-04-19

## Test Framework

**Runner:**
- Python standard `unittest` (no pytest, no vitest)
- No separate config file — uses Python's built-in test discovery

**Assertion Library:**
- `unittest.TestCase` assertions: `assertEqual`, `assertRaises`, `assertIn`, `assertGreater`, `assertIsNotNone`, `assertAlmostEqual`

**Mocking:**
- `unittest.mock.MagicMock` and `unittest.mock.patch` from standard library

**Run Commands:**
```bash
python test.py              # Run all unit tests
./run-e2e-tests.sh          # Run end-to-end tests (requires Docker)
python test_e2e.py          # Run e2e tests directly
```

## Test File Organization

**Location:**
- Unit tests: `test.py` at project root (flat, not co-located with source)
- End-to-end tests: `test_e2e.py` at project root

**Naming:**
- Test classes: `Test<Subject>` — `TestBlackjack`, `TestCasinoErrorHandling`, `TestSerialization`
- Test methods: `test_<description>` in snake_case — `test_winner_gets_2x_bet`, `test_state_transitions_to_betting`

**Structure:**
```
saloonbot/
├── test.py          # All unit tests (906 lines, single file)
├── test_e2e.py      # All end-to-end tests (single file)
└── cardgames/       # Source code — no co-located test files
```

## Test Structure

**Suite Organization:**

Unit tests are grouped into `TestCase` subclasses by domain:
- `TestWildWestNames` — name generator
- `TestCard` / `TestCardGame` — base card game primitives
- `TestBlackjack` — core game actions (hit, stand, dealer turn, tick)
- `TestBlackjackStateMachine` — state transition coverage
- `TestBlackjackBetting` — betting phase logic
- `TestBlackjackPayouts` — payout calculations
- `TestDatabaseIntegration` — DB interaction via mocks
- `TestCasinoErrorHandling` — error message formatting
- `TestSerialization` — `to_dict()`/`from_dict()` round-trips
- `TestNPCPlayer` / `TestSimpleBlackjackNPC` / `TestNPCBlackjackIntegration` — NPC strategy
- `TestCasinoNPCManagement` — Casino NPC add/remove

**setUp Pattern:**
```python
class TestBlackjack(unittest.TestCase):
    def setUp(self):
        mock_casino = MagicMock()
        mock_casino.db = MagicMock()
        mock_casino.db.get_user_wallet.return_value = 1000.0
        self.game = Blackjack(game_id="test_game", casino=mock_casino)
```

**Controlled deck setup:**
Tests use fixed decks (lists of `Card`) assigned directly to `game.deck` before calling game methods. Cards are dealt from the end of the list (`.pop()`), so decks are written in reverse draw order:
```python
# Dealer: 10, 6 (16); Player: 10, 10 (20) — drawn from END
game.deck = [Card("H", 10), Card("H", 10), Card("H", 10), Card("H", 6), Card("H", 10)]
```

## Mocking

**Framework:** `unittest.mock.MagicMock`

**Standard Casino Mock:**
```python
mock_casino = MagicMock()
mock_casino.db = MagicMock()
mock_casino.db.get_user_wallet.return_value = 1000.0
```

**Standard Casino+Redis Mock (for Casino class tests):**
```python
self.casino = Casino(redis_host="localhost", redis_port=6379)
self.casino.redis = self.mock_redis   # Replace after construction
self.casino.db = self.mock_db
```

**Patching random:**
```python
@patch("random.choice")
def test_random_name_male(self, mock_choice):
    mock_choice.side_effect = ["John", "Doe"]
    result = self.wild_west_names.random_name(gender="M")
    self.assertEqual(result, "♂ John Doe")
```

**What to Mock:**
- `Casino` object when testing `Blackjack` in isolation
- `Database` (as `casino.db`) for all game logic tests
- `Redis` client for `Casino` class tests
- `random.choice` to make name generation deterministic

**What NOT to Mock:**
- `Card`, `Player`, `Blackjack` — these are tested directly
- Time (`time.time()`) — tests manipulate `game.time_*` fields directly instead

## Fixtures and Factories

**Test Data:**
No dedicated fixture files or factory classes. Tests construct objects inline:
```python
Player("Player 1")
SimpleBlackjackNPC("TestNPC")
Card("H", 10)
```

**Wallet State:**
Database wallet mock always returns `1000.0` unless a specific payout test needs a different value (`200.0` for payout tests).

**Location:**
- No `fixtures/` directory
- No `conftest.py` (not pytest)
- All test data is inline per test method or in `setUp()`

## Coverage

**Requirements:** None enforced — no coverage config, no CI coverage gate

**View Coverage:**
```bash
# No coverage tooling configured. To run manually:
python -m coverage run test.py && python -m coverage report
```

## Test Types

**Unit Tests (`test.py`):**
- Scope: individual class/method behavior in isolation
- Dependencies mocked: `Casino`, `Database`, `Redis`
- Real objects used: `Card`, `Player`, `Blackjack`, `Casino` (with mocked internals)
- Includes state machine coverage, serialization round-trips, NPC strategy decisions

**End-to-End Tests (`test_e2e.py`):**
- Scope: full system integration via Redis pub/sub protocol
- Infrastructure: Docker Compose starts real Redis + MySQL (`compose.test.yml`)
- Server: `server.py` launched as a subprocess via `subprocess.Popen`
- No mocking — real Redis, real MySQL, real server process
- Test data cleaned between tests: `redis.flushall()` + `DELETE FROM users`
- `setUpModule`/`tearDownModule` manage Docker lifecycle for all test classes
- `EndToEndTestCase` base class provides helpers: `create_game()`, `join_player()`, `place_bet()`, `collect_messages()`, `poll_db()`

## Common Patterns

**Async Testing:**
Not applicable — all unit tests are synchronous. `test.py` has no `async`/`await`.

**State Machine Testing:**
Each state transition gets its own test method. Tests drive the game forward with explicit `tick()` calls and direct method calls:
```python
def test_state_transitions_to_betting(self):
    self.game.join(Player("Player 1"))
    self.game.tick()  # WAITING -> BETTING
    self.assertEqual(self.game.state, HandState.BETTING)
```

**Error Testing:**
```python
with self.assertRaises(InvalidBetError):
    self.game.bet(player, self.game.MIN_BET - 1)

# With message assertion:
with self.assertRaises(InvalidActionError) as context:
    game.action(data)
self.assertEqual(context.exception.user_message(), "You can't use 'hit' right now.")
```

**Timing Simulation:**
Tests manipulate timing fields directly rather than sleeping:
```python
self.game.time_last_hand_ended = time.time() - self.game.TIME_BETWEEN_HANDS - 1
self.game.tick()  # Should now transition
```

**DB Call Verification:**
```python
payout_calls = [call for call in mock_db.update_wallet.call_args_list
                if call[0][1] > 0]  # Positive amount = payout
self.assertEqual(len(payout_calls), 1)
self.assertEqual(payout_calls[0][0], ("Player 1", 40))
```

**E2E Message Collection:**
```python
pubsub = self.subscribe_to_game(game_id)
self.join_player(game_id, 'TestPlayer1')
updates = self.collect_messages(pubsub, timeout=5)
join_messages = [u for u in updates if 'TestPlayer1' in u and 'join' in u]
self.assertGreater(len(join_messages), 0)
```

**E2E DB Polling:**
```python
result = self.poll_db(
    "SELECT username FROM users WHERE username = %s",
    (player_name,)
)
self.assertIsNotNone(result, "User should be created in database")
```

---

*Testing analysis: 2026-04-19*
