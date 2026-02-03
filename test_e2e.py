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

# Module-level resources shared across all test classes
_redis = None
_db = None


def setUpModule():
    """Start docker-compose services once for all tests."""
    global _redis, _db

    logging.info("Starting docker-compose services...")

    # Start docker-compose services
    subprocess.run(
        ['docker', 'compose', '-f', 'compose.test.yml', 'up', '--wait'],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=60
    )

    # Give services a moment to fully stabilize
    time.sleep(2)

    logging.info("Docker-compose services ready")

    # Connect to Redis and MySQL to verify they're ready
    _redis = redis.Redis(host='localhost', port=6379, decode_responses=True)
    _redis.ping()

    # Test MySQL connection and keep it for the module
    _db = mysql.connector.connect(
        host='localhost',
        port=3306,
        user='saloonbot',
        password='saloonbot_password',
        database='saloonbot'
    )

    logging.info("Redis and MySQL are ready")


def tearDownModule():
    """Stop docker-compose services after all tests."""
    # Close Redis connection
    if _redis:
        _redis.close()

    # Close MySQL connection
    if _db:
        _db.close()

    # Stop docker-compose services
    logging.info("Stopping docker-compose services...")
    subprocess.run(
        ['docker', 'compose', '-f', 'compose.test.yml', 'down', '-v'],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )

    logging.info("Cleanup complete")


