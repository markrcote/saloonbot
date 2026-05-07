# Codebase Review

## Status (as of 2026-05-03)

**Fixed:** DI-1, DI-2, DI-3, DI-4, GL-1, GL-2, GL-3, GL-4, GL-5, SV-1, SV-2, SV-3, SV-4, PA-1, PA-2, PA-3, PA-5, SP-1, SP-2, SP-3, CQ-1, CQ-2, CQ-3, CQ-4, CQ-5, CQ-6, CQ-7, CQ-8, TG-1, TG-2

**Open:** (none)

---

## Summary

SaloonBot is a reasonably well-structured Discord blackjack bot with a clean pub/sub architecture and good test coverage. The code is readable and the state machine design for the game is sound. However, there are several notable defects ranging from data integrity risks in financial operations to logic bugs in game flow, security gaps in input handling, and a scattered set of code quality issues. Most critical issues cluster around wallet/bet management (money is real to players), game state correctness under edge cases, and missing input validation on the Discord command path.

---

## Issues by Theme

### Data Integrity / Financial Logic

#### [DI-1] ~~CRITICAL~~ **[FIXED]**: Wallet balance can go negative — no floor on `update_wallet` (complexity: trivial)
- **Location:** `cardgames/database.py:157-159`, `cardgames/sqlite_database.py:101-103`
- **Problem:** `update_wallet` does `wallet + ?` with no constraint preventing the result from going below zero. If two concurrent bet deductions race, or if a bug elsewhere calls `update_wallet(-amount)` with a stale balance, the wallet can go negative. There is also no `CHECK (wallet >= 0)` constraint in either the MySQL or SQLite schema definitions.
- **Impact:** Players can end up with a negative balance, which is never recoverable with the current payout logic (only positive amounts are ever added back). Negative wallets corrupt the displayed balance and break the `InsufficientFundsError` guard which relies on a correct database value.
- **Fix:** Add a `CHECK (wallet >= 0)` constraint to the schema and use a conditional update:
  ```sql
  UPDATE users SET wallet = wallet + ? WHERE username = ? AND wallet + ? >= 0
  ```
  Then check `rowcount == 0` to detect the failure and raise `InsufficientFundsError`.

#### [DI-2] ~~HIGH~~ **[FIXED]**: Race condition between wallet read and bet deduction (complexity: moderate)
- **Location:** `cardgames/blackjack.py:315-321`
- **Problem:** `bet()` reads the wallet with `get_user_wallet`, checks the balance, then calls `update_wallet(-amount)` in two separate DB round-trips. In a single-threaded server this is low risk today, but the NPC auto-bet path in `_tick_betting` can call `bet()` for multiple NPCs in the same tick iteration without any transaction boundary. If the DB ever becomes multi-writer (or a future refactor introduces threading), this is a TOCTOU vulnerability.
- **Impact:** A player could place a bet that exceeds their actual balance if balance checks are interleaved.
- **Fix:** Use a single atomic conditional update for the deduction and detect failure:
  ```sql
  UPDATE users SET wallet = wallet - ? WHERE username = ? AND wallet >= ?
  ```

#### [DI-3] ~~HIGH~~ **[FIXED]**: `end_hand` skips payout when player's bet is missing from `self.bets` (complexity: trivial)
- **Location:** `cardgames/blackjack.py:376`
- **Problem:** `bet_amount = self.bets.get(player.name, 0)` silently defaults to 0 if a player somehow has no bet entry. If this happens (e.g., deserialization bug, or the player joined mid-hand after `new_hand` was called), the winning player receives `0 * 2 = 0` payout.
- **Impact:** Players can win a hand and receive nothing.
- **Fix:** Assert or log a warning if a player in `self.players` is not in `self.bets` during resolution:
  ```python
  bet_amount = self.bets.get(player.name)
  if bet_amount is None:
      logging.error(f"Player {player.name} has no bet at resolution time")
      bet_amount = 0
  ```

