import json
import logging
import os
import time
import uuid

import redis

from .blackjack import Blackjack


class Casino:
    def __init__(self, redis_host, redis_port, use_db=True):
        self.games = {}
        self.redis = redis.Redis(host=redis_host, port=redis_port)
        self.use_db = use_db

        # Load active games from database on startup
        if self.use_db:
            self._load_active_games()

    def _load_active_games(self):
        """Load active games from database on startup."""
        if not self.use_db:
            return

        try:
            from .db import get_session
            session = get_session()
        except Exception as e:
            logging.warning(f"Database not available, running in memory-only mode: {e}")
            self.use_db = False
            return

        try:
            from .db import Game as DBGame, GamePlayer
            
            # Load games that are not finished
            active_games = session.query(DBGame).filter(
                DBGame.state.in_(['waiting', 'active'])
            ).all()
            
            logging.info(f"Loading {len(active_games)} active games from database")
            
            for db_game in active_games:
                try:
                    # Create the game object
                    game = Blackjack(str(db_game.game_id), self)
                    
                    # Load players for this game
                    game_players = session.query(GamePlayer).filter(
                        GamePlayer.game_id == db_game.id
                    ).order_by(GamePlayer.position).all()
                    
                    players_data = []
                    for gp in game_players:
                        players_data.append({
                            'name': gp.user.name,
                            'position': gp.position,
                            'hand': gp.hand or []
                        })

                    # Restore game state
                    if db_game.game_data:
                        game.restore_state(db_game.game_data, players_data)

                    self.games[str(db_game.game_id)] = game
                    logging.info(f"Restored game {db_game.game_id}")
                except Exception as e:
                    logging.error(f"Failed to restore game {db_game.game_id}: {e}")
        except Exception as e:
            logging.error(f"Failed to load active games: {e}")
        finally:
            session.close()

    def new_game(self, guild_id=None, channel_id=None):
        while True:
            game_id = str(uuid.uuid4())
            if game_id not in self.games.keys():
                break
        
        game = Blackjack(game_id, self)
        self.games[game_id] = game
        
        # Save to database
        if self.use_db:
            self._save_game_to_db(game, guild_id, channel_id, state='waiting')
        
        return game_id

    def _save_game_to_db(self, game, guild_id=None, channel_id=None, state='active'):
        """Save or update game in database."""
        if not self.use_db:
            return

        try:
            from .db import get_session, Game as DBGame, GamePlayer, User

            session = get_session()
        except Exception as e:
            logging.warning(f"Failed to get database session: {e}")
            return

        try:
            db_game = session.query(DBGame).filter(
                DBGame.game_id == uuid.UUID(game.game_id)
            ).first()

            if db_game:
                # Update existing game
                db_game.state = state
                db_game.game_data = game.serialize_state()

                # Update players
                # First, remove old player associations
                session.query(GamePlayer).filter(
                    GamePlayer.game_id == db_game.id
                ).delete()
            else:
                # Create new game
                db_game = DBGame(
                    game_id=uuid.UUID(game.game_id),
                    guild_id=guild_id,
                    channel_id=channel_id,
                    state=state,
                    game_data=game.serialize_state()
                )
                session.add(db_game)
                session.flush()  # Get the ID
            
            # Save current players
            for position, player in enumerate(game.players):
                # Ensure player exists in database
                db_user = session.query(User).filter(
                    User.discord_id == player.discord_id
                ).first()
                
                if not db_user:
                    db_user = User(
                        discord_id=player.discord_id,
                        name=player.name,
                        wallet=player.wallet
                    )
                    session.add(db_user)
                    session.flush()

                # Create game-player association
                game_player = GamePlayer(
                    game_id=db_game.id,
                    user_id=db_user.id,
                    position=position,
                    hand=[game._serialize_card(c) for c in player.hand]
                )
                session.add(game_player)

            session.commit()
            logging.debug(f"Game {game.game_id} saved to database")
        except Exception as e:
            logging.error(f"Failed to save game to database: {e}")
            session.rollback()
        finally:
            session.close()

    def persist_game(self, game_id):
        """Persist game state to database."""
        if not self.use_db:
            return
        
        game = self.games.get(game_id)
        if game:
            self._save_game_to_db(game)

    def finish_game(self, game_id):
        """Mark a game as finished in the database."""
        if not self.use_db:
            return

        try:
            from .db import get_session, Game as DBGame

            session = get_session()
        except Exception as e:
            logging.warning(f"Failed to get database session: {e}")
            return

        try:
            db_game = session.query(DBGame).filter(
                DBGame.game_id == uuid.UUID(game_id)
            ).first()

            if db_game:
                db_game.state = 'finished'
                session.commit()
        except Exception as e:
            logging.error(f"Failed to mark game as finished: {e}")
            session.rollback()
        finally:
            session.close()

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
        backoff = None
        while True:
            try:
                pubsub.subscribe("casino")
                break
            except redis.exceptions.ConnectionError as e:
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
                            guild_id = data.get('guild_id')
                            channel_id = data.get('channel_id')
                            if request_id:
                                game_id = self.new_game(guild_id=guild_id, channel_id=channel_id)
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
                    # Persist game state after player actions
                    self.persist_game(game_id)
                else:
                    logging.debug(f"Got unknown message: {data}")

            # TODO: This is too often.
            for game in self.games.values():
                game.tick()
                # Persist game state after tick (which may start/end hands)
                self.persist_game(game.game_id)
