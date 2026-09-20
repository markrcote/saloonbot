#!/usr/bin/env python3
"""Operator tool: a staging-side dead-man switch for an ambient cost trial.

watch_ambient_cost.py (the runaway-spend watchdog) and start_ambient_table.py
--teardown both run on the operator's machine and reach staging's Redis through
an SSH tunnel, so if that machine or the tunnel dies mid-run nothing can stop the
table. This arms a one-shot systemd timer *on staging* that republishes the same
teardown (npc_limits 0/0, then stop_game) through the saloonbot-redis container
after a fixed time, independent of this machine.

It uses a system-level transient timer (passwordless sudo on the staging host)
rather than a user one: the staging user has no lingering systemd session, so a
user timer could be torn down when the last SSH session closes. Transient units
vanish on reboot; that is acceptable for a bounded trial.

Usage (set --hours a little beyond the watchdog's --max-hours):
    python deadman_teardown.py arm --game-id <id> --hours 13
    python deadman_teardown.py status
    python deadman_teardown.py disarm --game-id <id>   # after a normal teardown
"""
import argparse
import json
import re
import shlex
import subprocess
import sys

STAGING_HOST = 'saloonbot-staging'
REDIS_CONTAINER = 'saloonbot-redis'
UNIT_PREFIX = 'saloonbot-deadman-'
# Pause between the two publishes so the server applies npc_limits before stop_game.
SETTLE_SECONDS = 3

# Game IDs are lowercase words and hyphens (or UUIDs from older games); keep the
# check strict so the ID is safe in a systemd unit name and a shell command.
_GAME_ID_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9-]*$')


def validate_game_id(game_id):
    if not _GAME_ID_RE.match(game_id):
        raise ValueError(f"Unsafe game id: {game_id!r}")
    return game_id


def unit_name(game_id):
    return UNIT_PREFIX + validate_game_id(game_id)


def teardown_messages(game_id):
    """The same wire messages start_ambient_table.teardown() sends, in order."""
    return [
        {'event_type': 'casino_action', 'action': 'npc_limits',
         'request_id': 'deadman', 'min': 0, 'max': 0},
        {'event_type': 'casino_action', 'action': 'stop_game', 'game_id': validate_game_id(game_id)},
    ]


def remote_payload(game_id):
    """Shell script the timer runs on staging: publish each message via the Redis container."""
    publishes = [
        shlex.join(['docker', 'exec', REDIS_CONTAINER, 'redis-cli', 'PUBLISH', 'casino', json.dumps(message)])
        for message in teardown_messages(game_id)
    ]
    return f' && sleep {SETTLE_SECONDS} && '.join(publishes)


def arm_command(game_id, hours):
    """The command (run on staging) that schedules the one-shot teardown."""
    if hours <= 0:
        raise ValueError("--hours must be positive")
    seconds = int(hours * 3600)
    return [
        'sudo', '-n', 'systemd-run',
        '--unit', unit_name(game_id),
        '--on-active', f'{seconds}s',
        '--description', f'SaloonBot dead-man teardown for {game_id}',
        '/bin/sh', '-c', remote_payload(game_id),
    ]


def disarm_command(game_id):
    return ['sudo', '-n', 'systemctl', 'stop', unit_name(game_id) + '.timer']


def status_command():
    return ['systemctl', 'list-timers', UNIT_PREFIX + '*', '--all', '--no-pager']


def run_remote(host, command):
    """Run a command on the staging host over SSH; ssh joins its args, so quote them once here."""
    return subprocess.run(['ssh', host, shlex.join(command)]).returncode


def main(argv=None):
    parser = argparse.ArgumentParser(description="Arm/disarm a staging-side dead-man teardown for an ambient trial.")
    parser.add_argument('--host', default=STAGING_HOST, help=f"SSH host alias (default: {STAGING_HOST})")
    sub = parser.add_subparsers(dest='command', required=True)

    arm = sub.add_parser('arm', help="schedule the teardown on staging")
    arm.add_argument('--game-id', required=True)
    arm.add_argument('--hours', type=float, required=True, help="hours from now until the teardown fires")

    disarm = sub.add_parser('disarm', help="cancel a scheduled teardown")
    disarm.add_argument('--game-id', required=True)

    sub.add_parser('status', help="list armed dead-man timers")

    args = parser.parse_args(argv)
    try:
        if args.command == 'arm':
            command = arm_command(args.game_id, args.hours)
        elif args.command == 'disarm':
            command = disarm_command(args.game_id)
        else:
            command = status_command()
    except ValueError as e:
        parser.error(str(e))
    return run_remote(args.host, command)


if __name__ == '__main__':
    sys.exit(main())
