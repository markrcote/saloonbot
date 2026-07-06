#!/usr/bin/env python3
"""
Flaky test hunter for saloonbot e2e tests.

Starts docker-compose ONCE, then runs each e2e test N times in sequence —
~100× faster than invoking pytest N times (which would spin docker up/down each run).

Usage:
    python hunt_flaky.py [--runs N] [--output FILE] [--class ClassName ...]
"""

import argparse
import json
import logging
import os
import subprocess
import sys
import traceback
from pathlib import Path

import mysql.connector
import redis as redislib

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
)
log = logging.getLogger("hunt_flaky")

MYSQL_CONF = dict(
    host="localhost",
    port=3306,
    user="saloonbot",
    password="saloonbot_password",
    database="saloonbot",
)

# ── Infrastructure ─────────────────────────────────────────────────────────────


def start_infra():
    log.info("Starting docker-compose services (this may take ~30s)…")
    subprocess.run(
        ["docker", "compose", "-f", "compose.test.yml", "up", "--wait"],
        check=True,
        capture_output=True,
        timeout=180,
    )
    r = redislib.Redis(host="localhost", port=6379, decode_responses=True)
    r.ping()
    db = mysql.connector.connect(**MYSQL_CONF)
    log.info("Infrastructure ready")
    return r, db


def stop_infra():
    log.info("Stopping docker-compose…")
    subprocess.run(
        ["docker", "compose", "-f", "compose.test.yml", "down", "-v"],
        capture_output=True,
        timeout=120,
    )


# ── Test runner ────────────────────────────────────────────────────────────────


def _read_server_log_from(log_path, start_byte):
    """Read server log output since start_byte; return last 50 lines."""
    if not log_path or not os.path.exists(log_path):
        return ""
    try:
        with open(log_path, errors="replace") as f:
            f.seek(start_byte)
            text = f.read()
        lines = text.splitlines()
        return "\n".join(lines[-50:])
    except Exception:
        return ""


def _server_log_pos(cls):
    log_path = getattr(cls, "_server_log_path", None)
    if log_path and os.path.exists(log_path):
        return os.path.getsize(log_path)
    return 0


def ensure_server_alive(cls):
    """If the class-level server process died, restart it."""
    proc = getattr(cls, "server_process", None)
    if proc is None or proc.poll() is not None:
        log.warning("Server for %s exited; restarting…", cls.__name__)
        cls._start_server()


def run_one(cls, method_name):
    """
    Run a single test method against the already-running server.

    Returns (passed: bool, error_msg: str | None, server_tail: str).
    """
    log_path = getattr(cls, "_server_log_path", None)
    log_start = _server_log_pos(cls)

    inst = cls(method_name)
    # setUp flushes Redis and clears DB tables — same as a normal test run.
    inst.setUp()

    error_msg = None
    try:
        getattr(inst, method_name)()
        passed = True
    except Exception as exc:
        passed = False
        error_msg = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"
    finally:
        try:
            inst.tearDown()
        except Exception:
            pass

    server_tail = ""
    if not passed:
        server_tail = _read_server_log_from(log_path, log_start)

    return passed, error_msg, server_tail


# ── Main hunt ──────────────────────────────────────────────────────────────────