#### [DI-4] ~~MEDIUM~~ **[FIXED]**: Bet forfeiture on `leave` during `PLAYING` state silently loses money (complexity: trivial)
- **Location:** `cardgames/blackjack.py:249-258`
- **Problem:** When a player leaves during `PLAYING` state (not `DEALER_TURN`/`RESOLVING`), their bet is forfeited. However, the state check on line 252 is `if self.state in (HandState.DEALER_TURN, HandState.RESOLVING)`. This means a player who leaves *after* standing (their turn is done, but state is still `PLAYING` while other players go) loses their bet even though they completed their action.
- **Impact:** Players who stand and then immediately leave before the dealer's turn lose their bet unfairly.
- **Fix:** Track a per-player "has played" flag, or alternatively return the bet once a player's turn index has passed `current_player_idx`.

---

### Game Logic Bugs

#### [GL-1] ~~HIGH~~ **[FIXED]**: `leave()` during `PLAYING` state can produce incorrect `current_player_idx` (complexity: moderate)
- **Location:** `cardgames/blackjack.py:264-270`
- **Problem:** When a player leaves during `PLAYING` state, the code adjusts `current_player_idx` only if `current_player_idx >= len(self.players)`. It does not handle the case where the *leaving player is the current player* (i.e., `self.players[current_player_idx] == player` before removal). After `self.players.remove(player)`, if the leaving player was at index `i < current_player_idx`, `current_player_idx` now points to the wrong player (off by one).
- **Impact:** The wrong player gets prompted for their turn, or a player is skipped entirely.
- **Fix:**
  ```python
  leaving_idx = self.players.index(player)
  self.players.remove(player)
  if self.state == HandState.PLAYING and self.current_player_idx is not None:
      if leaving_idx < self.current_player_idx:
          self.current_player_idx -= 1
      if self.current_player_idx >= len(self.players):
          self.state = HandState.DEALER_TURN
          self.current_player_idx = None
  ```

#### [GL-2] ~~HIGH~~ **[FIXED]**: `hit()` logic inverted — `get_score(player) <= 21` returns early before checking for bust (complexity: trivial)
- **Location:** `cardgames/blackjack.py:412-419`
- **Problem:** After dealing a card, the code checks `if self.get_score(player) <= 21: return` first — meaning a non-busting hit silently returns with no turn advancement. Only scores > 21 fall through to the `next_turn()` call. But then inside that block, there is a check `if self.get_score(player) == 21` which can never be true (21 <= 21 already returned). The bust message is then output when score > 21 but `next_turn()` is only called at line 419 for *both* the phantom 21 case and the real bust.
  
  The real issue: when a player hits and does NOT bust, `next_turn()` is never called. The current player remains the active player until they bust or stand. This is actually correct blackjack behavior (a player can hit multiple times) — BUT the 21 branch at line 415-416 is dead code and the comment intent is unclear.
  
  Looking more carefully: `if score <= 21: return` — this returns without calling `next_turn()`, which is correct (player can hit again). But the `if score == 21` branch at 415 is unreachable because `21 <= 21` already returned. This means hitting exactly 21 does NOT automatically advance to the next player's turn.
- **Impact:** A player who hits exactly 21 is not automatically moved on — they must explicitly stand. Real blackjack auto-advances on 21.
- **Fix:**
  ```python
  score = self.get_score(player)
  if score == 21:
      self.output(f"🎯 {player} hits 21!")
      self.next_turn()
  elif score > 21:
      self.output(f"💥 {player} busts! Too greedy, partner.")
      self.next_turn()
  # else: score < 21, player can continue hitting
  ```

