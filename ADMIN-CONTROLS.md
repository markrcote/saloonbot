# Admin Controls & Inspectors Roadmap

## Context

The only "admin" concept today is Discord's built-in `administrator` permission, which
gates a handful of slash commands (`/newgame`, `/stopgame`, `/quitgame`, `/usage`,
`/debug`). There is no application-level game-host/owner role, and no server-side
authorization — the casino trusts any action it receives over Redis. This is fine for now;
Discord-admin gating is the authorization model.

What's missing is operator tooling:

- **NPC population control.** Beyond the per-game `num_bots` (0–4) chosen at creation,
  there is no way to influence how many NPCs sit at a table. The casino already has
  `add_npc()` / `remove_npc()` methods and an `npc_action` Redis handler
  (`casino.py:533-598`, `:694-703`), **but no Discord command reaches them**. `MIN_NPC_ROSTER`
  (`casino.py:23`) only governs the size of the persistent roster, not per-table seating.
- **Wallet management.** `/wad` and the `get_wallet` handler only read the **users** table
  (players). NPC wallet helpers (`get_npc_wallet` / `update_npc_wallet`) exist but are
  unexposed, and nothing anywhere can *set* or *adjust* a balance.

This roadmap adds runtime, DB-persisted admin controls for NPC population (automatic
table auto-fill within a min/max, plus manual per-game add/remove) and for viewing and
editing any player's or NPC's wallet (set-absolute and adjust-by-delta). It supports the
ambient, NPC-driven saloon vision (see `ROADMAP.md` M6) while giving operators levers to
tune and correct live state.

**Design decisions (settled):**
- NPC control = auto-fill tables to a min/max **and** manual add/remove per game.
- Wallet edits support **both** set-absolute and adjust-by-delta, for players **and** NPCs.
- Min/max NPC limits are **runtime-settable via an admin command, persisted in the DB**
  (survive restarts; no redeploy needed).

**What exists that can be reused:**
- `casino.py` `get_wallet` / `update_wallet` (`:79-98`) — player-vs-NPC routing via
  `player.is_npc` / `player.npc_db_id`; the model for a wallet-target resolver.
- `database.py` / `sqlite_database.py` wallet methods (`get_user_wallet`, `update_wallet`,
  `get_npc_wallet`, `update_npc_wallet`) and the MySQL deadlock-retry helper.
- The `MIGRATIONS` append-only migration system in both DB backends.
- The request/response Redis pattern used by `/usage`, `/wad`, `/debug` (bot stores a
  pending interaction keyed by `request_id`; server replies on `casino_update`).
- The existing but unwired `add_npc` / `remove_npc` / `npc_action` plumbing.
- `_add_pending_bots` (`casino.py:372-429`) and `_get_or_create_npcs` — the roster-backed
  NPC spawn path to factor into a shared helper.

---

## AM1: Settings Store & Wallet DB Helpers

**Goal:** A DB-backed runtime config store, plus absolute-set and name-lookup wallet
primitives, that the later milestones build on.

**Changes:**
- New `settings` table via migration appended to `MIGRATIONS` in **both** `database.py` and
  `sqlite_database.py` (never edit existing entries):
  - Columns `setting_key` / `setting_value` (avoid the MySQL reserved words `key`/`value`).
- New DB methods (identical interface in both backends):
  - `get_setting(key, default=None) -> str | default`
  - `set_setting(key, value)` — UPSERT (MySQL `ON DUPLICATE KEY UPDATE`; SQLite
    `INSERT ... ON CONFLICT(setting_key) DO UPDATE`)
  - `set_user_wallet(username, amount) -> bool` — absolute set; sibling of `update_wallet`
    (`database.py:217`); wrap the MySQL write in the deadlock-retry helper
  - `set_npc_wallet(npc_id, amount) -> bool` — sibling of `update_npc_wallet`
  - `find_npc_by_name(name) -> dict | None` — case-insensitive (`WHERE LOWER(name)=LOWER(?)`),
    returning at least `id` and `wallet`
