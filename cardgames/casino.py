import json
import logging
import time
import uuid

import redis

from .blackjack import Blackjack
from .card_game import CardGameError
from .simple_bot import SimpleBlackjackBot

BOT_TYPES = {
    'simple': SimpleBlackjackBot,
}


class Casino:
    def __init__(self, redis_host, redis_port, db=None):
        self.games = {}
        self.redis = redis.Redis(host=redis_host, port=redis_port)
        self.db = db

    def new_game(self):
        while True:
            game_id = str(uuid.uuid4())
            if game_id not in self.games.keys():
                break
        self.games[game_id] = Blackjack(game_id, self)
        return game_id

    def add_bot(self, game_id, bot_name, bot_type='simple'):
        """Add a bot player to a game.

        Args:
            game_id: The game to add the bot to.
            bot_name: Name for the bot player.
            bot_type: Bot strategy type (key in BOT_TYPES).

        Returns:
            The created BotPlayer instance.

        Raises:
            CardGameError: If game_id is invalid or bot_type is unknown.
        """
        if game_id not in self.games:
            raise CardGameError(f"Game {game_id} not found")

        bot_class = BOT_TYPES.get(bot_type)
        if bot_class is None:
            available = ', '.join(BOT_TYPES.keys())
            raise CardGameError(f"Unknown bot type '{bot_type}'. Available: {available}")

        bot = bot_class(bot_name)
        game = self.games[game_id]
        game.join(bot)
        return bot

    def remove_bot(self, game_id, bot_name):
        """Remove a bot player from a game.

        Args:
            game_id: The game to remove the bot from.
            bot_name: Name of the bot to remove.

        Raises:
            CardGameError: If game_id is invalid or bot not found.
        """
        if game_id not in self.games:
            raise CardGameError(f"Game {game_id} not found")

        game = self.games[game_id]
        bot = None
        for player in game.players + game.players_waiting:
            if player.name == bot_name and player.is_bot:
                bot = player
                break

        if bot is None:
            raise CardGameError(f"Bot '{bot_name}' not found in game")

        game.leave(bot)

    def publish_event(self, event_type, data):
        logging.debug(f"Publishing event {event_type}: {data}")
        self.redis.publish(event_type, json.dumps(data))

    def game_output(self, game_id, output):
        self.publish_event(
            f"game_updates_{game_id}",
            {'game_id': game_id, 'text': output}
        )

    def listen(self):
        pubsub = self.redis.pubsub()
        backoff = None
        while True:
            try:
                pubsub.subscribe("casino")
                break
            except redis.exceptions.ConnectionError:
                if backoff is None:
                    backoff = 1
                else:
                    backoff *= 2
                logging.info(f"Couldn't connect to redis; sleeping for {backoff} seconds...")
                time.sleep(backoff)

        logging.info("Casino online.")

        while True:
            message = pubsub.get_message(ignore_subscribe_messages=True,
                                         timeout=2.0)
            if message:
                data = json.loads(message['data'])
                game_id = data.get('game_id')

                if game_id is None:
                    logging.debug(f"Got casino message: {data}")
                    if data['event_type'] == 'casino_action':
                        if data['action'] == 'new_game':
                            request_id = data.get('request_id')
                            if request_id:
                                game_id = self.new_game()
                                self.publish_event(
                                    'casino_update',
                                    {
                                        'event_type': 'new_game',
                                        'request_id': request_id,
                                        'game_id': game_id
                                    }
                                )
                elif game_id in self.games.keys():
                    logging.debug(f"Got game message: {data}")
                    try:
                        if data['event_type'] == 'bot_action':
                            action = data['action']
                            if action == 'add_bot':
                                bot_name = data.get('bot_name', f"Bot-{uuid.uuid4().hex[:6]}")
                                bot_type = data.get('bot_type', 'simple')
                                self.add_bot(game_id, bot_name, bot_type)
                            elif action == 'remove_bot':
                                bot_name = data.get('bot_name')
                                if bot_name:
                                    self.remove_bot(game_id, bot_name)
                        else:
                            self.games[game_id].action(data)
                    except CardGameError as e:
                        logging.warning(f"Game error: {e}")
                        self.game_output(game_id, e.user_message())
                else:
                    logging.debug(f"Got unknown message: {data}")

            # TODO: This is too often.
            for game in self.games.values():
                game.tick()