#### [GL-3] ~~MEDIUM~~ **[FIXED]**: Dealer blackjack handling in `new_hand` does not deal to players first (complexity: moderate)
- **Location:** `cardgames/blackjack.py:347-352`
- **Problem:** When the dealer has 21 after the initial deal, `state` is set to `RESOLVING` and the method returns before dealing cards to players. Players have no cards in their hands when `end_hand` is called (called by `_tick_resolving`). `end_hand` iterates `self.players` and calls `self.get_score(player)` on empty hands (score = 0), which will always be less than 21 — every player "loses" to the dealer's blackjack, which is mathematically correct but the output messages will show `0` as their score and `self.bets.get(player.name, 0)` returns 0 because bets haven't been placed yet (they're placed in `bet()` before `new_hand()` — actually bets ARE placed, but the player has no hand for the output message). This produces confusing output but is not a financial error.
- **Impact:** Confusing game output; players see they lost with "0" as their score. Also `self.bets` will be populated (bets were placed before `new_hand` is called), so the financial resolution is actually correct.
- **Fix:** Deal to players before checking for dealer blackjack, or announce the dealer blackjack with proper player hand display.

#### [GL-4] ~~MEDIUM~~ **[FIXED]**: `_tick_betting` removes non-betting players with `list.remove()` inside iteration (complexity: trivial)
- **Location:** `cardgames/blackjack.py:561-564`
- **Problem:** `players_without_bets` is computed as a list comprehension, then `self.players.remove(player)` is called in a loop — this is safe because it iterates `players_without_bets`, not `self.players`. However, `remove()` does a linear scan and removes the *first* occurrence. If two players have identical names (which the player registry doesn't prevent across different sessions), the wrong player could be removed.
- **Impact:** Low risk in practice, but name collision would remove the wrong player.
- **Fix:** See the player registry issue below. Use index-based removal or ensure name uniqueness.

#### [GL-5] ~~LOW~~ **[FIXED]**: `_tick_waiting` starts betting immediately without waiting for players to actually be "ready" (complexity: trivial)
- **Location:** `cardgames/blackjack.py:524-527`
- **Problem:** `_tick_waiting` starts the betting phase the instant any player is in `players` or `players_waiting`. There is no minimum wait time or confirmation step, so a player joining immediately triggers the betting phase before other players have a chance to join.
- **Impact:** Poor UX — the second player who joins right after the first may arrive during the betting phase rather than before it, and if they miss the bet window they're kicked out immediately.
- **Fix:** Add a configurable short delay (e.g., 5 seconds) in `WAITING` state after the first player joins before transitioning to `BETTING`.

---

### Security & Input Validation

#### [SV-1] ~~HIGH~~ **[FIXED]**: No bet amount validation in `bot.py` `on_message` handler (complexity: trivial)
- **Location:** `bot.py:220-225`
- **Problem:** The `on_message` handler parses `bet <amount>` from plain chat messages. The `amount` is cast with `int(parts[1])`, but there are no bounds checks before sending it to the server. Negative values, zero, or very large integers pass straight through to the server. The server's `bet()` does validate min/max, but the Discord message path bypasses the slash command's parameter type constraints.
- **Impact:** A user can send `bet -1000000` or `bet 0` via chat, which the server will reject with a user-visible error message, but the validation gap is present and the error path is inelegant.
- **Fix:** Add bounds checking in `on_message` before `send_command`:
  ```python
  if amount <= 0:
      await message.channel.send("⚠️ Bet amount must be positive.")
      return
  ```

#### [SV-2] ~~MEDIUM~~ **[FIXED]**: `on_message` processes any message text as a game command with no length or content check (complexity: trivial)
- **Location:** `bot.py:216-227`
- **Problem:** Any message in a channel with an active game is split and the first word is sent as a command to the server. The server will reject unknown actions, but there is no maximum length check on `parts[0]`, meaning arbitrarily long strings are published to Redis.
- **Impact:** Denial-of-service via large Redis messages; verbose error logging in the server for every mistyped chat message.
- **Fix:** Check `len(command) <= 20` before processing.

#### [SV-3] ~~MEDIUM~~ **[FIXED]**: Player name is taken directly from Discord username without sanitization (complexity: trivial)
- **Location:** `bot.py:222`, `bot.py:262`, `bot.py:289`
- **Problem:** `interaction.user.name` and `message.author.name` are passed as the `player` field in Redis messages. Discord usernames can contain characters that could cause issues in database queries or output rendering. While parameterized queries protect the DB, a username like `"); DROP TABLE users; --` would be stored safely but could cause visual confusion in game output messages which use f-strings directly.
- **Impact:** Low SQL injection risk (parameterized queries are used), but potential display/log injection via crafted usernames.
- **Fix:** Validate or sanitize usernames before use, or truncate to a reasonable max length (e.g., 32 chars).

#### [SV-4] ~~LOW~~ **[FIXED]**: `REDIS_PORT` environment variable is read as a string, not cast to int (complexity: trivial)
- **Location:** `bot.py:36`, `server.py:15`
- **Problem:** `REDIS_PORT = os.getenv("REDIS_PORT", 6379)` — `os.getenv` always returns a string when the variable is set, but the default is an int. When the env var IS set, `redis.asyncio.Redis(host=REDIS_HOST, port=REDIS_PORT)` receives a string for `port`, which the Redis library currently accepts but this is an implicit type mismatch.
- **Impact:** Could break with future Redis library versions; inconsistent behavior between "env var set" and "env var not set" paths.
- **Fix:** `REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))`

---

### Protocol / Architecture

#### [PA-1] ~~HIGH~~ **[FIXED]**: Bot games list is never pruned — `self.games` grows forever (complexity: moderate)
- **Location:** `bot.py:124`, `bot.py:186-187`
- **Problem:** The bot appends to `self.games` in `new_game` and `_handle_list_games_response` but never removes games. Finished games (those in `FINISHED` state or server-deleted games) remain in the bot's list indefinitely. `find_game` will still find a stale finished game and prevent a new game from being created in the same channel.
- **Impact:** After a game ends, the same channel can never start a new game. The bot effectively becomes non-functional in that channel after the first game.
- **Fix:** Handle game-over messages from the server (or add a `game_ended` event type) and remove the game from `self.games`. At minimum, transition game state to `FINISHED` and exclude `FINISHED` games from `find_game`.

#### [PA-2] ~~HIGH~~ **[FIXED]**: `process_message` in `bot.py` handles `casino_update` messages but never handles `game_updates_*` "game over" signals (complexity: moderate)
- **Location:** `bot.py:348-380`
- **Problem:** Related to the above — the server has no protocol message for "this game is over, bot should clean up." The bot has a `GameState.FINISHED` enum value but nothing ever sets it. When the server removes an idle game after `EMPTY_GAME_TIMEOUT`, the bot still holds a reference to the game object.
- **Impact:** Memory accumulation; channel permanently stuck; recovered games after restart may be orphaned in the bot's game list.
- **Fix:** Add a `game_over` event type to the server's `game_output` at end of game lifecycle, and handle it in the bot's `process_message` to remove the game from `self.games`.

#### [PA-3] ~~MEDIUM~~ **[FIXED]**: `try_subscribe` only subscribes to `casino_update` but not to game-specific topics — subscriptions lost on reconnect (complexity: moderate)
- **Location:** `bot.py:395-407`
- **Problem:** When Redis connection is lost and `try_subscribe` runs, it only resubscribes to `casino_update`. Any active game-specific topics (`game_updates_{game_id}`) that were subscribed are not resubscribed.
- **Impact:** After a Redis reconnect, the bot stops receiving game state updates for all active games, even though the games continue running on the server.
- **Fix:** After resubscribing to `casino_update`, resubscribe to all active game topics:
  ```python
  for game in self.games:
      if game.game_id:
          await self.pubsub.subscribe(game.topic())
  ```

#### [PA-4] ~~MEDIUM~~ **[CLOSED — NO FIX NEEDED]**: `casino.listen()` creates a new `pubsub` object on every reconnect but old subscriptions to game topics via `publish_event` are done on `self.redis` directly — this is fine, but the pubsub loop subscription only covers `"casino"` (complexity: trivial)
- **Location:** `cardgames/casino.py:291-325`
- **Problem:** Each reconnect re-subscribes only to `"casino"`. This is correct for the server (it only needs to receive on `"casino"`). No issue here — but worth noting that `_process_message` is the only message handler and it covers all expected message types. The real concern is on the bot side (see above).

#### [PA-5] ~~LOW~~ **[FIXED]**: `_list_games_request_id` attribute is set dynamically in `_request_list_games` but accessed with `hasattr` guard — if `list_games` response arrives before `_request_list_games` is called (race on reconnect), the response is silently dropped (complexity: trivial)
- **Location:** `bot.py:345-347`
- **Problem:** `if hasattr(self, '_list_games_request_id') and request_id == self._list_games_request_id` — this guard is needed because the attribute is not initialized in `__init__`. If the server responds faster than the bot processes messages, or if the attribute was cleared, the response is silently dropped.
- **Impact:** Bot fails to restore games on startup without any log message explaining why.
- **Fix:** Initialize `self._list_games_request_id = None` in `BlackjackCog.__init__` and check `self._list_games_request_id is not None`.

---

### State Persistence & Recovery

#### [SP-1] ~~MEDIUM~~ **[FIXED]**: `from_dict` time offset calculation is wrong — it adjusts `time_betting_started` forward relative to `time_last_event`, but `time_betting_started` is an absolute timestamp (complexity: moderate)
- **Location:** `cardgames/blackjack.py:656-658`
- **Problem:** 
  ```python
  time_offset = now - saved_time_last_event
  game.time_betting_started = data['time_betting_started'] + time_offset
  ```
  This adjusts `time_betting_started` forward by the elapsed time since save. The intent is to preserve the *remaining* betting time, not to rebase it to now. But `TIME_FOR_BETTING` is checked as `time.time() > self.time_betting_started + self.TIME_FOR_BETTING`. If the server was down for 60 seconds and betting timeout is 30 seconds, `time_betting_started` gets pushed 60 seconds forward — meaning players get an extra 60 seconds of betting time, not having their time reduced.
  
  The correct behavior is to keep `time_betting_started` at its original absolute value (so the timer continues from where it left off), or reset it to `now - elapsed`. The current code does the opposite of the intent.
- **Impact:** After a server restart, the betting timer is effectively reset rather than continuing. Players could get unlimited betting time if the server restarts during every betting phase.
- **Fix:** Do NOT adjust `time_betting_started` — keep the original value:
  ```python
  game.time_betting_started = data['time_betting_started']
  # (same for time_last_hand_ended)
  ```

#### [SP-2] ~~MEDIUM~~ **[FIXED]**: Player registry is a global singleton and is never cleared between game restores (complexity: moderate)
- **Location:** `cardgames/player.py:48`, `cardgames/blackjack.py:63`
- **Problem:** `registry = PlayerRegistry()` is a module-level singleton. `deserialize_player` calls `player_registry.get_player(name, add=True)` which adds the player to the global registry. Human players from loaded games will already exist in the registry from the server's previous run (no, actually — the registry is fresh on each server start, so this is a new registry). However, if two different games have a human player with the same username, `get_player(name, add=True)` returns the *same* `Player` object for both games. Changes to `player.hand` in one game corrupt the other game's hand.
- **Impact:** Two concurrent games with a player named "Alice" will share a single `Player` object. Alice's hand in game 1 will be overwritten when she's dealt cards in game 2.
- **Fix:** Scope the player registry per-game rather than globally, or use game-scoped player instances that don't share the global registry.

#### [SP-3] ~~LOW~~ **[FIXED]**: `load_all_active_games` loads ALL rows from the `games` table with no state filter (complexity: trivial)
- **Location:** `cardgames/database.py:260`, `cardgames/sqlite_database.py:173`
- **Problem:** `SELECT * FROM games` loads every game including those in `BETWEEN_HANDS` or that were never cleaned up. This is mitigated by the casino's idle-game cleanup logic, but there is no DB-level active game filter.
- **Impact:** On a long-running system with many completed games that weren't cleaned up (e.g., due to crashes), startup may be slow and may attempt to restore games in terminal states.
- **Fix:** Either filter by state in the query, or ensure games in `BETWEEN_HANDS` / `WAITING` with no players are deleted promptly. (The `_delete_game` is called from `_tick_games` but only after `EMPTY_GAME_TIMEOUT` — games in other states are never deleted.)

---

### Code Quality

#### [CQ-1] ~~MEDIUM~~ **[FIXED]**: `blackjack.py` imports `mysql.connector` at the top level — creates hard dependency in game logic (complexity: trivial)
- **Location:** `cardgames/blackjack.py:6`
- **Problem:** `import mysql.connector` is at the top of `blackjack.py`, but `mysql.connector.Error` is only used in the `join()` method when catching database errors. This creates a hard dependency on the MySQL driver in the game logic layer, breaking the abstraction that `sqlite_database.py` was meant to provide.
- **Impact:** Running tests or using SQLite requires `mysql.connector` to be installed even though it's never used in that code path.
- **Fix:** Either catch the generic `Exception` (or a custom DB exception), or move the import inside the `try` block. Better: define a common `DatabaseError` in `database.py` and raise that from both DB implementations.

#### [CQ-2] ~~MEDIUM~~ **[FIXED]**: `blackjack.py:join()` catches `mysql.connector.Error` specifically but the database layer may throw `sqlite3.Error` (complexity: trivial)
- **Location:** `cardgames/blackjack.py:234-236`
- **Problem:** The error handler `except mysql.connector.Error as e` will NOT catch SQLite errors when `USE_SQLITE=1`. The `add_user` call in SQLite mode can raise `sqlite3.Error`, which would propagate as an unhandled exception from `join()`.
- **Impact:** A SQLite database error during player join causes an unhandled exception that crashes the game action handler.
- **Fix:** Catch `Exception` generically here (acceptable since we only log and continue), or define a shared DB exception type.

#### [CQ-3] ~~MEDIUM~~ **[FIXED]**: `Casino.__init__` calls `_load_games_from_db()` synchronously before the Redis connection is tested (complexity: trivial)
- **Location:** `cardgames/casino.py:32-33`
- **Problem:** `Casino.__init__` calls `_load_games_from_db()` which calls `db.load_all_active_games()`. If the database is unavailable, this raises immediately in `__init__` before `listen()` is even called. The error is caught at line 46-47, which is fine, but restored games call `game.output()` → `casino.game_output()` → `self.publish_event()` which calls `self.redis.publish()` — at this point Redis is not yet connected (no `listen()` call). Any state transition triggered during a game tick during load would try to publish to an unconnected Redis.
- **Impact:** Restored games that are in `BETTING` with an expired timer will tick immediately on load and may attempt Redis publishes before the subscribe loop is running.
- **Fix:** Defer `_load_games_from_db()` to after the first successful Redis connection in `listen()`.

#### [CQ-4] ~~LOW~~ **[FIXED]**: `BlackjackCog.__init__` creates Redis connection eagerly; if Redis is unavailable at startup, the cog fails silently (complexity: trivial)
- **Location:** `bot.py:122`
- **Problem:** `self.redis = redis.asyncio.Redis(host=REDIS_HOST, port=REDIS_PORT)` creates the client object (no actual connection yet), but the first `await self.redis.publish(...)` will fail if Redis is down. The error is caught in individual methods, but `try_subscribe` has exponential backoff for the `pubsub` connection — the `self.redis` publish path (used for sending commands to the server) has no similar reconnection logic. Any failed publish just logs an error and the player command is silently dropped.
- **Impact:** If Redis is briefly unavailable, player commands (hit, stand, bet) are silently lost with no user feedback indicating the command failed.
- **Fix:** Implement retry logic for `send_command`, or at minimum send a user-facing error message when the publish fails:
  ```python
  except Exception as e:
      logging.error(f"Redis publish error: {e}")
      await game.channel.send("❌ Command failed — could not reach game server. Please try again.")
  ```

#### [CQ-5] ~~LOW~~ **[FIXED]**: `SimpleBlackjackNPC.decide_action` has a logic gap for dealer value 7-9 (complexity: trivial)
- **Location:** `cardgames/simple_npc.py:19`
- **Problem:** The condition `if dealer_value >= 10 or dealer_value == 14` checks `>= 10` which already includes `10, 11, 12, 13`. The `dealer_value == 14` (Ace) check is therefore redundant since `14 >= 10` is already true.
- **Impact:** No functional bug — Ace is correctly handled — but the redundant condition is misleading and suggests misunderstanding of the value encoding.
- **Fix:** `if dealer_value >= 10:` (Ace has value 14, which is >= 10)

#### [CQ-6] ~~LOW~~ **[FIXED]**: `wwnames.py` reads all name files on every `WildWestNames()` instantiation; in `bot.py` a new instance is created per `/wwname` command (complexity: trivial)
- **Location:** `bot.py:92`, `wwnames/wwnames.py:6-9`
- **Problem:** Every `/wwname` slash command creates a new `WildWestNames()` instance which reads three files from disk. While not a crash risk, it's unnecessary I/O on every command invocation.
- **Impact:** Slightly slower command response; unnecessary file I/O on every name request.
- **Fix:** Create a single module-level `WildWestNames` instance, or cache it as a class variable on `BlackjackCog`.

#### [CQ-7] ~~LOW~~ **[FIXED]**: `game.new_hand()` is called in both `_tick_betting` (after all bets in) and when transitioning from `WAITING` state's `start_betting` — but `start_betting` calls `self.players.extend(self.players_waiting)` AND `new_hand` also calls `self.players.extend(self.players_waiting)` (complexity: trivial)
- **Location:** `cardgames/blackjack.py:272-277` vs `cardgames/blackjack.py:331-332`
- **Problem:** `start_betting()` merges `players_waiting` into `players` at line 275. Then `new_hand()` at line 331 does it again with `self.players.extend(self.players_waiting)` — but `players_waiting` was already emptied in `start_betting()` (line 276), so the second extend is a no-op. However, the intent in `new_hand` to allow mid-hand joins via `players_waiting` is confused by this structure.
- **Impact:** No functional bug currently, but confusing and fragile. A future refactor of either method could accidentally double-add players.
- **Fix:** Remove the `self.players.extend(self.players_waiting)` / `self.players_waiting = []` from `new_hand()` since `start_betting()` already handles this, or add a comment explaining that `new_hand` may be called from paths other than `_tick_betting`.

#### [CQ-8] ~~LOW~~ **[FIXED]**: No `__hash__` defined on `Player` despite `__eq__` being overridden (complexity: trivial)
- **Location:** `cardgames/player.py:8-9`
- **Problem:** Python documentation states that if you define `__eq__`, you should also define `__hash__` (or explicitly set `__hash__ = None` to make it unhashable). Without `__hash__`, `Player` objects are unhashable in Python 3. This means `player in set()` or using a player as a dict key fails. Currently, players are compared via list membership (`player in self.players`) which uses `__eq__`, so this doesn't immediately break, but it's a subtle trap.
- **Impact:** Any future code that puts players in a set or uses them as dict keys will silently get identity-based hashing (Python 3 actually sets `__hash__ = None` when you define `__eq__` without `__hash__`, making the object unhashable and raising `TypeError` on hash attempts).
- **Fix:** Add `__hash__ = None` explicitly (to declare unhashable) or `def __hash__(self): return hash(self.name)`.

---

### Testing Gaps

#### [TG-1] ~~MEDIUM~~ **[FIXED]**: No test for the `leave` during `PLAYING` state index correction logic (complexity: trivial)
- **Location:** `cardgames/blackjack.py:264-270`
- **Problem:** The `leave()` index correction path is completely untested. Given the identified bug above (leaving player before current index causes off-by-one), this test gap allowed the bug to go undetected.
- **Impact:** Silent game logic errors in multi-player games when a player leaves mid-hand.
- **Fix:** Add unit tests covering: player leaves before current index, player leaves at current index, player leaves after current index, last player leaves.

#### [TG-2] ~~LOW~~ **[FIXED]**: `TestCasinoErrorHandling.setUp` constructs `Casino(redis_host="localhost", redis_port=6379)` which attempts a real Redis connection and `_load_games_from_db()` call (complexity: trivial)
- **Location:** `test.py:504`
- **Problem:** The test calls `Casino(...)` then immediately overrides `casino.redis` and `casino.db`. But `Casino.__init__` calls `_load_games_from_db()` before the constructor returns, which calls `self.db.load_all_active_games()` — at that point `self.db` is `None` (not yet overridden), so `_load_games_from_db` returns early safely. BUT `Casino.__init__` also calls `create_llm_client()` which may fail or make network calls in some environments.
- **Impact:** Fragile test setup; tests may fail or be slow in CI environments without LLM API keys configured.
- **Fix:** Patch `create_llm_client` in the test setup or add a `Casino(db=mock_db)` constructor path that skips LLM client initialization.
