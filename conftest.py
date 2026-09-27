"""Pytest-wide guard rails.

Caps the test process's address space so a runaway test (e.g. a loop that
never ends because a MagicMock's len() is always 0) dies with MemoryError
instead of eating all the RAM on a small dev box or CI runner. The limit is
inherited by subprocesses the tests start (the e2e server, docker CLI).

Override with SALOONBOT_TEST_MEM_LIMIT_MB; set it to 0 to disable the cap.
"""
import os
import resource

DEFAULT_MEM_LIMIT_MB = 2048


def pytest_configure(config):
    limit_mb = int(os.environ.get('SALOONBOT_TEST_MEM_LIMIT_MB', DEFAULT_MEM_LIMIT_MB))
    if limit_mb <= 0:
        return
    limit = limit_mb * 1024 * 1024
    _soft, hard = resource.getrlimit(resource.RLIMIT_AS)
    if hard != resource.RLIM_INFINITY:
        limit = min(limit, hard)
    resource.setrlimit(resource.RLIMIT_AS, (limit, hard))
