#!/usr/bin/env python3
"""Operator tool: stand up (or tear down) a headless, NPC-only ambient blackjack table.

Publishes the same casino_action wire messages the Discord bot would (see
CLAUDE.md's "Casino Protocol"), but without a guild_id/channel_id -- so nothing
gets posted to Discord. Intended for measuring the LLM cost of running
SaloonBot's ambient (NPC-only) tables over a long period; see
llm_cost_report.py for turning what accumulates into a $ report.

Note: NPC autofill limits (npc_min/npc_max) are casino-wide, not per-table --
setting them here affects every game the target server manages. Run this
against a server with no other active games for a clean measurement.

Usage:
    python start_ambient_table.py --min 3 --max 5
    python start_ambient_table.py --teardown --game-id <id>
"""
import argparse
import json
import logging
import os
import time
import uuid

import redis

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))

RESPONSE_TIMEOUT = 10.0  # seconds to wait for a casino_update reply

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


def _publish(r, message):
    r.publish("casino", json.dumps(message))


def _await_response(pubsub, event_type, request_id, timeout=RESPONSE_TIMEOUT):
    """Block until a casino_update message with the given event_type/request_id arrives."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        message = pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
        if not message:
            continue
        data = json.loads(message['data'])
        if data.get('event_type') == event_type and data.get('request_id') == request_id:
            return data
    return None


def set_npc_limits(r, pubsub, min_val, max_val):
    request_id = str(uuid.uuid4())
    _publish(r, {
        'event_type': 'casino_action',
        'action': 'npc_limits',
        'request_id': request_id,
        'min': min_val,
        'max': max_val,
    })
    response = _await_response(pubsub, 'npc_limits', request_id)
    if response is None:
        raise SystemExit("Timed out waiting for npc_limits response.")
    if not response.get('ok'):
        raise SystemExit(f"npc_limits rejected: {response.get('message')}")
    logging.info(response.get('message') or f"NPC limits set: min={response['min']}, max={response['max']}")
    return response


def create_headless_game(r, pubsub):
    request_id = str(uuid.uuid4())
    _publish(r, {
        'event_type': 'casino_action',
        'action': 'new_game',
        'request_id': request_id,
        # No guild_id/channel_id: headless, nothing posts to Discord.
    })
    response = _await_response(pubsub, 'new_game', request_id)
    if response is None:
        raise SystemExit("Timed out waiting for new_game response.")
    game_id = response.get('game_id')
    logging.info(f"Headless ambient game created: {game_id}")
    return game_id


def teardown(r, pubsub, game_id):
    # Stop autofill from replacing anyone else first...
    set_npc_limits(r, pubsub, 0, 0)
    # ...then end the table and refund any unresolved bets.
    _publish(r, {
        'event_type': 'casino_action',
        'action': 'stop_game',
        'game_id': game_id,
    })
    logging.info(f"Sent stop_game for {game_id}. NPC autofill limits set to 0/0.")


def main():
    parser = argparse.ArgumentParser(
        description="Stand up or tear down a headless, NPC-only ambient blackjack table."
    )
    parser.add_argument("--min", type=int, default=3, help="npc_autofill min (default: 3)")
    parser.add_argument("--max", type=int, default=5, help="npc_autofill max (default: 5)")
    parser.add_argument("--teardown", action="store_true",
                        help="Tear down an existing measurement table instead of creating one.")
    parser.add_argument("--game-id", help="Game id to tear down (required with --teardown).")
    parser.add_argument("--redis-host", default=REDIS_HOST)
    parser.add_argument("--redis-port", type=int, default=REDIS_PORT)
    args = parser.parse_args()

    if args.teardown and not args.game_id:
        parser.error("--teardown requires --game-id")
    if not args.teardown and args.min > args.max:
        parser.error("--min cannot exceed --max")

    r = redis.Redis(host=args.redis_host, port=args.redis_port)
    pubsub = r.pubsub()
    pubsub.subscribe("casino_update")

    if args.teardown:
        teardown(r, pubsub, args.game_id)
        return

    set_npc_limits(r, pubsub, args.min, args.max)
    game_id = create_headless_game(r, pubsub)
    logging.info(
        f"Ambient table running headless. NPCs will auto-fill to {args.min}-{args.max} seats "
        f"within ~15s. Check accumulated cost with llm_cost_report.py. Tear down later with: "
        f"python start_ambient_table.py --teardown --game-id {game_id}"
    )


if __name__ == "__main__":
    main()
