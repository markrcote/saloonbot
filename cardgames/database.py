import json
import logging
import time

import mysql.connector
from mysql.connector import Error

_DEADLOCK_ERRNO = 1213
_DEADLOCK_RETRIES = 3
_DEADLOCK_BACKOFF_BASE = 0.05  # seconds

DEFAULT_WALLET = 200.0

# Each entry is a list of SQL statements for that migration.
# Append new entries to add future schema changes — never edit existing ones.
MIGRATIONS = [
    [   # Migration 1: baseline schema
        f"""CREATE TABLE IF NOT EXISTS users (
            id INT AUTO_INCREMENT PRIMARY KEY,
            username VARCHAR(255) UNIQUE NOT NULL,
            wallet DECIMAL(10, 2) NOT NULL DEFAULT {DEFAULT_WALLET},
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""",
        """CREATE TABLE IF NOT EXISTS games (
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
        )""",
        """CREATE TABLE IF NOT EXISTS game_channels (
            game_id VARCHAR(36) PRIMARY KEY,
            guild_id BIGINT NOT NULL,
            channel_id BIGINT NOT NULL,
            FOREIGN KEY (game_id) REFERENCES games(game_id) ON DELETE CASCADE
        )""",
    ],
]


class Database:
    def __init__(self, host, port, user, password, database):
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.database = database
        self.connection = None
        self._init_database()

    def _rollback_safe(self):
        try:
            self.connection.rollback()
        except Exception:
            pass

    def _execute_write(self, fn, error_msg):
        """Run fn(cursor) inside a retry loop that handles InnoDB deadlocks."""
        for attempt in range(_DEADLOCK_RETRIES):
            self._connect()
            cursor = None
            try:
                cursor = self.connection.cursor()
                result = fn(cursor)
                self.connection.commit()
                return result
            except Error as e:
                if e.errno == _DEADLOCK_ERRNO and attempt < _DEADLOCK_RETRIES - 1:
                    logging.warning(f"Deadlock in {error_msg}, retrying (attempt {attempt + 1})")
                    self._rollback_safe()
                    time.sleep(_DEADLOCK_BACKOFF_BASE * (2 ** attempt))
                else:
                    logging.error(f"Error in {error_msg}: {e}")
                    raise
            finally:
                if cursor:
                    cursor.close()

    def _connect(self):
        try:
            if self.connection is not None:
                try:
                    self.connection.ping(reconnect=True)
                    return
                except Error:
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
        self._connect()
        cursor = None
        try:
            cursor = self.connection.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS schema_version (version INT NOT NULL)
            """)
            cursor.execute("SELECT COUNT(*) FROM schema_version")
            if cursor.fetchone()[0] == 0:
                cursor.execute("INSERT INTO schema_version (version) VALUES (0)")
            self.connection.commit()

            cursor.execute("SELECT version FROM schema_version")
            current = cursor.fetchone()[0]

            for i, statements in enumerate(MIGRATIONS, start=1):
                if i <= current:
                    continue
                logging.info(f"Applying database migration {i}")
                for sql in statements:
                    cursor.execute(sql)
                cursor.execute("UPDATE schema_version SET version = %s", (i,))
                self.connection.commit()
                logging.info(f"Migration {i} applied")
                current = i

            logging.info(f"Database schema at version {current}")
        except Error as e:
            logging.error(f"Error initializing database: {e}")
            raise
        finally:
            if cursor:
                cursor.close()

    def add_user(self, username):
        """Add a new user to the database if they don't exist."""
        self._connect()
        cursor = None
        try:
            cursor = self.connection.cursor()
            cursor.execute("""
                INSERT IGNORE INTO users (username) VALUES (%s)
            """, (username,))
            self.connection.commit()
            rows_affected = cursor.rowcount
            if rows_affected > 0:
                logging.info(f"Added new user: {username}")
            return rows_affected > 0
        except Error as e:
            logging.error(f"Error adding user {username}: {e}")
            raise
        finally:
            if cursor:
                cursor.close()

    def get_user_wallet(self, username):
        """Get the wallet balance for a user."""
        self._connect()
        cursor = None
        try:
            cursor = self.connection.cursor()
            cursor.execute("""
                SELECT wallet FROM users WHERE username = %s
            """, (username,))
            result = cursor.fetchone()
            if result is None:
                return None
            return float(result[0])
        except Error as e:
            logging.error(f"Error getting wallet for {username}: {e}")
            raise
        finally:
            if cursor:
                cursor.close()

    def update_wallet(self, username, amount):
        """Update a user's wallet by adding or subtracting an amount.

        Returns True on success, False if the update would make the wallet negative.
        """
        def fn(cursor):
            if amount < 0:
                cursor.execute("""
                    UPDATE users SET wallet = wallet + %s
                    WHERE username = %s AND wallet + %s >= 0
                """, (amount, username, amount))
            else:
                cursor.execute("""
                    UPDATE users SET wallet = wallet + %s WHERE username = %s
                """, (amount, username))
            rows_affected = cursor.rowcount
            if rows_affected > 0:
                logging.debug(f"Updated wallet for {username} by {amount}")
            return rows_affected > 0

        return self._execute_write(fn, f"update_wallet({username})")

    def save_game(self, game_id, game_data):
        """Save game state to database."""
        params = (
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
        )
        def fn(cursor):
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
            """, params)
            logging.debug(f"Saved game {game_id}")
            return True

        return self._execute_write(fn, f"save_game({game_id})")

    def load_game(self, game_id):
        """Load game state from database."""
        self._connect()
        cursor = None
        try:
            cursor = self.connection.cursor(dictionary=True)
            cursor.execute("""
                SELECT * FROM games WHERE game_id = %s
            """, (game_id,))
            result = cursor.fetchone()
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
        finally:
            if cursor:
                cursor.close()

    def load_all_active_games(self):
        """Load all active games from database."""
        self._connect()
        cursor = None
        try:
            cursor = self.connection.cursor(dictionary=True)
            cursor.execute("SELECT * FROM games WHERE state != 'waiting'")
            results = cursor.fetchall()
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
        finally:
            if cursor:
                cursor.close()

    def delete_game(self, game_id):
        """Delete a game from database."""
        def fn(cursor):
            cursor.execute("DELETE FROM games WHERE game_id = %s", (game_id,))
            rows_affected = cursor.rowcount
            if rows_affected > 0:
                logging.info(f"Deleted game {game_id}")
            return rows_affected > 0

        return self._execute_write(fn, f"delete_game({game_id})")

    def save_game_channel(self, game_id, guild_id, channel_id):
        """Save game-channel association for bot recovery."""
        def fn(cursor):
            cursor.execute("""
                INSERT INTO game_channels (game_id, guild_id, channel_id)
                VALUES (%s, %s, %s) AS new
                ON DUPLICATE KEY UPDATE
                    guild_id = new.guild_id,
                    channel_id = new.channel_id
            """, (game_id, guild_id, channel_id))
            logging.debug(f"Saved game channel: {game_id} -> {guild_id}/{channel_id}")
            return True

        return self._execute_write(fn, f"save_game_channel({game_id})")

    def load_game_channels(self):
        """Load all game-channel associations."""
        self._connect()
        cursor = None
        try:
            cursor = self.connection.cursor(dictionary=True)
            cursor.execute("SELECT * FROM game_channels")
            results = cursor.fetchall()
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
        finally:
            if cursor:
                cursor.close()

    def delete_game_channel(self, game_id):
        """Delete a game-channel association."""
        def fn(cursor):
            cursor.execute(
                "DELETE FROM game_channels WHERE game_id = %s", (game_id,)
            )
            rows_affected = cursor.rowcount
            if rows_affected > 0:
                logging.debug(f"Deleted game channel {game_id}")
            return rows_affected > 0

        return self._execute_write(fn, f"delete_game_channel({game_id})")

    def close(self):
        """Close the database connection."""
        if self.connection and self.connection.is_connected():
            self.connection.close()
            logging.info("Database connection closed")
