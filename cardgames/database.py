import json
import logging

import mysql.connector
from mysql.connector import Error

DEFAULT_WALLET = 200.0


class Database:
    def __init__(self, host, port, user, password, database):
        """Initialize database connection parameters."""
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.database = database
        self.connection = None
        self._init_database()

    def _connect(self):
        """Create a database connection."""
        try:
            # Check if connection is valid before attempting to reconnect
            if self.connection is not None:
                try:
                    if self.connection.is_connected():
                        return
                except Error:
                    # Connection exists but is invalid, will reconnect below
                    pass

            self.connection = mysql.connector.connect(
                host=self.host,
                port=self.port,
                user=self.user,
                password=self.password,
                database=self.database
            )
            logging.info("Connected to MySQL database")
        except Error as e:
            logging.error(f"Error connecting to MySQL: {e}")
            raise

    def _init_database(self):
        """Initialize the database schema."""
        self._connect()
        try:
            cursor = self.connection.cursor()
            # Create users table if it doesn't exist
            cursor.execute(f"""
                CREATE TABLE IF NOT EXISTS users (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    username VARCHAR(255) UNIQUE NOT NULL,
                    wallet DECIMAL(10, 2) NOT NULL DEFAULT {DEFAULT_WALLET},
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            # Add wallet column if it doesn't exist (for existing databases)
            cursor.execute("""
                SELECT COUNT(*) FROM information_schema.columns
                WHERE table_schema = %s
                AND table_name = 'users'
                AND column_name = 'wallet'
            """, (self.database,))
            if cursor.fetchone()[0] == 0:
                cursor.execute(f"""
                    ALTER TABLE users
                    ADD COLUMN wallet DECIMAL(10, 2) NOT NULL DEFAULT {DEFAULT_WALLET}
                """)
                logging.info("Added wallet column to users table")
            # Create games table for game state persistence
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS games (
                    game_id VARCHAR(36) PRIMARY KEY,
                    state VARCHAR(20) NOT NULL,
                    current_player_idx INT DEFAULT NULL,
                    time_betting_started DOUBLE DEFAULT NULL,
                    time_last_hand_ended DOUBLE DEFAULT NULL,
                    time_last_event DOUBLE NOT NULL,
                    deck_json TEXT NOT NULL,
                    discards_json TEXT NOT NULL,
                    dealer_hand_json TEXT NOT NULL,
                    players_json TEXT NOT NULL,
                    players_waiting_json TEXT NOT NULL,
                    bets_json TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
                )
            """)

            # Create game_channels table for bot recovery
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS game_channels (
                    game_id VARCHAR(36) PRIMARY KEY,
                    guild_id BIGINT NOT NULL,
                    channel_id BIGINT NOT NULL,
                    FOREIGN KEY (game_id) REFERENCES games(game_id) ON DELETE CASCADE
                )
            """)

            self.connection.commit()
            cursor.close()
            logging.info("Database schema initialized")
        except Error as e:
            logging.error(f"Error initializing database: {e}")
            raise

    def add_user(self, username):
        """Add a new user to the database if they don't exist."""
        self._connect()
        try:
            cursor = self.connection.cursor()
            cursor.execute("""
                INSERT IGNORE INTO users (username) VALUES (%s)
            """, (username,))
            self.connection.commit()
            rows_affected = cursor.rowcount
            cursor.close()
            if rows_affected > 0:
                logging.info(f"Added new user: {username}")
            return rows_affected > 0
        except Error as e:
            logging.error(f"Error adding user {username}: {e}")
            raise

    def get_user_wallet(self, username):
        """Get the wallet balance for a user."""
        self._connect()
        try:
            cursor = self.connection.cursor()
            cursor.execute("""
                SELECT wallet FROM users WHERE username = %s
            """, (username,))
            result = cursor.fetchone()
            cursor.close()
            if result is None:
                return None
            return float(result[0])
        except Error as e:
            logging.error(f"Error getting wallet for {username}: {e}")
            raise

    def update_wallet(self, username, amount):
        """Update a user's wallet by adding or subtracting an amount."""
        self._connect()
        try:
            cursor = self.connection.cursor()
            cursor.execute("""
                UPDATE users SET wallet = wallet + %s WHERE username = %s
            """, (amount, username))
            self.connection.commit()
            rows_affected = cursor.rowcount
            cursor.close()
            if rows_affected > 0:
                logging.info(f"Updated wallet for {username} by {amount}")
            return rows_affected > 0
        except Error as e:
            logging.error(f"Error updating wallet for {username}: {e}")
            raise

    def save_game(self, game_id, game_data):
        """Save game state to database."""
        self._connect()
        try:
            cursor = self.connection.cursor()
            cursor.execute("""
                INSERT INTO games (
                    game_id, state, current_player_idx,
                    time_betting_started, time_last_hand_ended, time_last_event,
                    deck_json, discards_json, dealer_hand_json,
                    players_json, players_waiting_json, bets_json
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) AS new
                ON DUPLICATE KEY UPDATE
                    state = new.state,
                    current_player_idx = new.current_player_idx,
                    time_betting_started = new.time_betting_started,
                    time_last_hand_ended = new.time_last_hand_ended,
                    time_last_event = new.time_last_event,
                    deck_json = new.deck_json,
                    discards_json = new.discards_json,
                    dealer_hand_json = new.dealer_hand_json,
                    players_json = new.players_json,
                    players_waiting_json = new.players_waiting_json,
                    bets_json = new.bets_json
            """, (
                game_id,
                game_data['state'],
                game_data['current_player_idx'],
                game_data['time_betting_started'],
                game_data['time_last_hand_ended'],
                game_data['time_last_event'],
                json.dumps(game_data['deck']),
                json.dumps(game_data['discards']),
                json.dumps(game_data['dealer_hand']),
                json.dumps(game_data['players']),
                json.dumps(game_data['players_waiting']),
                json.dumps(game_data['bets']),
            ))
            self.connection.commit()
            cursor.close()
            logging.debug(f"Saved game {game_id}")
            return True
        except Error as e:
            logging.error(f"Error saving game {game_id}: {e}")
            raise

    def load_game(self, game_id):
        """Load game state from database."""
        self._connect()
        try:
            cursor = self.connection.cursor(dictionary=True)
            cursor.execute("""
                SELECT * FROM games WHERE game_id = %s
            """, (game_id,))
            result = cursor.fetchone()
            cursor.close()
            if result is None:
                return None
            return {
                'game_id': result['game_id'],
                'state': result['state'],
                'current_player_idx': result['current_player_idx'],
                'time_betting_started': result['time_betting_started'],
                'time_last_hand_ended': result['time_last_hand_ended'],
                'time_last_event': result['time_last_event'],
                'deck': json.loads(result['deck_json']),
                'discards': json.loads(result['discards_json']),
                'dealer_hand': json.loads(result['dealer_hand_json']),
                'players': json.loads(result['players_json']),
                'players_waiting': json.loads(result['players_waiting_json']),
                'bets': json.loads(result['bets_json']),
            }
        except Error as e:
            logging.error(f"Error loading game {game_id}: {e}")
            raise

    def load_all_active_games(self):
        """Load all active games from database."""
        self._connect()
        try:
            cursor = self.connection.cursor(dictionary=True)
            cursor.execute("SELECT * FROM games")
            results = cursor.fetchall()
            cursor.close()
            games = []
            for result in results:
                games.append({
                    'game_id': result['game_id'],
                    'state': result['state'],
                    'current_player_idx': result['current_player_idx'],
                    'time_betting_started': result['time_betting_started'],
                    'time_last_hand_ended': result['time_last_hand_ended'],
                    'time_last_event': result['time_last_event'],
                    'deck': json.loads(result['deck_json']),
                    'discards': json.loads(result['discards_json']),
                    'dealer_hand': json.loads(result['dealer_hand_json']),
                    'players': json.loads(result['players_json']),
                    'players_waiting': json.loads(result['players_waiting_json']),
                    'bets': json.loads(result['bets_json']),
                })
            return games
        except Error as e:
            logging.error(f"Error loading active games: {e}")
            raise

    def delete_game(self, game_id):
        """Delete a game from database."""
        self._connect()
        try:
            cursor = self.connection.cursor()
            cursor.execute("DELETE FROM games WHERE game_id = %s", (game_id,))
            self.connection.commit()
            rows_affected = cursor.rowcount
            cursor.close()
            if rows_affected > 0:
                logging.info(f"Deleted game {game_id}")
            return rows_affected > 0
        except Error as e:
            logging.error(f"Error deleting game {game_id}: {e}")
            raise

    def save_game_channel(self, game_id, guild_id, channel_id):
        """Save game-channel association for bot recovery."""
        self._connect()
        try:
            cursor = self.connection.cursor()
            cursor.execute("""
                INSERT INTO game_channels (game_id, guild_id, channel_id)
                VALUES (%s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    guild_id = VALUES(guild_id),
                    channel_id = VALUES(channel_id)
            """, (game_id, guild_id, channel_id))
            self.connection.commit()
            cursor.close()
            logging.debug(f"Saved game channel: {game_id} -> {guild_id}/{channel_id}")
            return True
        except Error as e:
            logging.error(f"Error saving game channel {game_id}: {e}")
            raise

    def load_game_channels(self):
        """Load all game-channel associations."""
        self._connect()
        try:
            cursor = self.connection.cursor(dictionary=True)
            cursor.execute("SELECT * FROM game_channels")
            results = cursor.fetchall()
            cursor.close()
            return [
                {
                    'game_id': r['game_id'],
                    'guild_id': r['guild_id'],
                    'channel_id': r['channel_id']
                }
                for r in results
            ]
        except Error as e:
            logging.error(f"Error loading game channels: {e}")
            raise

    def delete_game_channel(self, game_id):
        """Delete a game-channel association."""
        self._connect()
        try:
            cursor = self.connection.cursor()
            cursor.execute(
                "DELETE FROM game_channels WHERE game_id = %s", (game_id,)
            )
            self.connection.commit()
            rows_affected = cursor.rowcount
            cursor.close()
            if rows_affected > 0:
                logging.debug(f"Deleted game channel {game_id}")
            return rows_affected > 0
        except Error as e:
            logging.error(f"Error deleting game channel {game_id}: {e}")
            raise

    def close(self):
        """Close the database connection."""
        if self.connection and self.connection.is_connected():
            self.connection.close()
            logging.info("Database connection closed")
