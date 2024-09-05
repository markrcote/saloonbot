# discord_wwnames

[![Lint and test](https://github.com/markrcote/discord_wwnames/actions/workflows/lint-and-test.yml/badge.svg)](https://github.com/markrcote/discord_wwnames/actions/workflows/lint-and-test.yml)

Discord bot originally built for randomly generating Old West names and now wandering off into card games.

Names were scraped from [Mithril and Mages](https://www.mithrilandmages.com/utilities/WesternBrowse.php).

## Commands

### Names

* `/wwname [gender] [number]`: Generates `number` Old West names by choosing a random first name of the given `gender` and a random surname.  The `gender` argument accepts any string starting with `f` or `m`.  If no `gender` is given, a random one is chosen. If not provided, `number` defaults to 1. The output is a newline-joined list of names in the form of `<gender emoji> first_name last_name`.

### Cards

The now badly names `wwnames` app provides an ultra-basic platform for card games.

A card game has a deck with 52 cards (no jokers atm).  These cards all start out in the deck.
A player is registered with the game when they are first dealt a hand.  After that, they are
(currently) always a player and will be affected by any commands involving all players.

* `/deal [player] [number]`: Registers `player` if not already registered.  Deals `number`
cards to `player`.  `number` defaults to 1 and `player` defaults to the current user.
* `/deal_all [number]`: Deals `number` cards to each registered player.
* `/discard <card value> <card suit> [player]`: Returns the indicated card to the deck from `player`'s hand.  `player` defaults to the current user.
* `/discard_all [player]`: Discards all cards from `player`, defaulting to the current user.
* `/show_hand [player] [short]`: Prints out (to everyone) the contents of `player`'s hand, defaulting to the current user.  `short` is a boolean value indicating whether to display a shortened version, defaulting to `False`.
* `/shuffle_deck`: Shuffles the deck.  Does **not** discard any cards from players' hands.

### Metadata

* `/wwname_version`: Outputs the current git sha.

## Tests

To run tests, run `python test.py`.
