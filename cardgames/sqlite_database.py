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
    [   # Migration 2: NPC roster table
        """CREATE TABLE IF NOT EXISTS npcs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            personality_name TEXT NOT NULL,
            backstory TEXT NOT NULL DEFAULT '',
            wallet INTEGER NOT NULL DEFAULT 200,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_played_at TIMESTAMP NULL,
            current_game_id TEXT NULL
        )""",
    ],
    [   # Migration 3: LLM usage tracking
        """CREATE TABLE IF NOT EXISTS llm_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            occurred_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            purpose TEXT NOT NULL,
            model TEXT NOT NULL,
            input_tokens INTEGER NOT NULL DEFAULT 0,
            output_tokens INTEGER NOT NULL DEFAULT 0,
            npc_id INTEGER NULL,
            game_id TEXT NULL
        )""",
    ],
    [   # Migration 4: player statistics for fame system
        "ALTER TABLE users ADD COLUMN games_played INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE users ADD COLUMN hands_played INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE users ADD COLUMN total_won REAL NOT NULL DEFAULT 0",
        "ALTER TABLE users ADD COLUMN total_lost REAL NOT NULL DEFAULT 0",
        "ALTER TABLE users ADD COLUMN biggest_win REAL NOT NULL DEFAULT 0",
        "ALTER TABLE users ADD COLUMN last_seen TIMESTAMP NULL",
    ],
    [   # Migration 5: runtime settings key/value store
        """CREATE TABLE IF NOT EXISTS settings (
            setting_key TEXT PRIMARY KEY,
            setting_value TEXT NOT NULL
        )""",
    ],
    [   # Migration 6: convert wallet/stats columns from dollars to integer cents
        "ALTER TABLE users ADD COLUMN wallet_cents INTEGER NOT NULL DEFAULT 20000",
        "UPDATE users SET wallet_cents = CAST(ROUND(wallet * 100) AS INTEGER)",
        "ALTER TABLE users DROP COLUMN wallet",
        "ALTER TABLE users ADD COLUMN total_won_cents INTEGER NOT NULL DEFAULT 0",
        "UPDATE users SET total_won_cents = CAST(ROUND(total_won * 100) AS INTEGER)",
        "ALTER TABLE users DROP COLUMN total_won",
        "ALTER TABLE users ADD COLUMN total_lost_cents INTEGER NOT NULL DEFAULT 0",
        "UPDATE users SET total_lost_cents = CAST(ROUND(total_lost * 100) AS INTEGER)",
        "ALTER TABLE users DROP COLUMN total_lost",
        "ALTER TABLE users ADD COLUMN biggest_win_cents INTEGER NOT NULL DEFAULT 0",
        "UPDATE users SET biggest_win_cents = CAST(ROUND(biggest_win * 100) AS INTEGER)",
        "ALTER TABLE users DROP COLUMN biggest_win",
        "ALTER TABLE npcs ADD COLUMN wallet_cents INTEGER NOT NULL DEFAULT 20000",
        "UPDATE npcs SET wallet_cents = wallet * 100",
        "ALTER TABLE npcs DROP COLUMN wallet",
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
        """Get the wallet balance for a user, in cents."""
        self._connect()
        try:
            cursor = self.connection.execute(
                "SELECT wallet_cents FROM users WHERE username = ?", (username,)
            )
            result = cursor.fetchone()
            if result is None:
                return None
            return int(result['wallet_cents'])
        except sqlite3.Error as e:
            logging.error(f"Error getting wallet for {username}: {e}")
            raise

    def update_wallet(self, username, amount_cents):
        """Update a user's wallet by an amount in cents. Returns True on success, False if update would go negative."""
        self._connect()
        try:
            amount_cents_int = int(amount_cents)
            if amount_cents_int < 0:
                cursor = self.connection.execute(
                    "UPDATE users SET wallet_cents = wallet_cents + ? "
                    "WHERE username = ? AND wallet_cents + ? >= 0",
                    (amount_cents_int, username, amount_cents_int)
                )
            else:
                cursor = self.connection.execute(
                    "UPDATE users SET wallet_cents = wallet_cents + ? WHERE username = ?",
                    (amount_cents_int, username)
                )
            self.connection.commit()
            if cursor.rowcount > 0:
                logging.debug(f"Updated wallet for {username} by {amount_cents_int}")
            return cursor.rowcount > 0
        except sqlite3.Error as e:
            logging.error(f"Error updating wallet for {username}: {e}")
            raise

    def set_user_wallet(self, username, amount_cents):
        """Set a user's wallet to an absolute amount in cents. Returns True on success."""
        self._connect()
        try:
            cursor = self.connection.execute(
                "UPDATE users SET wallet_cents = ? WHERE username = ?",
                (int(amount_cents), username)
            )
            self.connection.commit()
            if cursor.rowcount > 0:
                logging.debug(f"Set wallet for {username} to {amount_cents}")
            return cursor.rowcount > 0
        except sqlite3.Error as e:
            logging.error(f"Error setting wallet for {username}: {e}")
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
        """Load all persisted games from database, regardless of state."""
        self._connect()
        try:
            cursor = self.connection.execute("SELECT * FROM games")
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

    def create_npc(self, name, personality_name, wallet_cents):
        """Create a new NPC record. Returns the new npc id."""
        self._connect()
        try:
            cursor = self.connection.execute(
                "INSERT INTO npcs (name, personality_name, wallet_cents) VALUES (?, ?, ?)",
                (name, personality_name, int(wallet_cents))
            )
            self.connection.commit()
            return cursor.lastrowid
        except sqlite3.Error as e:
            logging.error(f"Error creating NPC {name}: {e}")
            raise

    def get_available_npcs(self, limit, exclude_personality_names=None):
        """Get available NPCs (current_game_id IS NULL). Returns list of dicts."""
        self._connect()
        try:
            excl = list(exclude_personality_names) if exclude_personality_names else []
            if excl:
                placeholders = ','.join(['?'] * len(excl))
                cursor = self.connection.execute(
                    f"SELECT * FROM npcs WHERE current_game_id IS NULL"
                    f" AND personality_name NOT IN ({placeholders})"
                    f" ORDER BY RANDOM() LIMIT ?",
                    excl + [limit]
                )
            else:
                cursor = self.connection.execute(
                    "SELECT * FROM npcs WHERE current_game_id IS NULL ORDER BY RANDOM() LIMIT ?",
                    (limit,)
                )
            return [dict(r) for r in cursor.fetchall()]
        except sqlite3.Error as e:
            logging.error(f"Error getting available NPCs: {e}")
            raise

    def get_npc_by_id(self, npc_id):
        """Get NPC by id. Returns dict or None."""
        self._connect()
        try:
            cursor = self.connection.execute("SELECT * FROM npcs WHERE id = ?", (npc_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
        except sqlite3.Error as e:
            logging.error(f"Error getting NPC {npc_id}: {e}")
            raise

    def get_all_npcs(self):
        """Get all NPCs ordered by name. Returns list of dicts."""
        self._connect()
        try:
            cursor = self.connection.execute("SELECT * FROM npcs ORDER BY name")
            return [dict(row) for row in cursor.fetchall()]
        except sqlite3.Error as e:
            logging.error(f"Error getting all NPCs: {e}")
            raise

    def find_npc_by_name(self, name):
        """Find an NPC by name (case-insensitive). Returns dict or None."""
        self._connect()
        try:
            cursor = self.connection.execute(
                "SELECT * FROM npcs WHERE LOWER(name) = LOWER(?)", (name,)
            )
            row = cursor.fetchone()
            return dict(row) if row else None
        except sqlite3.Error as e:
            logging.error(f"Error finding NPC by name {name}: {e}")
            raise

    def get_npc_wallet(self, npc_id):
        """Get NPC wallet balance in cents. Returns int or None."""
        self._connect()
        try:
            cursor = self.connection.execute(
                "SELECT wallet_cents FROM npcs WHERE id = ?", (npc_id,)
            )
            row = cursor.fetchone()
            return int(row[0]) if row else None
        except sqlite3.Error as e:
            logging.error(f"Error getting NPC wallet {npc_id}: {e}")
            raise

    def update_npc_wallet(self, npc_id, amount_cents):
        """Add amount_cents to NPC wallet. Returns True on success, False if would go negative."""
        self._connect()
        try:
            amount_cents_int = int(amount_cents)
            if amount_cents_int < 0:
                cursor = self.connection.execute(
                    "UPDATE npcs SET wallet_cents = wallet_cents + ? "
                    "WHERE id = ? AND wallet_cents + ? >= 0",
                    (amount_cents_int, npc_id, amount_cents_int)
                )
            else:
                cursor = self.connection.execute(
                    "UPDATE npcs SET wallet_cents = wallet_cents + ? WHERE id = ?",
                    (amount_cents_int, npc_id)
                )
            self.connection.commit()
            return cursor.rowcount > 0
        except sqlite3.Error as e:
            logging.error(f"Error updating NPC wallet {npc_id}: {e}")
            raise

    def set_npc_wallet(self, npc_id, amount_cents):
        """Set an NPC's wallet to an absolute amount in cents. Returns True on success."""
        self._connect()
        try:
            cursor = self.connection.execute(
                "UPDATE npcs SET wallet_cents = ? WHERE id = ?", (int(amount_cents), npc_id)
            )
            self.connection.commit()
            return cursor.rowcount > 0
        except sqlite3.Error as e:
            logging.error(f"Error setting NPC wallet {npc_id}: {e}")
            raise

    def set_npc_game(self, npc_id, game_id):
        """Assign NPC to a game and update last_played_at."""
        self._connect()
        try:
            self.connection.execute(
                "UPDATE npcs SET current_game_id = ?, last_played_at = CURRENT_TIMESTAMP WHERE id = ?",
                (game_id, npc_id)
            )
            self.connection.commit()
        except sqlite3.Error as e:
            logging.error(f"Error setting NPC game {npc_id}: {e}")
            raise

    def clear_npc_game(self, npc_id):
        """Clear an NPC's current_game_id."""
        self._connect()
        try:
            self.connection.execute(
                "UPDATE npcs SET current_game_id = NULL WHERE id = ?", (npc_id,)
            )
            self.connection.commit()
        except sqlite3.Error as e:
            logging.error(f"Error clearing NPC game {npc_id}: {e}")
            raise

    def count_npcs(self):
        """Return total number of NPC records."""
        self._connect()
        try:
            cursor = self.connection.execute("SELECT COUNT(*) FROM npcs")
            return cursor.fetchone()[0]
        except sqlite3.Error as e:
            logging.error(f"Error counting NPCs: {e}")
            raise

    def clear_stale_npc_games(self, active_game_ids):
        """Clear current_game_id for NPCs whose game is no longer active."""
        self._connect()
        try:
            if active_game_ids:
                placeholders = ','.join(['?'] * len(active_game_ids))
                self.connection.execute(
                    f"UPDATE npcs SET current_game_id = NULL"
                    f" WHERE current_game_id IS NOT NULL"
                    f" AND current_game_id NOT IN ({placeholders})",
                    list(active_game_ids)
                )
            else:
                self.connection.execute(
                    "UPDATE npcs SET current_game_id = NULL WHERE current_game_id IS NOT NULL"
                )
            self.connection.commit()
        except sqlite3.Error as e:
            logging.error(f"Error clearing stale NPC games: {e}")
            raise

    def update_npc_backstory(self, npc_id, backstory):
        """Set the backstory text for an NPC."""
        self._connect()
        try:
            self.connection.execute("UPDATE npcs SET backstory = ? WHERE id = ?", (backstory, npc_id))
            self.connection.commit()
        except sqlite3.Error as e:
            logging.error(f"Error updating NPC backstory {npc_id}: {e}")
            raise

    def log_llm_usage(self, purpose, model, input_tokens, output_tokens, npc_id=None, game_id=None):
        """Record a single LLM API call for usage tracking."""
        self._connect()
        try:
            self.connection.execute("""
                INSERT INTO llm_usage (purpose, model, input_tokens, output_tokens, npc_id, game_id)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (purpose, model, input_tokens, output_tokens, npc_id, game_id))
            self.connection.commit()
        except sqlite3.Error as e:
            logging.error(f"Error logging LLM usage: {e}")
            raise

    def get_llm_usage_summary(self, days=7):
        """Return token totals grouped by purpose for the past N days."""
        self._connect()
        try:
            cursor = self.connection.execute("""
                SELECT purpose, model,
                       SUM(input_tokens) AS total_input,
                       SUM(output_tokens) AS total_output,
                       COUNT(*) AS call_count
                FROM llm_usage
                WHERE occurred_at >= datetime('now', ?)
                GROUP BY purpose, model
                ORDER BY total_input + total_output DESC
            """, (f'-{days} days',))
            return [dict(r) for r in cursor.fetchall()]
        except sqlite3.Error as e:
            logging.error(f"Error getting LLM usage summary: {e}")
            raise

    def increment_games_played(self, username):
        """Increment games_played and refresh last_seen for a human player."""
        self._connect()
        try:
            self.connection.execute("""
                UPDATE users SET games_played = games_played + 1,
                    last_seen = CURRENT_TIMESTAMP
                WHERE username = ?
            """, (username,))
            self.connection.commit()
        except sqlite3.Error as e:
            logging.error(f"Error in increment_games_played({username}): {e}")
            raise

    def update_player_stats(self, username, won_cents=0, lost_cents=0):
        """Record the outcome of a hand for a human player. Amounts are in cents."""
        self._connect()
        try:
            self.connection.execute("""
                UPDATE users SET
                    hands_played = hands_played + 1,
                    total_won_cents = total_won_cents + ?,
                    total_lost_cents = total_lost_cents + ?,
                    biggest_win_cents = CASE WHEN ? > biggest_win_cents THEN ? ELSE biggest_win_cents END,
                    last_seen = CURRENT_TIMESTAMP
                WHERE username = ?
            """, (won_cents, lost_cents, won_cents, won_cents, username))
            self.connection.commit()
        except sqlite3.Error as e:
            logging.error(f"Error in update_player_stats({username}): {e}")
            raise

    def get_player_stats(self, username):
        """Return stats dict for a player, or None if not found. Money fields are in cents."""
        self._connect()
        try:
            cursor = self.connection.execute("""
                SELECT games_played, hands_played,
                       total_won_cents, total_lost_cents, biggest_win_cents, last_seen
                FROM users WHERE username = ?
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
        except sqlite3.Error as e:
            logging.error(f"Error getting player stats for {username}: {e}")
            raise

    def get_setting(self, key, default=None):
        """Get a runtime setting value (string), or default if not set."""
        self._connect()
        try:
            cursor = self.connection.execute(
                "SELECT setting_value FROM settings WHERE setting_key = ?", (key,)
            )
            row = cursor.fetchone()
            return row['setting_value'] if row else default
        except sqlite3.Error as e:
            logging.error(f"Error getting setting {key}: {e}")
            raise

    def set_setting(self, key, value):
        """Set a runtime setting value (stored as a string), upserting on key."""
        self._connect()
        try:
            self.connection.execute("""
                INSERT INTO settings (setting_key, setting_value) VALUES (?, ?)
                ON CONFLICT(setting_key) DO UPDATE SET setting_value = excluded.setting_value
            """, (key, str(value)))
            self.connection.commit()
            logging.debug(f"Set setting {key} = {value}")
        except sqlite3.Error as e:
            logging.error(f"Error setting {key}: {e}")
            raise

    def close(self):
        if self.connection:
            self.connection.close()
            self.connection = None
            logging.info("SQLite database connection closed")
