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

    def close(self):
        """Close the database connection."""
        if self.connection and self.connection.is_connected():
            self.connection.close()
            logging.info("Database connection closed")