class EndToEndTestCase(unittest.TestCase):
    """Base test case that manages the server process."""

    server_process = None

    @classmethod
    def setUpClass(cls):
        """Start the server process (docker-compose already running)."""
        # Reference module-level resources
        cls.redis = _redis
        cls.db = _db

        cls._start_server()

    @classmethod
    def tearDownClass(cls):
        """Stop the server process (NOT docker-compose)."""
        cls._stop_server()

    @classmethod
    def _start_server(cls):
        """Start the server process."""
        env = os.environ.copy()
        env.update({
            'REDIS_HOST': 'localhost',
            'REDIS_PORT': '6379',
            'MYSQL_HOST': 'localhost',
            'MYSQL_PORT': '3306',
            'MYSQL_USER': 'saloonbot',
            'MYSQL_PASSWORD': 'saloonbot_password',
            'MYSQL_DATABASE': 'saloonbot',
            'SALOONBOT_DEBUG': '1',
            'BLACKJACK_TIME_BETWEEN_HANDS': '0',
            'BLACKJACK_REMINDER_PERIOD': '1',
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
    def _stop_server(cls):
        """Stop the server process."""
        if cls.server_process and cls.server_process.poll() is None:
            logging.info("Stopping server process...")
            cls.server_process.send_signal(signal.SIGTERM)
            try:
                cls.server_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                cls.server_process.kill()
                cls.server_process.wait()

    def setUp(self):
        """Set up for each test."""
        # Clean up Redis before each test
        self.redis.flushall()

        # Clean up MySQL before each test using class-level connection
        cursor = self.db.cursor()
        cursor.execute("DELETE FROM users")
        self.db.commit()
        cursor.close()

    def subscribe_to_game(self, game_id):
        """Create pubsub subscription to a game's updates."""
        pubsub = self.redis.pubsub()
        pubsub.subscribe(f"game_updates_{game_id}")
        pubsub.get_message(timeout=1)  # Skip confirmation
        return pubsub

    def collect_messages(self, pubsub, timeout=5, stop_on=None):
        """Collect messages until timeout or stop condition met."""
        messages = []
        start = time.time()
        while time.time() - start < timeout:
            msg = pubsub.get_message(timeout=0.5)
            if msg and msg['type'] == 'message':
                text = json.loads(msg['data'])['text']
                messages.append(text)
                if stop_on and stop_on in text:
                    break
        return messages

    def join_player(self, game_id, player_name):
        """Send a player join action."""
        self.redis.publish("casino", json.dumps({
            'event_type': 'player_action',
            'game_id': game_id,
            'player': player_name,
            'action': 'join'
        }))

    def player_action(self, game_id, player_name, action):
        """Send a player action (hit/stand/etc)."""
        self.redis.publish("casino", json.dumps({
            'event_type': 'player_action',
            'game_id': game_id,
            'player': player_name,
            'action': action
        }))

    def place_bet(self, game_id, player_name, amount):
        """Send a bet action."""
        self.redis.publish("casino", json.dumps({
            'event_type': 'player_action',
            'game_id': game_id,
            'player': player_name,
            'action': 'bet',
            'amount': amount
        }))

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

        pubsub = self.subscribe_to_game(game_id)
        try:
            self.join_player(game_id, 'TestPlayer1')
            updates = self.collect_messages(pubsub, timeout=5)

            # Check that player joined
            join_messages = [u for u in updates if 'TestPlayer1' in u and 'join' in u]
            self.assertGreater(len(join_messages), 0, "Player should have joined the game")
        finally:
            pubsub.close()

    def test_database_user_creation(self):
        """Test that joining a game creates a user in the database."""
        game_id = self.create_game()

        pubsub = self.subscribe_to_game(game_id)
        try:
            player_name = 'DatabaseTestPlayer'
            self.join_player(game_id, player_name)

            # Give it time to process
            time.sleep(2)

            # Check database using class-level connection
            cursor = self.db.cursor()
            cursor.execute("SELECT username FROM users WHERE username = %s", (player_name,))
            result = cursor.fetchone()
            cursor.close()

            self.assertIsNotNone(result, "User should be created in database")
            self.assertEqual(result[0], player_name)
        finally:
            pubsub.close()


class TestBlackjackGame(EndToEndTestCase):
    """Test a complete blackjack game flow."""

    def test_complete_blackjack_hand(self):
        """Test a complete blackjack hand with player actions."""
        game_id = self.create_game()

        pubsub = self.subscribe_to_game(game_id)
        try:
            self.join_player(game_id, 'Player1')

            # Wait for betting phase
            all_updates = self.collect_messages(pubsub, timeout=5, stop_on='Place your bets')

            # Place a bet
            self.place_bet(game_id, 'Player1', 10)

            # Wait for player's initial hand to be dealt
            all_updates.extend(self.collect_messages(pubsub, timeout=5, stop_on='Player1 has'))

            # Check that hand started
            hand_started = any('shuffles and deals' in u for u in all_updates)
            self.assertTrue(hand_started, "A hand should have started")

            # Player stands
            self.player_action(game_id, 'Player1', 'stand')

            # Wait for dealer turn and end of hand
            all_updates.extend(self.collect_messages(pubsub, timeout=5, stop_on='dust settles'))

            # Verify game flow
            hand_ended = any('dust settles' in u for u in all_updates)
            self.assertTrue(hand_ended, f"Hand should have ended. Messages: {all_updates}")

            # Verify dealer played
            dealer_messages = [u for u in all_updates if 'Dealer' in u]
            self.assertGreater(len(dealer_messages), 0, "Dealer should have played")
        finally:
            pubsub.close()

    def test_player_hit_action(self):
        """Test player hitting (requesting a card)."""
        game_id = self.create_game()

        pubsub = self.subscribe_to_game(game_id)
        try:
            self.join_player(game_id, 'HitPlayer')

            # Wait for betting phase
            all_updates = self.collect_messages(pubsub, timeout=5, stop_on='Place your bets')

            # Place a bet
            self.place_bet(game_id, 'HitPlayer', 10)

            # Wait for player's initial hand to be dealt
            # (message like "HitPlayer has <card>, <card>")
            all_updates.extend(self.collect_messages(pubsub, timeout=5, stop_on='HitPlayer has'))

            # Player hits
            self.player_action(game_id, 'HitPlayer', 'hit')

            # Wait for hit result
            all_updates.extend(self.collect_messages(pubsub, timeout=5))

            # Verify hit action was processed (message like "HitPlayer draws... <card>")
            hit_messages = [u for u in all_updates if 'draws' in u and 'HitPlayer' in u]
            self.assertGreater(len(hit_messages), 0, "Player should have been dealt a card")
        finally:
            pubsub.close()


class TestServerRestart(EndToEndTestCase):
    """Test game persistence across server restarts."""

    def setUp(self):
        """Set up for each test - clean database tables including games."""
        super().setUp()
        # Also clean up games and game_channels tables
        cursor = self.db.cursor()
        cursor.execute("DELETE FROM game_channels")
        cursor.execute("DELETE FROM games")
        self.db.commit()
        cursor.close()

    def test_game_persists_across_server_restart(self):
        """Test that a game with a bet survives server restart."""
        game_id = self.create_game()

        pubsub = self.subscribe_to_game(game_id)
        try:
            # Join and place bet
            self.join_player(game_id, 'PersistPlayer')
            self.collect_messages(pubsub, timeout=5, stop_on='Place your bets')
            self.place_bet(game_id, 'PersistPlayer', 20)

            # Wait for hand to start and player turn
            self.collect_messages(pubsub, timeout=5, stop_on="you're up")

            # Give server time to save state after tick
            time.sleep(0.5)

            # Verify game is in database
            cursor = self.db.cursor()
            cursor.execute("SELECT game_id, state FROM games WHERE game_id = %s", (game_id,))
            result = cursor.fetchone()
            cursor.close()
            self.assertIsNotNone(result, "Game should be saved in database")
            self.assertEqual(result[0], game_id)
            self.assertEqual(result[1], 'playing')

            # Verify bet is saved
            cursor = self.db.cursor()
            cursor.execute("SELECT bets_json FROM games WHERE game_id = %s", (game_id,))
            result = cursor.fetchone()
            cursor.close()
            bets = json.loads(result[0])
            self.assertIn('PersistPlayer', bets)
            self.assertEqual(bets['PersistPlayer'], 20)

        finally:
            pubsub.close()

        # Restart server
        self._stop_server()
        time.sleep(1)
        self._start_server()

        # Reconnect pubsub after restart
        pubsub = self.subscribe_to_game(game_id)
        try:
            # Send a player action to verify game is restored
            self.player_action(game_id, 'PersistPlayer', 'stand')

            # Collect messages - should get stand acknowledgment and dealer turn
            messages = self.collect_messages(pubsub, timeout=5, stop_on='dust settles')

            # Verify game continued after restart
            stand_msg = any('stands pat' in m for m in messages)
            self.assertTrue(stand_msg, f"Game should continue after restart. Got: {messages}")

            # Verify hand resolved
            resolved = any('dust settles' in m for m in messages)
            self.assertTrue(resolved, "Hand should resolve after player stands")
        finally:
            pubsub.close()

    def test_bet_preserved_after_restart(self):
        """Test that player bets are preserved after server restart."""
        game_id = self.create_game()

        pubsub = self.subscribe_to_game(game_id)
        try:
            # Join and place bet
            self.join_player(game_id, 'BetPlayer')
            self.collect_messages(pubsub, timeout=5, stop_on='Place your bets')
            self.place_bet(game_id, 'BetPlayer', 25)

            # Wait for hand to start
            self.collect_messages(pubsub, timeout=5, stop_on="you're up")

            # Give server time to save state after tick
            time.sleep(0.5)

            # Check wallet was decremented
            cursor = self.db.cursor()
            cursor.execute("SELECT wallet FROM users WHERE username = 'BetPlayer'")
            after_bet = cursor.fetchone()
            cursor.close()
            self.assertIsNotNone(after_bet)
            # Default wallet is 200, so after betting 25 should be 175
            self.assertEqual(float(after_bet[0]), 175.0)

            # Verify bet is in DB before restart
            cursor = self.db.cursor()
            cursor.execute("SELECT bets_json, state FROM games WHERE game_id = %s", (game_id,))
            before_restart = cursor.fetchone()
            cursor.close()
            self.assertIsNotNone(before_restart, "Game should be in database before restart")
            bets_before = json.loads(before_restart[0])
            self.assertEqual(bets_before.get('BetPlayer'), 25,
                             f"Bet should be saved before restart. State: {before_restart[1]}")

        finally:
            pubsub.close()

        # Restart server immediately
        self._stop_server()
        time.sleep(1)
        self._start_server()

        # Verify bet is still in database
        cursor = self.db.cursor()
        cursor.execute("SELECT bets_json FROM games WHERE game_id = %s", (game_id,))
        result = cursor.fetchone()
        cursor.close()
        self.assertIsNotNone(result, "Game should still exist after restart")
        bets = json.loads(result[0])
        self.assertEqual(bets.get('BetPlayer'), 25, "Bet should be preserved")

        # Verify wallet wasn't double-decremented
        cursor = self.db.cursor()
        cursor.execute("SELECT wallet FROM users WHERE username = 'BetPlayer'")
        after_restart = cursor.fetchone()
        cursor.close()
        self.assertEqual(float(after_restart[0]), 175.0,
                         "Wallet should not be decremented again")

    def test_list_games_returns_active_games(self):
        """Test that list_games returns active games for bot recovery."""
        # Create a game with channel info
        pubsub = self.redis.pubsub()
        try:
            pubsub.subscribe("casino_update")
            pubsub.get_message(timeout=1)  # Skip subscribe confirmation

            request_id = f"test-request-{time.time()}"
            message = {
                'event_type': 'casino_action',
                'action': 'new_game',
                'request_id': request_id,
                'guild_id': 12345,
                'channel_id': 67890
            }
            self.redis.publish("casino", json.dumps(message))

            # Wait for game creation response
            game_id = None
            for _ in range(20):
                msg = pubsub.get_message(timeout=1)
                if msg and msg['type'] == 'message':
                    response = json.loads(msg['data'])
                    if response.get('request_id') == request_id:
                        game_id = response['game_id']
                        break

            self.assertIsNotNone(game_id, "Failed to create game")

            # Now request list_games
            list_request_id = f"list-request-{time.time()}"
            list_message = {
                'event_type': 'casino_action',
                'action': 'list_games',
                'request_id': list_request_id
            }
            self.redis.publish("casino", json.dumps(list_message))

            # Wait for list_games response
            games_response = None
            for _ in range(20):
                msg = pubsub.get_message(timeout=1)
                if msg and msg['type'] == 'message':
                    response = json.loads(msg['data'])
                    if response.get('event_type') == 'list_games' and \
                       response.get('request_id') == list_request_id:
                        games_response = response
                        break

            self.assertIsNotNone(games_response, "Should receive list_games response")
            self.assertIn('games', games_response)

            # Find our game in the list
            our_game = None
            for g in games_response['games']:
                if g['game_id'] == game_id:
                    our_game = g
                    break

            self.assertIsNotNone(our_game, "Our game should be in the list")
            self.assertEqual(our_game.get('guild_id'), 12345)
            self.assertEqual(our_game.get('channel_id'), 67890)

        finally:
            pubsub.close()


if __name__ == "__main__":
    unittest.main()
