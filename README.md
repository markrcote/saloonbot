# discord_wwnames

![Lint and test](https://github.com/markrcote/discord_wwnames/actions/workflows/lint-and-test.yml/badge.svg)

Discord bot for randomly generating Old West names. Names were scraped from [Mithril and Mages](https://www.mithrilandmages.com/utilities/WesternBrowse.php).

Provides these commands:

* `/wwname [gender]`: Generates an Old West name by choosing a random first name of the given gender and a random surname.  The `gender` argument accepts any string starting with `f` or `m`.  If no `gender` is given, a random one is chosen. The output is in the form of `<gender emoji> first_name last_name`.

To run tests, run `python test.py`.
