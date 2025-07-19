import logging
import os

from cardgames.casino import Casino

DEBUG_LOGGING = os.getenv("SALOONBOT_DEBUG")
if DEBUG_LOGGING:
    LOG_LEVEL = logging.DEBUG
else:
    LOG_LEVEL = logging.INFO

logging.basicConfig(level=LOG_LEVEL)

def main():
    casino = Casino()
    casino.listen()


if __name__ == "__main__":
    main()
