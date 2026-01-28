#!/usr/bin/env python3
"""
End-to-end tests for the saloonbot server using the Redis interface.

These tests start Redis and MySQL via docker-compose, run the actual server,
and test the complete system integration without mocking.
"""
import json
import logging
import os
import signal
import subprocess
import time
import unittest

import mysql.connector
import redis

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)


class EndToEndTestCase(unittest.TestCase):
    """Base test case that manages docker-compose and server process."""

    @classmethod
    def setUpClass(cls):
        """Start docker-compose services and wait for them to be ready."""
        logging.info("Starting docker-compose services...")

        # Start docker-compose services
        cls.compose_process = subprocess.Popen(
            ['docker', 'compose', '-f', 'compose.test.yml', 'up', '--wait'],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )

        # Wait for services to be ready
        cls.compose_process.wait(timeout=60)

        # Give services a moment to fully stabilize
        time.sleep(2)

        logging.info("Docker-compose services ready")

        # Connect to Redis and MySQL to verify they're ready
        cls.redis = redis.Redis(host='localhost', port=6379, decode_responses=True)
        cls.redis.ping()

        # Test MySQL connection
        db = mysql.connector.connect(
            host='localhost',
            port=3306,
            user='saloonbot',
            password='saloonbot_password',
            database='saloonbot'
        )
        db.close()

        logging.info("Redis and MySQL are ready")

        # Start the server process
        env = os.environ.copy()
        env.update({
            'REDIS_HOST': 'localhost',
            'REDIS_PORT': '6379',
            'MYSQL_HOST': 'localhost',
            'MYSQL_PORT': '3306',
            'MYSQL_USER': 'saloonbot',
            'MYSQL_PASSWORD': 'saloonbot_password',
            'MYSQL_DATABASE': 'saloonbot',
            'SALOONBOT_DEBUG': '1'
        })

        cls.server_process = subprocess.Popen(
            ['python', 'server.py'],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )

        # Wait for server to be online
        time.sleep(3)

        # Verify server is running
        if cls.server_process.poll() is not None:
            raise RuntimeError("Server process failed to start")

        logging.info("Server process started")

    @classmethod
    def tearDownClass(cls):
        """Stop the server and docker-compose services."""
        # Stop the server process
        if cls.server_process and cls.server_process.poll() is None:
            logging.info("Stopping server process...")
            cls.server_process.send_signal(signal.SIGTERM)
            try:
                cls.server_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                cls.server_process.kill()
                cls.server_process.wait()

        # Close Redis connection
        if cls.redis:
            cls.redis.close()

        # Stop docker-compose services
        logging.info("Stopping docker-compose services...")
        subprocess.run(
            ['docker', 'compose', '-f', 'compose.test.yml', 'down', '-v'],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )

        logging.info("Cleanup complete")

    def setUp(self):
        """Set up for each test."""
        # Clean up Redis before each test
        self.redis.flushall()

        # Clean up MySQL before each test
        db = mysql.connector.connect(
            host='localhost',
            port=3306,
            user='saloonbot',
            password='saloonbot_password',
            database='saloonbot'
        )
        cursor = db.cursor()
        cursor.execute("DELETE FROM users")
        db.commit()
        cursor.close()
        db.close()

    def create_game(self):
        """Helper method to create a game and return the game_id."""
        pubsub = self.redis.pubsub()
        try:
            pubsub.subscribe("casino_update")
            pubsub.get_message(timeout=1)  # Skip subscribe confirmation

            request_id = f"test-request-{time.time()}"
            message = {
                'event_type': 'casino_action',
                'action': 'new_game',
                'request_id': request_id
            }
            self.redis.publish("casino", json.dumps(message))

            # Wait for game creation response
            for _ in range(20):  # Increased from 10 to give more time
                msg = pubsub.get_message(timeout=1)
                if msg and msg['type'] == 'message':
                    response = json.loads(msg['data'])
                    if response.get('request_id') == request_id:
                        return response['game_id']

            self.fail("Failed to create game")
        finally:
            pubsub.close()


class TestGameCreation(EndToEndTestCase):
    """Test game creation through Redis interface."""

    def test_create_new_game(self):
        """Test creating a new game and receiving the game_id."""
        pubsub = self.redis.pubsub()
        try:
            pubsub.subscribe("casino_update")

            # Skip the subscribe confirmation message
            pubsub.get_message(timeout=1)

            # Request a new game
            request_id = "test-request-123"
            message = {
                'event_type': 'casino_action',
                'action': 'new_game',
                'request_id': request_id
            }
            self.redis.publish("casino", json.dumps(message))

            # Wait for response
            response = None
            for _ in range(20):
                msg = pubsub.get_message(timeout=1)
                if msg and msg['type'] == 'message':
                    response = json.loads(msg['data'])
                    break

            self.assertIsNotNone(response, "Should receive a response for new game request")
            self.assertEqual(response['event_type'], 'new_game')
            self.assertEqual(response['request_id'], request_id)
            self.assertIn('game_id', response)
            self.assertIsInstance(response['game_id'], str)
        finally:
            pubsub.close()