def hunt(n_runs, filter_classes=None):
    # Import test module AFTER we've set up infra so module-level code is clean
    import test_e2e  # noqa: PLC0415

    r, db = start_infra()
    test_e2e._redis = r
    test_e2e._db = db

    all_classes = [
        test_e2e.TestGameCreation,
        test_e2e.TestPlayerActions,
        test_e2e.TestBlackjackGame,
        test_e2e.TestServerRestart,
        test_e2e.TestStopGame,
        test_e2e.TestWalletBalance,
        test_e2e.TestMultiplePlayers,
        test_e2e.TestNPCBots,
        test_e2e.TestAdminWallet,
        test_e2e.TestNPCLimits,
        test_e2e.TestManualNPC,
    ]
    if filter_classes:
        all_classes = [c for c in all_classes if c.__name__ in filter_classes]

    results = {}  # "Class::method" -> {passes, fails, errors[]}

    try:
        for cls in all_classes:
            methods = sorted(m for m in dir(cls) if m.startswith("test_"))
            sep = "=" * 65
            log.info("\n%s\n%s  (%d tests)", sep, cls.__name__, len(methods))

            cls.setUpClass()
            try:
                for method in methods:
                    tid = f"{cls.__name__}::{method}"
                    results[tid] = {"passes": 0, "fails": 0, "errors": []}

                    label = f"  {method}"
                    sys.stdout.write(f"{label:<54}")
                    sys.stdout.flush()

                    for run_id in range(n_runs):
                        ensure_server_alive(cls)
                        passed, err, tail = run_one(cls, method)

                        if passed:
                            results[tid]["passes"] += 1
                            sys.stdout.write(".")
                        else:
                            results[tid]["fails"] += 1
                            results[tid]["errors"].append(
                                {
                                    "run": run_id,
                                    "error": err,
                                    "server_tail": tail,
                                }
                            )
                            sys.stdout.write("F")
                        sys.stdout.flush()

                        # Periodic progress marker
                        if (run_id + 1) % 25 == 0:
                            p = results[tid]["passes"]
                            f = results[tid]["fails"]
                            sys.stdout.write(f"|{run_id+1}")
                            sys.stdout.flush()

                    p = results[tid]["passes"]
                    f = results[tid]["fails"]
                    rate = p / n_runs * 100
                    tag = "OK" if f == 0 else f"FLAKY {f}/{n_runs}"
                    print(f"  {tag} ({rate:.0f}%)")

            finally:
                cls.tearDownClass()

    finally:
        try:
            r.close()
        except Exception:
            pass
        try:
            db.close()
        except Exception:
            pass
        stop_infra()

    return results


# ── Report ─────────────────────────────────────────────────────────────────────


def report(results, n_runs, output_file=None):
    flaky = {k: v for k, v in results.items() if v["fails"] > 0}
    stable = {k: v for k, v in results.items() if v["fails"] == 0}

    bar = "=" * 70
    print(f"\n{bar}")
    print("FLAKY TEST HUNTER — FINAL REPORT")
    print(bar)
    print(f"  Runs per test : {n_runs}")
    print(f"  Tests scanned : {len(results)}")
    print(f"  Stable        : {len(stable)}")
    print(f"  Flaky         : {len(flaky)}")

    if flaky:
        print(f"\n{'─'*70}")
        print("FLAKY TESTS (sorted by failure count):")
        for tid, data in sorted(
            flaky.items(), key=lambda x: x[1]["fails"], reverse=True
        ):
            rate = data["passes"] / n_runs * 100
            print(f"\n  ● {tid}")
            print(f"    Pass rate : {data['passes']}/{n_runs} ({rate:.1f}%)")
            print(f"    Failures  : {data['fails']}")

            # Deduplicate error messages
            seen = {}
            for e in data["errors"]:
                snippet = (e.get("error") or "")[:300]
                if snippet not in seen:
                    seen[snippet] = e
            for snippet, entry in seen.items():
                print(f"\n    ── Error (first seen run {entry['run']}):")
                for line in snippet.splitlines():
                    print(f"       {line}")
                tail = entry.get("server_tail", "")
                if tail:
                    print("    ── Server log (last lines):")
                    for line in tail.splitlines()[-15:]:
                        print(f"       {line}")
    else:
        print("\n  ✓ All tests are STABLE — no flakiness detected.")

    if output_file:
        out = {
            "n_runs": n_runs,
            "summary": {
                "total": len(results),
                "stable": len(stable),
                "flaky": len(flaky),
                "flaky_tests": sorted(flaky.keys()),
            },
            "results": results,
        }
        Path(output_file).write_text(json.dumps(out, indent=2))
        print(f"\n  Full results → {output_file}")

    return flaky


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    ap = argparse.ArgumentParser(
        description="Flaky test hunter for saloonbot e2e tests"
    )
    ap.add_argument(
        "-n", "--runs", type=int, default=100, help="Runs per test (default: 100)"
    )
    ap.add_argument(
        "-o",
        "--output",
        default="flaky_results.json",
        help="JSON output file (default: flaky_results.json)",
    )
    ap.add_argument(
        "--class",
        dest="classes",
        nargs="+",
        metavar="ClassName",
        help="Restrict to specific test classes",
    )
    args = ap.parse_args()

    results = hunt(args.runs, args.classes)
    flaky = report(results, args.runs, args.output)
    sys.exit(1 if flaky else 0)
