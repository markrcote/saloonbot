import logging
import os

from cardgames.casino import Casino

DEBUG_LOGGING = os.getenv("SALOONBOT_DEBUG")
if DEBUG_LOGGING:
    LOG_LEVEL = logging.DEBUG
else:
    LOG_LEVEL = logging.INFO

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = os.getenv("REDIS_PORT", 6379)

logging.basicConfig(level=LOG_LEVEL)


def main():
    logging.info("Setting up casino...")
    casino = Casino(REDIS_HOST, REDIS_PORT)
    casino.listen()


if __name__ == "__main__":
    main()