class TestPlayerActions(EndToEndTestCase):
    """Test player actions in a game."""

    def test_player_join_game(self):
        """Test a player joining a game."""
        game_id = self.create_game()

        # Subscribe to game updates
        pubsub = self.redis.pubsub()
        try:
            pubsub.subscribe(f"game_updates_{game_id}")
            pubsub.get_message(timeout=1)  # Skip subscribe confirmation

            # Player joins the game
            message = {
                'event_type': 'player_action',
                'game_id': game_id,
                'player': 'TestPlayer1',
                'action': 'join'
            }
            self.redis.publish("casino", json.dumps(message))

            # Wait for join confirmation
            updates = []
            for _ in range(20):
                msg = pubsub.get_message(timeout=1)
                if msg and msg['type'] == 'message':
                    update = json.loads(msg['data'])
                    updates.append(update['text'])

            # Check that player joined
            join_messages = [u for u in updates if 'TestPlayer1' in u and 'join' in u]
            self.assertGreater(len(join_messages), 0, "Player should have joined the game")
        finally:
            pubsub.close()

    def test_database_user_creation(self):
        """Test that joining a game creates a user in the database."""
        game_id = self.create_game()

        # Subscribe to game updates
        pubsub = self.redis.pubsub()
        try:
            pubsub.subscribe(f"game_updates_{game_id}")
            pubsub.get_message(timeout=1)

            # Player joins
            player_name = 'DatabaseTestPlayer'
            message = {
                'event_type': 'player_action',
                'game_id': game_id,
                'player': player_name,
                'action': 'join'
            }
            self.redis.publish("casino", json.dumps(message))

            # Give it time to process
            time.sleep(2)

            # Check database
            db = mysql.connector.connect(
                host='localhost',
                port=3306,
                user='saloonbot',
                password='saloonbot_password',
                database='saloonbot'
            )
            cursor = db.cursor()
            cursor.execute("SELECT username FROM users WHERE username = %s", (player_name,))
            result = cursor.fetchone()
            cursor.close()
            db.close()

            self.assertIsNotNone(result, "User should be created in database")
            self.assertEqual(result[0], player_name)
        finally:
            pubsub.close()


class TestBlackjackGame(EndToEndTestCase):
    """Test a complete blackjack game flow."""

    def test_complete_blackjack_hand(self):
        """Test a complete blackjack hand with player actions."""
        game_id = self.create_game()

        # Subscribe to game updates
        pubsub = self.redis.pubsub()
        try:
            pubsub.subscribe(f"game_updates_{game_id}")
            pubsub.get_message(timeout=1)

            # Player joins
            message = {
                'event_type': 'player_action',
                'game_id': game_id,
                'player': 'Player1',
                'action': 'join'
            }
            self.redis.publish("casino", json.dumps(message))

            # Collect messages for initial join and hand start
            # The hand should start after TIME_BETWEEN_HANDS (10 seconds)
            all_updates = []
            start_time = time.time()
            while time.time() - start_time < 15:  # Wait up to 15 seconds
                msg = pubsub.get_message(timeout=1)
                if msg and msg['type'] == 'message':
                    update = json.loads(msg['data'])
                    all_updates.append(update['text'])

            # Check that hand started
            hand_started = any('New hand started' in u for u in all_updates)
            self.assertTrue(hand_started, "A hand should have started")

            # Player stands
            message = {
                'event_type': 'player_action',
                'game_id': game_id,
                'player': 'Player1',
                'action': 'stand'
            }
            self.redis.publish("casino", json.dumps(message))

            # Wait for dealer turn and end of hand
            for _ in range(20):
                msg = pubsub.get_message(timeout=1)
                if msg and msg['type'] == 'message':
                    update = json.loads(msg['data'])
                    all_updates.append(update['text'])

            # Verify game flow
            hand_ended = any('End of hand' in u for u in all_updates)
            self.assertTrue(hand_ended, "Hand should have ended")

            # Verify dealer played
            dealer_messages = [u for u in all_updates if 'Dealer' in u]
            self.assertGreater(len(dealer_messages), 0, "Dealer should have played")
        finally:
            pubsub.close()

    def test_player_hit_action(self):
        """Test player hitting (requesting a card)."""
        game_id = self.create_game()

        pubsub = self.redis.pubsub()
        try:
            pubsub.subscribe(f"game_updates_{game_id}")
            pubsub.get_message(timeout=1)

            # Player joins
            message = {
                'event_type': 'player_action',
                'game_id': game_id,
                'player': 'HitPlayer',
                'action': 'join'
            }
            self.redis.publish("casino", json.dumps(message))

            # Wait for hand to start (depends on server's TIME_BETWEEN_HANDS = 10 seconds)
            all_updates = []
            start_time = time.time()
            while time.time() - start_time < 15:
                msg = pubsub.get_message(timeout=1)
                if msg and msg['type'] == 'message':
                    update = json.loads(msg['data'])
                    all_updates.append(update['text'])
                    if 'New hand started' in update['text']:
                        break

            # Player hits
            message = {
                'event_type': 'player_action',
                'game_id': game_id,
                'player': 'HitPlayer',
                'action': 'hit'
            }
            self.redis.publish("casino", json.dumps(message))

            # Wait for hit result
            for _ in range(10):
                msg = pubsub.get_message(timeout=1)
                if msg and msg['type'] == 'message':
                    update = json.loads(msg['data'])
                    all_updates.append(update['text'])

            # Verify hit action was processed
            hit_messages = [u for u in all_updates if 'dealt' in u and 'HitPlayer' in u]
            self.assertGreater(len(hit_messages), 0, "Player should have been dealt a card")
        finally:
            pubsub.close()


if __name__ == "__main__":
    unittest.main()
