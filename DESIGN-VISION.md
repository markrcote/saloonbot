# Design Vision

Decisions and refinements to [VISION.md](VISION.md).

---

## Opening / influences

**Current text:** *(kept mostly as-is — strongest part of the draft)*

**Decisions:**
- Fix typo: "emergent and stories" → "emergent stories"
- Remove one instance of "cozy" to reduce redundancy
- When writing final VISION.md, move the setting paragraph to follow the influences section

---

## Setting

**Current text:** *(mentioned only in the title "Saloonbot" and implicitly in influences)*

**Issue:** The Old West setting is central to the experience but absent from the vision.

**Decisions:**
- Setting is American frontier, late 19th century
- Constrains aesthetics (names, language, table talk) and NPC story generation (backstories, events, relationships must be era-appropriate)
- The saloon has a name and identity; ships with strong defaults but is configurable (name, town, flavor)

**Replacement text:**
> The setting is the American frontier, late 19th century. The saloon has a name, a reputation, and a cast of regulars who talk, dress, and live like they belong there. Names are period-appropriate, stories are era-grounded, and the table talk sounds like it. The setting ships with strong defaults but can be configured — a different name, a different town, a different flavor of the same dust and whiskey.

---

## Emergent stories

**Current text:** *(one clause in the simulator paragraph, no detail)*

**Issue:** This is the most distinctive part of the vision and gets the least space.

**Decisions:**
- NPC stories are surfaced at varying levels — some blatant, some subtle; players can infer from behavior changes
- NPCs are generated with a backstory and NPC-NPC relationships on creation (procedural); NPC-NPC relationships also evolve through game interactions
- PC-NPC relationships come only from game interactions; PCs are strangers to an NPC until they share a table
- Fame is mechanical, not just flavor: a notorious player gets a different game from sharp-eyed regulars than an unknown would

**Replacement text:**
> NPCs have lives beyond the table. Each one is generated with a backstory and relationships to other regulars — old friends, rivals, strangers with history. Random events shape them over time, drawing some to the tables more and pushing others away. They form opinions of each other through play, and they'll form opinions of you too. Show up enough, win enough, and word gets around; a notorious player won't get the same game from a sharp-eyed regular as an unknown one would.

---

## Closing paragraph

**Current text:**
> Concretely, Saloonbot is a server with multiple interfaces, such as Discord and local command line.
>
> Games have admins, who can modify options such as minimum and maximum number of PCs & NPCs, level of NPC activity, etc.

**Issue:** The admin sentence reads as a feature spec, not vision. The interfaces line doesn't explain why Discord fits.

**Options under consideration:**
1. Cut the admin sentence; expand the interfaces line to say why Discord fits (persistent community, public tables, social layer).
2. Reframe admin controls around the experience they enable — e.g., a server owner can tune how lively the saloon feels, from a quiet afternoon to a packed Friday night.
3. Replace both sentences with something about world persistence — the saloon runs whether or not anyone's playing, NPCs keep their habits and history, players drop in and out.

**Decision:** Option 3 — replace both sentences with world-persistence framing. Mention Discord/CLI as examples of access points, not implementation detail. Player-as-visitor (drops in, leaves) is primary; player-as-regular (accumulates history) is a future direction.

**Replacement text:**
> The saloon never closes. NPCs keep their habits and their histories whether anyone's at the table or not. Players can pull up a chair — from Discord, the command line, or wherever else — drop into whatever's happening, and leave when they're done. The world doesn't wait for them, and it doesn't stop when they go.
