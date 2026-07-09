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
import tempfile
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
            'BLACKJACK_TIME_WAIT_FOR_PLAYERS': '0',
            'BLACKJACK_REMINDER_PERIOD': '1',
            'BLACKJACK_DRAMATIC_PAUSE': '0',
            'BLACKJACK_DEALER_CARD_PAUSE': '0',
            'BLACKJACK_RESULT_PAUSE': '0',
            'LLM_TIMEOUT': '1',
            'PYTHONUNBUFFERED': '1',
        })

        fd, cls._server_log_path = tempfile.mkstemp(suffix='.log', prefix='saloonbot_server_')
        cls._server_log_fh = os.fdopen(fd, 'w')

        cls.server_process = subprocess.Popen(
            ['python', 'server.py'],
            env=env,
            stdout=cls._server_log_fh,
            stderr=subprocess.STDOUT,
        )

        cls._wait_for_server_ready()

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
        if hasattr(cls, '_server_log_fh') and cls._server_log_fh:
            cls._server_log_fh.close()
            cls._server_log_fh = None
        if hasattr(cls, '_server_log_path') and cls._server_log_path:
            try:
                os.unlink(cls._server_log_path)
            except OSError:
                pass
            cls._server_log_path = None

    @classmethod
    def _wait_for_server_ready(cls, timeout=15):
        """Wait until the server has subscribed to the Redis 'casino' channel."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if cls.server_process.poll() is not None:
                raise RuntimeError("Server process exited unexpectedly")
            numsub = dict(cls.redis.pubsub_numsub("casino"))
            if numsub.get("casino", 0) >= 1:
                logging.info("Server is ready (subscribed to casino channel)")
                return
            time.sleep(0.1)
        raise RuntimeError(f"Server did not become ready within {timeout}s")

    def poll_db(self, query, params, predicate=None, timeout=5, interval=0.1):
        """Poll the database until predicate(row) returns True, returning the row.

        Executes *query* with *params* repeatedly until either a row is returned
        and the optional *predicate* passes, or *timeout* seconds elapse.
        Returns the matching row, or None on timeout.
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            self.db.commit()  # End current transaction so we get a fresh snapshot
            cursor = self.db.cursor()
            cursor.execute(query, params)
            row = cursor.fetchone()
            cursor.close()
            if row is not None and (predicate is None or predicate(row)):
                return row
            time.sleep(interval)
        return None

    def setUp(self):
        """Set up for each test."""
        self.redis.flushall()

        cursor = self.db.cursor()
        cursor.execute("DELETE FROM game_channels")
        cursor.execute("DELETE FROM games")
        cursor.execute("DELETE FROM users")
        self.db.commit()
        cursor.close()

    def tearDown(self):
        """Dump server log on test failure."""
        outcome = getattr(self, '_outcome', None)
        if outcome is not None and not outcome.success:
            self._dump_server_log()

    def _dump_server_log(self):
        log_path = getattr(self.__class__, '_server_log_path', None)
        if not log_path:
            return
        try:
            with open(log_path) as f:
                lines = f.readlines()
            print(f"\n--- Server log ({self.__class__.__name__}) ---")
            print(''.join(lines[-50:]))
            print("--- End server log ---\n")
        except Exception:
            pass

    def subscribe_to_game(self, game_id):
        """Create pubsub subscription to a game's updates."""
        pubsub = self.redis.pubsub()
        pubsub.subscribe(f"game_updates_{game_id}")
        pubsub.get_message(timeout=1)  # Skip confirmation
        return pubsub

    def collect_messages(self, pubsub, timeout=5, stop_on=None):
        """Collect messages until timeout or stop condition met.

        stop_on may be a string or a list of strings; collection stops when any matches.
        """
        messages = []
        start = time.time()
        stop_conditions = [stop_on] if isinstance(stop_on, str) else (stop_on or [])
        while time.time() - start < timeout:
            msg = pubsub.get_message(timeout=0.5)
            if msg and msg['type'] == 'message':
                text = json.loads(msg['data'])['text']
                messages.append(text)
                if any(cond in text for cond in stop_conditions):
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

    # A deck where dealer gets 16 (no blackjack) and player gets 15.
    # Cards are dealt via pop(), so the last element is dealt first.
    # Deal order: dealer face-up H6, dealer hole S10 (total 16),
    #             player C7, player D8 (total 15).
    # Dealer must hit; draws D2 for total 18, stands.
    DETERMINISTIC_DECK = [
        'H2', 'H3', 'H4', 'H5', 'H7', 'H8', 'H9',  # filler (never reached in one hand)
        'D2',   # dealer hit card → dealer total 18
        'D8',   # player card 2
        'C7',   # player card 1
        'S10',  # dealer hole card
        'H6',   # dealer face-up (last in list = first popped)
    ]

    def create_game(self, num_bots=0, deck=None):
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
            if num_bots:
                message['num_bots'] = num_bots
            if deck is not None:
                message['deck'] = deck
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

            result = self.poll_db(
                "SELECT username FROM users WHERE username = %s",
                (player_name,)
            )

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
            self.place_bet(game_id, 'Player1', 1000)

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
        game_id = self.create_game(deck=self.DETERMINISTIC_DECK)

        pubsub = self.subscribe_to_game(game_id)
        try:
            self.join_player(game_id, 'HitPlayer')

            # Wait for betting phase
            all_updates = self.collect_messages(pubsub, timeout=5, stop_on='Place your bets')

            # Place a bet
            self.place_bet(game_id, 'HitPlayer', 1000)

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

    def test_game_persists_across_server_restart(self):
        """Test that a game with a bet survives server restart."""
        game_id = self.create_game(deck=self.DETERMINISTIC_DECK)

        self.join_player(game_id, 'PersistPlayer')

        # Wait for BETTING state
        self.assertIsNotNone(
            self.poll_db("SELECT state FROM games WHERE game_id = %s", (game_id,),
                         predicate=lambda row: row[0] == 'betting', timeout=5),
            "Game should reach betting state"
        )
        self.place_bet(game_id, 'PersistPlayer', 2000)

        # With a deterministic deck the dealer cannot get blackjack; expect PLAYING directly
        result = self.poll_db(
            "SELECT game_id, state FROM games WHERE game_id = %s",
            (game_id,),
            predicate=lambda row: row[1] == 'playing',
            timeout=5
        )
        self.assertIsNotNone(result, "Game should reach playing state")
        self.assertEqual(result[0], game_id)
        self.assertEqual(result[1], 'playing')

        # Verify the active bet is persisted
        bet_result = self.poll_db(
            "SELECT bets_json FROM games WHERE game_id = %s",
            (game_id,),
            predicate=lambda row: json.loads(row[0]).get('PersistPlayer') == 2000
        )
        self.assertIsNotNone(bet_result, "Bet should be saved in database")
        bets = json.loads(bet_result[0])
        self.assertIn('PersistPlayer', bets)
        self.assertEqual(bets['PersistPlayer'], 2000)

        # Restart server
        self._stop_server()
        self._start_server()

        # Subscribe before sending action so we don't miss any published messages
        pubsub = self.subscribe_to_game(game_id)
        try:
            self.player_action(game_id, 'PersistPlayer', 'stand')
            messages = self.collect_messages(pubsub, timeout=10, stop_on='dust settles')
            self.assertTrue(any('stands pat' in m for m in messages),
                            f"Game should continue after restart. Got: {messages}")
            self.assertTrue(any('dust settles' in m for m in messages),
                            "Hand should resolve after player stands")
        finally:
            pubsub.close()

    def test_empty_waiting_game_persists_across_server_restart(self):
        """A game with no players yet (WAITING state) must survive a
        restart too, not just games already in progress."""
        game_id = self.create_game(deck=self.DETERMINISTIC_DECK)

        self.assertIsNotNone(
            self.poll_db("SELECT state FROM games WHERE game_id = %s", (game_id,),
                         predicate=lambda row: row[0] == 'waiting', timeout=5),
            "Game should be persisted in waiting state before restart"
        )

        # Restart server
        self._stop_server()
        self._start_server()

        # The row must still be there after restart...
        result = self.poll_db(
            "SELECT state FROM games WHERE game_id = %s", (game_id,), timeout=5
        )
        self.assertIsNotNone(result, "Empty game should still be persisted after restart")
        self.assertEqual(result[0], 'waiting')

        # ...and the server must have reloaded it into memory, not just left
        # an orphaned DB row: list_games should still report it.
        pubsub = self.redis.pubsub()
        try:
            pubsub.subscribe("casino_update")
            pubsub.get_message(timeout=1)  # Skip subscribe confirmation

            list_request_id = f"list-request-{time.time()}"
            self.redis.publish("casino", json.dumps({
                'event_type': 'casino_action',
                'action': 'list_games',
                'request_id': list_request_id,
            }))

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
            game_ids = [g['game_id'] for g in games_response['games']]
            self.assertIn(game_id, game_ids, "Empty game should be reloaded into memory after restart")
        finally:
            pubsub.close()

    def test_bet_preserved_after_restart(self):
        """Test that player bets are preserved after server restart."""
        game_id = self.create_game(deck=self.DETERMINISTIC_DECK)

        self.join_player(game_id, 'BetPlayer')

        # Wait for BETTING state, place bet, then wait for PLAYING
        self.assertIsNotNone(
            self.poll_db("SELECT state FROM games WHERE game_id = %s", (game_id,),
                         predicate=lambda row: row[0] == 'betting', timeout=5),
            "Game should reach betting state"
        )
        self.place_bet(game_id, 'BetPlayer', 2500)

        # Deterministic deck: dealer can't get blackjack, game must reach PLAYING
        self.assertIsNotNone(
            self.poll_db("SELECT state FROM games WHERE game_id = %s", (game_id,),
                         predicate=lambda row: row[0] == 'playing', timeout=5),
            "Game should reach playing state"
        )

        # Wallet should be decremented by the bet amount
        after_bet = self.poll_db(
            "SELECT wallet_cents FROM users WHERE username = 'BetPlayer'",
            (),
            predicate=lambda row: row[0] == 17500
        )
        self.assertIsNotNone(after_bet, "Wallet should be decremented to 17500 cents after a 2500-cent bet")

        # Bet must be persisted while the hand is live (game is in PLAYING state)
        before_restart = self.poll_db(
            "SELECT bets_json FROM games WHERE game_id = %s",
            (game_id,),
            predicate=lambda row: json.loads(row[0]).get('BetPlayer') == 2500
        )
        self.assertIsNotNone(before_restart, "Bet should be saved in database before restart")
        self.assertEqual(json.loads(before_restart[0]).get('BetPlayer'), 2500)

        # Restart server
        self._stop_server()
        self._start_server()

        # Verify bet survives restart
        result = self.poll_db(
            "SELECT bets_json FROM games WHERE game_id = %s",
            (game_id,)
        )
        self.assertIsNotNone(result, "Game should still exist after restart")
        bets = json.loads(result[0])
        self.assertEqual(bets.get('BetPlayer'), 2500, "Bet should be preserved")

        # Wallet must not be double-decremented
        after_restart = self.poll_db(
            "SELECT wallet_cents FROM users WHERE username = 'BetPlayer'",
            ()
        )
        self.assertEqual(after_restart[0], 17500,
                         "Wallet should not be decremented again on restart")

        # Verify wallet wasn't double-decremented
        after_restart = self.poll_db(
            "SELECT wallet_cents FROM users WHERE username = 'BetPlayer'",
            ()
        )
        self.assertEqual(after_restart[0], 17500,
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


class TestStopGame(EndToEndTestCase):
    """Test admin stop_game action."""

    def test_stop_game_ends_game(self):
        """Test that stop_game removes the game and emits game_over."""
        game_id = self.create_game()

        game_pubsub = self.subscribe_to_game(game_id)
        try:
            self.redis.publish("casino", json.dumps({
                'event_type': 'casino_action',
                'action': 'stop_game',
                'game_id': game_id,
            }))

            # Collect raw events (game_over has no 'text', so bypass collect_messages)
            deadline = time.time() + 5
            game_over_received = False
            while time.time() < deadline:
                msg = game_pubsub.get_message(timeout=0.5)
                if msg and msg['type'] == 'message':
                    data = json.loads(msg['data'])
                    if data.get('event_type') == 'game_over':
                        game_over_received = True
                        break

            self.assertTrue(game_over_received, "Should receive game_over event after stop_game")
        finally:
            game_pubsub.close()

    def test_stop_game_removes_from_database(self):
        """Test that stop_game deletes the game record from the database."""
        # Create a game with a player so it gets persisted
        game_id = self.create_game()
        pubsub = self.subscribe_to_game(game_id)
        try:
            self.join_player(game_id, 'StopPlayer')
            self.collect_messages(pubsub, timeout=5, stop_on='Place your bets')
        finally:
            pubsub.close()

        # Verify game is in database
        result = self.poll_db(
            "SELECT game_id FROM games WHERE game_id = %s",
            (game_id,)
        )
        self.assertIsNotNone(result, "Game should exist before stop")

        # Stop the game
        self.redis.publish("casino", json.dumps({
            'event_type': 'casino_action',
            'action': 'stop_game',
            'game_id': game_id,
        }))

        # Verify game is removed from database
        deadline = time.time() + 5
        while time.time() < deadline:
            self.db.commit()
            cursor = self.db.cursor()
            cursor.execute("SELECT game_id FROM games WHERE game_id = %s", (game_id,))
            row = cursor.fetchone()
            cursor.close()
            if row is None:
                break
            time.sleep(0.1)

        self.db.commit()
        cursor = self.db.cursor()
        cursor.execute("SELECT game_id FROM games WHERE game_id = %s", (game_id,))
        row = cursor.fetchone()
        cursor.close()
        self.assertIsNone(row, "Game should be removed from database after stop")


class TestWalletBalance(EndToEndTestCase):
    """Test wallet balance correctness after hand resolution."""

    def test_wallet_updated_correctly_after_hand(self):
        """Wallet is credited on win, restored on push, unchanged on loss (bet already escrowed)."""
        game_id = self.create_game()
        pubsub = self.subscribe_to_game(game_id)
        try:
            player_name = 'WalletPlayer'
            self.join_player(game_id, player_name)

            # Poll DB for betting state — more reliable than message timing under server load.
            self.assertIsNotNone(
                self.poll_db(
                    "SELECT state FROM games WHERE game_id = %s",
                    (game_id,),
                    predicate=lambda row: row[0] == 'betting',
                    timeout=10,
                ),
                "Game should reach betting state",
            )

            row = self.poll_db("SELECT wallet_cents FROM users WHERE username = %s", (player_name,))
            self.assertIsNotNone(row)
            starting = row[0]

            bet = 1000
            # Drain any buffered messages accumulated while we were polling.
            self.collect_messages(pubsub, timeout=0.5)
            self.place_bet(game_id, player_name, bet)

            # Stop on either "you're up" (normal) or "dust settles" (dealer blackjack).
            pre_stand = self.collect_messages(pubsub, timeout=5, stop_on=["you're up", 'dust settles'])
            if any("you're up" in m for m in pre_stand):
                self.player_action(game_id, player_name, 'stand')
                messages = self.collect_messages(pubsub, timeout=5, stop_on='dust settles')
            else:
                # Dealer blackjack — hand resolved without a player turn.
                messages = pre_stand

            # Determine expected wallet from the outcome message
            if any('strikes gold' in m for m in messages):
                expected = starting + bet       # bet*2 credited, net gain = bet
            elif any('pushes with the dealer' in m for m in messages):
                expected = starting              # bet returned, net zero
            else:
                expected = starting - bet        # loss: bet escrowed, nothing returned

            result = self.poll_db(
                "SELECT wallet_cents FROM users WHERE username = %s",
                (player_name,),
                predicate=lambda row: row[0] == expected
            )
            self.assertIsNotNone(
                result,
                f"Wallet should be {expected} cents after hand. Messages: {messages}"
            )
        finally:
            pubsub.close()


class TestMultiplePlayers(EndToEndTestCase):
    """Test game flow with two human players."""

    def test_turn_order_follows_join_order(self):
        """Players take turns in the order they joined, and both hands resolve."""
        game_id = self.create_game()
        pubsub = self.subscribe_to_game(game_id)
        try:
            self.join_player(game_id, 'Alpha')
            self.join_player(game_id, 'Beta')

            self.collect_messages(pubsub, timeout=5, stop_on='Place your bets')
            self.place_bet(game_id, 'Alpha', 1000)
            self.place_bet(game_id, 'Beta', 1000)

            first_turn = self.collect_messages(
                pubsub, timeout=5, stop_on=["you're up", 'dust settles']
            )
            # Dealer blackjack resolves the hand immediately with no player turns — valid outcome.
            if any('dust settles' in m for m in first_turn):
                return
            self.assertTrue(
                any("Alpha, you're up" in m for m in first_turn),
                f"Alpha should be prompted first. Messages: {first_turn}"
            )

            self.player_action(game_id, 'Alpha', 'stand')

            second_turn = self.collect_messages(pubsub, timeout=5, stop_on="you're up")
            self.assertTrue(
                any("Beta, you're up" in m for m in second_turn),
                f"Beta should be prompted after Alpha. Messages: {second_turn}"
            )

            self.player_action(game_id, 'Beta', 'stand')

            end = self.collect_messages(pubsub, timeout=5, stop_on='dust settles')
            self.assertTrue(
                any('dust settles' in m for m in end),
                f"Hand should resolve after both players stand. Messages: {end}"
            )
        finally:
            pubsub.close()


class TestNPCBots(EndToEndTestCase):
    """Test games with NPC bot players."""

    def test_npc_bot_plays_without_human_intervention(self):
        """NPC bot takes its turn automatically so the hand resolves without prompting it."""
        # NPC is added before the human when the human joins, so NPC goes first
        game_id = self.create_game(num_bots=1)
        pubsub = self.subscribe_to_game(game_id)
        try:
            self.join_player(game_id, 'HumanPlayer')

            self.collect_messages(pubsub, timeout=5, stop_on='Place your bets')
            # NPC auto-bets via tick loop; human places their bet
            self.place_bet(game_id, 'HumanPlayer', 1000)

            # Wait until it's the human's turn (NPC plays first and is handled automatically).
            # Dealer blackjack resolves the hand immediately with no player turns — valid outcome.
            pre_human = self.collect_messages(
                pubsub, timeout=10, stop_on=["HumanPlayer, you're up", 'dust settles']
            )
            if any('dust settles' in m for m in pre_human):
                return
            self.assertTrue(
                any("HumanPlayer, you're up" in m for m in pre_human),
                f"HumanPlayer should be prompted for their turn. Messages: {pre_human}"
            )

            self.player_action(game_id, 'HumanPlayer', 'stand')

            end = self.collect_messages(pubsub, timeout=10, stop_on='dust settles')
            self.assertTrue(
                any('dust settles' in m for m in end),
                f"Hand should resolve after both NPC and human act. Messages: {end}"
            )
        finally:
            pubsub.close()


class TestAdminWallet(EndToEndTestCase):
    """E2E tests for admin wallet inspection and editing (AM2)."""

    def setUp(self):
        super().setUp()
        cursor = self.db.cursor()
        cursor.execute("DELETE FROM npcs")
        cursor.execute("DELETE FROM settings")
        self.db.commit()
        cursor.close()

    def _casino_request(self, action, **kwargs):
        """Publish a casino action and wait for the matching casino_update response."""
        pubsub = self.redis.pubsub()
        pubsub.subscribe("casino_update")
        pubsub.get_message(timeout=1)  # skip subscribe confirmation

        request_id = f"test-wallet-{time.time()}"
        message = {
            'event_type': 'casino_action',
            'action': action,
            'request_id': request_id,
            **kwargs,
        }
        self.redis.publish("casino", json.dumps(message))

        deadline = time.time() + 5
        while time.time() < deadline:
            msg = pubsub.get_message(timeout=0.5)
            if msg and msg['type'] == 'message':
                data = json.loads(msg['data'])
                if data.get('request_id') == request_id:
                    pubsub.close()
                    return data
        pubsub.close()
        return None

    def _seed_player(self, name, wallet_cents=20000):
        cursor = self.db.cursor()
        cursor.execute(
            "INSERT INTO users (username, wallet_cents) VALUES (%s, %s)", (name, wallet_cents)
        )
        self.db.commit()
        cursor.close()

    def _seed_npc(self, name, wallet_cents=10000):
        cursor = self.db.cursor()
        cursor.execute(
            "INSERT INTO npcs (name, personality_name, backstory, wallet_cents) VALUES (%s, %s, %s, %s)",
            (name, 'Grizzled Prospector', '', wallet_cents)
        )
        self.db.commit()
        npc_id = cursor.lastrowid
        cursor.close()
        return npc_id

    def test_lookup_wallet_player(self):
        """lookup_wallet returns correct balance for a seeded player."""
        self._seed_player('LookupPlayer', wallet_cents=25000)
        resp = self._casino_request('lookup_wallet', target='LookupPlayer')
        self.assertIsNotNone(resp, "Should receive wallet_info response")
        self.assertEqual(resp['event_type'], 'wallet_info')
        self.assertEqual(resp['kind'], 'player')
        self.assertEqual(resp['balance_cents'], 25000)

    def test_lookup_wallet_npc(self):
        """lookup_wallet finds an NPC by name (case-insensitive)."""
        self._seed_npc('Jebediah Kane', wallet_cents=7500)
        resp = self._casino_request('lookup_wallet', target='jebediah kane')
        self.assertIsNotNone(resp, "Should receive wallet_info response")
        self.assertEqual(resp['event_type'], 'wallet_info')
        self.assertEqual(resp['kind'], 'npc')
        self.assertEqual(resp['balance_cents'], 7500)

    def test_lookup_wallet_unknown(self):
        """lookup_wallet returns kind=None for an unknown target."""
        resp = self._casino_request('lookup_wallet', target='Nobody Atall')
        self.assertIsNotNone(resp, "Should receive wallet_info response")
        self.assertEqual(resp['event_type'], 'wallet_info')
        self.assertIsNone(resp['kind'])
        self.assertIsNone(resp['balance_cents'])

    def test_set_wallet_player(self):
        """set_wallet (mode=set) sets a player's wallet to an absolute amount."""
        self._seed_player('SetPlayer', wallet_cents=20000)
        resp = self._casino_request('set_wallet', target='SetPlayer', mode='set', amount=50000)
        self.assertIsNotNone(resp, "Should receive wallet_set response")
        self.assertTrue(resp['ok'], f"Expected ok=True, got message: {resp.get('message')}")
        row = self.poll_db("SELECT wallet_cents FROM users WHERE username = %s", ('SetPlayer',))
        self.assertIsNotNone(row)
        self.assertEqual(row[0], 50000)

    def test_adjust_wallet_player(self):
        """set_wallet (mode=adjust) adds chips to a player's wallet."""
        self._seed_player('AdjustPlayer', wallet_cents=20000)
        resp = self._casino_request('set_wallet', target='AdjustPlayer', mode='adjust', amount=5000)
        self.assertIsNotNone(resp, "Should receive wallet_set response")
        self.assertTrue(resp['ok'], f"Expected ok=True, got message: {resp.get('message')}")
        self.assertEqual(resp['new_balance_cents'], 25000)
        row = self.poll_db("SELECT wallet_cents FROM users WHERE username = %s", ('AdjustPlayer',))
        self.assertEqual(row[0], 25000)

    def test_adjust_wallet_npc(self):
        """set_wallet (mode=adjust) adds chips to an NPC's wallet."""
        self._seed_npc('RichNPC', wallet_cents=10000)
        resp = self._casino_request('set_wallet', target='RichNPC', mode='adjust', amount=2500)
        self.assertIsNotNone(resp, "Should receive wallet_set response")
        self.assertTrue(resp['ok'], f"Expected ok=True, got message: {resp.get('message')}")
        self.assertEqual(resp['new_balance_cents'], 12500)

    def test_set_wallet_negative_rejected(self):
        """set_wallet (mode=set, amount<0) is rejected without touching the wallet."""
        self._seed_player('NegPlayer', wallet_cents=20000)
        resp = self._casino_request('set_wallet', target='NegPlayer', mode='set', amount=-5000)
        self.assertIsNotNone(resp, "Should receive wallet_set response")
        self.assertFalse(resp['ok'])
        row = self.poll_db("SELECT wallet_cents FROM users WHERE username = %s", ('NegPlayer',))
        self.assertEqual(row[0], 20000)

    def test_adjust_wallet_would_go_negative(self):
        """set_wallet (mode=adjust) that would make balance negative is rejected."""
        self._seed_player('PoorPlayer', wallet_cents=5000)
        resp = self._casino_request('set_wallet', target='PoorPlayer', mode='adjust', amount=-10000)
        self.assertIsNotNone(resp, "Should receive wallet_set response")
        self.assertFalse(resp['ok'])
        row = self.poll_db("SELECT wallet_cents FROM users WHERE username = %s", ('PoorPlayer',))
        self.assertEqual(row[0], 5000)


class TestNPCLimits(EndToEndTestCase):
    """E2E tests for NPC autofill min/max (AM3)."""

    def setUp(self):
        super().setUp()
        cursor = self.db.cursor()
        cursor.execute("DELETE FROM npcs")
        cursor.execute("DELETE FROM settings")
        self.db.commit()
        cursor.close()

    def _casino_request(self, action, **kwargs):
        """Publish a casino action and wait for a matching casino_update response."""
        pubsub = self.redis.pubsub()
        pubsub.subscribe("casino_update")
        pubsub.get_message(timeout=1)

        request_id = f"test-limits-{time.time()}"
        message = {
            'event_type': 'casino_action',
            'action': action,
            'request_id': request_id,
            **kwargs,
        }
        self.redis.publish("casino", json.dumps(message))

        deadline = time.time() + 5
        while time.time() < deadline:
            msg = pubsub.get_message(timeout=0.5)
            if msg and msg['type'] == 'message':
                data = json.loads(msg['data'])
                if data.get('request_id') == request_id:
                    pubsub.close()
                    return data
        pubsub.close()
        return None

    def _get_debug(self):
        """Request and return the full debug_state from the server."""
        return self._casino_request('get_debug')

    def _npc_count_in_game(self, debug_data, game_id):
        """Count NPCs across players + players_waiting for a given game."""
        for g in debug_data.get('games', []):
            if g['game_id'] == game_id:
                return sum(1 for p in g['players'] + g.get('players_waiting', [])
                           if p['is_npc'])
        return 0

    def test_npc_limits_view_defaults(self):
        """npc_limits with no args returns the current (default) limits."""
        resp = self._casino_request('npc_limits')
        self.assertIsNotNone(resp, "Should receive npc_limits response")
        self.assertEqual(resp['event_type'], 'npc_limits')
        self.assertTrue(resp['ok'])
        self.assertIn('min', resp)
        self.assertIn('max', resp)

    def test_npc_limits_set_and_view(self):
        """Setting npc_limits persists and is reflected in the next view."""
        set_resp = self._casino_request('npc_limits', min=1, max=3)
        self.assertIsNotNone(set_resp)
        self.assertTrue(set_resp['ok'], f"Set failed: {set_resp.get('message')}")
        self.assertEqual(set_resp['min'], 1)
        self.assertEqual(set_resp['max'], 3)

        # View should now show the updated limits
        view_resp = self._casino_request('npc_limits')
        self.assertIsNotNone(view_resp)
        self.assertEqual(view_resp['min'], 1)
        self.assertEqual(view_resp['max'], 3)

    def test_npc_limits_invalid_min_gt_max(self):
        """Setting min > max is rejected."""
        resp = self._casino_request('npc_limits', min=5, max=2)
        self.assertIsNotNone(resp)
        self.assertFalse(resp['ok'])

    def test_autofill_fills_to_min(self):
        """With npc_min=2, a new game gains 2 NPCs via autofill within ~30s."""
        # Set min=2 so autofill kicks in
        set_resp = self._casino_request('npc_limits', min=2, max=4)
        self.assertIsNotNone(set_resp)
        self.assertTrue(set_resp['ok'])

        game_id = self.create_game()

        # Poll get_debug until the game has >= 2 NPCs (autofill runs every 15s)
        deadline = time.time() + 35
        npc_count = 0
        while time.time() < deadline:
            debug = self._get_debug()
            if debug:
                npc_count = self._npc_count_in_game(debug, game_id)
                if npc_count >= 2:
                    break
            time.sleep(1)

        self.assertGreaterEqual(
            npc_count, 2,
            f"Expected >= 2 NPCs via autofill, got {npc_count}"
        )


class TestManualNPC(EndToEndTestCase):
    """E2E tests for manual NPC add/remove commands (AM4)."""

    def setUp(self):
        super().setUp()
        self.game_id = None
        cursor = self.db.cursor()
        cursor.execute("DELETE FROM npcs")
        cursor.execute("DELETE FROM settings")
        self.db.commit()
        cursor.close()

    def tearDown(self):
        # Stop the game created by the test and wait for confirmation, so no
        # live game (still holding references to this test's NPCs) survives
        # into the next test's setUp(), which deletes the npcs table.
        if self.game_id:
            self._stop_game(self.game_id)
        super().tearDown()

    def _stop_game(self, game_id):
        pubsub = self.subscribe_to_game(game_id)
        try:
            self.redis.publish("casino", json.dumps({
                'event_type': 'casino_action',
                'action': 'stop_game',
                'game_id': game_id,
            }))
            deadline = time.time() + 5
            while time.time() < deadline:
                msg = pubsub.get_message(timeout=0.5)
                if msg and msg['type'] == 'message':
                    data = json.loads(msg['data'])
                    if data.get('event_type') == 'game_over':
                        return
        finally:
            pubsub.close()

    def _npc_action(self, action, game_id, **kwargs):
        self.redis.publish("casino", json.dumps({
            'event_type': 'npc_action',
            'action': action,
            'game_id': game_id,
            **kwargs,
        }))

    def _get_debug(self):
        pubsub = self.redis.pubsub()
        pubsub.subscribe("casino_update")
        pubsub.get_message(timeout=1)
        request_id = f"test-debug-{time.time()}"
        self.redis.publish("casino", json.dumps({
            'event_type': 'casino_action',
            'action': 'get_debug',
            'request_id': request_id,
        }))
        deadline = time.time() + 5
        while time.time() < deadline:
            msg = pubsub.get_message(timeout=0.5)
            if msg and msg['type'] == 'message':
                data = json.loads(msg['data'])
                if data.get('request_id') == request_id:
                    pubsub.close()
                    return data
        pubsub.close()
        return None

    def _npc_count_in_game(self, debug_data, game_id):
        for g in debug_data.get('games', []):
            if g['game_id'] == game_id:
                return sum(1 for p in g['players'] + g.get('players_waiting', [])
                           if p['is_npc'])
        return 0

    def _npc_names_in_game(self, debug_data, game_id):
        for g in debug_data.get('games', []):
            if g['game_id'] == game_id:
                return [p['name'] for p in g['players'] + g.get('players_waiting', [])
                        if p['is_npc']]
        return []

    def test_addnpc_increases_npc_count(self):
        """add_npc action adds an NPC from the roster to the game."""
        game_id = self.create_game()
        self.game_id = game_id
        time.sleep(1)

        debug_before = self._get_debug()
        count_before = self._npc_count_in_game(debug_before, game_id)

        self._npc_action('add_npc', game_id, count=1)
        time.sleep(2)

        debug_after = self._get_debug()
        count_after = self._npc_count_in_game(debug_after, game_id)

        self.assertEqual(count_after, count_before + 1,
                         f"Expected NPC count to increase by 1, was {count_before} → {count_after}")

    def test_addnpc_multiple(self):
        """add_npc with count=2 adds two NPCs."""
        game_id = self.create_game()
        self.game_id = game_id
        time.sleep(1)

        debug_before = self._get_debug()
        count_before = self._npc_count_in_game(debug_before, game_id)

        self._npc_action('add_npc', game_id, count=2)
        time.sleep(2)

        debug_after = self._get_debug()
        count_after = self._npc_count_in_game(debug_after, game_id)

        self.assertEqual(count_after, count_before + 2,
                         f"Expected NPC count to increase by 2, was {count_before} → {count_after}")

    def test_removenpc_by_name(self):
        """remove_npc with a name removes exactly that NPC."""
        game_id = self.create_game()
        self.game_id = game_id
        time.sleep(1)

        self._npc_action('add_npc', game_id, count=1)
        time.sleep(2)

        debug_after_add = self._get_debug()
        names = self._npc_names_in_game(debug_after_add, game_id)
        self.assertGreater(len(names), 0, "Expected at least one NPC after add_npc")

        target = names[0]
        self._npc_action('remove_npc', game_id, npc_name=target)
        time.sleep(2)

        debug_after_remove = self._get_debug()
        names_after = self._npc_names_in_game(debug_after_remove, game_id)
        self.assertNotIn(target, names_after,
                         f"NPC '{target}' should have been removed, remaining: {names_after}")

    def test_removenpc_arbitrary(self):
        """remove_npc with no name removes one NPC."""
        game_id = self.create_game()
        self.game_id = game_id
        time.sleep(1)

        self._npc_action('add_npc', game_id, count=1)
        time.sleep(2)

        debug_before = self._get_debug()
        count_before = self._npc_count_in_game(debug_before, game_id)
        self.assertGreater(count_before, 0, "Expected at least one NPC after add_npc")

        self._npc_action('remove_npc', game_id)
        time.sleep(2)

        debug_after = self._get_debug()
        count_after = self._npc_count_in_game(debug_after, game_id)
        self.assertEqual(count_after, count_before - 1,
                         f"Expected NPC count to decrease by 1, was {count_before} → {count_after}")


if __name__ == "__main__":
    unittest.main()
