#!/usr/bin/env python3
"""Operator tool: follow a game's table talk on stdout, like watching it in Discord.

Subscribes to a game's `game_updates_<id>` Redis topic and prints each message's
text as it arrives, tinted to match the embed colours bot.py uses. Read-only: it
never sends an action, so it can't affect the game. Game updates are live pub/sub
with no history, so only what happens after it connects is shown. Exits when the
game ends (`game_over`) or on Ctrl-C.

The classification below mirrors the branches in bot.py's message handler; keep
the two in step when a message type is added or reworded.

Usage:
    python watch_game.py --game-id dusty-saloon
    REDIS_HOST=localhost python watch_game.py --game-id dusty-saloon   # e.g. via an SSH tunnel
"""
import argparse
import json
import os
import sys

import redis

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))

POLL_TIMEOUT = 1.0  # seconds to block per pubsub poll, so Ctrl-C stays responsive

# Embed colours from bot.py.
SEPIA = 0xc8a96e
GOLD = 0xffd700
RED = 0xff0000
ROYAL_BLUE = 0x4169e1
PURPLE = 0x9370db
ORANGE = 0xff8c00


def classify(text):
    """Return (message_type, embed_colour_or_None) for a game update, as bot.py would."""
    if text.startswith("🤠") and ': "' in text:
        return "npc_quip", SEPIA
    if "🏆 strikes gold" in text:
        return "win", GOLD
    if "💥" in text and ("bust" in text.lower() or "lost" in text.lower()):
        return "bust", RED
    if "✨ ~*~ The dust settles" in text:
        return "hand_result", ROYAL_BLUE
    if "🃏 The dealer shuffles" in text:
        return "new_hand", PURPLE
    if "💰 Ante up" in text:
        return "bet_prompt", ORANGE
    if "🔄 Dealer flips" in text:
        return "dealer_reveal", None
    return "game_event", None


def format_line(text, use_colour):
    """The text as it should print: coloured for embed-style messages, plain otherwise."""
    _, colour = classify(text)
    if not use_colour or colour is None:
        return text
    r, g, b = (colour >> 16) & 0xff, (colour >> 8) & 0xff, colour & 0xff
    return f"\x1b[38;2;{r};{g};{b}m{text}\x1b[0m"


def watch(pubsub, out, use_colour):
    """Print updates until the game ends. `pubsub` must already be subscribed to the game topic."""
    while True:
        message = pubsub.get_message(ignore_subscribe_messages=True, timeout=POLL_TIMEOUT)
        if not message:
            continue
        data = json.loads(message['data'])
        if data.get('event_type') == 'game_over':
            print("-- game over --", file=out, flush=True)
            return
        text = data.get('text')
        if text:
            print(format_line(text, use_colour), file=out, flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Follow a game's table talk on stdout.")
    parser.add_argument("--game-id", required=True)
    parser.add_argument("--redis-host", default=REDIS_HOST)
    parser.add_argument("--redis-port", type=int, default=REDIS_PORT)
    args = parser.parse_args(argv)

    r = redis.Redis(host=args.redis_host, port=args.redis_port)
    try:
        r.ping()
    except redis.ConnectionError as e:
        print(f"Can't reach Redis at {args.redis_host}:{args.redis_port}: {e}", file=sys.stderr)
        return 1

    pubsub = r.pubsub()
    pubsub.subscribe(f"game_updates_{args.game_id}")
    use_colour = sys.stdout.isatty() and 'NO_COLOR' not in os.environ
    try:
        watch(pubsub, sys.stdout, use_colour)
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == '__main__':
    sys.exit(main())
