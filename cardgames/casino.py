import json
import logging
import time
import uuid

import redis

from .blackjack import Blackjack
from .card_game import CardGameError
from .simple_npc import SimpleBlackjackNPC

NPC_TYPES = {
    'simple': SimpleBlackjackNPC,
}


class Casino:
    def __init__(self, redis_host, redis_port, db=None):
        self.games = {}
        self.redis = redis.Redis(host=redis_host, port=redis_port)
        self.db = db
        self._load_games_from_db()

    def _load_games_from_db(self):
        """Load all active games from database on startup."""
        if self.db is None:
            return

        try:
            game_data_list = self.db.load_all_active_games()
            for game_data in game_data_list:
                game_id = game_data['game_id']
                game = Blackjack.from_dict(game_data, self)
                self.games[game_id] = game
                logging.info(f"Restored game {game_id} in state {game.state.value}")
        except Exception as e:
            logging.error(f"Error loading games from database: {e}")

    def _save_game(self, game_id):
        """Save a game's current state to database."""
        if self.db is None:
            return

        game = self.games.get(game_id)
        if game is None:
            return

        try:
            game_data = game.to_dict()
            self.db.save_game(game_id, game_data)
        except Exception as e:
            logging.error(f"Error saving game {game_id}: {e}")

    def _delete_game(self, game_id):
        """Delete a game from database."""
        if self.db is None:
            return

        try:
            self.db.delete_game(game_id)
            self.db.delete_game_channel(game_id)
        except Exception as e:
            logging.error(f"Error deleting game {game_id}: {e}")

    def new_game(self, guild_id=None, channel_id=None):
        while True:
            game_id = str(uuid.uuid4())
            if game_id not in self.games.keys():
                break
        self.games[game_id] = Blackjack(game_id, self)

        # Save game and channel info to database
        self._save_game(game_id)
        if guild_id is not None and channel_id is not None and self.db is not None:
            try:
                self.db.save_game_channel(game_id, guild_id, channel_id)
            except Exception as e:
                logging.error(f"Error saving game channel {game_id}: {e}")

        return game_id

    def _handle_list_games(self, request_id):
        """Handle a list_games request from the bot."""
        games_info = []

        # Get channel info from database
        channel_map = {}
        if self.db is not None:
            try:
                channels = self.db.load_game_channels()
                channel_map = {c['game_id']: c for c in channels}
            except Exception as e:
                logging.error(f"Error loading game channels: {e}")

        for game_id, game in self.games.items():
            game_info = {
                'game_id': game_id,
                'state': game.state.value,
            }
            if game_id in channel_map:
                game_info['guild_id'] = channel_map[game_id]['guild_id']
                game_info['channel_id'] = channel_map[game_id]['channel_id']
            games_info.append(game_info)

        self.publish_event(
            'casino_update',
            {
                'event_type': 'list_games',
                'request_id': request_id,
                'games': games_info
            }
        )
        logging.info(f"Responded to list_games with {len(games_info)} games")

    def add_npc(self, game_id, npc_name, npc_type='simple'):
        """Add an NPC player to a game.

        Args:
            game_id: The game to add the NPC to.
            npc_name: Name for the NPC player.
            npc_type: NPC strategy type (key in NPC_TYPES).

        Returns:
            The created NPCPlayer instance.

        Raises:
            CardGameError: If game_id is invalid or npc_type is unknown.
        """
        if game_id not in self.games:
            raise CardGameError(f"Game {game_id} not found")

        npc_class = NPC_TYPES.get(npc_type)
        if npc_class is None:
            available = ', '.join(NPC_TYPES.keys())
            raise CardGameError(f"Unknown NPC type '{npc_type}'. Available: {available}")

        npc = npc_class(npc_name)
        game = self.games[game_id]
        game.join(npc)
        return npc

    def remove_npc(self, game_id, npc_name):
        """Remove an NPC player from a game.

        Args:
            game_id: The game to remove the NPC from.
            npc_name: Name of the NPC to remove.

        Raises:
            CardGameError: If game_id is invalid or NPC not found.
        """
        if game_id not in self.games:
            raise CardGameError(f"Game {game_id} not found")

        game = self.games[game_id]
        npc = None
        for player in game.players + game.players_waiting:
            if player.name == npc_name and player.is_npc:
                npc = player
                break

        if npc is None:
            raise CardGameError(f"NPC '{npc_name}' not found in game")

        game.leave(npc)

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
                                guild_id = data.get('guild_id')
                                channel_id = data.get('channel_id')
                                game_id = self.new_game(guild_id, channel_id)
                                self.publish_event(
                                    'casino_update',
                                    {
                                        'event_type': 'new_game',
                                        'request_id': request_id,
                                        'game_id': game_id
                                    }
                                )
                        elif data['action'] == 'list_games':
                            request_id = data.get('request_id')
                            if request_id:
                                self._handle_list_games(request_id)
                elif game_id in self.games.keys():
                    logging.debug(f"Got game message: {data}")
                    try:
                        if data['event_type'] == 'npc_action':
                            action = data['action']
                            if action == 'add_npc':
                                npc_name = data.get('npc_name', f"NPC-{uuid.uuid4().hex[:6]}")
                                npc_type = data.get('npc_type', 'simple')
                                self.add_npc(game_id, npc_name, npc_type)
                            elif action == 'remove_npc':
                                npc_name = data.get('npc_name')
                                if npc_name:
                                    self.remove_npc(game_id, npc_name)
                        else:
                            self.games[game_id].action(data)
                        # Save game after player action
                        self._save_game(game_id)
                    except CardGameError as e:
                        logging.warning(f"Game error: {e}")
                        self.game_output(game_id, e.user_message())
                else:
                    logging.debug(f"Got unknown message: {data}")

            # Process game ticks and save on state changes
            for game_id, game in list(self.games.items()):
                state_before = game.state
                game.tick()
                state_after = game.state

                # Save if state changed
                if state_before != state_after:
                    self._save_game(game_id)
