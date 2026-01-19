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

MYSQL_HOST = os.getenv("MYSQL_HOST", "localhost")
MYSQL_PORT = os.getenv("MYSQL_PORT", 3306)
MYSQL_USER = os.getenv("MYSQL_USER", "saloonbot")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "")
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "saloonbot")

logging.basicConfig(level=LOG_LEVEL)

def main():
    casino = Casino(REDIS_HOST, REDIS_PORT)
    casino.listen()


if __name__ == "__main__":
    main()
