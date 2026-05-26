# M1 Architecture Decisions

Six decisions to resolve before implementing M1 (Persistent NPC Roster).

---

## Decision 1: NPC roster selection

**Question:** How do we pick which NPC shows up in a game?

**Proposal:**
- Add `current_game_id` (nullable) column to `npcs` table
- Selection query: `SELECT * FROM npcs WHERE current_game_id IS NULL ORDER BY RAND() LIMIT N`
- Within a game, still filter out duplicate personality archetypes
- If fewer than N available, create new NPC records on the spot
- Target minimum roster size: 20

**Status:** OPEN

---

## Decision 2: Backstory generation timing

**Question:** When and how do we generate an NPC's backstory?

**Options:**
- A) Sync at creation — simple but adds latency to game start
- B) Async fire-and-forget — same ThreadPoolExecutor pattern as LLM actions; NPC's first game has no backstory, second does
- C) Template only for M1 — defer LLM generation to M2 when backstories are actually used in prompts

**Proposal:** Option B (async). Backstories aren't injected into LLM context until M2, so it doesn't matter if they arrive late.

**Status:** OPEN

---

## Decision 3: NPC wallet

**Question:** Where does an NPC's wallet live?

**Options:**
- A) `wallet` column on `npcs` table + `casino.get_wallet(player)` / `casino.update_wallet(player, delta)` dispatcher
- B) NPCs as rows in `users` table (simpler DB, conceptually wrong)
- C) Wallet stays in game JSON, copied back to `npcs.wallet` at game end only

**Proposal:** Option A — clean separation, thin dispatcher on Casino, pays off in M6 autonomous games.

**Status:** OPEN

---

## Decision 4: NPC object — where does the DB id live?

**Question:** How does `npc_db_id` (and `backstory`) get onto the NPC object without breaking the constructor?

**Options:**
- A) Add as optional constructor args to `LLMBlackjackNPC`
- B) Set as plain attributes post-construction (`npc.npc_db_id = row['id']`)

**Proposal:** Option B — no constructor change; `npc_db_id` defaults to `None` for the manual `add_npc` path (stays ephemeral).

**Status:** OPEN

---

## Decision 5: Serialization

**Question:** How do we persist NPC DB identity across server restarts?

**Proposal:**
- `serialize_player` gains `'npc_db_id': getattr(player, 'npc_db_id', None)`
- `deserialize_player`: if `npc_db_id` present, load NPC record from DB; otherwise fall back to current behavior (reconstruct from `npc_personality` name)
- Fully backward compatible with existing game state blobs

**Status:** OPEN

---

## Decision 6: `current_game_id` bookkeeping

**Question:** Who sets/clears `current_game_id` and when?

**Proposal:**
- Set by `Casino._add_pending_bots` when seating an NPC
- Cleared in `Casino._delete_game` (game ends) and `Casino.remove_npc` (NPC leaves mid-game)
- `Blackjack` never touches it — `Casino` layer owns all NPC DB state

**Status:** OPEN
