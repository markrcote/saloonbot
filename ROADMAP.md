# Saloonbot Vision Roadmap

## Context

[VISION.md](/VISION.md) describes an atmospheric, continuously-running frontier casino simulator. NPCs should have persistent identities, backstories, and relationships — with each other and with returning players. The saloon never closes; the world evolves whether or not anyone is at the table. Fame is mechanical, not flavor: a notorious player gets a different game.

**Current state:** M1–M4 are done: NPCs persist across games as a permanent roster with LLM-generated backstories and names drawn from `wwnames.py`, the saloon has a name/identity injected into LLM context, player stats/fame are tracked, and every NPC-departure path routes through one shared hook. Still missing: broke NPCs stay poor forever, NPCs have no memory of individual sessions, no relationships — with each other or with returning players — and the world is inert when no humans are present (no world loop, no ambient NPC-only play). **M5 (NPC Wallet Replenishment) is next up.**

**What exists that can be reused:**
- `personalities.py` — 19 rich personality definitions with system prompts
- `LLMBlackjackNPC` / `llm_client.py` — LLM abstraction with timeout fallback
- DB migration system (`MIGRATIONS` list in `database.py` / `sqlite_database.py`) — append-only, auto-applied on startup
- `casino.py` `_dirty_games` write-behind pattern (game-level) and `Blackjack._dirty` flag (per-instance) — model for any new dirty-flag persistence
- `wwnames/wwnames.py` — Old West name generator, used for NPC names since M1
- `Blackjack.leave()` / `on_npc_departed` hook (M4) — the single point to observe any NPC leaving a table; M6 attaches session condensation here

---

## Milestone 1: Persistent NPC Roster ✓ DONE

**Goal:** NPCs persist between games. The same "Grizzled Prospector" Winifred Cobb can show up again next session.

**Changes (implemented):**
- New `npcs` table (via DB migration): `id`, `name`, `personality_name`, `backstory` (text), `wallet`, `created_at`, `last_played_at`
- On NPC creation in `casino.py`: query `npcs` table for existing NPCs with the requested personality (or any personality if random); create a new DB record if roster is thin (<10 NPCs)
- Backstory generation: on first creation, call LLM with personality system prompt + a "generate your backstory in 2 sentences" prompt; store result in `npcs.backstory`; fall back to empty string on failure
- NPC names drawn from `wwnames.py`
- Serialize NPCs with their `npc_db_id`; on deserialization, load from DB by ID
- NPC wallet tracked in `npcs` table (mirroring how human wallets work in `users`)
- Files: `cardgames/database.py`, `cardgames/sqlite_database.py`, `cardgames/casino.py`, `cardgames/npc_player.py`, `cardgames/llm_npc.py`

**Verification:** Start a game with bots, let it end, start another — confirm the same NPC names reappear with the same backstory. Check DB `npcs` table directly.

---

## Milestone 2: Saloon Identity & Richer LLM Context ✓ DONE

**Goal:** The saloon has a name. NPCs know where they are, who they're playing with, and what their backstory is.

**Changes (implemented):**
- Saloon config via env vars: `SALOON_NAME` (default "The Rusty Spur"), `SALOON_TOWN` (default "Redemption, Texas"), `SALOON_DETAIL_LEVEL` (low/medium/high, default medium)
- LLM system prompt enrichment in `llm_npc.py`: inject saloon name/town, NPC backstory (based on detail level), other players at the table
- Backstory generation via LLM on NPC first creation; stored in `npcs.backstory`; skipped when `low` detail level or no LLM
- `LLMClient.complete()` returns `(text, input_tokens, output_tokens)` tuple
- LLM usage tracking: `llm_usage` DB table (migration 3); logged fire-and-forget for all LLM calls
- `casino.py`: `_log_usage()`, `_generate_backstory()`, `_make_table_context_fn()`, `_handle_get_usage()`
- `/saloon` Discord slash command: shows saloon name, town, active game channels
- `/usage` Discord slash command (admin-only): deferred, Redis request/response, shows 7-day token totals by purpose
- Files: `cardgames/database.py`, `cardgames/sqlite_database.py`, `cardgames/llm_client.py`, `cardgames/llm_npc.py`, `cardgames/casino.py`, `server.py`, `bot.py`

