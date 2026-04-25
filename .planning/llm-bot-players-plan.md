# Plan: LLM-Powered Bot Players with Wild West Personalities

## Context

SaloonBot's blackjack game currently supports human players and a rule-based SimpleBlackjackNPC.
The goal is to add bot players with Wild West personalities that use an LLM to make actual
gameplay decisions (hit/stand/bet) AND generate in-character quips, making games playable solo
or with fewer humans. Players choose how many bots (0–4) when starting a game via `/newgame`.

**Key design decisions (user confirmed):**
- LLM provider is configurable (Claude primary, OpenAI secondary) via env var
- LLM makes actual gameplay decisions + generates quips (not just flavor on top of basic strategy)
- Fallback to basic strategy on LLM timeout/error
- Personality pool: ~90% archetypes, ~10% (1 in 10–20) named historical figures
- Quips appear inline in the game feed channel

---

## Architecture Overview

```
LLMBlackjackNPC.decide_action()
   ↓ submits to ThreadPoolExecutor (non-blocking)
   → returns None on first tick (still thinking)
   → returns "hit"/"stand" + sets self.last_quip when done

blackjack._tick_playing()
   ↓ if None: skip this tick (player stays current)
   ↓ if "hit"/"stand": take action, then check player.last_quip
   → self.output(f"🤠 {player.name}: \"{quip}\"")

casino.game_output() → Redis game_updates_{game_id} → bot.py renders quip embed
```

The server.py loop is synchronous. LLM calls run in per-NPC thread pools so the game loop
never blocks. Decisions are eventually consistent across ticks (~2s).

---

## Milestone 1: LLM Infrastructure + NPC Class

### New files

**`cardgames/llm_client.py`**
- Abstract `LLMClient` with `complete(system: str, user: str, timeout: float) -> str`
- `ClaudeClient(LLMClient)` using `anthropic` SDK, model `claude-haiku-4-5-20251001` by default
- `OpenAIClient(LLMClient)` using `openai` SDK, model `gpt-4o-mini` by default
- `create_llm_client() -> LLMClient` factory reading `LLM_PROVIDER` env var (default: `"claude"`)
- Both clients accept model override via env var (`LLM_MODEL`)
- Both raise a shared `LLMError` on API failure

**`cardgames/personalities.py`**
- `Personality` dataclass: `name`, `is_famous`, `system_prompt`, `emoji`, `betting_style`
  (`"conservative"` | `"moderate"` | `"reckless"`)
- `PersonalityRegistry` with `get_random() -> Personality`, weighted: 1 famous per 20 draws
- Placeholder with 2 archetypes + 1 historical figure (expanded in M2)
- `get_personality(name: str) -> Personality` for lookup by name (needed for deserialization)

**`cardgames/llm_npc.py`**
- `LLMBlackjackNPC(NPCPlayer)`
- Constructor: `(name, personality: Personality, llm_client: LLMClient)`
- `last_quip: str | None = None` attribute
- `_executor = ThreadPoolExecutor(max_workers=1)` per instance
- `_pending_action_future = None`, `_pending_bet_future = None`
- `decide_action(hand, dealer_visible_card, score) -> str | None`:
  - No pending future → submit `_llm_decide_action()` to executor → return `None`
  - Future not done → return `None`
  - Future done → extract result, set `self.last_quip`, clear future, return action
  - On exception in future → log warning, fall back to `SimpleBlackjackNPC` strategy
- `decide_bet(min_bet, max_bet, wallet) -> int | None`: same non-blocking pattern
- `_llm_decide_action(hand, dealer_visible_card, score) -> dict`:
  - Calls `llm_client.complete()` with structured prompt returning `{"action": "...", "quip": "..."}`
  - Parses JSON; on parse failure or invalid action, falls back to simple strategy
  - Timeout: 5 seconds
- `_llm_decide_bet(min_bet, max_bet, wallet) -> dict`: similar, returns `{"amount": int, "quip": str}`

### Modified files

**`cardgames/blackjack.py`**
- `serialize_player(player)`: add `"is_npc"`, `"npc_type"`, `"npc_personality"` fields
  (npc_type/personality are `None` for human players)
- `deserialize_player(data)`: if `is_npc`, reconstruct the appropriate NPC class
  using `NPC_TYPES` registry (imported lazily to avoid circular imports)
- `_tick_playing()`: if `decide_action()` returns `None`, return early (skip this tick).
  After a non-None action, check `getattr(player, 'last_quip', None)` and call
  `self.output(f"🤠 {player.name}: \"{player.last_quip}\"")` then clear it.
- `_tick_betting()`: same `None`-guard for `decide_bet()` return value

**`cardgames/casino.py`**
- Import `LLMBlackjackNPC` and `create_llm_client`
- Add `'llm': LLMBlackjackNPC` to `NPC_TYPES`
- Casino constructor: call `create_llm_client()` and store as `self.llm_client`
- `new_game(guild_id, channel_id, num_bots=0)`: after creating the game, loop
  `num_bots` times, pick a random personality, create `LLMBlackjackNPC`, call
  `game.join(npc)` directly (bypassing Redis)

