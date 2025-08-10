import json
import logging
import time
import uuid

import redis

from .blackjack import Blackjack


class Casino:
    def __init__(self, redis_host, redis_port):
        self.games = {}
        logging.debug("Setting up redis...")
        self.redis = redis.Redis(host=redis_host, port=redis_port)
        logging.debug("Redis set up.")

    def new_game(self):
        logging.debug("Creating new game...")
        while True:
            game_id = str(uuid.uuid4())
            if game_id not in self.games.keys():
                break
        self.games[game_id] = Blackjack(game_id, self)
        logging.debug(f"Game created: {game_id}")
        return game_id

    def publish_event(self, event_type, data):
        logging.debug(f"Publishing event {event_type}: {data}")
        self.redis.publish(event_type, json.dumps(data))

    def game_output(self, game_id, output):
        self.publish_event(
            f"game_updates_{game_id}",
            { 'game_id': game_id, 'text': output }
        )

    def listen(self):
        logging.debug("Creating pubsub...")
        pubsub = self.redis.pubsub()
        logging.debug("Pubsub created.")

        backoff = None

        while True:
            try:
                logging.debug("Subscribing to casino...")
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
            logging.debug("Waiting for message...")
            message = pubsub.get_message(ignore_subscribe_messages=True,
                                         timeout=2.0)

            logging.debug("get_message returned.")

            if message:
                logging.debug(f"Got message: {message}")
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
                    self.games[game_id].action(data)
                else:
                    logging.debug(f"Got unknown message: {data}")

            # TODO: This is too often.
            for game in self.games.values():
                logging.debug("Tick...")
                game.tick()
                logging.debug("Tock.")
