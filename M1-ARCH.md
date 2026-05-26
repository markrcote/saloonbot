# M1 Architecture Decisions

Six decisions resolved before implementing M1 (Persistent NPC Roster).

---

## Assumption: Single Game Constraint

SaloonBot is a single-guild, single-game bot for M1. At most N NPCs (N ≤ 4) are in use at once, so there are no race conditions on roster selection. Multi-game support is deferred; when that changes, `SELECT FOR UPDATE` and dynamic pool sizing are the levers to pull.

---

## Decision 1: NPC roster selection

**Question:** How do we pick which NPC shows up in a game?

**Resolution:**
- Add `current_game_id` (nullable) column to `npcs` table
- Selection query: `SELECT * FROM npcs WHERE current_game_id IS NULL ORDER BY RAND() LIMIT N`
- Within a game, still filter out duplicate personality archetypes
- If fewer than N available, create new NPC records on the spot
- Target minimum roster size: 20

---

## Decision 2: Backstory generation timing

**Question:** When and how do we generate an NPC's backstory?

**Resolution:** Option C — template only for M1. No LLM backstory generation until M2, when backstories are actually injected into LLM prompts. NPCs are created with an empty backstory field.

---

## Decision 3: NPC wallet

**Question:** Where does an NPC's wallet live?

**Resolution:** Option A — `wallet` column on `npcs` table. Casino gets a thin `get_wallet(player)` / `update_wallet(player, delta)` dispatcher that routes to either `users` or `npcs` depending on player type. A unified `wallets` table is noted as a potential M6 refactor when NPCs play autonomous games.

---

## Decision 4: NPC object — where does the DB id live?

**Question:** How does `npc_db_id` (and `backstory`) get onto the NPC object?

**Resolution:** Option A — add as optional constructor args to `LLMBlackjackNPC`:

```python
def __init__(self, name: str, personality: Personality, llm_client: LLMClient,
             npc_db_id: int | None = None, backstory: str | None = None):
```

Existing callers are unaffected (args default to `None`). `npc_db_id=None` means the NPC is ephemeral (e.g. via manual `add_npc`).

---

## Decision 5: Serialization

**Question:** How do we persist NPC DB identity across server restarts?

**Resolution:**
- `serialize_player` adds `'npc_db_id': player.npc_db_id`
- `deserialize_player`: if `npc_db_id` is present, load the NPC record from DB and reconstruct with full identity; otherwise reconstruct from `npc_personality` name alone
- No backward compatibility required — DB can be dropped and recreated freely during development

---

## Decision 6: `current_game_id` bookkeeping

**Question:** Who sets/clears `current_game_id` and when?

**Resolution:**
- Set by `Casino._add_pending_bots` when seating an NPC
- Cleared in `Casino._delete_game` (game ends) and `Casino.remove_npc` (NPC leaves mid-game)
- `Blackjack` never touches it — `Casino` owns all NPC DB state

---

## Pre-M1 Fixes

These must land before M1 implementation begins:

1. **Executor leak** (`llm_npc.py`) — add `shutdown()` to `LLMBlackjackNPC`, call it from `Casino._delete_game` for any LLM NPCs in the game
2. **NPC bet save gap** (`blackjack.py` / `casino.py`) — add `_bets_dirty` flag to `Blackjack`; set whenever `self.bets` changes; include in `_tick_games()` save condition
3. **Dead fallback** (`llm_npc.py`) — remove unreachable `except` clause in `decide_action`; `_llm_decide_action` already handles all its own exceptions internally