**`server.py`** — pass `num_bots` from Redis message data to `casino.new_game()`

**`requirements.txt`** — add `anthropic` and `openai`

### New env vars (document in CLAUDE.md)
| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_PROVIDER` | `claude` | `claude` or `openai` |
| `ANTHROPIC_API_KEY` | — | Required if provider is `claude` |
| `OPENAI_API_KEY` | — | Required if provider is `openai` |
| `LLM_MODEL` | provider default | Override LLM model name |
| `LLM_TIMEOUT` | `5` | Seconds before falling back to basic strategy |

### Verification
- `python test.py` passes
- Start a game locally, send `npc_action add_npc` with `npc_type: "llm"` via `cli.py`
- Confirm NPC takes real turns, quip appears in output
- Kill and restart server; verify LLM NPC is restored with correct personality

---

## Milestone 2: Personality Library

### Modified file: `cardgames/personalities.py`

Expand to the full personality set:

**Archetypes (~15):**
- The Grizzled Prospector — paranoid, hoards chips, suspicious of everyone
- The Drunk Cowboy — reckless bets, slurred boasts, occasionally folds on a good hand
- The Snake Oil Salesman — smooth-talking bluffer, inflates confidence before folding
- The Prim Schoolmarm — prim and proper, quietly ruthless, disapproves of the dealer
- The Bounty Hunter — cold, calculating, speaks in short sentences, bets to intimidate
- The Frontier Preacher — invokes scripture on every bet, believes luck is divine will
- The Railroad Baron — rich and arrogant, bets big to humiliate rather than win
- The Half-Broke Drifter — always underfunded, surprisingly lucky, gallows-humored
- The Card Sharp — narrates strategy as if teaching a class, condescending
- The Saloon Singer — dramatic, every hand is a performance
- The Greenhorn Deputy — nervous, second-guesses every decision, apologizes a lot
- The Apache Tracker — speaks in metaphor, patient, rarely surprised
- The Patent Medicine Widow — claims tonics give her visions of the next card
- The Retired Outlaw — been around, seen it all, drops oblique references to past crimes
- The Railroad Cook — talks about food constantly, philosophy through food metaphors

**Historical figures (~4, each with weight 1/20):**
- Doc Holliday — dandy, dying of TB, nothing-to-lose gambler ("I'm your huckleberry")
- Calamity Jane — brash, profane, takes no nonsense from anyone
- Jesse James — charming outlaw, disarming until the moment he isn't
- Wild Bill Hickok — calm showman, dies looking at his cards

Each personality gets a ~150-word `system_prompt` covering: voice, vocabulary, attitude toward
winning/losing, betting temperament, signature phrases, and how they address other players.

**`PersonalityRegistry`** expanded:
- `get_random()` uses `random.choices()` with weights (famous=1, archetype=20 baseline)
- Ensures no duplicate personalities in the same game (casino passes in-use names)
- `get_all_names()` for admin/debug listing

### Verification
- Run personality sampling test: call `get_random()` 1000 times, confirm ~5% famous rate
- Start a 4-bot game; confirm 4 distinct personalities assigned
- Play a full hand; confirm each bot produces distinct voice in quips

---

## Milestone 3: Discord UX + End-to-End Polish

### Modified files

**`bot.py`**
- `/newgame` command: add `num_bots: int = 0` parameter (slash command option,
  range 0–4, description "How many bot players to add")
- Pass `num_bots` in the Redis `new_game` casino_action message
- Quip message detection: messages matching `^🤠 .+: "` get a warm sepia color
  (`0xc8a96e`) to visually distinguish them from game action text

**`cardgames/casino.py`**
- `_process_message()`: extract `num_bots` from `new_game` action data, pass to `casino.new_game()`

**`CLAUDE.md`** — add new env vars table entries for LLM config

**`compose.yml` / `compose.test.yml`** — add LLM env var passthrough (no new services needed)

### Verification
- `/newgame num_bots:2` in Discord → game starts with 2 bots
- Bots place bets, take turns, quips appear inline in sepia color
- `/newgame` with no argument → game starts with no bots (backward compatible)
- `./run-e2e-tests.sh` passes (e2e tests use `num_bots=0` to avoid LLM calls in CI;
  add a note in test comments about this)
- Restart server mid-game; bots resume with correct personalities

---

## Critical files to modify (summary)

| File | Change |
|------|--------|
| `cardgames/blackjack.py` | None-guard in tick loops; quip publishing; NPC serialization |
| `cardgames/casino.py` | LLM client init; num_bots in new_game; NPC_TYPES entry |
| `cardgames/npc_player.py` | Allow `decide_action`/`decide_bet` to return `None` (update docstring) |
| `bot.py` | `num_bots` param on `/newgame`; quip embed color |
| `server.py` | Thread `num_bots` through to casino |
| `requirements.txt` | `anthropic`, `openai` |
| `CLAUDE.md` | New env vars |

## New files to create (summary)

| File | Purpose |
|------|---------|
| `cardgames/llm_client.py` | Provider-agnostic LLM abstraction |
| `cardgames/personalities.py` | Personality dataclass + full registry |
| `cardgames/llm_npc.py` | `LLMBlackjackNPC` implementation |
