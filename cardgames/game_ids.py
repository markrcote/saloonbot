"""Memorable game IDs: Old West themed adjective-noun pairs like ``dusty-saloon``."""
import random

# Lowercase a-z only and hyphen-free: IDs end up in Redis topic names
# (``game_updates_{game_id}``) and Discord messages, and the hyphen is the separator.
ADJECTIVES = [
    "barren", "bitter", "blazing", "bold", "brazen", "cunning", "copper", "crooked",
    "dead", "drifting", "dusty", "feisty", "gilded", "golden", "gritty", "grizzled",
    "hardscrabble", "hollow", "howling", "iron", "lonesome", "lucky", "midnight", "ornery",
    "parched", "ragged", "restless", "rowdy", "rusty", "salty", "scarlet", "shady",
    "silver", "sly", "stormy", "sunburnt", "tumbling", "wandering", "weary", "wild",
]

NOUNS = [
    "bandit", "bluff", "bounty", "buckle", "cactus", "canyon", "cattle", "corral",
    "coyote", "creek", "depot", "drifter", "gambler", "gulch", "holster", "homestead",
    "jackpot", "lasso", "marshal", "mesa", "mirage", "mustang", "nugget", "outlaw",
    "posse", "prairie", "railroad", "ranch", "rattler", "ridge", "saddle", "saloon",
    "sheriff", "showdown", "spur", "stagecoach", "stallion", "tumbleweed", "wagon", "wrangler",
]

# Bare adjective-noun pairs to try before falling back to a numeric suffix.
PLAIN_ATTEMPTS = 20


def _random_pair():
    return f"{random.choice(ADJECTIVES)}-{random.choice(NOUNS)}"


def generate_game_id(exists):
    """Return a fresh game ID that ``exists(candidate)`` reports as unused.

    Tries plain ``adjective-noun`` pairs first. If they keep colliding (the word space is
    only a couple of thousand pairs), falls back to ``adjective-noun-N`` and widens the
    range of N as needed, so it always terminates.
    """
    for _ in range(PLAIN_ATTEMPTS):
        candidate = _random_pair()
        if not exists(candidate):
            return candidate

    upper = 100
    while True:
        for _ in range(PLAIN_ATTEMPTS):
            candidate = f"{_random_pair()}-{random.randrange(2, upper)}"
            if not exists(candidate):
                return candidate
        upper *= 10
