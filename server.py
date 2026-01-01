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
    # Initialize database if enabled
    use_db = os.getenv("USE_DATABASE", "true").lower() in ("true", "1", "yes")

    if use_db:
        try:
            from cardgames.db import init_db
            logging.info("Initializing database...")
            init_db()
            logging.info("Database initialized successfully")
        except Exception as e:
            logging.error(f"Failed to initialize database: {e}")
            logging.warning("Continuing without database support")
            use_db = False

    casino = Casino(REDIS_HOST, REDIS_PORT, use_db=use_db)
    casino.listen()


if __name__ == "__main__":
    main()
