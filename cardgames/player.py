class Player:
    def __init__(self, name, discord_id=None, db_id=None):
        self.name = name  # must be unique
        self.discord_id = discord_id or name  # Discord user ID or name as fallback
        self.db_id = db_id  # Database ID
        self.hand = []
        self.wallet = 0
        self.games_played = 0
        self.games_won = 0
        self.games_lost = 0
        self.games_tied = 0

    def __eq__(self, other):
        return self.name == other.name

    def __ne__(self, other):
        return not self.__eq__(other)

    def __repr__(self):
        return f"{self.name}"

    def __str__(self):
        return f"{self.name}"

    def hand_str(self):
        return ", ".join([card.str() for card in self.hand])


class PlayerNotFoundError(Exception):

    def __init__(self, playername):
        self.playername = playername

    def __str__(self):
        return f"Player {self.playername} not found"


class PlayerRegistry:
    def __init__(self, use_db=True):
        self.players = {}
        self.use_db = use_db

    def get_player(self, player_name, add=False):
        """Get or create a player.

        Args:
            player_name: The player's name (can be discord_id)
            add: If True, create player if not found

        Returns:
            Player object

        Raises:
            PlayerNotFoundError: If player not found and add=False
        """
        # Check in-memory cache first
        player = self.players.get(player_name)
        if player is not None:
            return player

        # Try to load from database if enabled
        if self.use_db:
            try:
                from .db import get_session, User

                session = get_session()
                try:
                    db_user = session.query(User).filter(
                        (User.discord_id == player_name) | (User.name == player_name)
                    ).first()

                    if db_user:
                        player = Player(
                            name=db_user.name,
                            discord_id=db_user.discord_id,
                            db_id=db_user.id
                        )
                        player.wallet = float(db_user.wallet or 0)
                        player.games_played = db_user.games_played or 0
                        player.games_won = db_user.games_won or 0
                        player.games_lost = db_user.games_lost or 0
                        player.games_tied = db_user.games_tied or 0
                        self.players[player_name] = player
                        return player
                finally:
                    session.close()
            except Exception as e:
                import logging
                logging.warning(f"Error loading player from database: {e}")

        # Create new player if requested
        if add:
            player = Player(player_name)
            self.players[player_name] = player

            # Save to database if enabled
            if self.use_db:
                try:
                    from .db import get_session, User

                    session = get_session()
                    try:
                        db_user = User(
                            discord_id=player.discord_id,
                            name=player.name,
                            wallet=player.wallet
                        )
                        session.add(db_user)
                        session.commit()
                        player.db_id = db_user.id
                    except Exception as e:
                        import logging
                        logging.warning(f"Error saving player to database: {e}")
                        session.rollback()
                    finally:
                        session.close()
                except Exception as e:
                    import logging
                    logging.warning(f"Failed to get database session: {e}")

            return player

        raise PlayerNotFoundError(player_name)

    def save_player(self, player):
        """Save player statistics to database."""
        if not self.use_db:
            return

        try:
            from .db import get_session, User

            session = get_session()
        except Exception as e:
            import logging
            logging.warning(f"Failed to get database session: {e}")
            return

        try:
            if player.db_id:
                db_user = session.query(User).filter(User.id == player.db_id).first()
                if db_user:
                    db_user.wallet = player.wallet
                    db_user.games_played = player.games_played
                    db_user.games_won = player.games_won
                    db_user.games_lost = player.games_lost
                    db_user.games_tied = player.games_tied
                    session.commit()
        except Exception as e:
            import logging
            logging.warning(f"Error saving player statistics: {e}")
            session.rollback()
        finally:
            session.close()


# Create global registry - determine use_db from environment
import os
_use_db = os.getenv("USE_DATABASE", "true").lower() in ("true", "1", "yes")
registry = PlayerRegistry(use_db=_use_db)
