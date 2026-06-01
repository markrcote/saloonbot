# Saloonbot Vision Roadmap

## Context

VISION.md describes an atmospheric, continuously-running frontier casino simulator. NPCs should have persistent identities, backstories, and relationships — with each other and with returning players. The saloon never closes; the world evolves whether or not anyone is at the table. Fame is mechanical, not flavor: a notorious player gets a different game.

**Current state:** The foundation is solid (LLM-backed NPCs with personalities, game persistence, Redis pub/sub, DB migrations), but NPCs are ephemeral (created fresh per game, deleted on end), the saloon has no identity, there is no relationship system, and the world is inert when no humans are present.

**What exists that can be reused:**
- `personalities.py` — 19 rich personality definitions with system prompts
- `LLMBlackjackNPC` / `llm_client.py` — LLM abstraction with timeout fallback
- DB migration system (`MIGRATIONS` list in `database.py` / `sqlite_database.py`) — append-only, auto-applied on startup
- `casino.py` `_dirty_games` write-behind pattern — model for any new dirty-flag persistence
- `wwnames/wwnames.py` — Old West name generator (currently unused by NPCs)

---

## Milestone 1: Persistent NPC Roster

**Goal:** NPCs persist between games. The same "Grizzled Prospector" Winifred Cobb can show up again next session.

**Changes:**
- New `npcs` table (via DB migration): `id`, `name`, `personality_name`, `backstory` (text), `wallet`, `created_at`, `last_played_at`
- On NPC creation in `casino.py`: query `npcs` table for existing NPCs with the requested personality (or any personality if random); create a new DB record if roster is thin (<10 NPCs)
- Backstory generation: on first creation, call LLM with personality system prompt + a "generate your backstory in 2 sentences" prompt; store result in `npcs.backstory`; fall back to empty string on failure
- NPC names drawn from `wwnames.py` (currently unused for this purpose)
- Serialize NPCs with their `npc_db_id`; on deserialization, load from DB by ID
- NPC wallet tracked in `npcs` table (mirroring how human wallets work in `users`)
- Files: `cardgames/database.py`, `cardgames/sqlite_database.py`, `cardgames/casino.py`, `cardgames/npc_player.py`, `cardgames/llm_npc.py`

See `M1-ARCH.md` for detailed architectural decisions.

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

## Milestone 3: Player Statistics & Fame

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

## Milestone 4: NPC–NPC Relationships

**Goal:** Regular NPCs have history with each other. Two old rivals play differently when they share a table.

**Changes:**
- New `npc_relationships` table (migration): `npc_id_a`, `npc_id_b`, `relationship_type` (enum: `friend`/`rival`/`stranger`/`complicated`), `strength` (int 0–100), `notes` (text)
- On new NPC creation: probabilistically generate 1–3 relationships to existing roster NPCs; for each, call LLM with both personalities to produce a 1-sentence relationship note; store in DB
- When two related NPCs share a table, inject their relationship summary into both their LLM contexts
- Relationship `strength` nudges up after shared sessions (regardless of outcome); rival relationships can form from repeated big wins/losses against each other
- Periodic relationship evolution pass (run during `tick()` or server idle loop): update `notes` summaries via LLM if strength has changed significantly
- Files: `cardgames/database.py`, `cardgames/sqlite_database.py`, `cardgames/casino.py`, `cardgames/llm_npc.py`

**Verification:** Seed two NPCs with a "rival" relationship; confirm their LLM prompts include the relationship context; play a session and check that relationship strength updates.

---

## Milestone 5: PC–NPC Relationships

**Goal:** NPCs remember you. A player who has sat across from Winifred Cobb three times gets a different reception than a stranger.

**Changes:**
- New `pc_npc_relationships` table (migration): `player_id`, `npc_id`, `times_met`, `sessions_played`, `npc_notes_on_player` (text, LLM-generated summary)
- After each game where a human and NPC shared a table: increment `times_met`, update `sessions_played`; if `times_met` is a milestone (1st, 3rd, 10th…), regenerate `npc_notes_on_player` via LLM (based on outcome history)
- LLM context in `llm_npc.py`: if relationship record exists, inject NPC's notes on this player alongside fame context
- NPCs greet returning players differently ("Back again, partner?" on 2nd meeting; more familiar tone on 5th+)
- Files: `cardgames/database.py`, `cardgames/sqlite_database.py`, `cardgames/casino.py`, `cardgames/llm_npc.py`

**Verification:** Play two sessions with the same NPC; confirm 2nd session quips reference prior meeting. Check `pc_npc_relationships` table updates in DB.

---

## Milestone 6: Autonomous World (The Saloon Never Closes)

**Goal:** The saloon runs between sessions. NPCs come and go, play each other, and accumulate history without any human present.

**Changes:**
- Background world loop in `server.py` (or new `world.py`): runs on a configurable interval (e.g., every 5–15 minutes real time); spawns NPC-only games when no human games are active; lets them play out a few hands; updates all relationship data
- NPC "availability" model: each NPC has a `next_available_at` timestamp; world loop picks available NPCs and seats them together, simulating a night at the saloon
- Random world events (small set): NPC goes on winning/losing streak (adjust wallet), NPC gets "restless" (plays more often), NPC has a falling-out with another (relationship type changes)
- World event log: lightweight `world_events` table (npc_id, event_type, description, occurred_at); last 20 events queryable
- New `/news` Discord command: shows recent world events in-character ("Word around the saloon: Winifred Cobb cleaned out the table last Tuesday...")
- Files: `server.py`, new `cardgames/world.py`, `cardgames/casino.py`, `cardgames/database.py`, `cardgames/sqlite_database.py`, `bot.py`
- Config: `SALOON_WORLD_TICK_MINUTES` (default 10), `SALOON_WORLD_ENABLED` (default true)

**Verification:** Disable human games; let world loop run for a few ticks; confirm NPC wallets change, relationships update, and `/news` returns in-character events.

---

## Cross-Cutting: LLM Usage Tracking & Detail Level

These concerns apply across all milestones and should be introduced in **M1** and extended as later milestones add LLM calls.

### LLM Usage Tracking

**Goal:** Know how many tokens/credits are being consumed and by what.

- New `llm_usage` table (migration): `id`, `occurred_at`, `purpose` (enum: `npc_action`, `npc_bet`, `backstory_gen`, `relationship_gen`, `relationship_update`, `pc_npc_summary`, `world_event`), `model`, `input_tokens`, `output_tokens`, `npc_id` (nullable), `game_id` (nullable)
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
├── M2 (Saloon Identity + Context)   ← can start after M1
├── M3 (Player Fame)                  ← can start after M1
├── M4 (NPC–NPC Relationships)       ← requires M1
│   └── M6 (Autonomous World)        ← requires M1 + M4
└── M5 (PC–NPC Relationships)        ← requires M1 + M3
```

M1 is the critical prerequisite. M2 and M3 can proceed in parallel after M1. M4 can start after M1, M5 after M1+M3. M6 is last and benefits from all prior milestones.