- Files: `cardgames/database.py`, `cardgames/sqlite_database.py`, `test.py`

**Verification:** Unit tests for settings UPSERT (insert then overwrite), absolute wallet
sets on a user and an NPC, and case-insensitive NPC name lookup (hit and miss).

---

## AM2: Wallet Inspection & Editing Commands

**Depends on:** AM1.

**Goal:** Admins can view and change any player's or NPC's wallet.

**Changes:**
- Casino actions (on the `casino` topic), each request/response with a `request_id`:
  - `lookup_wallet {target}` → search users then NPCs (`get_user_wallet`, else
    `find_npc_by_name`); reply `event_type:"wallet_info"`
    `{request_id, target, kind:'player'|'npc'|None, balance}`
  - `set_wallet {target, mode:'set'|'adjust', amount}` → resolve target, apply via
    `set_user_wallet`/`set_npc_wallet` (set) or `update_wallet`/`update_npc_wallet`
    (adjust); reply `event_type:"wallet_set"`
    `{request_id, target, kind, new_balance, ok, message}`
  - Shared `_resolve_wallet_target(name) -> (kind, ref)` helper to avoid duplication; reuse
    the routing idea from `get_wallet`/`update_wallet` (`casino.py:79-98`)
  - Reject `set` amounts `< 0`; adjusts that would drive a balance negative fail (the
    `update_*` helpers already guard `>= 0`) and report `ok:false`
- Bot slash commands (admin-gated, ephemeral, request/response like `/usage` at
  `bot.py:305`; add matching `_pending_*_interactions` dicts and routes in
  `process_message`):
  - `/checkwallet target:str`
  - `/setwallet target:str amount:int`
  - `/givechips target:str amount:int` (negative allowed to take chips)
- Leave `/wad` and the existing `get_wallet` handler untouched (player self-check).
- Files: `cardgames/casino.py`, `bot.py`, `test_e2e.py`

**Verification:** E2E round-trips (mirroring the `TestStopGame` style, `test_e2e.py:661`):
`set` and `adjust` on a seeded player and an NPC; `lookup_wallet` for both kinds; the
negative-balance rejection path. Clean the `settings` table in `setUp` alongside existing
table cleanup.

---

## AM3: NPC Limits & Table Auto-Fill

**Depends on:** AM1.

**Goal:** Active tables stay populated within an admin-set min/max, enabling NPC-only
ambient play.

**Changes:**
- Constants near `MIN_NPC_ROSTER` (`casino.py:23`): `DEFAULT_NPC_AUTOFILL_MIN = 0`
  (auto-fill off by default), `DEFAULT_NPC_AUTOFILL_MAX = 4`, `MAX_NPCS_PER_TABLE = 6`
  (hard cap), `AUTOFILL_INTERVAL = 15` (seconds).
- `__init__`: `self.npc_min` / `self.npc_max` (defaults) and `self._last_autofill = {}`
  (game_id → timestamp).
- `_load_npc_limits()` reads `settings`, clamps to `[0, MAX_NPCS_PER_TABLE]` with
  `min <= max`; called from `_load_games_from_db()` (`casino.py:272`) next to
  `_ensure_npc_roster()`.
- Refactor the NPC-spawn body of `_add_pending_bots` (`casino.py:372-429`) into
  `_spawn_npcs_into_game(game_id, count, exclude_personalities=None)` (roster via
  `_get_or_create_npcs`, build `LLMBlackjackNPC`/`SimpleBlackjackNPC`, set
  `current_game_id`, `game.join`); `_add_pending_bots` then calls it.
- `_autofill_npcs(game_id, game)` invoked from `_tick_games()` (`casino.py:722`):
  throttled by `AUTOFILL_INTERVAL` per game; acts only in `WAITING` / `BETWEEN_HANDS`;
  counts NPCs in `players + players_waiting`; spawns up to `npc_min` (bounded by
  `MAX_NPCS_PER_TABLE`) or trims down to `npc_max` (prefer `players_waiting`); marks dirty.