---

## Milestone 3: Player Statistics & Fame ✓ DONE

**Goal:** The game tracks how players play. Notorious players get a different game.

**Changes:**
- Extend `users` table (migration): `games_played`, `hands_played`, `total_won`, `total_lost`, `biggest_win`, `last_seen`
- Update stats after each hand resolution in `cardgames/blackjack.py` → `casino.py` (on hand end callback)
- `fame_score` derived from `total_won`, `games_played`, and recency (computed, not stored)
- LLM NPC context in `llm_npc.py`: pass human players' fame level ("unknown stranger", "known regular", "notorious gambler") alongside the player's name
- NPCs adjust quip tone accordingly (caution toward notorious players; friendliness toward regulars; curiosity toward newcomers)
- New `/stats` Discord command: shows a player's own stats
- Files: `cardgames/blackjack.py`, `cardgames/casino.py`, `cardgames/database.py`, `cardgames/sqlite_database.py`, `cardgames/llm_npc.py`, `bot.py`

**Verification:** Play several hands, check `/stats`. Join a game as an established player and verify NPC quips reference player fame. Unit-test fame score computation.

---

## Milestone 4: Unified NPC Departure Hook ✓ DONE

**Goal:** Every way an NPC can leave a table flows through one shared "NPC left a table" hook, so later features (M6's session condensation) can reliably observe departures. Pure refactor — zero behavior change.

**Changes (implemented):**
- `Blackjack.__init__` takes an optional `on_npc_departed(game, player)` callback; `Blackjack.leave()` calls it (via a new `_fire_departure_hook()` helper) from both of its exit points whenever the departing player `is_npc`, regardless of which state branch removed them
- `Casino._on_npc_departed(game, player)` is the concrete hook: it clears the NPC's `current_game_id` in the DB (`clear_npc_game`). It's wired in at both `Blackjack` construction sites (`Casino.new_game()` and `Blackjack.from_dict()`)
- All four paths now route through `leave()`: the broke-NPC drop in `_tick_betting` switched from direct `self.players` manipulation to `self.leave(player, reason='broke')` (the `reason` param preserves the "tapped out and tips their hat goodbye" flavor message); `remove_npc` and the `_autofill_npcs` trim already called `game.leave()` but had their own duplicated `clear_npc_game` calls removed, since the hook now does it once, centrally
- This closed the NPC save gap: the broke-NPC path previously never cleared `current_game_id`, leaving broke NPCs permanently stuck as "in a game" in the DB
- Files: `cardgames/blackjack.py`, `cardgames/casino.py`

**Verification:** Existing unit (187) + e2e (29) tests pass unchanged; added unit tests asserting each departure path (broke, `remove_npc`, autofill trim, normal `leave`, and leaving from `players_waiting`) fires the shared hook exactly once, that human departures never fire it, and that the broke-NPC flavor message is preserved.

---

## Milestone 5: NPC Wallet Replenishment

**Goal:** NPCs who go broke and leave a table aren't stuck poor forever — idle NPCs slowly rebuild their stake between sessions, at a rate that reflects who they are.

**Changes:**
- Periodic replenishment pass lives in `Casino._tick_games()`, throttled by a `_last_wallet_replenish` timestamp against a new `WALLET_REPLENISH_INTERVAL = 300` (5 minutes) constant — the exact same throttling shape as `_last_autofill`/`AUTOFILL_INTERVAL`. No independent scheduler or thread needed: `listen()`'s main loop already calls `_tick_games()` on every iteration (bounded by a 2s pubsub poll timeout), regardless of whether any games are active, so a throttled check there already satisfies "must run even with no active games." (Correcting an earlier assumption: there's no single `Casino.tick()` method — `_tick_games()` is the per-iteration driver.)
- Each cycle, for every NPC currently **not** seated at any table (`npcs.current_game_id IS NULL` — `get_available_npcs()` already selects exactly this set) whose `wallet < personality.starting_wallet`: roll `P = 0.15 + 0.35 * (starting_wallet - 75) / (300 - 75)`, i.e. linearly scaled across the personalities' known `starting_wallet` range (~75–300) — a "drifter" archetype (75) gets a 15% chance per 5-minute cycle, a "rancher" (300) gets 50%. On success, nudge `wallet += 0.2 * (starting_wallet - wallet)` — 20% of the remaining gap, asymptotically approaching the target and never exceeding it (no separate cap check needed; the formula can't overshoot).
- Only idle NPCs replenish. NPCs actively seated at a table are governed purely by game outcomes — no passive top-up while playing, so wins/losses still matter at the table.
- Wealth signal: reuse `Personality.starting_wallet` directly for both the replenishment target and the probability driver — no dedicated `npcs.wealth` column. It already varies 4x across archetypes (a designed-in wealth proxy), needs no new migration, and avoids the fragility of trying to extract a "wealth" signal from a 2–4 sentence LLM-generated backstory that may never mention money at all (which would also mean a new LLM call/purpose tag just to classify it). If backstory-level variance within the same personality ever matters, that's a future refinement, not a blocker here.
- Files: `cardgames/casino.py` (new throttled pass inside `_tick_games()`, `WALLET_REPLENISH_INTERVAL` constant, `_last_wallet_replenish` timestamp)

