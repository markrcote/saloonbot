# Manual QA Checklist

Covers the main flows end-to-end. Aim: **under 5 minutes** total.

## Setup (do once)

```bash
# Terminal A – Redis
./dev-redis.sh

# Terminal B – server
export REDIS_HOST=localhost REDIS_PORT=6379 USE_SQLITE=1 SALOONBOT_DEBUG=1 ANTHROPIC_API_KEY=<your-key>
# No API key handy? export LLM_PROVIDER=fake instead — bots run the full LLM
# path (quips, session memories) with canned deterministic responses.
source .venv/bin/activate && python server.py

# Terminal C – CLI
export REDIS_HOST=localhost REDIS_PORT=6379
source .venv/bin/activate
```

---

## Run 1 — Solo game, full hand (~1 min)

```
python cli.py   # name: Alice, bots: 0
```

- [ ] "Joined game" then "💰 Ante up, folks!" with wallet shown
- [ ] `bet 10` → bet confirmed, cards dealt, "👉 Alice, you're up..."
- [ ] `hit` or `stand` → hand resolves, wallet updates, returns to WAITING
- [ ] `quit`

---

## Run 2 — LLM bot game, full hand (~2 min)

```
python cli.py   # name: Bob, bots: 1
```

- [ ] Bot personality name logged in server; "🎭 New arrivals: \<emoji\> \<Name\>" in CLI
- [ ] Betting phase opens for both Bob and the bot
- [ ] Wait ~10 s — bot auto-bets ("💵 \<Name\> throws $X on the table") with optional quip
- [ ] `bet 10` → cards dealt
- [ ] `stand` → bot takes its turn within ~10 s, hits or stands, quip appears
- [ ] Hand resolves; both wallets updated
- [ ] `quit`

---

## Run 3 — Two bots, `addnpc`, `removenpc` (~1.5 min)

```
python cli.py   # name: Carol, bots: 2
```

- [ ] Two distinct bots join, distinct personality names in server log
- [ ] Both auto-bet; `bet 10` triggers card deal
- [ ] `stand` → both bots act in turn order; hand resolves

```
python cli.py   # name: Dave, bots: 0
```

- [ ] After joining: `addnpc 1` → roster NPC joins and announces in-channel
- [ ] NPC auto-bets and plays; `quit` after hand resolves
- [ ] `addnpc 2` → two more NPCs join; `removenpc` (no name) → one NPC leaves (no crash)
- [ ] Relationships: `sqlite3 saloonbot.db "SELECT * FROM npc_relationships"` shows rows with non-empty notes (~70% of new NPCs have some); after a removenpc with a related NPC still seated, server log shows `strength X -> Y`. In Discord, `/npcrelationships <name>` lists them.
- [ ] PC–NPC memory: after `quit` and rejoining with the same NPC still on the roster (`addnpc` again), `sqlite3 saloonbot.db "SELECT * FROM pc_npc_relationships"` shows a row for Dave with `times_met=1` and a non-empty `npc_notes_on_player`; after a second session, `times_met=2` and the note has changed.

---

## Run 4 — LLM fallback on bad key (~30 s)

Stop server, then:

```bash
export LLM_TIMEOUT=0.001
source .venv/bin/activate && python server.py
```

```
python cli.py   # name: Eve, bots: 1
```

- [ ] Server log shows LLM timeout warning for bot's action
- [ ] Bot still acts (basic strategy fallback); game completes without hang
- [ ] `curl localhost:9400/metrics` shows `saloonbot_llm_calls_total` and `saloonbot_llm_provider_up` series (check via Discord `/debug` too, if available: LLM Health section reflects the fallback)
- [ ] Restore: `unset LLM_TIMEOUT`, restart server

---

## Pass criteria

| Run | Must pass |
|-----|-----------|
| 1 | Solo game completes end-to-end |
| 2 | LLM bot auto-bets, plays, quips |
| 3 | Multi-bot distinct personalities; addnpc/removenpc work |
| 4 | LLM timeout falls back gracefully; no crash; `/metrics` shows LLM series |
