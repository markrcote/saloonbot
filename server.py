import logging
import os

from cardgames.blackjack_engine import Blackjack

DEBUG_LOGGING = os.getenv("SALOONBOT_DEBUG")
if DEBUG_LOGGING:
    LOG_LEVEL = logging.DEBUG
else:
    LOG_LEVEL = logging.INFO

logging.basicConfig(level=LOG_LEVEL)

def main():
    blackjack_game = Blackjack()
    blackjack_game.listen()


if __name__ == "__main__":
    main()
