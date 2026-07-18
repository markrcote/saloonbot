# Changelog

Notable changes to SaloonBot, for players and server admins. Dates are when each change shipped.

## 2026-07-09 — NPCs rebuild their stakes

- NPCs who go broke and leave the table now slowly earn back their stake between sessions, instead of staying poor forever. Well-off personalities recover faster than drifters.
- Fixed a bug where a broke NPC could get stuck showing as "still in a game," which kept it from being picked for future tables.

## 2026-06-19 — Admin toolkit expansion

- `/quitgame` force-ends a game and returns any unresolved bets to players (`/stopgame` still ends a game immediately without refunds).
- `/checkwallet`, `/setwallet`, and `/givechips` let admins inspect and adjust any player's or NPC's wallet by name.
- `/npclimits` sets how many NPCs auto-fill a table; `/addnpc` and `/removenpc` manage them directly.

## 2026-06-08 — Admin safeguards & diagnostics

- `/newgame`, `/stopgame`, and `/usage` are now restricted to server administrators.
- New `/debug` (admin) dumps internal game state for troubleshooting.
- New `/wad` lets any player privately check their own balance.

## 2026-06-06 — Player stats & fame

- New `/stats` shows your games and hands played, and how much you've won or lost.
- NPCs now recognize strangers, regulars, and notorious high rollers, and their banter shifts accordingly.

## 2026-06-01 — Saloon identity

- The saloon now has a name and a home town, and NPCs reference where they are in their chatter.
- New `/saloon` shows the saloon's name, town, and which tables are active.
- New `/usage` (admin) tracks LLM token usage for the AI-powered NPCs.

## 2026-05-31 — Persistent NPCs

- NPC players are no longer regenerated from scratch every game. The same named NPCs — with the same backstories — return across sessions, so regulars start to feel like regulars.
