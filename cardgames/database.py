import functools
import json
import logging
import threading
import time

import mysql.connector
from mysql.connector import Error

_DEADLOCK_ERRNO = 1213
_DEADLOCK_RETRIES = 3
_DEADLOCK_BACKOFF_BASE = 0.05  # seconds

DEFAULT_WALLET = 200.0


def _synchronized(method):
    """Serialize access to the shared DB connection: the main game loop and
    NPC worker threads (usage logging, session memories) all use this object,
    and mysql.connector connections are not safe for concurrent use."""
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)
    return wrapper


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
    [   # Migration 2: NPC roster table
        """CREATE TABLE IF NOT EXISTS npcs (
            id INT AUTO_INCREMENT PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            personality_name VARCHAR(255) NOT NULL,
            backstory TEXT NOT NULL,
            wallet INT NOT NULL DEFAULT 200,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_played_at TIMESTAMP NULL,
            current_game_id VARCHAR(36) NULL
        )""",
    ],
    [   # Migration 3: LLM usage tracking
        """CREATE TABLE IF NOT EXISTS llm_usage (
            id INT AUTO_INCREMENT PRIMARY KEY,
            occurred_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            purpose VARCHAR(64) NOT NULL,
            model VARCHAR(128) NOT NULL,
            input_tokens INT NOT NULL DEFAULT 0,
            output_tokens INT NOT NULL DEFAULT 0,
            npc_id INT NULL,
            game_id VARCHAR(36) NULL
        )""",
    ],
    [   # Migration 4: player statistics for fame system
        "ALTER TABLE users ADD COLUMN games_played INT NOT NULL DEFAULT 0",
        "ALTER TABLE users ADD COLUMN hands_played INT NOT NULL DEFAULT 0",
        "ALTER TABLE users ADD COLUMN total_won DECIMAL(10, 2) NOT NULL DEFAULT 0",
        "ALTER TABLE users ADD COLUMN total_lost DECIMAL(10, 2) NOT NULL DEFAULT 0",
        "ALTER TABLE users ADD COLUMN biggest_win DECIMAL(10, 2) NOT NULL DEFAULT 0",
        "ALTER TABLE users ADD COLUMN last_seen TIMESTAMP NULL",
    ],
    [   # Migration 5: runtime settings key/value store
        """CREATE TABLE IF NOT EXISTS settings (
            setting_key VARCHAR(64) PRIMARY KEY,
            setting_value TEXT NOT NULL
        )""",
    ],
    [   # Migration 6: convert wallet/stats columns from dollars to integer cents
        "ALTER TABLE users ADD COLUMN wallet_cents INT NOT NULL DEFAULT 20000",
        "UPDATE users SET wallet_cents = ROUND(wallet * 100)",
        "ALTER TABLE users DROP COLUMN wallet",
        "ALTER TABLE users ADD COLUMN total_won_cents INT NOT NULL DEFAULT 0",
        "UPDATE users SET total_won_cents = ROUND(total_won * 100)",
        "ALTER TABLE users DROP COLUMN total_won",
        "ALTER TABLE users ADD COLUMN total_lost_cents INT NOT NULL DEFAULT 0",
        "UPDATE users SET total_lost_cents = ROUND(total_lost * 100)",
        "ALTER TABLE users DROP COLUMN total_lost",
        "ALTER TABLE users ADD COLUMN biggest_win_cents INT NOT NULL DEFAULT 0",
        "UPDATE users SET biggest_win_cents = ROUND(biggest_win * 100)",
        "ALTER TABLE users DROP COLUMN biggest_win",
        "ALTER TABLE npcs ADD COLUMN wallet_cents INT NOT NULL DEFAULT 20000",
        "UPDATE npcs SET wallet_cents = wallet * 100",
        "ALTER TABLE npcs DROP COLUMN wallet",
    ],
    [   # Migration 7: NPC session memories
        """CREATE TABLE IF NOT EXISTS npc_memories (
            id INT AUTO_INCREMENT PRIMARY KEY,
            npc_id INT NOT NULL,
            game_id VARCHAR(36) NULL,
            session_summary TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            KEY idx_npc_memories_npc (npc_id)
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
        self._lock = threading.RLock()
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

    @_synchronized
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

    @_synchronized
    def get_user_wallet(self, username):
        """Get the wallet balance for a user, in cents."""
        self._connect()
        self.connection.commit()  # end any open txn so we read the latest committed data
        cursor = None
        try:
            cursor = self.connection.cursor()
            cursor.execute("""
                SELECT wallet_cents FROM users WHERE username = %s
            """, (username,))
            result = cursor.fetchone()
            if result is None:
                return None
            return int(result[0])
        except Error as e:
            logging.error(f"Error getting wallet for {username}: {e}")
            raise
        finally:
            if cursor:
                cursor.close()

    @_synchronized
    def update_wallet(self, username, amount_cents):
        """Update a user's wallet by adding or subtracting an amount, in cents.

        Returns True on success, False if the update would make the wallet negative.
        """
        def fn(cursor):
            amount_cents_int = int(amount_cents)
            if amount_cents_int < 0:
                cursor.execute("""
                    UPDATE users SET wallet_cents = wallet_cents + %s
                    WHERE username = %s AND wallet_cents + %s >= 0
                """, (amount_cents_int, username, amount_cents_int))
            else:
                cursor.execute("""
                    UPDATE users SET wallet_cents = wallet_cents + %s WHERE username = %s
                """, (amount_cents_int, username))
            rows_affected = cursor.rowcount
            if rows_affected > 0:
                logging.debug(f"Updated wallet for {username} by {amount_cents_int}")
            return rows_affected > 0

        return self._execute_write(fn, f"update_wallet({username})")

    @_synchronized
    def set_user_wallet(self, username, amount_cents):
        """Set a user's wallet to an absolute amount, in cents. Returns True on success."""
        def fn(cursor):
            cursor.execute(
                "UPDATE users SET wallet_cents = %s WHERE username = %s",
                (int(amount_cents), username)
            )
            rows_affected = cursor.rowcount
            if rows_affected > 0:
                logging.debug(f"Set wallet for {username} to {amount_cents}")
            return rows_affected > 0

        return self._execute_write(fn, f"set_user_wallet({username})")

    @_synchronized
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

    @_synchronized
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

    @_synchronized
    def load_all_active_games(self):
        """Load all persisted games from database, regardless of state."""
        self._connect()
        cursor = None
        try:
            cursor = self.connection.cursor(dictionary=True)
            cursor.execute("SELECT * FROM games")
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

    @_synchronized
    def delete_game(self, game_id):
        """Delete a game from database."""
        def fn(cursor):
            cursor.execute("DELETE FROM games WHERE game_id = %s", (game_id,))
            rows_affected = cursor.rowcount
            if rows_affected > 0:
                logging.info(f"Deleted game {game_id}")
            return rows_affected > 0

        return self._execute_write(fn, f"delete_game({game_id})")

    @_synchronized
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

    @_synchronized
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

    @_synchronized
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

    @_synchronized
    def create_npc(self, name, personality_name, wallet_cents):
        """Create a new NPC record. Returns the new npc id."""
        def fn(cursor):
            cursor.execute("""
                INSERT INTO npcs (name, personality_name, backstory, wallet_cents) VALUES (%s, %s, '', %s)
            """, (name, personality_name, int(wallet_cents)))
            return cursor.lastrowid
        return self._execute_write(fn, f"create_npc({name})")

    @_synchronized
    def get_available_npcs(self, limit, exclude_personality_names=None):
        """Get available NPCs (current_game_id IS NULL). Returns list of dicts."""
        self._connect()
        cursor = None
        try:
            cursor = self.connection.cursor(dictionary=True)
            excl = list(exclude_personality_names) if exclude_personality_names else []
            if excl:
                placeholders = ','.join(['%s'] * len(excl))
                cursor.execute(
                    f"SELECT * FROM npcs WHERE current_game_id IS NULL"
                    f" AND personality_name NOT IN ({placeholders})"
                    f" ORDER BY RAND() LIMIT %s",
                    excl + [limit]
                )
            else:
                cursor.execute(
                    "SELECT * FROM npcs WHERE current_game_id IS NULL ORDER BY RAND() LIMIT %s",
                    (limit,)
                )
            return cursor.fetchall()
        except Error as e:
            logging.error(f"Error getting available NPCs: {e}")
            raise
        finally:
            if cursor:
                cursor.close()

    @_synchronized
    def get_npc_by_id(self, npc_id):
        """Get NPC by id. Returns dict or None."""
        self._connect()
        cursor = None
        try:
            cursor = self.connection.cursor(dictionary=True)
            cursor.execute("SELECT * FROM npcs WHERE id = %s", (npc_id,))
            return cursor.fetchone()
        except Error as e:
            logging.error(f"Error getting NPC {npc_id}: {e}")
            raise
        finally:
            if cursor:
                cursor.close()

    @_synchronized
    def get_all_npcs(self):
        """Get all NPCs ordered by name. Returns list of dicts."""
        self._connect()
        cursor = None
        try:
            cursor = self.connection.cursor(dictionary=True)
            cursor.execute("SELECT * FROM npcs ORDER BY name")
            return cursor.fetchall()
        except Error as e:
            logging.error(f"Error getting all NPCs: {e}")
            raise
        finally:
            if cursor:
                cursor.close()

    @_synchronized
    def find_npc_by_name(self, name):
        """Find an NPC by name (case-insensitive). Returns dict or None."""
        self._connect()
        self.connection.commit()  # end any open txn so we read the latest committed data
        cursor = None
        try:
            cursor = self.connection.cursor(dictionary=True)
            cursor.execute("SELECT * FROM npcs WHERE LOWER(name) = LOWER(%s)", (name,))
            return cursor.fetchone()
        except Error as e:
            logging.error(f"Error finding NPC by name {name}: {e}")
            raise
        finally:
            if cursor:
                cursor.close()

    @_synchronized
    def get_npc_wallet(self, npc_id):
        """Get NPC wallet balance in cents. Returns int or None."""
        self._connect()
        self.connection.commit()  # end any open txn so we read the latest committed data
        cursor = None
        try:
            cursor = self.connection.cursor()
            cursor.execute("SELECT wallet_cents FROM npcs WHERE id = %s", (npc_id,))
            result = cursor.fetchone()
            return int(result[0]) if result else None
        except Error as e:
            logging.error(f"Error getting NPC wallet {npc_id}: {e}")
            raise
        finally:
            if cursor:
                cursor.close()

    @_synchronized
    def update_npc_wallet(self, npc_id, amount_cents):
        """Add amount_cents to NPC wallet. Returns True on success, False if would go negative."""
        def fn(cursor):
            amount_cents_int = int(amount_cents)
            if amount_cents_int < 0:
                cursor.execute("""
                    UPDATE npcs SET wallet_cents = wallet_cents + %s
                    WHERE id = %s AND wallet_cents + %s >= 0
                """, (amount_cents_int, npc_id, amount_cents_int))
            else:
                cursor.execute(
                    "UPDATE npcs SET wallet_cents = wallet_cents + %s WHERE id = %s",
                    (amount_cents_int, npc_id)
                )
            return cursor.rowcount > 0
        return self._execute_write(fn, f"update_npc_wallet({npc_id})")

    @_synchronized
    def set_npc_wallet(self, npc_id, amount_cents):
        """Set an NPC's wallet to an absolute amount in cents. Returns True on success."""
        def fn(cursor):
            cursor.execute(
                "UPDATE npcs SET wallet_cents = %s WHERE id = %s", (int(amount_cents), npc_id)
            )
            return cursor.rowcount > 0
        return self._execute_write(fn, f"set_npc_wallet({npc_id})")

    @_synchronized
    def set_npc_game(self, npc_id, game_id):
        """Assign NPC to a game and update last_played_at."""
        def fn(cursor):
            cursor.execute("""
                UPDATE npcs SET current_game_id = %s, last_played_at = NOW()
                WHERE id = %s
            """, (game_id, npc_id))
        return self._execute_write(fn, f"set_npc_game({npc_id})")

    @_synchronized
    def clear_npc_game(self, npc_id):
        """Clear an NPC's current_game_id."""
        def fn(cursor):
            cursor.execute(
                "UPDATE npcs SET current_game_id = NULL WHERE id = %s", (npc_id,)
            )
        return self._execute_write(fn, f"clear_npc_game({npc_id})")

    @_synchronized
    def count_npcs(self):
        """Return total number of NPC records."""
        self._connect()
        cursor = None
        try:
            cursor = self.connection.cursor()
            cursor.execute("SELECT COUNT(*) FROM npcs")
            return cursor.fetchone()[0]
        except Error as e:
            logging.error(f"Error counting NPCs: {e}")
            raise
        finally:
            if cursor:
                cursor.close()

    @_synchronized
    def clear_stale_npc_games(self, active_game_ids):
        """Clear current_game_id for NPCs whose game is no longer active."""
        def fn(cursor):
            if active_game_ids:
                placeholders = ','.join(['%s'] * len(active_game_ids))
                cursor.execute(
                    f"UPDATE npcs SET current_game_id = NULL"
                    f" WHERE current_game_id IS NOT NULL"
                    f" AND current_game_id NOT IN ({placeholders})",
                    list(active_game_ids)
                )
            else:
                cursor.execute("UPDATE npcs SET current_game_id = NULL WHERE current_game_id IS NOT NULL")
        return self._execute_write(fn, "clear_stale_npc_games")

    @_synchronized
    def update_npc_backstory(self, npc_id, backstory):
        """Set the backstory text for an NPC."""
        def fn(cursor):
            cursor.execute("UPDATE npcs SET backstory = %s WHERE id = %s", (backstory, npc_id))
        return self._execute_write(fn, f"update_npc_backstory({npc_id})")

    @_synchronized
    def add_npc_memory(self, npc_id, game_id, session_summary, max_rows):
        """Insert a session memory for an NPC, pruning to the max_rows most recent."""
        def fn(cursor):
            cursor.execute("""
                INSERT INTO npc_memories (npc_id, game_id, session_summary)
                VALUES (%s, %s, %s)
            """, (npc_id, game_id, session_summary))
            memory_id = cursor.lastrowid
            cursor.execute("""
                DELETE FROM npc_memories WHERE npc_id = %s AND id NOT IN (
                    SELECT id FROM (
                        SELECT id FROM npc_memories WHERE npc_id = %s
                        ORDER BY id DESC LIMIT %s
                    ) AS keep
                )
            """, (npc_id, npc_id, int(max_rows)))
            return memory_id
        return self._execute_write(fn, f"add_npc_memory({npc_id})")

    @_synchronized
    def get_npc_memories(self, npc_id, limit):
        """Return the most recent session memories for an NPC, newest first. List of dicts."""
        self._connect()
        self.connection.commit()  # end any open txn so we read the latest committed data
        cursor = None
        try:
            cursor = self.connection.cursor(dictionary=True)
            cursor.execute(
                "SELECT * FROM npc_memories WHERE npc_id = %s ORDER BY id DESC LIMIT %s",
                (npc_id, int(limit))
            )
            return cursor.fetchall()
        except Error as e:
            logging.error(f"Error getting NPC memories {npc_id}: {e}")
            raise
        finally:
            if cursor:
                cursor.close()

    @_synchronized
    def log_llm_usage(self, purpose, model, input_tokens, output_tokens, npc_id=None, game_id=None):
        """Record a single LLM API call for usage tracking."""
        def fn(cursor):
            cursor.execute("""
                INSERT INTO llm_usage (purpose, model, input_tokens, output_tokens, npc_id, game_id)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (purpose, model, input_tokens, output_tokens, npc_id, game_id))
        return self._execute_write(fn, "log_llm_usage")

    @_synchronized
    def get_llm_usage_summary(self, days=7):
        """Return token totals grouped by purpose for the past N days."""
        self._connect()
        cursor = None
        try:
            cursor = self.connection.cursor(dictionary=True)
            cursor.execute("""
                SELECT purpose, model,
                       SUM(input_tokens) AS total_input,
                       SUM(output_tokens) AS total_output,
                       COUNT(*) AS call_count
                FROM llm_usage
                WHERE occurred_at >= NOW() - INTERVAL %s DAY
                GROUP BY purpose, model
                ORDER BY total_input + total_output DESC
            """, (days,))
            return cursor.fetchall()
        except Error as e:
            logging.error(f"Error getting LLM usage summary: {e}")
            raise
        finally:
            if cursor:
                cursor.close()

    @_synchronized
    def increment_games_played(self, username):
        """Increment games_played and refresh last_seen for a human player."""
        def fn(cursor):
            cursor.execute("""
                UPDATE users SET games_played = games_played + 1, last_seen = NOW()
                WHERE username = %s
            """, (username,))
        return self._execute_write(fn, f"increment_games_played({username})")

    @_synchronized
    def update_player_stats(self, username, won_cents=0, lost_cents=0):
        """Record the outcome of a hand for a human player. Amounts are in cents."""
        def fn(cursor):
            cursor.execute("""
                UPDATE users SET
                    hands_played = hands_played + 1,
                    total_won_cents = total_won_cents + %s,
                    total_lost_cents = total_lost_cents + %s,
                    biggest_win_cents = GREATEST(biggest_win_cents, %s),
                    last_seen = NOW()
                WHERE username = %s
            """, (won_cents, lost_cents, won_cents, username))
        return self._execute_write(fn, f"update_player_stats({username})")

    @_synchronized
    def get_player_stats(self, username):
        """Return stats dict for a player, or None if not found. Money fields are in cents."""
        self._connect()
        cursor = None
        try:
            cursor = self.connection.cursor(dictionary=True)
            cursor.execute("""
                SELECT games_played, hands_played,
                       total_won_cents, total_lost_cents, biggest_win_cents, last_seen
                FROM users WHERE username = %s
            """, (username,))
            row = cursor.fetchone()
            if row is None:
                return None
            return {
                'games_played': int(row['games_played']),
                'hands_played': int(row['hands_played']),
                'total_won_cents': int(row['total_won_cents']),
                'total_lost_cents': int(row['total_lost_cents']),
                'biggest_win_cents': int(row['biggest_win_cents']),
                'last_seen': str(row['last_seen']) if row['last_seen'] else None,
            }
        except Error as e:
            logging.error(f"Error getting player stats for {username}: {e}")
            raise
        finally:
            if cursor:
                cursor.close()

    @_synchronized
    def get_setting(self, key, default=None):
        """Get a runtime setting value (string), or default if not set."""
        self._connect()
        cursor = None
        try:
            cursor = self.connection.cursor()
            cursor.execute(
                "SELECT setting_value FROM settings WHERE setting_key = %s", (key,)
            )
            result = cursor.fetchone()
            return result[0] if result else default
        except Error as e:
            logging.error(f"Error getting setting {key}: {e}")
            raise
        finally:
            if cursor:
                cursor.close()

    @_synchronized
    def set_setting(self, key, value):
        """Set a runtime setting value (stored as a string), upserting on key."""
        def fn(cursor):
            cursor.execute("""
                INSERT INTO settings (setting_key, setting_value) VALUES (%s, %s) AS new
                ON DUPLICATE KEY UPDATE setting_value = new.setting_value
            """, (key, str(value)))
            logging.debug(f"Set setting {key} = {value}")
        return self._execute_write(fn, f"set_setting({key})")

    @_synchronized
    def close(self):
        """Close the database connection."""
        if self.connection and self.connection.is_connected():
            self.connection.close()
            logging.info("Database connection closed")
