import logging
import os

from cardgames.casino import Casino
from cardgames.database import Database
from cardgames.sqlite_database import SqliteDatabase

DEBUG_LOGGING = os.getenv("SALOONBOT_DEBUG")
if DEBUG_LOGGING:
    LOG_LEVEL = logging.DEBUG
else:
    LOG_LEVEL = logging.INFO

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = os.getenv("REDIS_PORT", 6379)

USE_SQLITE = os.getenv("USE_SQLITE")
SQLITE_PATH = os.getenv("SQLITE_PATH", "saloonbot.db")

MYSQL_HOST = os.getenv("MYSQL_HOST", "localhost")
MYSQL_PORT = os.getenv("MYSQL_PORT", 3306)
MYSQL_USER = os.getenv("MYSQL_USER", "saloonbot")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "")
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "saloonbot")

logging.basicConfig(
    level=LOG_LEVEL,
    format='%(asctime)s - %(levelname)s - %(message)s'
)


def main():
    if USE_SQLITE:
        db = SqliteDatabase(SQLITE_PATH)
    else:
        db = Database(MYSQL_HOST, MYSQL_PORT, MYSQL_USER, MYSQL_PASSWORD, MYSQL_DATABASE)
    casino = Casino(REDIS_HOST, REDIS_PORT, db)
    casino.listen()


if __name__ == "__main__":
    main()
