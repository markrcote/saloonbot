# discord_wwnames

[![Lint and test](https://github.com/markrcote/discord_wwnames/actions/workflows/lint-and-test.yml/badge.svg)](https://github.com/markrcote/discord_wwnames/actions/workflows/lint-and-test.yml)

Discord bot originally built for randomly generating Old West names and now wandering off into card games.

Names were scraped from [Mithril and Mages](https://www.mithrilandmages.com/utilities/WesternBrowse.php).

## Commands

### Names

* `/wwname [gender] [number]`: Generates `number` Old West names by choosing a random first name of the given `gender` and a random surname.  The `gender` argument accepts any string starting with `f` or `m`.  If no `gender` is given, a random one is chosen. If not provided, `number` defaults to 1. The output is a newline-joined list of names in the form of `<gender emoji> first_name last_name`.

### Cards

* `/newgame` starts a new game of blackjack.  Commands (hit, stand, etc.) are read
  from messages.

### Metadata

* `/version`: Outputs the current git sha.

## Tests

To run tests, run `python test.py`.
