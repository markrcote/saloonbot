import json
import logging
import sqlite3

DEFAULT_WALLET = 200.0

# Each entry is a list of SQL statements for that migration.
# Append new entries to add future schema changes — never edit existing ones.
MIGRATIONS = [
    [   # Migration 1: baseline schema
        f"""CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            wallet REAL NOT NULL DEFAULT {DEFAULT_WALLET},
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""",
        """CREATE TABLE IF NOT EXISTS games (
            game_id TEXT PRIMARY KEY,
            state TEXT NOT NULL,
            current_player_idx INTEGER DEFAULT NULL,
            time_betting_started REAL DEFAULT NULL,
            time_last_hand_ended REAL DEFAULT NULL,
            time_last_event REAL NOT NULL,
            deck_json TEXT NOT NULL,
            discards_json TEXT NOT NULL,
            dealer_hand_json TEXT NOT NULL,
            players_json TEXT NOT NULL,
            players_waiting_json TEXT NOT NULL,
            bets_json TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""",
        """CREATE TABLE IF NOT EXISTS game_channels (
            game_id TEXT PRIMARY KEY,
            guild_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            FOREIGN KEY (game_id) REFERENCES games(game_id) ON DELETE CASCADE
        )""",
    ],
]


class SqliteDatabase:
    def __init__(self, db_path):
        self.db_path = db_path
        self.connection = None
        self._init_database()

    def _connect(self):
        if self.connection is None:
            self.connection = sqlite3.connect(self.db_path, check_same_thread=False)
            self.connection.row_factory = sqlite3.Row
            self.connection.execute("PRAGMA foreign_keys = ON")
            logging.info(f"Connected to SQLite database: {self.db_path}")

    def _init_database(self):
        self._connect()
        try:
            self.connection.execute("""
                CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)
            """)
            count = self.connection.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0]
            if count == 0:
                self.connection.execute("INSERT INTO schema_version (version) VALUES (0)")
            self.connection.commit()

            current = self.connection.execute("SELECT version FROM schema_version").fetchone()[0]

            for i, statements in enumerate(MIGRATIONS, start=1):
                if i <= current:
                    continue
                logging.info(f"Applying database migration {i}")
                for sql in statements:
                    self.connection.execute(sql)
                self.connection.execute("UPDATE schema_version SET version = ?", (i,))
                self.connection.commit()
                logging.info(f"Migration {i} applied")
                current = i

            logging.info(f"Database schema at version {current}")
        except sqlite3.Error as e:
            logging.error(f"Error initializing SQLite database: {e}")
            raise

    def add_user(self, username):
        self._connect()
        try:
            cursor = self.connection.execute(
                "INSERT OR IGNORE INTO users (username) VALUES (?)", (username,)
            )
            self.connection.commit()
            if cursor.rowcount > 0:
                logging.info(f"Added new user: {username}")
            return cursor.rowcount > 0
        except sqlite3.Error as e:
            logging.error(f"Error adding user {username}: {e}")
            raise

    def get_user_wallet(self, username):
        self._connect()
        try:
            cursor = self.connection.execute(
                "SELECT wallet FROM users WHERE username = ?", (username,)
            )
            result = cursor.fetchone()
            if result is None:
                return None
            return float(result['wallet'])
        except sqlite3.Error as e:
            logging.error(f"Error getting wallet for {username}: {e}")
            raise

    def update_wallet(self, username, amount):
        """Update a user's wallet. Returns True on success, False if update would go negative."""
        self._connect()
        try:
            if amount < 0:
                cursor = self.connection.execute(
                    "UPDATE users SET wallet = wallet + ? WHERE username = ? AND wallet + ? >= 0",
                    (amount, username, amount)
                )
            else:
                cursor = self.connection.execute(
                    "UPDATE users SET wallet = wallet + ? WHERE username = ?", (amount, username)
                )
            self.connection.commit()
            if cursor.rowcount > 0:
                logging.info(f"Updated wallet for {username} by {amount}")
            return cursor.rowcount > 0
        except sqlite3.Error as e:
            logging.error(f"Error updating wallet for {username}: {e}")
            raise

    def save_game(self, game_id, game_data):
        self._connect()
        try:
            self.connection.execute("""
                INSERT INTO games (
                    game_id, state, current_player_idx,
                    time_betting_started, time_last_hand_ended, time_last_event,
                    deck_json, discards_json, dealer_hand_json,
                    players_json, players_waiting_json, bets_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(game_id) DO UPDATE SET
                    state = excluded.state,
                    current_player_idx = excluded.current_player_idx,
                    time_betting_started = excluded.time_betting_started,
                    time_last_hand_ended = excluded.time_last_hand_ended,
                    time_last_event = excluded.time_last_event,
                    deck_json = excluded.deck_json,
                    discards_json = excluded.discards_json,
                    dealer_hand_json = excluded.dealer_hand_json,
                    players_json = excluded.players_json,
                    players_waiting_json = excluded.players_waiting_json,
                    bets_json = excluded.bets_json,
                    updated_at = CURRENT_TIMESTAMP
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
            logging.debug(f"Saved game {game_id}")
            return True
        except sqlite3.Error as e:
            logging.error(f"Error saving game {game_id}: {e}")
            raise

    def load_game(self, game_id):
        self._connect()
        try:
            cursor = self.connection.execute(
                "SELECT * FROM games WHERE game_id = ?", (game_id,)
            )
            result = cursor.fetchone()
            if result is None:
                return None
            return self._row_to_game(result)
        except sqlite3.Error as e:
            logging.error(f"Error loading game {game_id}: {e}")
            raise

    def load_all_active_games(self):
        self._connect()
        try:
            cursor = self.connection.execute("SELECT * FROM games WHERE state != 'waiting'")
            return [self._row_to_game(row) for row in cursor.fetchall()]
        except sqlite3.Error as e:
            logging.error(f"Error loading active games: {e}")
            raise

    def _row_to_game(self, result):
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

    def delete_game(self, game_id):
        self._connect()
        try:
            cursor = self.connection.execute(
                "DELETE FROM games WHERE game_id = ?", (game_id,)
            )
            self.connection.commit()
            if cursor.rowcount > 0:
                logging.info(f"Deleted game {game_id}")
            return cursor.rowcount > 0
        except sqlite3.Error as e:
            logging.error(f"Error deleting game {game_id}: {e}")
            raise

    def save_game_channel(self, game_id, guild_id, channel_id):
        self._connect()
        try:
            self.connection.execute("""
                INSERT INTO game_channels (game_id, guild_id, channel_id)
                VALUES (?, ?, ?)
                ON CONFLICT(game_id) DO UPDATE SET
                    guild_id = excluded.guild_id,
                    channel_id = excluded.channel_id
            """, (game_id, guild_id, channel_id))
            self.connection.commit()
            logging.debug(f"Saved game channel: {game_id} -> {guild_id}/{channel_id}")
            return True
        except sqlite3.Error as e:
            logging.error(f"Error saving game channel {game_id}: {e}")
            raise

    def load_game_channels(self):
        self._connect()
        try:
            cursor = self.connection.execute("SELECT * FROM game_channels")
            return [
                {
                    'game_id': r['game_id'],
                    'guild_id': r['guild_id'],
                    'channel_id': r['channel_id']
                }
                for r in cursor.fetchall()
            ]
        except sqlite3.Error as e:
            logging.error(f"Error loading game channels: {e}")
            raise

    def delete_game_channel(self, game_id):
        self._connect()
        try:
            cursor = self.connection.execute(
                "DELETE FROM game_channels WHERE game_id = ?", (game_id,)
            )
            self.connection.commit()
            if cursor.rowcount > 0:
                logging.debug(f"Deleted game channel {game_id}")
            return cursor.rowcount > 0
        except sqlite3.Error as e:
            logging.error(f"Error deleting game channel {game_id}: {e}")
            raise

    def close(self):
        if self.connection:
            self.connection.close()
            self.connection = None
            logging.info("SQLite database connection closed")
