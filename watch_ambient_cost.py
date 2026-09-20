#!/usr/bin/env python3
"""Operator tool: watch an ambient table's LLM spend and tear it down if it runs away.

Companion to start_ambient_table.py, for long unattended measurement runs. It polls
the server's Prometheus /metrics endpoint for the LLM token counters, prices the
growth since it started with llm_cost_report.PRICING, and:

  - warns when spend reaches --warn, or (with --expected-hourly-cost) runs well
    ahead of the expected rate;
  - tears the table down (same as start_ambient_table.py --teardown) when spend
    reaches --cap, when it can't price the usage (a model missing from PRICING),
    or when the metrics endpoint stays unreachable (rather than watching blind);
  - tears the table down and exits cleanly when --max-hours has elapsed.

Cost is computed from token counters, so it is a close estimate, not the invoice
(scrape lag, and failed calls aren't tracked) -- the provider dashboard remains the
source of truth. Only usage after this script's first poll is counted, so start it
right after the table. Ctrl-C leaves the table running UNWATCHED.

Usage:
    python start_ambient_table.py --min 3 --max 5           # note the game id
    python watch_ambient_cost.py --game-id <id> --cap 1.50 --warn 0.50 --max-hours 12
"""
import argparse
import http.client
import logging
import os
import sys
import time
import urllib.request

import redis
from prometheus_client.parser import text_string_to_metric_families

from llm_cost_report import compute_costs
from start_ambient_table import REDIS_HOST, REDIS_PORT, _publish, teardown

METRICS_URL = os.getenv("WATCH_METRICS_URL", "http://localhost:9400/metrics")
QUERY_TIMEOUT = 10.0  # seconds for one /metrics fetch

INPUT_TOKENS = "saloonbot_llm_input_tokens_total"
OUTPUT_TOKENS = "saloonbot_llm_output_tokens_total"

RATE_WARN_FACTOR = 3.0  # warn when spend is this many times the expected rate
RATE_WARN_MIN_HOURS = 0.5  # ...but not before the start-up burst (roster seeding) has settled

EXIT_OK = 0
EXIT_ABORTED = 2  # spend cap, unpriced usage, or unreachable metrics; table torn down
EXIT_CANNOT_WATCH = 3  # couldn't establish a baseline / reach Redis; nothing was started or stopped
EXIT_TEARDOWN_FAILED = 4  # decided to stop the table but couldn't confirm it stopped

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


class MetricsError(Exception):
    """The /metrics endpoint couldn't be fetched or parsed."""


def _fetch_text(url, timeout=QUERY_TIMEOUT):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.read().decode('utf-8')
    except (OSError, ValueError, http.client.HTTPException) as e:
        raise MetricsError(f"could not fetch {url}: {e}") from e


def read_token_totals(url=METRICS_URL, timeout=QUERY_TIMEOUT):
    """Cumulative token counters summed over purpose: {(provider, model): (input, output)}."""
    text = _fetch_text(url, timeout)
    totals = {}
    try:
        for family in text_string_to_metric_families(text):
            for sample in family.samples:
                if sample.name not in (INPUT_TOKENS, OUTPUT_TOKENS):
                    continue
                key = (sample.labels.get('provider') or 'unknown', sample.labels.get('model'))
                current = list(totals.get(key, (0.0, 0.0)))
                current[0 if sample.name == INPUT_TOKENS else 1] += sample.value
                totals[key] = tuple(current)
    except ValueError as e:
        raise MetricsError(f"could not parse metrics from {url}: {e}") from e
    return totals


