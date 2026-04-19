# Codebase Concerns

**Analysis Date:** 2026-04-19

## Tech Debt

**Games Are Never Removed from Memory or Database:**
- Issue: `Casino._delete_game()` exists in `cardgames/casino.py` (line 54) but is never called. Games accumulate in `self.games` dict and in the `games` database table indefinitely. There is no concept of a "finished" game state. Once a game enters `HandState.BETWEEN_HANDS` it loops back to `WAITING`, but games with no players sit in `WAITING` forever, persisted and loaded on every restart.
- Files: `cardgames/casino.py`, `cardgames/database.py`
- Impact: Memory growth over time; every server restart loads all ever-created games. On an active server this will eventually degrade startup time and memory usage.
- Fix approach: Define a "finished" condition (e.g., empty table has been in WAITING for N minutes), call `_delete_game()` and remove the entry from `self.games` in the `Casino.listen()` tick loop.

**Global Module-Level PlayerRegistry Singleton:**
- Issue: `registry = PlayerRegistry()` is created at module level in `cardgames/player.py` (line 48). All deserialized players (`deserialize_player` in `blackjack.py` line 46) and all action-driven players (`blackjack.py` line 444) are stored in this global registry. It is never pruned and grows unboundedly across all games for the process lifetime.
- Files: `cardgames/player.py`, `cardgames/blackjack.py`
- Impact: Memory leak. In tests, the registry is shared across test cases, allowing player state to bleed between tests (e.g., a player deserialized in one test is returned by `get_player` in another). Unit tests using `MagicMock` for casino avoid the worst of this but it is still present.
- Fix approach: Scope the registry to the `Casino` instance, or at minimum add an eviction mechanism tied to game deletion.

**Text-Matching for Embed Colors in Bot:**
- Issue: `bot.py` lines 352–374 determine Discord embed colors by checking for specific emoji and English strings within game update text (e.g., `"🏆 strikes gold"`, `"✨ ~*~ The dust settles"`). Any server-side text change silently breaks the formatting.
- Files: `bot.py`
- Impact: Fragile coupling between server output strings and bot UI logic. Changing any server message affects visual rendering without any static analysis or test catching it.
- Fix approach: Add a `message_type` field to game update events so the bot can key on a structured value rather than substring matching.

**Prefix Commands Accepted Alongside Slash Commands:**
- Issue: `bot.py` line 70 registers the bot with `command_prefix="!"` and line 205 handles raw `on_message` events to parse `bet`, `hit`, `stand`, etc. as plain-text commands. This requires the privileged `message_content` intent (line 68), which Discord has increasingly restricted. The slash command equivalents exist but prefix commands remain active in parallel.
- Files: `bot.py`
- Impact: Requires a privileged intent. Plain-text command handling is untested (unit tests only cover slash commands). Discord may further restrict or remove the intent in future API versions.
- Fix approach: Remove prefix command handling and the `message_content` intent; rely solely on slash commands. Add `/hit`, `/stand` slash commands for in-game actions.

**`assert` Used for Deck-Size Invariant:** ✓ Fixed (2026-04-19)
- Replaced `assert` with `raise CardGameError(...)` in `cardgames/card_game.py:87`.

**`leave()` Silently Mishandles DEALER_TURN/RESOLVING States:** ✓ Fixed (2026-04-19)
- `leave()` in `cardgames/blackjack.py` now returns the player's bet via `update_wallet` when leaving during `DEALER_TURN` or `RESOLVING`, instead of silently forfeiting it to the house.

## Security Considerations

**MySQL Password in Plaintext Compose File:**
- Risk: `compose.yml` contains `MYSQL_PASSWORD=saloonbot_password` and `MYSQL_ROOT_PASSWORD=root_password` inline as environment variables visible to anyone with repository or filesystem access.
- Files: `compose.yml`, `compose.staging.yml`, `compose.test.yml`
- Current mitigation: Discord credentials are handled via Docker secrets (`discord_token.txt`), but database credentials are not.
- Recommendations: Move MySQL credentials to Docker secrets or an `.env` file excluded from version control. At minimum, use a non-default root password distinct from the application user's password in all non-test environments.

**No Input Validation on Player Names:**
- Risk: Player names come directly from Discord usernames passed through Redis JSON. There is no length limit, character filter, or sanitization before they are stored in the MySQL `users` table as `VARCHAR(255)`.
- Files: `cardgames/blackjack.py` (line 444), `cardgames/database.py` (line 109)
- Current mitigation: MySQL parameterized queries (`%s`) prevent SQL injection.
- Recommendations: Add a maximum length check and allowed-character validation on `player` field before passing to game logic.

**No Redis Authentication:**
- Risk: Redis is exposed on `0.0.0.0:6379` (see `compose.yml`) with no password configured. Any process or container on the host network can publish arbitrary game actions.
- Files: `compose.yml`
- Current mitigation: None visible in configuration.
- Recommendations: Add `requirepass` to Redis config and update the `redis.Redis` and `redis.asyncio.Redis` client constructors in `bot.py` (line 121) and `cardgames/casino.py` (line 20) to supply the password.

## Performance Bottlenecks