**Verification:** Drive an NPC's wallet to zero (or set it manually), remove it from all tables, let the replenishment pass run several cycles (or fast-forward `_last_wallet_replenish`/`WALLET_REPLENISH_INTERVAL` in a test), confirm wallet trends upward toward its personality's `starting_wallet` and stops there; confirm a wallet is untouched while its NPC is seated at a table.

---

## Milestone 6: NPC Memory & Context Window

**Goal:** NPCs stop making stateless, one-shot LLM calls. Each NPC accumulates a running memory of what happens while it's seated at a table, and condenses that into a persistent memory when it leaves — feeding future prompts and supplying the raw material for M7/M8's relationship notes.

**Changes:**
- Session = one NPC's table tenure: from the moment it joins a table (creation, `add_npc`, or autofill) until it leaves (`leave`, `remove_npc`, or the game itself ending). Each NPC's session is tracked independently — two NPCs sharing a table each build their own memory of it.
- In-session event buffer: `LLMBlackjackNPC` accumulates a bounded, structured log of **every player's** turns at the table for the duration of its session — every PC's and NPC's bets/hits/stands and outcomes, plus quips/banter from NPCs (PCs have no free-text channel today; their turns are logged as structured events, not raw text). Capped at **40 events** (FIFO eviction via a `deque(maxlen=40)`), not raw LLM message history and not a token budget — each buffered event is already a short templated string, so an event-count cap is simpler than estimating tokens and matches the codebase's existing preference for simple counters over token accounting (usage tracking only ever reads *actual* token counts back from API responses, never estimates them beforehand).
- No PC free-text banter for now: building a chat/quip input for PCs would also open a prompt-injection surface (arbitrary player text feeding straight into other NPCs' LLM prompts) — deliberately out of scope here. Revisit once this mechanism is proven out.
- Recent-window continuity: `_build_context_block()` includes a short recap of the last few buffered events so mid-session decisions react to what just happened at the table (runtime-only, not persisted separately from the buffer itself).
- **Growing departure chance:** because the buffer covers every player's turns (not just the NPC's own), it grows faster on a busy table. On each `BETWEEN_HANDS` tick (mirroring where `_autofill_npcs`'s trim check already runs), roll `P = 0.02 + 0.28 * (len(buffer) / 40)` — a linear ramp from a 2% baseline "ambient turnover" chance at an empty buffer up to ~30% per hand once the buffer is full. Linear-on-fill-fraction rather than a step function or token-based curve: it needs no new estimation machinery (consistent with the event-count cap above), and a smooth ramp avoids a visible "cliff" where NPCs abruptly leave in unison at some threshold, which would read as mechanical rather than natural. The ramp is deliberately steep enough that buffer overflow (oldest events silently evicted) should be rare in practice, not the norm — framed in-character as the NPC "calling it a night."
- All departure paths flow through the shared "NPC left a table" hook delivered by M4 — condensation attaches there, so it fires for broke departures, `remove_npc`, autofill trims, and normal `leave` alike. (Without that unification, condensation would silently never fire for broke departures.)
- Condensation on departure: when an NPC leaves a table (via the shared hook above), submit one LLM summarization call — **fire-and-forget**, submitted to the NPC's own single-worker `ThreadPoolExecutor` (the same executor `decide_action`/`decide_bet` already use) — over its full session event buffer, producing a short first-person "memory" of the session (2–4 sentences: what happened, backstory reveals, standout interactions with named PCs/NPCs). Blocking is the wrong call here: unlike an action/bet decision, which the game loop must wait on because play literally can't proceed without it, nothing needs this NPC's summary to exist immediately after it leaves — the seat should free up right away for autofill/join regardless of whether the write has finished. (Backstory generation is the one existing blocking LLM call in the codebase, but that's justified by rarity — it only fires when the roster is thin — and by the fact the *same* NPC's very next prompt needs it immediately; departure has no such immediate dependency.) Stored in a new `npc_memories` table (`id`, `npc_id`, `game_id`, `session_summary`, `created_at`).
- Retention: cap at the **20 most recent** `npc_memories` rows per NPC, pruning older ones on insert. Unbounded accumulation would be pure technical debt in a continuously-running saloon (VISION.md) — only the most recent rows are ever read back (recall surfaces at most 3, at `high` detail level), so anything beyond a modest cap is waste with no product upside. 20 gives headroom over the max ever surfaced today without unbounded growth, and is a tunable constant, not a schema decision.
- Restart durability: the in-session event buffer does **not** get persisted in `to_dict()`/`from_dict()` — losing a partial buffer on server restart is an accepted trade-off. It's inherently transient (it exists only to be condensed and discarded at session end), a restart mid-session only thins that one session's eventual memory rather than corrupting anything, and already-condensed `npc_memories` rows are ordinary persisted DB rows unaffected by this. Persisting it would mean growing the payload of every dirty-flag write-behind flush for games with LLM NPCs, for a value whose entire purpose is to be thrown away — not worth it for a rare, self-healing failure mode.
- Memory feeds M7/M8 in two steps, not one combined call: M6's condensation call only ever produces the generic `npc_memories.session_summary` and ships independently of M7/M8. When M7/M8 land, a separate, smaller follow-up call reads that fresh summary to generate/update the relevant `npc_relationships.notes` and `pc_npc_relationships.npc_notes_on_player` rows for whoever shared the table. Keeping these as separate calls (and separate `llm_usage` purpose tags — `session_memory` vs. `relationship_gen`/`pc_npc_summary`) matches the existing one-purpose-per-call pattern and keeps M6 shippable and testable before M7/M8 exist, rather than requiring M6's prompt to already know about M7/M8's schema.
- Memory recall in future prompts: `_build_context_block()` gains a "recent memories" section (most recent `npc_memories` rows for that NPC), gated by `SALOON_DETAIL_LEVEL` (`low` = feature off entirely, `medium` = 1 short summary, `high` = up to 3).
- Detail-level gating covers the whole feature, not just recall: at `low`, skip event buffering and condensation calls outright (mirrors how `low` already skips backstory generation).
- New `llm_usage` purpose tag: `session_memory`.
- Files: `cardgames/llm_npc.py`, `cardgames/casino.py`, `cardgames/blackjack.py`, `cardgames/database.py`, `cardgames/sqlite_database.py`

**Verification:** Seat an NPC, play a few hands with quips and a human player, remove the NPC, confirm an `npc_memories` row is created summarizing the session; seat it again later and confirm the next session's prompt references the prior memory. Separately, seat an NPC at a busy table and confirm its departure probability measurably increases as the buffer grows over many hands.

---

## Milestone 7: NPC–NPC Relationships

**Goal:** Regular NPCs have history with each other. Two old rivals play differently when they share a table.

**Changes:**
- New `npc_relationships` table (migration): `npc_id_a`, `npc_id_b`, `relationship_type` (enum: `friend`/`rival`/`complicated`), `strength` (int 0–100), `notes` (text, NOT NULL). No `stranger` type — **absence of a row means strangers**, avoiding O(n²) rows across a mostly-stranger roster. Rows are stored with `npc_id_a < npc_id_b` by convention, enforced by a unique index on the pair, so A↔B can never exist twice.
- Creation-time generation: when a new NPC is created, roll a **70% chance** that it has any pre-existing relationships; if so, pick **1–3 partners** (uniform) sampled from up to **10** random roster NPCs, with type weights **friend 45% / rival 30% / complicated 25%** and initial `strength` uniform in **20–60** (some pairs start as passing acquaintances, others with real history already baked in). All of these are module constants, not schema.
- Relationship note generation is **fire-and-forget** on the NPC's own single-worker executor (same as M6's condensation), with a per-type template fallback (e.g. "Old friends from way back.") written on failure — `notes` is never NULL. Blocking (like backstory) isn't justified here: creation can spawn up to 3 notes, and nothing needs them immediately — if a note isn't ready for the NPC's first prompt, the relationship simply doesn't surface yet, which is self-healing. At `low` detail level, skip the LLM call entirely and use the template (mirroring backstory behavior).
- When two related NPCs share a table, inject their relationship summary into both their LLM contexts, gated by `SALOON_DETAIL_LEVEL` per the cross-cutting table: `low` = omitted from prompts (rows are still created, with template notes, so raising the detail level later just works), `medium` = type + 1-sentence note, `high` = full notes.
- Strength semantics and evolution: `strength` measures how much **history** a pair has (familiarity/intensity — valence lives in `relationship_type`; a strength-90 rivalry is a storied one, not a friendly one). **+5 per shared session, capped at 100**, applied in the M4 departure hook: when an NPC leaves, award +5 to its pair with each related NPC still seated. This dedupes for free — when the second NPC of a pair leaves, the first is already gone, so each shared session is counted exactly once (including simultaneous departures at game end, which are processed sequentially).
- Note/type evolution: when a +5 increment **crosses a 20-point boundary** (`old // 20 != new // 20` — computed at increment time, no extra tracking column), fire one LLM call (purpose `relationship_gen`) that reads both personalities, the current relationship, and the fresh M6 session summary, and outputs an updated note **and possibly an updated type** (e.g. friend→complicated) as JSON. Type changes are LLM-driven at these boundary crossings — i.e. at most every ~4 shared sessions per pair — rather than tracked mechanically: blackjack is dealer-vs-players, so "rivals form from wins/losses against each other" has no mechanical meaning, and letting the summarization step decide keeps evolution organic with zero new columns.
- Accepted consequences of the boundary scheme: a pair at strength 100 never crosses again, so its note/type freeze (a maxed bond being stable is coherent); and there is **no decay** while NPCs are apart — M9b's "falling-out" world event is the designed mechanism for relationships changing off-table.
- New `/npcrelationships` Discord command (admin-only): given an NPC name, lists its relationships (partner, type, strength, note) via the `/checkwallet`-style Redis request/response pattern — the practical way to verify and debug the feature without SQL access.
- Files: `cardgames/database.py`, `cardgames/sqlite_database.py`, `cardgames/casino.py`, `cardgames/llm_npc.py`, `bot.py`

