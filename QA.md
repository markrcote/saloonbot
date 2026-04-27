# Manual QA: LLM Bot Players (M1a–M1e)

## Prerequisites

```bash
# Terminal A – infrastructure
./dev-redis.sh

# Terminal B – server
export REDIS_HOST=localhost REDIS_PORT=6379 SALOONBOT_DEBUG=1
export MYSQL_HOST=localhost MYSQL_PORT=3306
export MYSQL_USER=saloonbot MYSQL_PASSWORD=saloonbot_password MYSQL_DATABASE=saloonbot
export ANTHROPIC_API_KEY=<your-key>
source venv/bin/activate && python server.py

# Terminal C – CLI (used for all tests below)
export REDIS_HOST=localhost REDIS_PORT=6379
export ANTHROPIC_API_KEY=<your-key>
source venv/bin/activate
```

---

## Test 1 — Regression: no-bot game still works

1. `python cli.py`
2. Name: `Alice`, bots: `0`
3. **Expect:** "Joined game", then immediately "💰 Ante up, folks!" and wallet info
4. Type `bet 10`
5. **Expect:** bet confirmation, then cards dealt, "👉 Alice, you're up..."
6. Type `hit` or `stand`, play through to resolution
7. **Expect:** hand resolves normally, wallet updates, game returns to WAITING
8. Type `quit`

---

## Test 2 — LLM bot joins on human join (timing check)

1. `python cli.py`
2. Name: `Bob`, bots: `1`
3. **Expect in server log:** game created, then on join: bot personality name logged, "🪑 \<PersonalityName\> pulls up a chair"
4. **Expect in CLI output:** both the bot's join message AND Bob's join message appear before betting starts
5. **Expect:** "💰 Ante up, folks!" shows wallet for both Bob and the bot

> Key check: the bot is NOT in the game before Bob joins — betting should only start after Bob's `join` is processed.

---

## Test 3 — LLM bot bets automatically

Continuing from Test 2 (or start a new 1-bot game):

1. After "Ante up!", wait up to ~10 seconds without typing anything
2. **Expect:** bot places a bet automatically — "💵 \<BotName\> throws $X on the table"
3. **Expect:** bot may emit a quip — "🤠 \<BotName\>: \"...\""
4. After bot bets, type `bet 10` yourself
5. **Expect:** cards are dealt immediately after all bets are in

---

## Test 4 — LLM bot plays its turn

Continuing from Test 3:

1. After cards are dealt, wait for your turn (you go first as the human)
2. Type `stand` to pass quickly
3. **Expect:** bot's turn starts; within ~5–10 seconds the bot hits or stands
4. **Expect:** a quip appears — "🤠 \<BotName\>: \"...\""
5. **Expect:** dealer plays, hand resolves, wallet updates for both you and the bot

---

## Test 5 — Multiple bots (2)

1. `python cli.py`
2. Name: `Carol`, bots: `2`
3. **Expect:** TWO bots join when Carol joins — two "pulls up a chair" messages
4. **Expect:** both bots have distinct personality names (check server logs)
5. Play through a full hand, verify both bots act in turn order

---

## Test 6 — `addnpc` CLI command with `llm` type

1. `python cli.py`, name: `Dave`, bots: `0`
2. After joining: type `addnpc "Whiskey Pete" llm`
3. **Expect:** "🪑 Whiskey Pete pulls up a chair" with a random personality assigned
4. Betting starts when tick fires; Whiskey Pete should auto-bet
5. **Expect:** quip from Pete during betting or play

---

## Test 7 — LLM fallback on timeout/bad key

1. Stop the server, set `LLM_TIMEOUT=0.001` (near-zero timeout), restart server
2. `python cli.py`, name: `Eve`, bots: `1`
3. Play through — the bot should still act (fallback to basic strategy)
4. **Expect:** server log shows "LLM action decision failed for \<name\>: ..." warning
5. **Expect:** game continues normally — no hang, no crash
6. Restore `LLM_TIMEOUT` to default

---

## Test 8 — Server restart with active bot game

1. Start a game with 1 bot, get through betting so cards are dealt (PLAYING state)
2. Kill the server (`Ctrl+C` in Terminal B)
3. Restart server (`python server.py`)
4. **Expect server log:** "Restored game \<id\> in state playing"
5. **Expect:** bot resumes with the same personality name (check server log or wait for its action)
6. In CLI, type `stand` to take your turn
7. **Expect:** bot takes its turn normally; hand resolves

---

## Test 9 — LLM unavailable at startup

1. Stop server, **unset** `ANTHROPIC_API_KEY`, restart server
2. **Expect server log:** "Could not initialize LLM client: ... LLM bot players disabled."
3. `python cli.py`, name: `Frank`, bots: `2`
4. **Expect server log:** "num_bots requested but LLM client is not available."
5. **Expect:** Frank joins, no bots appear — game waits for Frank alone
6. Re-set `ANTHROPIC_API_KEY` and restart server when done

---

## Test 10 — `addnpc` with unknown type returns error

1. In an active CLI session, type `addnpc Villain badtype`
2. **Expect:** error message in CLI output: "Unknown NPC type 'badtype'. Available: simple, llm"
3. Game should continue normally

---

## Pass criteria summary

| # | What to verify |
|---|---------------|
| 1 | No-bot game plays end-to-end without errors |
| 2 | Bots only join after a human joins (no premature game start) |
| 3 | Bot auto-bets within the betting window; quip appears |
| 4 | Bot plays hit/stand; quip appears |
| 5 | Two bots get distinct personalities |
| 6 | `addnpc ... llm` assigns a random personality and plays correctly |
| 7 | LLM timeout falls back to basic strategy without crashing |
| 8 | Bot personality survives server restart |
| 9 | Server starts cleanly with no API key; bots gracefully disabled |
| 10 | Unknown NPC type returns a user-facing error |
