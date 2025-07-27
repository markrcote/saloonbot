import json
import logging
import uuid

import redis

from .blackjack import Blackjack


class Casino:
    def __init__(self):
        self.games = {}
        self.redis = redis.Redis()

    def new_game(self):
        while True:
            game_id = str(uuid.uuid4())
            if game_id not in self.games.keys():
                break
        self.games[game_id] = Blackjack(game_id, self)
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
        pubsub = self.redis.pubsub()
        pubsub.subscribe("casino")
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
                    self.games[game_id].action(data)
                else:
                    logging.debug(f"Got unknown message: {data}")

            # TODO: This is too often.
            for game in self.games.values():
                game.tick()