**Excessive DB Reads During Betting Phase:**
- Problem: `Blackjack.start_betting()` in `cardgames/blackjack.py` (lines 247–251) issues one `get_user_wallet()` SELECT per player to display coin purses. `Blackjack.bet()` (lines 272–284) then issues two more SELECTs plus one UPDATE per bet. For N players in a hand, that is `3N + 1` sequential database round-trips within the betting phase.
- Files: `cardgames/blackjack.py`, `cardgames/database.py`
- Cause: No batching or caching of wallet reads.
- Improvement path: Batch-read wallets for all players in a single `WHERE username IN (...)` query; cache the value locally for the duration of the hand.

**Casino Tick Loop Saves Game State on Every State Transition:**
- Problem: `cardgames/casino.py` lines 246–253 save every game after every tick that causes a state change. State transitions can happen in rapid succession (BETTING→PLAYING→DEALER_TURN→RESOLVING→BETWEEN_HANDS in a few ticks), generating 4–5 full-game JSON serializations and DB upserts for a single hand.
- Files: `cardgames/casino.py`, `cardgames/database.py`
- Cause: Correctness-first design with no batching or debounce.
- Improvement path: Mark games dirty and flush on a fixed interval (e.g., every 5 seconds) rather than on every state change, except for bet escrow operations which need immediate durability.

## Fragile Areas

**`process_message()` for-else Indentation Bug:** ✓ Fixed (2026-04-19)
- Added `break` after dispatching a matched game message and aligned `else:` with `for` in `bot.py:346–377`. "Unknown message" now only logs when no game matched the topic.

**`Casino.listen()` Has No Redis Reconnection After Initial Subscribe:**
- Files: `cardgames/casino.py` lines 177–253
- Why fragile: The initial subscription uses exponential backoff (lines 182–190), but the inner `while True:` message loop (lines 194–253) calls `pubsub.get_message()` with a bare `timeout=2.0` and no exception handler. A transient Redis disconnect during the game loop raises an unhandled exception and crashes the server process, relying on Docker's `restart: always` to recover.
- Safe modification: Wrap the inner loop in a try/except for `redis.exceptions.ConnectionError` and re-subscribe with backoff, mirroring the pattern used in `bot.py`.
- Test coverage: E2E tests do not simulate Redis disconnection mid-game.

**Database Connection Silently Returns Stale Data:**
- Files: `cardgames/database.py` lines 21–43
- Why fragile: `_connect()` checks `self.connection.is_connected()` before reconnecting. MySQL's `is_connected()` does not actually ping the server; it only checks internal state. A TCP-level disconnect (e.g., MySQL container restart) can leave `is_connected()` returning `True` while the connection is unusable, causing the next query to raise `OperationalError`. The `_connect()` guard then silently passes, and the re-raise in each method surfaces as a game error rather than triggering reconnection.
- Safe modification: Use `connection.ping(reconnect=True)` or catch `OperationalError` in `_connect()` and force a reconnect. Currently the `except Error: pass` block (line 30) swallows the check failure but still proceeds to `mysql.connector.connect()`, which may work — but only if `self.connection is not None` evaluates to trigger the try block. The logic is subtle and easy to break.
- Test coverage: Unit tests mock the database; E2E tests do not simulate MySQL reconnection scenarios.

## Missing Critical Features

**No Mechanism to End or Close a Game:**
- Problem: There is no `/endgame` command or any server-side equivalent. Once created, a game runs forever. A game with no players persists in `HandState.WAITING`, is saved to the database, and is reloaded on every server restart. The only way to remove a game is direct database manipulation.
- Blocks: Admins cannot clean up stale games; the games table grows indefinitely.

**No Wallet Top-Up or Reset:**
- Problem: Players start with $200 (the `DEFAULT_WALLET` in `cardgames/database.py` line 7). Once a player's wallet reaches $0 they can never bet again and are automatically removed from every hand (via the NPC auto-bet guard at line 495 in `blackjack.py`; human players receive `InsufficientFundsError`). There is no command to replenish funds.
- Blocks: A player who goes broke is permanently locked out of gameplay.

## Test Coverage Gaps

**No Tests for `bot.py` Message Processing:**
- What's not tested: `process_message()`, `on_message()`, `send_command()`, game recovery via `_handle_list_games_response()`, and all slash command handlers in `BlackjackCog`.
- Files: `bot.py`
- Risk: Embed color logic and Redis reconnection flow could break silently.
- Priority: High

**No Tests for Server-Side Redis Reconnection:**
- What's not tested: `Casino.listen()` behavior when Redis drops mid-game.
- Files: `cardgames/casino.py`
- Risk: Server crashes silently under transient network issues.
- Priority: High

**No Tests for `leave()` During DEALER_TURN / RESOLVING:** ✓ Fixed behaviour (2026-04-19)
- Bet refund is now implemented; test coverage still missing.
- Files: `cardgames/blackjack.py`
- Risk: Regression in bet-return logic could go undetected.
- Priority: Low

**No Tests for Game Accumulation / Memory Leak:**
- What's not tested: Long-running casino with many games created; `_delete_game()` path never exercised.
- Files: `cardgames/casino.py`
- Risk: Goes unnoticed until production memory pressure or startup latency grows.
- Priority: Medium

---

*Concerns audit: 2026-04-19*