class SpendTracker:
    """Accumulates token usage across polls, tolerating counter resets.

    The first update is the baseline (usage before the watchdog started isn't
    counted). Afterwards each poll adds the growth since the last one; a counter
    that went backwards means the server restarted, so its new value is all new
    usage. A series first seen after the baseline counts in full.
    """

    def __init__(self):
        self._last = {}
        self._primed = False
        self._usage = {}

    def update(self, totals):
        for key, (tokens_in, tokens_out) in totals.items():
            if self._primed:
                prev_in, prev_out = self._last.get(key, (0.0, 0.0))
                add_in = tokens_in - prev_in if tokens_in >= prev_in else tokens_in
                add_out = tokens_out - prev_out if tokens_out >= prev_out else tokens_out
                used_in, used_out = self._usage.get(key, (0.0, 0.0))
                self._usage[key] = (used_in + add_in, used_out + add_out)
            self._last[key] = (tokens_in, tokens_out)
        self._primed = True

    def rows(self):
        """Usage in get_llm_usage_summary() row shape, ready for compute_costs()."""
        return [
            {'provider': provider, 'model': model, 'total_input': int(tokens_in), 'total_output': int(tokens_out)}
            for (provider, model), (tokens_in, tokens_out) in sorted(self._usage.items(), key=lambda kv: str(kv[0]))
            if tokens_in or tokens_out
        ]


def evaluate(total_cost, unpriced, elapsed_hours, warn_at, cap, max_hours, expected_hourly=None):
    """Decide what to do: returns (level, reason), level one of 'ok', 'warn', 'abort', 'done'."""
    if unpriced:
        names = ", ".join(f"{p}/{m}" for p, m in unpriced)
        return 'abort', f"usage from model(s) with no pricing on file ({names}); can't bound the spend"
    if total_cost >= cap:
        return 'abort', f"spend ${total_cost:.4f} reached the ${cap:.2f} cap"
    if elapsed_hours >= max_hours:
        return 'done', f"reached the {max_hours:g}h time limit (spend ${total_cost:.4f})"
    if total_cost >= warn_at:
        return 'warn', f"spend ${total_cost:.4f} passed the ${warn_at:.2f} warning level"
    if (expected_hourly and elapsed_hours >= RATE_WARN_MIN_HOURS
            and total_cost > RATE_WARN_FACTOR * expected_hourly * elapsed_hours):
        return 'warn', (f"spend ${total_cost:.4f} is over {RATE_WARN_FACTOR:g}x the expected "
                        f"${expected_hourly:.4f}/h after {elapsed_hours:.2f}h")
    return 'ok', ''


def watch(read_totals, stop_table, *, warn_at, cap, max_hours, interval, unreachable_limit,
          expected_hourly=None, clock=time.monotonic, sleep=time.sleep):
    """Poll until the table is stopped; returns a process exit code.

    read_totals() -> {(provider, model): (input, output)}, raising MetricsError on failure.
    stop_table() -> bool, whether the table was confirmed stopped.
    """
    tracker = SpendTracker()
    try:
        tracker.update(read_totals())
    except MetricsError as e:
        logging.error(f"Can't establish a baseline, so not watching: {e}")
        return EXIT_CANNOT_WATCH
    started = clock()
    failures = 0
    logging.info(f"Baseline recorded. Watching: warn at ${warn_at:.2f}, abort at ${cap:.2f}, "
                 f"stop after {max_hours:g}h, poll every {interval:g}s.")

    def finish(exit_code):
        if stop_table():
            return exit_code
        logging.critical("COULD NOT CONFIRM THE TABLE STOPPED -- check it by hand and stop it.")
        return EXIT_TEARDOWN_FAILED

    while True:
        sleep(interval)
        elapsed_hours = (clock() - started) / 3600
        try:
            tracker.update(read_totals())
            failures = 0
        except MetricsError as e:
            failures += 1
            logging.warning(f"Metrics unreachable ({failures}/{unreachable_limit}): {e}")
            if failures >= unreachable_limit:
                logging.error("Metrics unreachable too long; stopping the table rather than watching blind.")
                return finish(EXIT_ABORTED)

        _, total_cost, unpriced = compute_costs(tracker.rows())
        level, reason = evaluate(total_cost, unpriced, elapsed_hours, warn_at, cap, max_hours, expected_hourly)
        rate = total_cost / elapsed_hours if elapsed_hours else 0.0
        logging.info(f"{elapsed_hours:.2f}h in: spend ${total_cost:.4f} of ${cap:.2f} cap (about ${rate:.4f}/h)")
        if level == 'warn':
            logging.warning(reason)
        elif level == 'abort':
            logging.error(f"ABORTING: {reason}")
            return finish(EXIT_ABORTED)
        elif level == 'done':
            logging.info(f"Finished: {reason}")
            return finish(EXIT_OK)