**Verification:** Unit tests with seeded RNG for creation probabilities/pairing, strength/boundary logic, and prompt injection via a fake LLM client; plus one e2e test that runs without an API key and asserts relationship rows are created via the template path. Manually: seed two NPCs as rivals, confirm both LLM prompts include the relationship context, play shared sessions, and check the +5 increments and a note regeneration at the first boundary crossing.

---

## Milestone 8: PC–NPC Relationships

**Goal:** NPCs remember you. A player who has sat across from Winifred Cobb three times gets a different reception than a stranger.

**Changes:**
- New `pc_npc_relationships` table (migration): `player_id`, `npc_id`, `times_met`, `sessions_played`, `npc_notes_on_player` (text, LLM-generated summary)
- After each game where a human and NPC shared a table: increment `times_met`, update `sessions_played`; `npc_notes_on_player` is regenerated via the M6 session-condensation step (based on outcome history and the NPC's own session memory), not a standalone milestone-triggered call
- LLM context in `llm_npc.py`: if relationship record exists, inject NPC's notes on this player alongside fame context
- NPCs greet returning players differently ("Back again, partner?" on 2nd meeting; more familiar tone on 5th+)
- Files: `cardgames/database.py`, `cardgames/sqlite_database.py`, `cardgames/casino.py`, `cardgames/llm_npc.py`

**Verification:** Play two sessions with the same NPC; confirm 2nd session quips reference prior meeting. Check `pc_npc_relationships` table updates in DB.

---

## Milestone 9a: Ambient World Loop & Pacing (The Saloon Never Closes)

**Goal:** The saloon runs between sessions. NPCs come and go and play each other without any human present, at a pace that reads as background ambience.

**Changes:**
- **Scope check first:** NPC autofill (`npc_min > 0`) already keeps existing tables populated and un-reaped, enabling NPC-only ambient play — part of this milestone's original scope has been absorbed. Re-verify the remaining gap before implementing: it's the spawning/scheduling of NPC-only games and the availability model, not "NPCs playing without humans" per se.
- Background world loop in `server.py` (or new `world.py`): runs on a configurable interval (e.g., every 5–15 minutes real time); spawns NPC-only games when no human games are active; lets them play out a few hands. Relationship/memory updates happen automatically via the M6/M7 machinery — no separate update pass needed here.
- NPC "availability" model: each NPC has a `next_available_at` timestamp; world loop picks available NPCs and seats them together, simulating a night at the saloon
- **NPC-only pacing**: when no human players are at the table, the game runs at a slower, ambient pace — longer delays between hands and actions, so it reads like background conversation rather than active play. New env var `SALOON_NPC_PACE_MULTIPLIER` (default `3.0`) scales `BLACKJACK_TIME_BETWEEN_HANDS` and inter-action delays; the channel stream becomes something players can ignore or tune into for entertainment. Pace returns to normal the moment a human joins.
- Files: `server.py`, new `cardgames/world.py`, `cardgames/casino.py`, `cardgames/database.py`, `cardgames/sqlite_database.py`
- Config: `SALOON_WORLD_TICK_MINUTES` (default 10), `SALOON_WORLD_ENABLED` (default true)

**Verification:** Disable human games; let world loop run for a few ticks; confirm NPC-only games spawn, play at the slower pace, and wind down; confirm pace returns to normal the moment a human joins.

---

## Milestone 9b: World Events & /news

**Goal:** The world accumulates visible history. Players can catch up on what happened at the saloon while they were away.

**Changes:**
- Random world events (small set): NPC goes on winning/losing streak (adjust wallet), NPC gets "restless" (plays more often), NPC has a falling-out with another (relationship type changes)
- Event generation runs as a throttled pass inside `Casino._tick_games()` (same shape as M5's replenishment pass), so it does **not** depend on M9a's world loop — M9b can ship before or after M9a. Caveat: the "restless" event's mechanical effect (plays more often) requires M9a's availability model; if M9b lands first, that event is flavor-only until M9a exists.
- World event log: lightweight `world_events` table (npc_id, event_type, description, occurred_at); last 20 events queryable
- New `/news` Discord command: shows recent world events in-character ("Word around the saloon: Winifred Cobb cleaned out the table last Tuesday...")
- Files: `cardgames/casino.py`, `cardgames/database.py`, `cardgames/sqlite_database.py`, `bot.py`

**Verification:** Let the event pass run (or fast-forward its throttle in a test); confirm `world_events` rows appear, relationship-changing events update `npc_relationships`, and `/news` returns in-character events.

---

## Cross-Cutting: LLM Usage Tracking & Detail Level

These concerns apply across all milestones and should be introduced in **M1** and extended as later milestones add LLM calls.

### LLM Usage Tracking

**Goal:** Know how many tokens/credits are being consumed and by what.

- New `llm_usage` table (migration): `id`, `occurred_at`, `purpose` (enum: `npc_action`, `npc_bet`, `backstory_gen`, `session_memory`, `relationship_gen`, `relationship_update`, `pc_npc_summary`, `world_event`), `model`, `input_tokens`, `output_tokens`, `npc_id` (nullable), `game_id` (nullable)
- `llm_client.py`: capture token counts from API responses (Claude returns `usage.input_tokens` / `usage.output_tokens`; OpenAI returns `usage.prompt_tokens` / `usage.completion_tokens`); return alongside the response
- Each call site passes a `purpose` tag and persists a record asynchronously (fire-and-forget; never block gameplay on a usage write)
- New `/usage` Discord command (admin-only): shows token totals by purpose for the past 7 days, estimated cost (configurable per-token rate via `LLM_COST_PER_1K_INPUT` / `LLM_COST_PER_1K_OUTPUT` env vars)
- Files: `cardgames/llm_client.py`, `cardgames/database.py`, `cardgames/sqlite_database.py`, `bot.py`

### Detail Level Configuration

**Goal:** Let operators tune how much NPC depth (and thus how many tokens) the system uses.

- New env var `SALOON_DETAIL_LEVEL`: `low` / `medium` / `high` (default `medium`)
- Controls what context is injected into LLM prompts at each milestone:

| Feature | `low` | `medium` | `high` |
|---|---|---|---|
| NPC backstory in prompt | omitted | 1–2 sentences | full backstory |
| Other players at table | names only | names + archetype | names + archetype + fame |
| NPC–NPC relationships | omitted | type + 1-sentence note | full notes |
| PC–NPC history | omitted | times met + tone | full NPC notes on player |
| World events context | omitted | omitted | last 3 events mentioning NPC |

- Backstory generation length mirrors detail level: `low` = skip LLM (use template), `medium` = 2-sentence LLM call, `high` = 4-sentence LLM call
- Relationship note generation: `low` = template-only, `medium` = 1 sentence, `high` = 2 sentences
- Files: `server.py` (read env var, pass to Casino), `cardgames/casino.py`, `cardgames/llm_npc.py`

---

## Dependency Order

```
M1 (Persistent NPCs)
├── M2 (Saloon Identity + Context)        ← can start after M1
├── M3 (Player Fame)                      ← can start after M1
├── M5 (NPC Wallet Replenishment)         ← requires M1, independent otherwise
├── M4 (Unified NPC Departure Hook)       ← pure refactor; no deps beyond M1
│   └── M6 (NPC Memory & Context Window) ← requires M1 + M4
│       ├── M7 (NPC–NPC Relationships)   ← requires M1 + M6
│       │   ├── M9a (Ambient World Loop & Pacing) ← requires M1 + M7
│       │   └── M9b (World Events & /news)        ← requires M1 + M7; independent of M9a
│       └── M8 (PC–NPC Relationships)    ← requires M1 + M3 + M6
```

M1 is the critical prerequisite. M2 and M3 can proceed in parallel after M1. M5 is independent — it can be picked up any time after M1 with no other dependencies, which is why it's slotted in next: it's small, self-contained, and unblocks nothing else, so there's no cost to doing it before the memory/relationships chain. M4 is a small standalone refactor that must land before M6 (it supplies the departure hook condensation attaches to). M6 is a prerequisite for both M7 and M8 (it supplies the session-condensation mechanism their relationship notes are generated from). M7 can start after M1+M6, M8 after M1+M3+M6. M9a and M9b both follow M7 and are independent of each other — M9b's event pass piggybacks on the existing tick rather than M9a's world loop, though the "restless" event only gains mechanical effect once M9a's availability model exists.
