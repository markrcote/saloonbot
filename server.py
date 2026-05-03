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
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))

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


def _key_status(env_var):
    """Return 'set', 'set (via file)', or 'not set' for a secret resolved via env/_FILE/secrets."""
    if os.environ.get(env_var):
        return "set"
    file_path = os.environ.get(f"{env_var}_FILE") or f"/run/secrets/{env_var.lower()}"
    return "set (via file)" if os.path.isfile(file_path) else "not set"


def _log_config():
    logging.info("=== Server Configuration ===")
    logging.info(f"  Redis: {REDIS_HOST}:{REDIS_PORT}")
    logging.info(f"  Debug logging: {'enabled' if DEBUG_LOGGING else 'disabled'}")
    if USE_SQLITE:
        logging.info(f"  Database: SQLite @ {SQLITE_PATH}")
    else:
        logging.info(f"  Database: MySQL {MYSQL_USER}@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DATABASE}")
        logging.info(f"  MYSQL_PASSWORD: {'set' if MYSQL_PASSWORD else 'not set'}")
    llm_provider = os.getenv("LLM_PROVIDER", "claude")
    llm_model = os.getenv("LLM_MODEL") or f"(default for {llm_provider})"
    logging.info(f"  LLM_PROVIDER: {llm_provider}")
    logging.info(f"  LLM_MODEL: {llm_model}")
    logging.info(f"  LLM_TIMEOUT: {os.getenv('LLM_TIMEOUT', '5')}s")
    logging.info(f"  ANTHROPIC_API_KEY: {_key_status('ANTHROPIC_API_KEY')}")
    logging.info(f"  OPENAI_API_KEY: {_key_status('OPENAI_API_KEY')}")
    logging.info(f"  BLACKJACK_MIN_BET: ${os.getenv('BLACKJACK_MIN_BET', '5')}")
    logging.info(f"  BLACKJACK_MAX_BET: ${os.getenv('BLACKJACK_MAX_BET', '100')}")
    logging.info(f"  BLACKJACK_TIME_FOR_BETTING: {os.getenv('BLACKJACK_TIME_FOR_BETTING', '30')}s")
    logging.info(f"  BLACKJACK_TIME_BETWEEN_HANDS: {os.getenv('BLACKJACK_TIME_BETWEEN_HANDS', '10')}s")
    logging.info(f"  BLACKJACK_REMINDER_PERIOD: {os.getenv('BLACKJACK_REMINDER_PERIOD', '30')}s")
    logging.info("============================")


def main():
    _log_config()
    if USE_SQLITE:
        db = SqliteDatabase(SQLITE_PATH)
    else:
        db = Database(MYSQL_HOST, MYSQL_PORT, MYSQL_USER, MYSQL_PASSWORD, MYSQL_DATABASE)
    casino = Casino(REDIS_HOST, REDIS_PORT, db)
    casino.listen()


if __name__ == "__main__":
    main()