def abort_table(r, pubsub, game_id):
    """Tear the table down, whatever it takes. Returns True if fully confirmed.

    start_ambient_table.teardown() sets npc limits 0/0 first and raises SystemExit if
    that isn't acknowledged, which would skip stop_game -- so fall back to publishing
    stop_game directly. That fallback is unacknowledged, so it still reports False.
    """
    try:
        teardown(r, pubsub, game_id)
        return True
    except (SystemExit, redis.RedisError) as e:
        logging.error(f"Clean teardown failed ({e}); sending stop_game directly.")
    try:
        _publish(r, {'event_type': 'casino_action', 'action': 'stop_game', 'game_id': game_id})
    except redis.RedisError as e:
        logging.critical(f"Could not publish stop_game either: {e}")
    return False


def main():
    parser = argparse.ArgumentParser(
        description="Watch an ambient table's LLM spend and tear it down if it runs away."
    )
    parser.add_argument("--game-id", required=True, help="Game id from start_ambient_table.py.")
    parser.add_argument("--cap", type=float, default=1.50, help="Abort at this cumulative spend in $ (default: 1.50).")
    parser.add_argument("--warn", type=float, default=0.50, help="Warn at this cumulative spend in $ (default: 0.50).")
    parser.add_argument("--max-hours", type=float, default=12.0,
                        help="Stop the table after this many hours (default: 12).")
    parser.add_argument("--interval", type=float, default=300.0, help="Seconds between polls (default: 300).")
    parser.add_argument("--unreachable-limit", type=int, default=3,
                        help="Consecutive failed polls before stopping the table (default: 3).")
    parser.add_argument("--expected-hourly-cost", type=float,
                        help="Expected $/hour; warn if spend runs over 3x this (optional).")
    parser.add_argument("--metrics-url", default=METRICS_URL, help=f"Server /metrics URL (default: {METRICS_URL}).")
    parser.add_argument("--redis-host", default=REDIS_HOST)
    parser.add_argument("--redis-port", type=int, default=REDIS_PORT)
    args = parser.parse_args()

    if not 0 < args.warn < args.cap:
        parser.error("--warn must be positive and below --cap")
    if args.max_hours <= 0 or args.interval <= 0 or args.unreachable_limit < 1:
        parser.error("--max-hours and --interval must be positive and --unreachable-limit at least 1")

    # Refuse to watch if we couldn't act on what we see.
    r = redis.Redis(host=args.redis_host, port=args.redis_port)
    try:
        r.ping()
    except redis.RedisError as e:
        logging.error(f"Can't reach Redis at {args.redis_host}:{args.redis_port}, so an abort would be impossible: {e}")
        sys.exit(EXIT_CANNOT_WATCH)
    pubsub = r.pubsub()
    pubsub.subscribe("casino_update")

    try:
        code = watch(
            lambda: read_token_totals(args.metrics_url),
            lambda: abort_table(r, pubsub, args.game_id),
            warn_at=args.warn, cap=args.cap, max_hours=args.max_hours, interval=args.interval,
            unreachable_limit=args.unreachable_limit, expected_hourly=args.expected_hourly_cost,
        )
    except KeyboardInterrupt:
        logging.warning(f"Interrupted: table {args.game_id} is still running and NO LONGER WATCHED.")
        sys.exit(130)
    sys.exit(code)


if __name__ == "__main__":
    main()