- Casino action `npc_limits {min?, max?}` → validate, persist via `set_setting`, update
  `self.npc_min/max`, reply `event_type:"npc_limits" {request_id, min, max, ok, message}`.
- Bot `/npclimits min:int=None max:int=None` (admin, request/response): no args = view,
  args = set.
- **Note:** with `npc_min > 0`, tables stay populated and the `EMPTY_GAME_TIMEOUT`
  (`casino.py:731`) won't reap them — this is the intended NPC-only ambient behavior, and
  overlaps conceptually with `ROADMAP.md` M6 (Autonomous World).
- Files: `cardgames/casino.py`, `bot.py`, `test.py`, `test_e2e.py`

**Verification:** Unit tests for limit clamping and `_autofill_npcs` count logic (fills to
min, trims to max, no-op mid-hand). E2E: `npc_limits` set→view; set a min then create a
game and poll (`games` table / `get_debug`) until NPC count reaches min.

---

## AM4: Manual NPC Add/Remove Commands

**Depends on:** AM3 (shares `_spawn_npcs_into_game`).

**Goal:** Admins add or remove NPCs from the current channel's game on demand.

**Changes:**
- Server: refactor `add_npc` (`casino.py:533`) to add `count` NPCs drawn from the roster
  via `_spawn_npcs_into_game` (instead of ad-hoc, un-persisted NPCs); make `remove_npc`
  accept an optional name (`None` → remove one NPC, preferring `players_waiting`); update
  the `npc_action` dispatch (`casino.py:694-703`) for `count` / optional `name`.
- Bot (admin-gated, fire-and-forget targeting the channel's game via
  `find_game_by_interaction`, like `stop_game` at `bot.py:528`; join/leave already announced
  in-channel via `game.output`):
  - `/addnpc count:int=1` → `npc_action`/`add_npc` with `game_id`, `count` (respect
    `MAX_NPCS_PER_TABLE` server-side)
  - `/removenpc name:str=None` → `npc_action`/`remove_npc` with `game_id`, `name`
- Files: `cardgames/casino.py`, `bot.py`, `test_e2e.py`

**Verification:** E2E `/addnpc` grows the NPC count in a game; `/removenpc` by name and the
arbitrary (no-name) variant.

---

## Cross-Cutting: Docs to Update Per Milestone

When **implementing** each milestone, update docs in the same change (per project
convention — grep `*.md` for the changed concept before declaring done):
- `CLAUDE.md` — new `settings` table; new casino_actions (`npc_limits`, `lookup_wallet`,
  `set_wallet`, `npc_action` add/remove) and `casino_update` responses; the new admin
  command list; auto-fill behavior and its interaction with `EMPTY_GAME_TIMEOUT`.
- `README.md` — admin command reference (`/addnpc`, `/removenpc`, `/npclimits`,
  `/checkwallet`, `/setwallet`, `/givechips`).
- `QA.md` — manual flows for NPC limits/auto-fill and wallet edits.

Per repo conventions: small focused commits, run tests before each commit, activate
`.venv`, and run `python test.py` + `./run-e2e-tests.sh` for milestones with e2e coverage.

---

## Dependency Order

```
AM1 (settings + wallet DB helpers)
├── AM2 (wallet inspection & editing)   ← after AM1
└── AM3 (NPC limits + table auto-fill)  ← after AM1
    └── AM4 (manual NPC add/remove)     ← after AM3 (shares _spawn_npcs_into_game)
```

AM1 is the prerequisite for everything. AM2 and AM3 can proceed in parallel after AM1.
AM4 follows AM3 because it reuses the `_spawn_npcs_into_game` refactor.

---

## Follow-ups (not yet scoped)

- `/kick <player>` — remove a human from a table (admin).
- `/resetwallet target` — reset a wallet to the default $200.
- `/npcroster` — inspector listing the full persistent NPC roster with wallets.
- Per-channel (rather than global) NPC limits.
- Audit logging of admin wallet edits to a dedicated table for traceability.
