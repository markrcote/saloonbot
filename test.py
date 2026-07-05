import json
import time
import unittest
from unittest.mock import MagicMock, patch

from cardgames.blackjack import (
    Action, Blackjack, HandState, InvalidActionError, InvalidBetError,
    card_to_str, str_to_card, serialize_hand, deserialize_hand,
    serialize_player, deserialize_player
)
from cardgames.npc_player import NPCPlayer
from cardgames.card_game import Card, CardGame, CardGameError
from cardgames.casino import (
    NPC_TYPES, Casino,
    DEFAULT_NPC_AUTOFILL_MIN, DEFAULT_NPC_AUTOFILL_MAX, MAX_NPCS_PER_TABLE,
)
from cardgames.player import Player
from cardgames.simple_npc import SimpleBlackjackNPC
from cardgames.sqlite_database import SqliteDatabase

from wwnames.wwnames import WildWestNames

# Remove join-delay so tests can tick WAITING→BETTING immediately
Blackjack.TIME_WAIT_FOR_PLAYERS = 0
# Skip dramatic pauses in tests
Blackjack.DRAMATIC_PAUSE = 0
Blackjack.DEALER_CARD_PAUSE = 0
Blackjack.RESULT_PAUSE = 0


class TestWildWestNames(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.wild_west_names = WildWestNames()

    @patch("random.choice")
    def test_random_name_male(self, mock_choice):
        mock_choice.side_effect = ["John", "Doe"]
        result = self.wild_west_names.random_name(gender="M")
        self.assertEqual(result, "♂ John Doe")

    @patch("random.choice")
    def test_random_name_female(self, mock_choice):
        mock_choice.side_effect = ["Jane", "Smith"]
        result = self.wild_west_names.random_name(gender="F")
        self.assertEqual(result, "♀ Jane Smith")

    @patch("random.choice")
    def test_random_name_random_gender(self, mock_choice):
        mock_choice.side_effect = ["F", "Mary", "Brown"]
        result = self.wild_west_names.random_name()
        self.assertEqual(result, "♀ Mary Brown")

    @patch("random.choice")
    def test_multiple_random_name_random_gender(self, mock_choice):
        mock_choice.side_effect = ["F", "Mary", "Brown", "M", "Aiden", "Patel"]
        result = self.wild_west_names.random_name(number=2)
        self.assertEqual(result, "♀ Mary Brown\n♂ Aiden Patel")


class TestCard(unittest.TestCase):
    def test_invalid_card(self):
        with self.assertRaises(CardGameError):
            Card("H", 16)

        with self.assertRaises(CardGameError):
            Card("X", 5)


class TestCardGame(unittest.TestCase):
    def setUp(self):
        self.game = CardGame()

    def test_create_deck(self):
        self.game.create_deck()
        # Check if the deck has 52 cards
        self.assertEqual(len(self.game.deck), 52)

    def test_deal(self):
        self.game.create_deck()
        self.game.players = [Player("Player 1"), Player("Player 2")]
        self.game.deal(self.game.players[0], 5)
        # Check if 5 cards were removed from the deck
        self.assertEqual(len(self.game.deck), 47)
        # Check if 5 cards were added to the player"s hand
        self.assertEqual(len(self.game.players[0].hand), 5)

    def test_discard(self):
        self.game.deck = [Card("H", 13), Card("H", 3), Card("H", 4),
                          Card("H", 5), Card("H", 6), Card("H", 7)]
        self.game.players = [Player("Player 1"), Player("Player 2")]
        self.game.deal(self.game.players[0], 3)
        self.game.discard(self.game.players[0], Card("H", 7))
        self.assertEqual(len(self.game.players[0].hand), 2)
        self.assertEqual(self.game.discards[-1].suit, "H")
        self.assertEqual(self.game.discards[-1].value, 7)
        # test discarding nonexistent card (should this raise an exception?)
        self.game.discard(self.game.players[0], Card("D", 3))
        self.assertEqual(len(self.game.deck), 3)
        self.assertEqual(len(self.game.discards), 1)
        self.assertEqual(len(self.game.players[0].hand), 2)

    def test_discard_all(self):
        self.game.create_deck()
        self.game.players = [Player("Player 1"), Player("Player 2")]
        self.game.deal(self.game.players[0], 7)
        self.game.deal(self.game.players[1], 7)
        self.assertEqual(len(self.game.deck), 38)
        self.game.discard_all(self.game.players[0])
        self.assertEqual(len(self.game.deck), 38)
        self.assertEqual(len(self.game.discards), 7)
        self.game.discard_all(self.game.players[1])
        # Check if each hand is empty
        for player in self.game.players:
            self.assertEqual(len(player.hand), 0)
        self.assertEqual(len(self.game.deck), 38)
        self.assertEqual(len(self.game.discards), 14)
        self.game.shuffle()
        self.assertEqual(len(self.game.deck), 52)
        self.assertEqual(len(self.game.discards), 0)

    def test_compare(self):
        card1 = Card("H", 5)
        card2 = Card("H", 5)
        card3 = Card("S", 5)
        card4 = Card("S", 7)
        self.assertGreater(card4, card3)
        self.assertLess(card2, card3)
        self.assertEqual(card1, card2)

    def test_card_strings(self):
        self.assertEqual("5 of Hearts", str(Card("H", 5)))
        self.assertEqual("Jack of Spades", Card("S", 11).str())
        self.assertEqual("A♥", Card("H", 14).str(short=True))
        self.assertEqual("2♦", Card("D", 2).str(short=True))


class TestBlackjack(unittest.TestCase):
    def setUp(self):
        mock_casino = MagicMock()
        mock_casino.db = MagicMock()
        mock_casino.get_wallet.return_value = 1000.0
        mock_casino.update_wallet.return_value = True
        self.game = Blackjack(game_id="test_game", casino=mock_casino)

    def test_new_hand(self):
        # Set up a mock deck (8 cards) to ensure dealer never has 21.
        # Pop order: dealer gets 5+6=11, player1 gets 7+8=15, player2 gets 9+4=13, 2 remain.
        self.game.deck = [Card("H", 2), Card("H", 3), Card("H", 4), Card("H", 9),
                          Card("H", 8), Card("H", 7), Card("H", 6), Card("H", 5)]

        # Verify that an error is raised when no players are present
        with self.assertRaises(CardGameError):
            self.game.new_hand()

        self.game.players.append(Player("Player 1"))
        self.game.players.append(Player("Player 2"))
        self.game.new_hand()
        self.assertEqual(len(self.game.players), 2)
        self.assertEqual(len(self.game.deck), 2)

    def test_dealer_has_21(self):
        # Hand 1 pop order: dealer gets H10+Ace=21, player gets H2+H3=5.
        # Hand 2 pop order (from remaining): dealer gets D2+D3=5, player gets D4+D5=9.
        self.game.deck = [Card("D", 5), Card("D", 4), Card("D", 3), Card("D", 2),
                          Card("H", 3), Card("H", 2), Card("H", 14), Card("H", 10)]
        self.game.players.append(Player("Player 1"))
        self.game.new_hand()
        self.assertEqual(self.game.get_score(self.game.dealer), 21)
        self.assertEqual(self.game.current_player_idx, None)
        self.game.new_hand()
        self.assertEqual(self.game.get_score(self.game.dealer), 5)
        self.assertEqual(self.game.get_score(self.game.players[0]), 9)

    def test_hit(self):
        self.game.deck = [Card("H", 13), Card("H", 3), Card("H", 4),
                          Card("H", 5), Card("H", 6), Card("H", 7)]

        self.game.players.append(Player("Player 1"))
        self.game.new_hand()
        self.assertEqual(len(self.game.dealer.hand), 2)
        self.assertEqual(self.game.get_score(self.game.dealer), 13)
        self.assertEqual(len(self.game.players[0].hand), 2)
        self.assertEqual(self.game.get_score(self.game.players[0]), 9)
        self.game.hit(self.game.players[0])
        self.assertEqual(len(self.game.players[0].hand), 3)
        self.assertEqual(self.game.get_score(self.game.players[0]), 12)
        self.assertEqual(len(self.game.deck), 1)  # from the mock deck
        self.assertEqual(self.game.current_player_idx, 0)
        self.game.hit(self.game.players[0])
        self.assertEqual(self.game.get_score(self.game.players[0]), 22)

    def test_hit_21_auto_advances(self):
        # deck.pop() deals last element first
        # deal order: dealer[0], dealer[1], player[0], player[1], then hit card
        # deck = [hit, player1, player0, dealer1, dealer0]
        # dealer gets 6+5=11 (not 21, so hand proceeds normally)
        # player gets 10+K=20, then hits Ace → 20+1=21 (Ace forced to 1 since 20+11>21)
        player = Player("Player 1")
        self.game.players.append(player)
        self.game.deck = [Card("H", 14), Card("H", 13), Card("H", 10), Card("H", 5), Card("H", 6)]
        self.game.new_hand()
        self.assertEqual(self.game.get_score(player), 20)
        self.game.hit(player)
        self.assertEqual(self.game.get_score(player), 21)
        # Hitting 21 must auto-advance — dealer's turn since there are no other players
        self.assertEqual(self.game.state, HandState.DEALER_TURN)

    def test_dealer_turn(self):
        self.assertFalse(self.game.is_dealer_turn())
        self.game.deck = [Card("H", 13), Card("H", 3), Card("H", 4),
                          Card("H", 5), Card("H", 6), Card("H", 7)]
        self.game.players.append(Player("Player 1"))
        self.game.new_hand()
        self.assertEqual(self.game.get_score(self.game.dealer), 13)
        self.game.stand(self.game.players[0])
        with self.assertRaises(CardGameError):
            self.game.next_turn()
        self.game.dealer_turn()
        self.assertEqual(len(self.game.dealer.hand), 4)
        self.assertEqual(self.game.get_score(self.game.dealer), 26)

    def test_tick(self):
        self.game.deck = [Card("H", 13), Card("H", 3), Card("H", 4),
                          Card("H", 5), Card("H", 6), Card("H", 7)]
        self.game.time_last_hand_ended = time.time() - self.game.TIME_BETWEEN_HANDS
        self.game.tick()  # shouldn"t do anything
        self.game.time_last_hand_ended = None

        self.game.players.append(Player("Player 1"))
        self.game.new_hand()
        self.game.bets["Player 1"] = self.game.MIN_BET
        self.assertEqual(self.game.get_score(self.game.dealer), 13)
        self.game.stand(self.game.players[0])
        self.game.tick()
        self.assertEqual(len(self.game.dealer.hand), 4)
        self.assertEqual(self.game.get_score(self.game.dealer), 26)
        self.game.tick()


class TestBlackjackStateMachine(unittest.TestCase):
    def setUp(self):
        mock_casino = MagicMock()
        mock_casino.db = MagicMock()
        mock_casino.get_wallet.return_value = 1000.0
        mock_casino.update_wallet.return_value = True
        self.game = Blackjack(game_id="test_game", casino=mock_casino)

    def test_initial_state_is_waiting(self):
        self.assertEqual(self.game.state, HandState.WAITING)

    def test_state_transitions_to_playing_on_new_hand(self):
        self.game.deck = [Card("H", 3), Card("H", 2), Card("H", 5), Card("H", 6)]
        self.game.players.append(Player("Player 1"))
        self.game.new_hand()
        self.assertEqual(self.game.state, HandState.PLAYING)

    def test_state_transitions_to_dealer_turn_after_all_players_stand(self):
        self.game.deck = [Card("H", 3), Card("H", 2), Card("H", 5), Card("H", 6)]
        self.game.players.append(Player("Player 1"))
        self.game.new_hand()
        self.game.stand(self.game.players[0])
        self.assertEqual(self.game.state, HandState.DEALER_TURN)

    def test_state_transitions_to_resolving_after_dealer_turn(self):
        # Need enough cards for dealer to potentially hit multiple times
        self.game.deck = [Card("H", 3), Card("H", 2), Card("H", 5), Card("H", 6),
                          Card("H", 7), Card("H", 8), Card("H", 9)]
        self.game.players.append(Player("Player 1"))
        self.game.new_hand()
        self.game.stand(self.game.players[0])
        self.game.dealer_turn()
        self.assertEqual(self.game.state, HandState.RESOLVING)

    def test_state_transitions_to_between_hands_after_resolving(self):
        self.game.deck = [Card("H", 3), Card("H", 2), Card("H", 5), Card("H", 6),
                          Card("H", 7), Card("H", 8), Card("H", 9)]
        self.game.players.append(Player("Player 1"))
        self.game.new_hand()
        self.game.bets["Player 1"] = self.game.MIN_BET
        self.game.stand(self.game.players[0])
        self.game.dealer_turn()
        self.assertEqual(self.game.state, HandState.RESOLVING)
        # Tick resolves the hand and transitions to BETWEEN_HANDS
        self.game.tick()
        self.assertEqual(self.game.state, HandState.BETWEEN_HANDS)

    def test_state_transitions_to_waiting_after_time_between_hands(self):
        self.game.deck = [Card("H", 3), Card("H", 2), Card("H", 5), Card("H", 6),
                          Card("H", 7), Card("H", 8), Card("H", 9)]
        self.game.players.append(Player("Player 1"))
        self.game.new_hand()
        self.game.bets["Player 1"] = self.game.MIN_BET
        self.game.stand(self.game.players[0])
        self.game.dealer_turn()
        self.game.tick()  # RESOLVING -> BETWEEN_HANDS
        self.assertEqual(self.game.state, HandState.BETWEEN_HANDS)
        # Simulate time passing
        self.game.time_last_hand_ended = time.time() - self.game.TIME_BETWEEN_HANDS - 1
        self.game.tick()
        self.assertEqual(self.game.state, HandState.WAITING)

    def test_invalid_action_hit_during_waiting(self):
        self.assertEqual(self.game.state, HandState.WAITING)
        with self.assertRaises(InvalidActionError):
            self.game.action({
                'event_type': 'player_action',
                'player': 'TestPlayer',
                'action': Action.HIT
            })

    def test_invalid_action_join_during_playing(self):
        self.game.deck = [Card("H", 3), Card("H", 2), Card("H", 5), Card("H", 6)]
        self.game.players.append(Player("Player 1"))
        self.game.new_hand()
        self.assertEqual(self.game.state, HandState.PLAYING)
        with self.assertRaises(InvalidActionError):
            self.game.action({
                'event_type': 'player_action',
                'player': 'Player 2',
                'action': Action.JOIN
            })


class TestDatabaseIntegration(unittest.TestCase):
    def test_join_game_with_database(self):
        # Create a mock database
        mock_db = MagicMock()
        mock_db.add_user.return_value = True

        # Create a mock casino with the database
        mock_casino = MagicMock()
        mock_casino.db = mock_db
        mock_casino.game_output = MagicMock()

        # Create a blackjack game with the casino
        game = Blackjack(game_id="test_game", casino=mock_casino)

        # Join a player
        player = Player("TestPlayer")
        game.join(player)

        # Verify that add_user was called with the player name
        mock_db.add_user.assert_called_once_with("TestPlayer")

        # Verify player was added to waiting list
        self.assertIn(player, game.players_waiting)

    def test_load_all_active_games_includes_waiting_games(self):
        """A freshly created, empty (WAITING) game must survive a server
        restart just like any other game — deploys shouldn't drop it."""
        db = SqliteDatabase(":memory:")
        try:
            mock_casino = MagicMock()
            mock_casino.db = db

            game = Blackjack(game_id="fresh_empty_game", casino=mock_casino)
            self.assertEqual(game.state, HandState.WAITING)
            db.save_game(game.game_id, game.to_dict())

            loaded = db.load_all_active_games()
            loaded_ids = {g['game_id'] for g in loaded}
            self.assertIn("fresh_empty_game", loaded_ids)
        finally:
            db.close()


class TestSettingsStore(unittest.TestCase):
    """AM1: settings key/value store on the SQLite backend."""

    def setUp(self):
        # In-memory DB runs all migrations, including the settings table.
        self.db = SqliteDatabase(":memory:")

    def tearDown(self):
        self.db.close()

    def test_missing_setting_returns_default(self):
        self.assertIsNone(self.db.get_setting("nope"))
        self.assertEqual(self.db.get_setting("nope", "fallback"), "fallback")

    def test_set_then_get(self):
        self.db.set_setting("npc_min", "2")
        self.assertEqual(self.db.get_setting("npc_min"), "2")

    def test_set_upserts_on_key(self):
        self.db.set_setting("npc_max", "4")
        self.db.set_setting("npc_max", "6")
        self.assertEqual(self.db.get_setting("npc_max"), "6")

    def test_non_string_value_stored_as_string(self):
        self.db.set_setting("npc_min", 3)
        self.assertEqual(self.db.get_setting("npc_min"), "3")


class TestWalletAdmin(unittest.TestCase):
    """AM1: absolute wallet sets and case-insensitive NPC lookup."""

    def setUp(self):
        self.db = SqliteDatabase(":memory:")

    def tearDown(self):
        self.db.close()

    def test_set_user_wallet_absolute(self):
        self.db.add_user("Maverick")
        self.assertTrue(self.db.set_user_wallet("Maverick", 555.0))
        self.assertEqual(self.db.get_user_wallet("Maverick"), 555.0)

    def test_set_user_wallet_missing_user_returns_false(self):
        self.assertFalse(self.db.set_user_wallet("Ghost", 100.0))

    def test_set_npc_wallet_absolute(self):
        npc_id = self.db.create_npc("Dusty Pete", "Prospector", 200)
        self.assertTrue(self.db.set_npc_wallet(npc_id, 42))
        self.assertEqual(self.db.get_npc_wallet(npc_id), 42.0)

    def test_set_npc_wallet_missing_npc_returns_false(self):
        self.assertFalse(self.db.set_npc_wallet(9999, 50))

    def test_find_npc_by_name_case_insensitive(self):
        npc_id = self.db.create_npc("Dusty Pete", "Prospector", 200)
        found = self.db.find_npc_by_name("dusty pete")
        self.assertIsNotNone(found)
        self.assertEqual(found["id"], npc_id)
        self.assertEqual(found["wallet"], 200)

    def test_find_npc_by_name_miss_returns_none(self):
        self.assertIsNone(self.db.find_npc_by_name("Nobody"))


class TestBlackjackBetting(unittest.TestCase):
    def setUp(self):
        mock_casino = MagicMock()
        mock_casino.db = MagicMock()
        mock_casino.get_wallet.return_value = 1000.0
        mock_casino.update_wallet.return_value = True
        self.game = Blackjack(game_id="test_game", casino=mock_casino)
        # Set up a mock deck
        self.game.deck = [Card("H", 3), Card("H", 2), Card("H", 5), Card("H", 6),
                          Card("H", 7), Card("H", 8), Card("H", 9), Card("H", 10)]

    def test_state_transitions_to_betting(self):
        self.game.join(Player("Player 1"))
        self.game.tick()  # WAITING -> BETTING
        self.assertEqual(self.game.state, HandState.BETTING)

    def test_bet_action_valid_in_betting_state(self):
        self.game.join(Player("Player 1"))
        self.game.tick()  # WAITING -> BETTING
        player = self.game.players[0]
        self.game.bet(player, 10)
        self.assertEqual(self.game.bets[player.name], 10)

    def test_bet_invalid_in_waiting_state(self):
        self.assertEqual(self.game.state, HandState.WAITING)
        self.game.join(Player("Player 1"))
        player = self.game.players_waiting[0]
        with self.assertRaises(CardGameError):
            self.game.bet(player, 10)

    def test_bet_below_minimum_rejected(self):
        self.game.join(Player("Player 1"))
        self.game.tick()  # WAITING -> BETTING
        player = self.game.players[0]
        with self.assertRaises(InvalidBetError):
            self.game.bet(player, self.game.MIN_BET - 1)

    def test_bet_above_maximum_rejected(self):
        self.game.join(Player("Player 1"))
        self.game.tick()  # WAITING -> BETTING
        player = self.game.players[0]
        with self.assertRaises(InvalidBetError):
            self.game.bet(player, self.game.MAX_BET + 1)

    def test_all_players_bet_triggers_dealing(self):
        self.game.join(Player("Player 1"))
        self.game.tick()  # WAITING -> BETTING
        player = self.game.players[0]
        self.game.bet(player, 10)
        self.game.tick()  # All bet -> PLAYING
        self.assertEqual(self.game.state, HandState.PLAYING)

    def test_timeout_removes_non_betting_players(self):
        self.game.join(Player("Player 1"))
        self.game.join(Player("Player 2"))
        self.game.tick()  # WAITING -> BETTING
        player1 = self.game.players[0]
        self.game.bet(player1, 10)
        # Simulate timeout
        self.game.time_betting_started = time.time() - self.game.TIME_FOR_BETTING - 1
        self.game.tick()  # Timeout -> remove non-betting player -> PLAYING
        self.assertEqual(self.game.state, HandState.PLAYING)
        self.assertEqual(len(self.game.players), 1)
        self.assertEqual(self.game.players[0].name, "Player 1")

    def test_double_bet_rejected(self):
        self.game.join(Player("Player 1"))
        self.game.tick()  # WAITING -> BETTING
        player = self.game.players[0]
        self.game.bet(player, 10)
        with self.assertRaises(CardGameError):
            self.game.bet(player, 20)


class TestBlackjackPayouts(unittest.TestCase):
    def test_winner_gets_2x_bet(self):
        mock_casino = MagicMock()
        mock_casino.db = MagicMock()
        mock_casino.get_wallet.return_value = 200.0
        mock_casino.update_wallet.return_value = True
        mock_casino.game_output = MagicMock()

        game = Blackjack(game_id="test", casino=mock_casino)
        # Stack deck so player wins (player gets 20, dealer gets 16 then busts)
        # Cards dealt from END: dealer gets 2, player gets 2, dealer hits
        # Deck order: [dealer_hit, player2, player1, dealer2, dealer1]
        # Dealer: 10, 6 (16), then hits and gets 10 (26 bust)
        # Player: 10, 10 (20)
        game.deck = [Card("H", 10), Card("H", 10), Card("H", 10), Card("H", 6),
                     Card("H", 10)]
        game.join(Player("Player 1"))
        game.tick()  # WAITING -> BETTING
        player = game.players[0]
        game.bet(player, 20)
        game.tick()  # BETTING -> PLAYING
        game.stand(player)
        game.tick()  # DEALER_TURN
        game.tick()  # RESOLVING -> BETWEEN_HANDS

        # Find the payout call (should be 40 = 2x bet)
        payout_calls = [call for call in mock_casino.update_wallet.call_args_list
                        if call[0][1] > 0]  # Positive amount = payout
        self.assertEqual(len(payout_calls), 1)
        self.assertEqual(payout_calls[0][0][1], 40)

    def test_tie_returns_bet(self):
        mock_casino = MagicMock()
        mock_casino.db = MagicMock()
        mock_casino.get_wallet.return_value = 200.0
        mock_casino.update_wallet.return_value = True
        mock_casino.game_output = MagicMock()

        game = Blackjack(game_id="test", casino=mock_casino)
        # Stack deck for tie - both dealer and player get 20
        # Dealer: 10, 10 (20)
        # Player: 10, 10 (20)
        game.deck = [Card("H", 10), Card("H", 10), Card("S", 10), Card("S", 10)]
        game.join(Player("Player 1"))
        game.tick()  # WAITING -> BETTING
        player = game.players[0]
        game.bet(player, 20)
        game.tick()  # BETTING -> PLAYING
        game.stand(player)
        game.tick()  # DEALER_TURN
        game.tick()  # RESOLVING -> BETWEEN_HANDS

        # Find the return call (should be 20 = bet returned)
        payout_calls = [call for call in mock_casino.update_wallet.call_args_list
                        if call[0][1] > 0]  # Positive amount = payout
        self.assertEqual(len(payout_calls), 1)
        self.assertEqual(payout_calls[0][0][1], 20)

    def test_loser_forfeits_bet(self):
        mock_casino = MagicMock()
        mock_casino.db = MagicMock()
        mock_casino.get_wallet.return_value = 200.0
        mock_casino.update_wallet.return_value = True
        mock_casino.game_output = MagicMock()

        game = Blackjack(game_id="test", casino=mock_casino)
        # Stack deck so player loses (player gets 15, dealer gets 20)
        # Cards dealt from END: dealer gets 2, player gets 2
        # Deck order: [player2, player1, dealer2, dealer1]
        # Dealer: 10, 10 (20)
        # Player: 10, 5 (15)
        game.deck = [Card("H", 5), Card("H", 10), Card("H", 10), Card("H", 10)]
        game.join(Player("Player 1"))
        game.tick()  # WAITING -> BETTING
        player = game.players[0]
        game.bet(player, 20)
        game.tick()  # BETTING -> PLAYING
        game.stand(player)
        game.tick()  # DEALER_TURN
        game.tick()  # RESOLVING -> BETWEEN_HANDS

        # Should have only one update call (the initial bet deduction)
        payout_calls = [call for call in mock_casino.update_wallet.call_args_list
                        if call[0][1] > 0]  # Positive amount = payout
        self.assertEqual(len(payout_calls), 0)

    def test_leave_during_betting_returns_bet(self):
        mock_casino = MagicMock()
        mock_casino.db = MagicMock()
        mock_casino.get_wallet.return_value = 200.0
        mock_casino.update_wallet.return_value = True
        mock_casino.game_output = MagicMock()

        game = Blackjack(game_id="test", casino=mock_casino)
        game.deck = [Card("H", 3), Card("H", 2), Card("H", 5), Card("H", 6)]
        game.join(Player("Player 1"))
        game.tick()  # WAITING -> BETTING
        player = game.players[0]
        game.bet(player, 20)
        game.leave(player)

        # Bet should be returned — cards haven't been dealt yet
        refund_calls = [call for call in mock_casino.update_wallet.call_args_list
                        if call[0][1] > 0]  # Positive amount = refund
        self.assertEqual(len(refund_calls), 1)
        self.assertEqual(refund_calls[0][0][1], 20)

    def test_leave_during_playing_forfeits_bet(self):
        mock_casino = MagicMock()
        mock_casino.db = MagicMock()
        mock_casino.get_wallet.return_value = 200.0
        mock_casino.update_wallet.return_value = True
        mock_casino.game_output = MagicMock()

        game = Blackjack(game_id="test", casino=mock_casino)
        game.deck = [Card("H", 3), Card("H", 2), Card("H", 5), Card("H", 6)]
        game.join(Player("Player 1"))
        game.tick()  # WAITING -> BETTING
        player = game.players[0]
        game.bet(player, 20)
        game.tick()  # BETTING -> PLAYING (new_hand)
        game.leave(player)

        # Bet forfeited — player left mid-hand on their own turn
        refund_calls = [call for call in mock_casino.update_wallet.call_args_list
                        if call[0][1] > 0]  # Positive amount = refund
        self.assertEqual(len(refund_calls), 0)

    def _make_three_player_playing_game(self):
        """Return a game with 3 players mid-hand (Alice=0, Bob=1, Carol=2), current=Bob."""
        mock_casino = MagicMock()
        mock_casino.db = MagicMock()
        mock_casino.get_wallet.return_value = 200.0
        mock_casino.update_wallet.return_value = True
        mock_casino.game_output = MagicMock()

        game = Blackjack(game_id="test", casino=mock_casino)
        alice, bob, carol = Player("Alice"), Player("Bob"), Player("Carol")
        for p in (alice, bob, carol):
            game.join(p)
        game.tick()  # WAITING -> BETTING
        game.bet(alice, 10)
        game.bet(bob, 10)
        game.bet(carol, 10)
        # Control the deck: dealer gets 5+6=11, players get safe hands; no blackjack possible
        safe = [Card("H", 5), Card("H", 6), Card("H", 7), Card("H", 8),
                Card("H", 3), Card("H", 4), Card("H", 5), Card("H", 6)]
        game.deck = [Card("H", 2)] * 4 + safe
        game.new_hand()  # BETTING -> PLAYING, current_player_idx = 0
        self.assertEqual(game.state, HandState.PLAYING, "dealer should not have blackjack")
        game.current_player_idx = 1  # simulate it being Bob's turn
        return game, alice, bob, carol

    def test_leave_before_current_adjusts_idx(self):
        """Player before current index leaves — idx must shift down by 1."""
        game, alice, bob, carol = self._make_three_player_playing_game()
        game.leave(alice)  # removes idx 0; current was 1 (Bob), should become 0
        self.assertEqual(game.current_player_idx, 0)
        self.assertEqual(game.players[game.current_player_idx].name, "Bob")

    def test_leave_at_current_advances_turn(self):
        """Current player leaves — turn should advance to next player."""
        game, alice, bob, carol = self._make_three_player_playing_game()
        game.leave(bob)  # removes idx 1 (current); Carol slides to idx 1
        self.assertEqual(game.current_player_idx, 1)
        self.assertEqual(game.players[game.current_player_idx].name, "Carol")

    def test_leave_after_current_no_change(self):
        """Player after current index leaves — idx unchanged."""
        game, alice, bob, carol = self._make_three_player_playing_game()
        game.leave(carol)  # removes idx 2; current=1 (Bob), no change
        self.assertEqual(game.current_player_idx, 1)
        self.assertEqual(game.players[game.current_player_idx].name, "Bob")

    def test_leave_last_player_transitions_to_waiting(self):
        """All players forfeit before acting — empty table with no departed players goes to WAITING."""
        game, alice, bob, carol = self._make_three_player_playing_game()
        # Reset to alice's turn so no one has acted yet; all leaves are forfeits
        game.current_player_idx = 0
        game.leave(alice)   # current player → forfeit
        game.leave(bob)     # current player → forfeit
        game.leave(carol)   # current player → forfeit
        self.assertEqual(game.state, HandState.WAITING)
        self.assertIsNone(game.current_player_idx)
        self.assertEqual(game.departed_players, [])

    def test_leave_after_acting_goes_to_departed_then_dealer_turn(self):
        """Player who already acted goes to departed_players; table moves to DEALER_TURN for resolution."""
        game, alice, bob, carol = self._make_three_player_playing_game()
        # current_player_idx=1 (Bob's turn); Alice (idx 0) has already acted → departed
        game.leave(alice)
        self.assertIn(alice, game.departed_players)
        self.assertNotIn(alice, game.players)
        # Alice's bet still present for end_hand() to process
        self.assertIn(alice.name, game.bets)
        # Bob and Carol forfeit
        game.leave(carol)
        game.leave(bob)
        # departed_players=[alice] → DEALER_TURN, not WAITING
        self.assertEqual(game.state, HandState.DEALER_TURN)
        self.assertIsNone(game.current_player_idx)

    def test_leave_advances_to_dealer_turn_with_players_remaining(self):
        """Current player (last in turn order) leaves while others still at table — goes to DEALER_TURN."""
        game, alice, bob, carol = self._make_three_player_playing_game()
        # Set current to Carol (last turn), then Carol leaves — Alice and Bob still present
        game.current_player_idx = 2
        game.leave(carol)
        self.assertEqual(game.state, HandState.DEALER_TURN)
        self.assertIsNone(game.current_player_idx)
        self.assertGreater(len(game.players), 0)

    def test_departed_player_resolved_at_end_hand(self):
        """Departed player's hand is settled at end_hand() with correct payout."""
        game, alice, bob, carol = self._make_three_player_playing_game()
        # current_player_idx=1 (Bob's turn); Alice (idx 0) already acted → departed
        game.leave(alice)
        self.assertIn(alice, game.departed_players)
        alice_bet = game.bets[alice.name]

        # Give alice a winning hand (score 20), dealer a losing hand (score 16)
        alice.hand = [Card("H", 10), Card("S", 10)]
        game.dealer.hand = [Card("H", 8), Card("S", 8)]
        game.state = HandState.RESOLVING

        game.end_hand()

        # Alice's bet cleared and departed_players reset
        self.assertEqual(game.departed_players, [])
        self.assertNotIn(alice.name, game.bets)
        # Alice should have received 2× her bet (winning payout)
        game.casino.update_wallet.assert_any_call(alice, alice_bet * 2)


class TestNPCDepartureHook(unittest.TestCase):
    """M4.4: Blackjack.leave() fires the shared on_npc_departed hook exactly
    once per NPC departure, regardless of path, and never fires it for humans."""

    def _make_game(self):
        mock_casino = MagicMock()
        mock_casino.db = MagicMock()
        mock_casino.get_wallet.return_value = 200.0
        mock_casino.update_wallet.return_value = True
        mock_casino.game_output = MagicMock()
        hook = MagicMock()
        game = Blackjack(game_id="test", casino=mock_casino, on_npc_departed=hook)
        return game, hook

    def test_leave_fires_hook_for_npc(self):
        game, hook = self._make_game()
        npc = SimpleBlackjackNPC("Deuces Wilder")
        game.join(npc)
        game.tick()  # WAITING -> BETTING, npc promoted to players
        game.leave(npc)
        hook.assert_called_once_with(game, npc)

    def test_leave_does_not_fire_hook_for_human(self):
        game, hook = self._make_game()
        human = Player("Player 1")
        game.join(human)
        game.tick()  # WAITING -> BETTING
        game.leave(human)
        hook.assert_not_called()

    def test_leave_from_players_waiting_fires_hook_for_npc(self):
        """NPC removed before its first hand (still in players_waiting) still fires the hook."""
        game, hook = self._make_game()
        npc = SimpleBlackjackNPC("Widow Maker")
        game.join(npc)  # WAITING state -> goes to players_waiting
        self.assertIn(npc, game.players_waiting)
        game.leave(npc)
        hook.assert_called_once_with(game, npc)

    def test_broke_npc_removal_routes_through_leave_and_fires_hook(self):
        """The broke-NPC auto-drop in _tick_betting goes through leave(), not
        direct self.players manipulation, and fires the shared hook."""
        game, hook = self._make_game()
        game.casino.get_wallet.return_value = 0.0  # below MIN_BET
        npc = SimpleBlackjackNPC("Broke Betty")
        game.join(npc)
        game.tick()  # WAITING -> BETTING
        game.tick()  # _tick_betting drops the broke NPC
        self.assertNotIn(npc, game.players)
        hook.assert_called_once_with(game, npc)

    def test_broke_npc_gets_tapped_out_message(self):
        """Flavor text is preserved even though the removal now routes through leave()."""
        game, hook = self._make_game()
        game.casino.get_wallet.return_value = 0.0
        npc = SimpleBlackjackNPC("Broke Betty")
        game.join(npc)
        game.tick()
        game.tick()
        messages = [call.args[1] for call in game.casino.game_output.call_args_list]
        self.assertTrue(any("tapped out" in m for m in messages))


class TestCasinoErrorHandling(unittest.TestCase):
    def setUp(self):
        self.mock_redis = MagicMock()
        self.mock_db = MagicMock()
        self.mock_db.get_user_wallet.return_value = 1000.0
        self.casino = Casino(redis_host="localhost", redis_port=6379)
        self.casino.redis = self.mock_redis
        self.casino.db = self.mock_db

    def test_invalid_action_user_message(self):
        """Test that InvalidActionError has a user-friendly message."""
        game_id = self.casino.new_game()
        game = self.casino.games[game_id]

        data = {
            'event_type': 'player_action',
            'game_id': game_id,
            'player': 'TestPlayer',
            'action': 'hit'
        }

        with self.assertRaises(InvalidActionError) as context:
            game.action(data)

        self.assertEqual(context.exception.user_message(), "You can't use 'hit' right now.")

    def test_unrecognized_action_user_message(self):
        """Test user-friendly message for unrecognized actions."""
        game_id = self.casino.new_game()
        game = self.casino.games[game_id]

        game.join(Player("TestPlayer"))
        game.tick()  # WAITING -> BETTING

        data = {
            'event_type': 'player_action',
            'game_id': game_id,
            'player': 'TestPlayer',
            'action': '11'
        }

        with self.assertRaises(InvalidActionError) as context:
            game.action(data)

        self.assertEqual(context.exception.user_message(), "You can't use '11' right now.")

    def test_idle_game_removed_and_game_over_event_published(self):
        """Idle empty games should be deleted and a game_over event published to the bot."""
        game_id = self.casino.new_game()

        # Fast-forward time past the idle timeout
        game = self.casino.games[game_id]
        game.time_last_event = 0

        self.casino._tick_games()

        # Game should be gone from casino
        self.assertNotIn(game_id, self.casino.games)

        # A game_over event must have been published on the game's topic
        calls = self.mock_redis.publish.call_args_list
        game_over_call = None
        for call in calls:
            channel, payload = call.args
            if channel == f"game_updates_{game_id}":
                msg = json.loads(payload)
                if msg.get('event_type') == 'game_over':
                    game_over_call = msg
                    break
        self.assertIsNotNone(game_over_call, "game_over event was not published")
        self.assertEqual(game_over_call['game_id'], game_id)


class TestSerialization(unittest.TestCase):
    """Tests for game state serialization/deserialization."""

    def test_card_serialization_roundtrip(self):
        """Test card serialization and deserialization."""
        cards = [
            Card("H", 2),   # 2 of Hearts
            Card("S", 14),  # Ace of Spades
            Card("D", 10),  # 10 of Diamonds
            Card("C", 13),  # King of Clubs
        ]
        for card in cards:
            serialized = card_to_str(card)
            deserialized = str_to_card(serialized)
            self.assertEqual(card.suit, deserialized.suit)
            self.assertEqual(card.value, deserialized.value)

    def test_card_serialization_format(self):
        """Test that cards serialize to expected format."""
        self.assertEqual(card_to_str(Card("H", 10)), "H10")
        self.assertEqual(card_to_str(Card("S", 14)), "S14")
        self.assertEqual(card_to_str(Card("D", 2)), "D2")

    def test_hand_serialization_roundtrip(self):
        """Test hand serialization and deserialization."""
        hand = [Card("H", 10), Card("S", 14), Card("D", 5)]
        serialized = serialize_hand(hand)
        self.assertEqual(serialized, ["H10", "S14", "D5"])
        deserialized = deserialize_hand(serialized)
        for orig, restored in zip(hand, deserialized):
            self.assertEqual(orig.suit, restored.suit)
            self.assertEqual(orig.value, restored.value)

    def test_player_serialization_roundtrip(self):
        """Test player serialization and deserialization."""
        player = Player("TestPlayer")
        player.hand = [Card("H", 10), Card("S", 14)]
        serialized = serialize_player(player)
        self.assertEqual(serialized['name'], "TestPlayer")
        self.assertEqual(serialized['hand'], ["H10", "S14"])
        deserialized = deserialize_player(serialized)
        self.assertEqual(deserialized.name, "TestPlayer")
        self.assertEqual(len(deserialized.hand), 2)
        self.assertEqual(deserialized.hand[0].suit, "H")
        self.assertEqual(deserialized.hand[0].value, 10)

    def test_game_serialization_roundtrip(self):
        """Test full game state serialization and deserialization."""
        mock_casino = MagicMock()
        mock_casino.db = MagicMock()
        mock_casino.get_wallet.return_value = 1000.0
        mock_casino.update_wallet.return_value = True

        game = Blackjack(game_id="test_game", casino=mock_casino)
        game.deck = [Card("H", 3), Card("H", 2), Card("H", 5), Card("H", 6),
                     Card("H", 7), Card("H", 8), Card("H", 9), Card("H", 10)]

        # Set up a game in progress
        game.join(Player("Player1"))
        game.tick()  # WAITING -> BETTING
        game.bet(game.players[0], 20)
        game.tick()  # BETTING -> PLAYING

        # Serialize
        game_data = game.to_dict()

        # Verify serialized data
        self.assertEqual(game_data['game_id'], "test_game")
        self.assertEqual(game_data['state'], "playing")
        self.assertEqual(game_data['current_player_idx'], 0)
        self.assertIn('Player1', game_data['bets'])
        self.assertEqual(game_data['bets']['Player1'], 20)

        # Deserialize into new game
        restored_game = Blackjack.from_dict(game_data, mock_casino)

        # Verify restored state
        self.assertEqual(restored_game.game_id, "test_game")
        self.assertEqual(restored_game.state, HandState.PLAYING)
        self.assertEqual(restored_game.current_player_idx, 0)
        self.assertEqual(len(restored_game.players), 1)
        self.assertEqual(restored_game.players[0].name, "Player1")
        self.assertEqual(restored_game.bets['Player1'], 20)

        # Verify hands were restored
        self.assertEqual(len(restored_game.dealer.hand), 2)
        self.assertEqual(len(restored_game.players[0].hand), 2)

    def test_timing_adjustment_on_restore(self):
        """Test that timing fields are adjusted correctly on restore."""
        mock_casino = MagicMock()
        mock_casino.db = MagicMock()
        mock_casino.get_wallet.return_value = 1000.0
        mock_casino.update_wallet.return_value = True

        game = Blackjack(game_id="test_game", casino=mock_casino)
        game.deck = [Card("H", 3), Card("H", 2), Card("H", 5), Card("H", 6)]

        # Start betting
        game.join(Player("Player1"))
        game.tick()  # WAITING -> BETTING

        # Serialize with a fake "old" time_last_event
        game_data = game.to_dict()
        fake_save_time = time.time() - 5  # Pretend saved 5 seconds ago
        betting_started = fake_save_time - 2  # Betting started 2s before save = 7s ago total
        game_data['time_last_event'] = fake_save_time
        game_data['time_betting_started'] = betting_started

        # Restore
        before_restore = time.time()
        restored_game = Blackjack.from_dict(game_data, mock_casino)
        after_restore = time.time()

        # time_last_event should be approximately now
        self.assertGreaterEqual(restored_game.time_last_event, before_restore)
        self.assertLessEqual(restored_game.time_last_event, after_restore)

        # time_betting_started must keep its original absolute timestamp so the timer
        # continues from where it left off (7s elapsed total, not reset to 2s)
        self.assertAlmostEqual(restored_game.time_betting_started, betting_started, places=1)
        elapsed = time.time() - restored_game.time_betting_started
        self.assertAlmostEqual(elapsed, 7.0, places=0)

    def test_empty_game_serialization(self):
        """Test serialization of a game with no players."""
        mock_casino = MagicMock()
        mock_casino.db = MagicMock()

        game = Blackjack(game_id="empty_game", casino=mock_casino)
        game_data = game.to_dict()

        self.assertEqual(game_data['state'], "waiting")
        self.assertEqual(game_data['players'], [])
        self.assertEqual(game_data['players_waiting'], [])
        self.assertEqual(game_data['bets'], {})

        restored = Blackjack.from_dict(game_data, mock_casino)
        self.assertEqual(restored.state, HandState.WAITING)
        self.assertEqual(len(restored.players), 0)


class TestPersonalities(unittest.TestCase):
    def test_full_archetype_count(self):
        from cardgames.personalities import _ARCHETYPES, _FAMOUS
        self.assertEqual(len(_ARCHETYPES), 15)
        self.assertEqual(len(_FAMOUS), 4)

    def test_get_all_names_returns_all(self):
        from cardgames.personalities import get_all_names, _ALL
        names = get_all_names()
        self.assertEqual(len(names), len(_ALL))
        self.assertIn("Doc Holliday", names)
        self.assertIn("The Grizzled Prospector", names)

    def test_get_random_excludes_names(self):
        from cardgames.personalities import get_random, get_all_names
        all_names = set(get_all_names())
        exclude = all_names - {"The Drunk Cowboy"}
        for _ in range(20):
            p = get_random(exclude_names=exclude)
            self.assertEqual(p.name, "The Drunk Cowboy")

    def test_get_random_falls_back_when_all_excluded(self):
        from cardgames.personalities import get_random, get_all_names
        all_names = set(get_all_names())
        p = get_random(exclude_names=all_names)
        self.assertIn(p.name, all_names)

    def test_famous_rate(self):
        from cardgames.personalities import get_random
        draws = [get_random() for _ in range(5000)]
        famous_count = sum(1 for p in draws if p.is_famous)
        famous_rate = famous_count / len(draws)
        # Expected ~1.32% (4 famous at weight 1 vs 15 archetypes at weight 20)
        self.assertGreater(famous_rate, 0.005)
        self.assertLess(famous_rate, 0.05)

    def test_all_personalities_have_json_instruction(self):
        from cardgames.personalities import _ALL
        for p in _ALL:
            self.assertIn("Respond ONLY with valid JSON", p.system_prompt, p.name)

    def test_no_duplicate_names(self):
        from cardgames.personalities import _ALL
        names = [p.name for p in _ALL]
        self.assertEqual(len(names), len(set(names)))


class TestNPCPlayer(unittest.TestCase):
    def test_npc_player_is_abstract(self):
        """NPCPlayer cannot be instantiated directly."""
        with self.assertRaises(TypeError):
            NPCPlayer("AbstractNPC")

    def test_player_is_not_npc(self):
        """Regular Player should not be an NPC."""
        player = Player("Human")
        self.assertFalse(player.is_npc)

    def test_simple_npc_is_npc(self):
        """SimpleBlackjackNPC should be identified as an NPC."""
        npc = SimpleBlackjackNPC("TestNPC")
        self.assertTrue(npc.is_npc)

    def test_simple_npc_is_player(self):
        """SimpleBlackjackNPC should be a Player instance."""
        npc = SimpleBlackjackNPC("TestNPC")
        self.assertIsInstance(npc, Player)


class TestSimpleBlackjackNPC(unittest.TestCase):
    def setUp(self):
        self.npc = SimpleBlackjackNPC("TestNPC")

    def test_bet_returns_minimum(self):
        self.assertEqual(self.npc.decide_bet(5, 100, 200), 5)

    def test_hit_on_low_score_strong_dealer(self):
        """NPC should hit when score is below 17 against strong dealer card."""
        card = Card("H", 10)
        self.assertEqual(self.npc.decide_action([], card, 15), "hit")

    def test_stand_on_17_strong_dealer(self):
        """NPC should stand on 17 against strong dealer card."""
        card = Card("H", 10)
        self.assertEqual(self.npc.decide_action([], card, 17), "stand")

    def test_stand_on_12_weak_dealer(self):
        """NPC should stand on 12+ against weak dealer card (2-6)."""
        card = Card("H", 5)
        self.assertEqual(self.npc.decide_action([], card, 12), "stand")

    def test_hit_on_11_weak_dealer(self):
        """NPC should hit on 11 against weak dealer card."""
        card = Card("H", 5)
        self.assertEqual(self.npc.decide_action([], card, 11), "hit")

    def test_hit_on_low_score_moderate_dealer(self):
        """NPC should hit below 17 against moderate dealer card (7-9)."""
        card = Card("H", 8)
        self.assertEqual(self.npc.decide_action([], card, 16), "hit")

    def test_stand_on_17_moderate_dealer(self):
        """NPC should stand on 17 against moderate dealer card."""
        card = Card("H", 8)
        self.assertEqual(self.npc.decide_action([], card, 17), "stand")

    def test_hit_against_dealer_ace(self):
        """NPC should hit below 17 against dealer ace (strong card)."""
        card = Card("H", 14)
        self.assertEqual(self.npc.decide_action([], card, 16), "hit")


class TestNPCBlackjackIntegration(unittest.TestCase):
    def setUp(self):
        mock_casino = MagicMock()
        mock_casino.db = MagicMock()
        mock_casino.get_wallet.return_value = 1000.0
        mock_casino.update_wallet.return_value = True
        self.game = Blackjack(game_id="test_game", casino=mock_casino)

    def test_npc_auto_bets_during_tick(self):
        """NPC should automatically place a bet during the betting phase."""
        self.game.deck = [Card("H", 3), Card("H", 2), Card("H", 5), Card("H", 6),
                          Card("H", 7), Card("H", 8)]
        npc = SimpleBlackjackNPC("AutoBetNPC")
        self.game.join(npc)
        self.game.tick()  # WAITING -> BETTING
        self.assertEqual(self.game.state, HandState.BETTING)
        self.game.tick()  # BETTING: NPC auto-bets, all bets in -> deals
        self.assertIn("AutoBetNPC", self.game.bets)
        self.assertEqual(self.game.bets["AutoBetNPC"], self.game.MIN_BET)

    def test_npc_auto_bets_then_deals(self):
        """After NPC auto-bets, the same tick should deal cards."""
        self.game.deck = [Card("H", 3), Card("H", 2), Card("H", 5), Card("H", 6),
                          Card("H", 7), Card("H", 8)]
        npc = SimpleBlackjackNPC("DealNPC")
        self.game.join(npc)
        self.game.tick()  # WAITING -> BETTING
        self.game.tick()  # BETTING: NPC auto-bets -> PLAYING
        self.assertEqual(self.game.state, HandState.PLAYING)

    def test_npc_auto_plays_turn(self):
        """NPC should automatically play during its turn."""
        # Stack the deck: dealer gets 10+6=16, NPC gets 10+8=18 -> stands
        self.game.deck = [Card("H", 8), Card("H", 10), Card("H", 6), Card("H", 10)]
        npc = SimpleBlackjackNPC("PlayNPC")
        self.game.join(npc)
        self.game.tick()  # WAITING -> BETTING
        self.game.tick()  # BETTING -> PLAYING
        self.assertEqual(self.game.state, HandState.PLAYING)
        self.game.tick()  # NPC auto-plays (score 18 -> stand)
        self.assertEqual(self.game.state, HandState.DEALER_TURN)

    def test_npc_hits_on_low_score(self):
        """NPC should hit when score is low."""
        # Deck: dealer 10+7=17, NPC 3+2=5 -> NPC hits, gets 10 -> 15, hits again, gets 5 -> 20
        self.game.deck = [Card("H", 5), Card("H", 10), Card("H", 2), Card("H", 3),
                          Card("H", 7), Card("H", 10)]
        npc = SimpleBlackjackNPC("HitNPC")
        self.game.join(npc)
        self.game.tick()  # WAITING -> BETTING
        self.game.tick()  # BETTING -> PLAYING
        # NPC has 5, dealer shows 10 (strong) -> hit
        self.assertEqual(self.game.get_score(npc), 5)
        self.game.tick()  # NPC hits -> 15
        self.assertEqual(self.game.get_score(npc), 15)
        self.assertEqual(self.game.state, HandState.PLAYING)
        self.game.tick()  # NPC hits again -> 20
        self.assertEqual(self.game.get_score(npc), 20)
        self.assertEqual(self.game.state, HandState.PLAYING)
        self.game.tick()  # NPC stands on 20
        self.assertEqual(self.game.state, HandState.DEALER_TURN)

    def test_npc_complete_game(self):
        """NPC should play a complete game through all state transitions."""
        # Dealer: 10+7=17, NPC: 10+8=18 -> NPC stands -> dealer stands -> resolve
        self.game.deck = [Card("H", 8), Card("H", 10), Card("H", 7), Card("H", 10)]
        npc = SimpleBlackjackNPC("FullGameNPC")
        self.game.join(npc)
        self.game.tick()  # WAITING -> BETTING
        self.game.tick()  # BETTING -> PLAYING
        self.game.tick()  # NPC stands (18)
        self.assertEqual(self.game.state, HandState.DEALER_TURN)
        self.game.tick()  # Dealer plays
        self.assertEqual(self.game.state, HandState.RESOLVING)
        self.game.tick()  # Resolve
        self.assertEqual(self.game.state, HandState.BETWEEN_HANDS)

    def test_npc_and_human_together(self):
        """NPC and human player should coexist in the same game."""
        # Dealer: 10+6=16, Human: 10+8=18, NPC: 10+7=17
        self.game.deck = [Card("H", 7), Card("H", 8), Card("H", 10), Card("H", 10),
                          Card("H", 6), Card("H", 10), Card("H", 10)]
        human = Player("Human")
        npc = SimpleBlackjackNPC("NPCFriend")
        self.game.join(human)
        self.game.join(npc)
        self.game.tick()  # WAITING -> BETTING
        self.assertNotIn("NPCFriend", self.game.bets)
        self.assertNotIn("Human", self.game.bets)
        # Human places bet; NPC will auto-bet on next tick
        self.game.bet(human, 10)
        self.game.tick()  # BETTING: NPC auto-bets, all bets in -> PLAYING
        self.assertIn("NPCFriend", self.game.bets)
        self.assertEqual(self.game.state, HandState.PLAYING)
        # Human is first, should be their turn
        self.assertEqual(self.game.players[self.game.current_player_idx], human)
        self.game.stand(human)
        # Now it's NPC's turn - NPC auto-plays on tick
        self.assertEqual(self.game.players[self.game.current_player_idx], npc)
        self.game.tick()  # NPC auto-stands (17, dealer shows 10=strong, 17 >= 17)
        self.assertEqual(self.game.state, HandState.DEALER_TURN)


class TestCasinoNPCManagement(unittest.TestCase):
    def setUp(self):
        self.mock_redis = MagicMock()
        self.mock_db = MagicMock()
        self.mock_db.get_user_wallet.return_value = 1000.0
        self.casino = Casino(redis_host="localhost", redis_port=6379)
        self.casino.redis = self.mock_redis
        self.casino.db = self.mock_db

    def test_add_npc_to_game(self):
        self.casino.db = None  # use ephemeral NPC path (no DB needed)
        game_id = self.casino.new_game()
        self.casino.add_npc(game_id, 1)
        game = self.casino.games[game_id]
        npcs = [p for p in game.players_waiting if p.is_npc]
        self.assertEqual(len(npcs), 1)
        self.assertTrue(npcs[0].is_npc)

    def test_add_npc_batch_gets_combined_intro_message(self):
        """Adding NPCs together produces one combined 'New arrivals' intro
        message instead of a per-NPC 'pulls up a chair' line."""
        self.casino.db = None
        game_id = self.casino.new_game()
        self.casino.game_output = MagicMock()
        self.casino.add_npc(game_id, 2)
        messages = [call.args[1] for call in self.casino.game_output.call_args_list]
        arrival_msgs = [m for m in messages if "New arrivals" in m]
        self.assertEqual(len(arrival_msgs), 1)
        self.assertEqual(len([m for m in messages if "pulls up a chair" in m]), 0)
        game = self.casino.games[game_id]
        for npc in (p for p in game.players_waiting if p.is_npc):
            self.assertIn(npc.name, arrival_msgs[0])

    def test_add_npc_capped_at_max(self):
        """add_npc is a no-op when the game is already at MAX_NPCS_PER_TABLE."""
        self.casino.db = None
        game_id = self.casino.new_game()
        game = self.casino.games[game_id]
        # Fill to the hard cap manually
        for i in range(MAX_NPCS_PER_TABLE):
            game.join(SimpleBlackjackNPC(f"NPC{i}"))
        count_before = len(game.players_waiting)
        self.casino.add_npc(game_id, 2)  # should be no-op
        self.assertEqual(len(game.players_waiting), count_before)

    def test_add_npc_invalid_game(self):
        with self.assertRaises(CardGameError):
            self.casino.add_npc("nonexistent")

    def test_remove_npc_from_waiting(self):
        self.casino.db = None
        game_id = self.casino.new_game()
        self.casino.add_npc(game_id, 1)
        game = self.casino.games[game_id]
        npc_name = next(p.name for p in game.players_waiting if p.is_npc)
        self.assertEqual(len([p for p in game.players_waiting if p.is_npc]), 1)
        self.casino.remove_npc(game_id, npc_name)
        self.assertEqual(len([p for p in game.players_waiting if p.is_npc]), 0)

    def test_remove_npc_arbitrary(self):
        """remove_npc with no name removes any one NPC."""
        self.casino.db = None
        game_id = self.casino.new_game()
        self.casino.add_npc(game_id, 1)
        game = self.casino.games[game_id]
        self.assertEqual(len([p for p in game.players_waiting if p.is_npc]), 1)
        self.casino.remove_npc(game_id)  # no name = remove any
        self.assertEqual(len([p for p in game.players_waiting if p.is_npc]), 0)

    def test_remove_npc_not_found(self):
        game_id = self.casino.new_game()
        with self.assertRaises(CardGameError):
            self.casino.remove_npc(game_id, "Ghost")

    def test_remove_npc_no_npcs(self):
        """remove_npc with no name raises when no NPCs exist."""
        game_id = self.casino.new_game()
        with self.assertRaises(CardGameError):
            self.casino.remove_npc(game_id)

    def test_remove_npc_does_not_remove_human(self):
        """remove_npc should not remove a human player with the same name."""
        game_id = self.casino.new_game()
        game = self.casino.games[game_id]
        human = Player("SameName")
        game.join(human)
        with self.assertRaises(CardGameError):
            self.casino.remove_npc(game_id, "SameName")
        self.assertIn(human, game.players_waiting)

    def test_remove_npc_fires_shared_hook_exactly_once(self):
        """M4.4: remove_npc no longer clears npc_game itself — it relies on the
        shared on_npc_departed hook fired from within Blackjack.leave()."""
        game_id = self.casino.new_game()
        game = self.casino.games[game_id]
        npc = SimpleBlackjackNPC("Deuces Wilder", npc_db_id=42)
        game.join(npc)
        self.casino.remove_npc(game_id, "Deuces Wilder")
        self.mock_db.clear_npc_game.assert_called_once_with(42)

    def test_npc_types_registry(self):
        self.assertIn('simple', NPC_TYPES)
        self.assertEqual(NPC_TYPES['simple'], SimpleBlackjackNPC)

    def test_tick_games_saves_after_npc_advances_current_player_idx(self):
        """Game must be saved when NPC turn advances current_player_idx without changing state.

        Regression test for the NPC save gap: when server restarts mid-PLAYING in a mixed
        human+NPC game, current_player_idx was not persisted after NPC turns because
        _tick_games() only saved on state changes, not on player-index changes.
        """
        # Deck (pop from end): dealer=[10,7], human1=[10,5], npc=[9,8], human2=[6,4]
        # npc score=17, dealer shows 10 -> SimpleBlackjackNPC stands immediately
        game_id = self.casino.new_game()
        game = self.casino.games[game_id]
        game.deck = [
            Card("H", 4), Card("H", 6),   # human2 cards
            Card("H", 8), Card("H", 9),   # npc cards
            Card("H", 5), Card("H", 10),  # human1 cards
            Card("H", 7), Card("H", 10),  # dealer cards
        ]

        human1 = Player("Human1")
        npc = SimpleBlackjackNPC("BotPlayer")
        human2 = Player("Human2")
        game.join(human1)
        game.join(npc)
        game.join(human2)

        game.tick()                           # WAITING -> BETTING
        game.bet(human1, game.MIN_BET)
        game.bet(human2, game.MIN_BET)
        game.tick()                           # BETTING: NPC auto-bets -> PLAYING

        self.assertEqual(game.state, HandState.PLAYING)
        self.assertEqual(game.players[game.current_player_idx], human1)

        game.stand(human1)                    # human1 done; now NPC's turn (idx=1)
        self.assertEqual(game.current_player_idx, 1)
        self.assertEqual(game.state, HandState.PLAYING)

        self.mock_db.save_game.reset_mock()
        self.casino._tick_games()             # NPC stands; idx advances to 2 (human2), still PLAYING

        self.assertEqual(game.state, HandState.PLAYING)
        self.assertEqual(game.current_player_idx, 2)
        self.mock_db.save_game.assert_called_once_with(game_id, game.to_dict())

    def test_delete_game_shuts_down_llm_npcs(self):
        """_delete_game() must call shutdown() on LLM NPC executors to prevent thread leaks."""
        from cardgames.llm_npc import LLMBlackjackNPC
        from cardgames.personalities import get_personality
        game_id = self.casino.new_game()
        game = self.casino.games[game_id]
        personality = get_personality("The Grizzled Prospector")
        npc = LLMBlackjackNPC("BotPlayer", personality, MagicMock())
        game.players_waiting.append(npc)
        with patch.object(npc, 'shutdown') as mock_shutdown:
            self.casino._delete_game(game_id)
            mock_shutdown.assert_called_once()

    def test_tick_games_saves_after_npc_bets_while_human_pending(self):
        """Game must be saved after NPC auto-bets even when state stays BETTING.

        Regression for NPC bet save gap: if a human hasn't bet yet, state stays
        BETTING after NPC bets, so the old state-change guard wouldn't trigger a save.
        """
        game_id = self.casino.new_game()
        game = self.casino.games[game_id]
        npc = SimpleBlackjackNPC("BotPlayer")
        human = Player("Human")
        game.join(human)
        game.join(npc)
        game.tick()  # WAITING -> BETTING
        self.assertEqual(game.state, HandState.BETTING)

        self.mock_db.save_game.reset_mock()
        self.casino._tick_games()  # NPC auto-bets; human hasn't; state stays BETTING

        self.assertIn('BotPlayer', game.bets)
        self.assertEqual(game.state, HandState.BETTING)
        self.mock_db.save_game.assert_called_once_with(game_id, game.to_dict())
        self.assertFalse(game._dirty)


class TestLLMBlackjackNPC(unittest.TestCase):
    def _make_npc(self, llm_response):
        from cardgames.llm_npc import LLMBlackjackNPC
        from cardgames.personalities import get_personality
        mock_llm = MagicMock()
        mock_llm.complete.return_value = (llm_response, 100, 50)
        personality = get_personality("The Grizzled Prospector")
        return LLMBlackjackNPC("TestNPC", personality, mock_llm)

    def test_is_npc_player(self):
        from cardgames.llm_npc import LLMBlackjackNPC
        npc = self._make_npc('{"action": "stand", "quip": "I reckon."}')
        self.assertIsInstance(npc, LLMBlackjackNPC)
        self.assertIsInstance(npc, NPCPlayer)
        self.assertTrue(npc.is_npc)

    def test_decide_action_returns_none_on_first_call(self):
        npc = self._make_npc('{"action": "stand", "quip": "Steady now."}')
        hand = [Card("H", 10), Card("H", 8)]
        dealer_card = Card("S", 7)
        result = npc.decide_action(hand, dealer_card, 18)
        self.assertIsNone(result)

    def test_decide_action_returns_action_after_future_resolves(self):
        npc = self._make_npc('{"action": "stand", "quip": "Steady now."}')
        hand = [Card("H", 10), Card("H", 8)]
        dealer_card = Card("S", 7)
        npc.decide_action(hand, dealer_card, 18)
        # Wait for the future to complete
        npc._pending_action_future.result(timeout=2.0)
        result = npc.decide_action(hand, dealer_card, 18)
        self.assertEqual(result, "stand")
        self.assertEqual(npc.last_quip, "Steady now.")

    def test_decide_action_fallback_on_llm_error(self):
        from cardgames.llm_client import LLMError
        from cardgames.llm_npc import LLMBlackjackNPC
        from cardgames.personalities import get_personality
        mock_llm = MagicMock()
        mock_llm.complete.side_effect = LLMError("API down")
        personality = get_personality("The Grizzled Prospector")
        npc = LLMBlackjackNPC("TestNPC", personality, mock_llm)
        hand = [Card("H", 10), Card("H", 5)]
        dealer_card = Card("S", 10)
        with self.assertLogs('cardgames.llm_npc', level='WARNING'):
            npc.decide_action(hand, dealer_card, 15)
            npc._pending_action_future.result(timeout=2.0)
        result = npc.decide_action(hand, dealer_card, 15)
        # Fallback: score 15 vs dealer 10 (strong) -> hit
        self.assertEqual(result, "hit")

    def test_decide_bet_returns_none_on_first_call(self):
        npc = self._make_npc('{"amount": 20, "quip": "Bettin big pardner."}')
        result = npc.decide_bet(5, 100, 200)
        self.assertIsNone(result)

    def test_decide_bet_returns_amount_after_future_resolves(self):
        npc = self._make_npc('{"amount": 20, "quip": "Bettin big pardner."}')
        npc.decide_bet(5, 100, 200)
        npc._pending_bet_future.result(timeout=2.0)
        result = npc.decide_bet(5, 100, 200)
        self.assertEqual(result, 20)
        self.assertEqual(npc.last_quip, "Bettin big pardner.")

    def test_decide_bet_clamps_to_range(self):
        npc = self._make_npc('{"amount": 9999, "quip": "All in!"}')
        npc.decide_bet(5, 100, 200)
        npc._pending_bet_future.result(timeout=2.0)
        result = npc.decide_bet(5, 100, 200)
        self.assertEqual(result, 100)

    def test_decide_bet_fallback_on_bad_json(self):
        from cardgames.llm_npc import LLMBlackjackNPC
        from cardgames.personalities import get_personality
        mock_llm = MagicMock()
        mock_llm.complete.return_value = ("not valid json at all", 100, 50)
        personality = get_personality("The Grizzled Prospector")
        npc = LLMBlackjackNPC("TestNPC", personality, mock_llm)
        with self.assertLogs('cardgames.llm_npc', level='WARNING'):
            npc.decide_bet(5, 100, 200)
            npc._pending_bet_future.result(timeout=2.0)
        result = npc.decide_bet(5, 100, 200)
        # Fallback is min_bet
        self.assertEqual(result, 5)

    def test_shutdown_calls_executor_shutdown(self):
        """shutdown() must call executor shutdown to release thread resources."""
        npc = self._make_npc('{"action": "stand", "quip": ""}')
        with patch.object(npc._executor, 'shutdown') as mock_shutdown:
            npc.shutdown()
            mock_shutdown.assert_called_once_with(wait=False)


class TestNPCSerialization(unittest.TestCase):
    def test_serialize_human_player(self):
        player = Player("Alice")
        player.hand = [Card("H", 10), Card("S", 5)]
        data = serialize_player(player)
        self.assertFalse(data['is_npc'])
        self.assertIsNone(data['npc_type'])
        self.assertIsNone(data['npc_personality'])

    def test_serialize_simple_npc(self):
        npc = SimpleBlackjackNPC("BotBob")
        npc.hand = [Card("D", 7)]
        data = serialize_player(npc)
        self.assertTrue(data['is_npc'])
        self.assertEqual(data['npc_type'], 'simple')
        self.assertIsNone(data['npc_personality'])

    def test_serialize_llm_npc(self):
        from cardgames.llm_npc import LLMBlackjackNPC
        from cardgames.personalities import get_personality
        personality = get_personality("The Grizzled Prospector")
        npc = LLMBlackjackNPC("LLMBot", personality, MagicMock())
        npc.hand = [Card("C", 3)]
        data = serialize_player(npc)
        self.assertTrue(data['is_npc'])
        self.assertEqual(data['npc_type'], 'llm')
        self.assertEqual(data['npc_personality'], "The Grizzled Prospector")

    def test_deserialize_human_player(self):
        data = {'name': 'Charlie', 'hand': ['H10', 'S5'], 'is_npc': False,
                'npc_type': None, 'npc_personality': None}
        player = deserialize_player(data)
        self.assertFalse(player.is_npc)
        self.assertEqual(player.name, 'Charlie')
        self.assertEqual(len(player.hand), 2)

    def test_deserialize_simple_npc(self):
        data = {'name': 'BotBob', 'hand': ['D7'], 'is_npc': True,
                'npc_type': 'simple', 'npc_personality': None}
        player = deserialize_player(data)
        self.assertTrue(player.is_npc)
        self.assertIsInstance(player, SimpleBlackjackNPC)
        self.assertEqual(player.name, 'BotBob')

    def test_deserialize_llm_npc_with_llm_client(self):
        from cardgames.llm_npc import LLMBlackjackNPC
        mock_casino = MagicMock()
        mock_casino.llm_client = MagicMock()
        data = {'name': 'LLMBot', 'hand': ['C3'], 'is_npc': True,
                'npc_type': 'llm', 'npc_personality': 'The Grizzled Prospector'}
        player = deserialize_player(data, casino=mock_casino)
        self.assertIsInstance(player, LLMBlackjackNPC)
        self.assertEqual(player.personality.name, 'The Grizzled Prospector')

    def test_deserialize_llm_npc_without_llm_client_falls_back(self):
        mock_casino = MagicMock(spec=[])  # no llm_client attribute
        data = {'name': 'LLMBot', 'hand': ['C3'], 'is_npc': True,
                'npc_type': 'llm', 'npc_personality': 'The Grizzled Prospector'}
        player = deserialize_player(data, casino=mock_casino)
        self.assertIsInstance(player, SimpleBlackjackNPC)

    def test_llm_npc_serialization_roundtrip(self):
        from cardgames.llm_npc import LLMBlackjackNPC
        from cardgames.personalities import get_personality
        personality = get_personality("The Grizzled Prospector")
        mock_llm = MagicMock()
        npc = LLMBlackjackNPC("LLMBot", personality, mock_llm)
        npc.hand = [Card("H", 8), Card("D", 3)]

        data = serialize_player(npc)
        mock_casino = MagicMock()
        mock_casino.llm_client = mock_llm
        restored = deserialize_player(data, casino=mock_casino)

        self.assertIsInstance(restored, LLMBlackjackNPC)
        self.assertEqual(restored.name, 'LLMBot')
        self.assertEqual(restored.personality.name, 'The Grizzled Prospector')
        self.assertEqual(len(restored.hand), 2)


class TestLLMNPCBlackjackIntegration(unittest.TestCase):
    def setUp(self):
        self.mock_casino = MagicMock()
        self.mock_casino.db = MagicMock()
        self.mock_casino.get_wallet.return_value = 1000.0
        self.mock_casino.update_wallet.return_value = True
        self.game = Blackjack(game_id="test_game", casino=self.mock_casino)

    def _make_llm_npc(self, llm_response):
        from cardgames.llm_npc import LLMBlackjackNPC
        from cardgames.personalities import get_personality
        mock_llm = MagicMock()
        mock_llm.complete.return_value = (llm_response, 100, 50)
        personality = get_personality("The Grizzled Prospector")
        return LLMBlackjackNPC("LLMBot", personality, mock_llm)

    def _setup_playing_state(self, npc):
        """Reach PLAYING state with a synchronous bet mock on npc."""
        npc.decide_bet = MagicMock(return_value=self.game.MIN_BET)
        self.game.join(npc)
        self.game.tick()  # WAITING -> BETTING
        self.game.tick()  # BETTING -> PLAYING
        self.assertEqual(self.game.state, HandState.PLAYING)

    def _get_output_messages(self):
        return [call[0][1] for call in self.mock_casino.game_output.call_args_list]

    def test_tick_playing_skips_when_decide_action_returns_none(self):
        """When decide_action returns None, playing tick should not advance state."""
        self.game.deck = [Card("H", 8), Card("H", 10), Card("H", 7), Card("H", 10)]
        npc = self._make_llm_npc('{"action": "stand", "quip": "I reckon."}')
        self._setup_playing_state(npc)

        npc.decide_action = MagicMock(return_value=None)
        self.game.tick()  # action pending — should stay PLAYING
        self.assertEqual(self.game.state, HandState.PLAYING)

    def test_tick_playing_advances_when_action_resolved(self):
        """When decide_action returns an action, playing tick should advance state."""
        self.game.deck = [Card("H", 8), Card("H", 10), Card("H", 7), Card("H", 10)]
        npc = self._make_llm_npc('{"action": "stand", "quip": "I reckon."}')
        self._setup_playing_state(npc)

        npc.decide_action = MagicMock(return_value="stand")
        self.game.tick()  # NPC stands -> DEALER_TURN
        self.assertEqual(self.game.state, HandState.DEALER_TURN)

    def test_tick_playing_outputs_quip(self):
        """Quip should be output when last_quip is set after decide_action resolves."""
        self.game.deck = [Card("H", 8), Card("H", 10), Card("H", 7), Card("H", 10)]
        npc = self._make_llm_npc('{"action": "stand", "quip": "I reckon."}')
        self._setup_playing_state(npc)

        npc.last_quip = "Steady as she goes."
        npc.decide_action = MagicMock(return_value="stand")
        self.game.tick()

        self.assertTrue(any('Steady as she goes.' in m for m in self._get_output_messages()))
        self.assertIsNone(npc.last_quip)

    def test_tick_betting_skips_npc_when_decide_bet_returns_none(self):
        """When decide_bet returns None, NPC should not be bet this tick."""
        self.game.deck = [Card("H", 8), Card("H", 10), Card("H", 7), Card("H", 10)]
        npc = self._make_llm_npc('{"amount": 10, "quip": "I am in."}')
        self.game.join(npc)
        self.game.tick()  # WAITING -> BETTING

        npc.decide_bet = MagicMock(return_value=None)
        self.game.tick()  # NPC pending — no bet placed yet
        self.assertNotIn('LLMBot', self.game.bets)
        self.assertEqual(self.game.state, HandState.BETTING)

    def test_tick_betting_outputs_quip_on_bet(self):
        """Quip should be output when NPC bets and last_quip is set."""
        self.game.deck = [Card("H", 8), Card("H", 10), Card("H", 7), Card("H", 10)]
        npc = self._make_llm_npc('{"amount": 10, "quip": "All in, pardner."}')
        self.game.join(npc)
        self.game.tick()  # WAITING -> BETTING

        npc.last_quip = "All in, pardner."
        npc.decide_bet = MagicMock(return_value=10)
        self.game.tick()

        self.assertTrue(any('All in, pardner.' in m for m in self._get_output_messages()))
        self.assertIsNone(npc.last_quip)


class TestNPCPersistence(unittest.TestCase):
    """Tests for M1 NPC roster persistence."""

    def _make_sqlite_db(self):
        from cardgames.sqlite_database import SqliteDatabase
        return SqliteDatabase(":memory:")

    def test_create_and_retrieve_npc(self):
        db = self._make_sqlite_db()
        npc_id = db.create_npc("Billy Thornton", "The Grizzled Prospector", 150)
        self.assertIsNotNone(npc_id)
        npc = db.get_npc_by_id(npc_id)
        self.assertEqual(npc['name'], "Billy Thornton")
        self.assertEqual(npc['personality_name'], "The Grizzled Prospector")
        self.assertEqual(npc['wallet'], 150)
        self.assertIsNone(npc['current_game_id'])

    def test_get_available_npcs_excludes_in_game(self):
        db = self._make_sqlite_db()
        id1 = db.create_npc("Alice", "The Card Sharp", 400)
        db.create_npc("Bob", "The Railroad Baron", 500)
        db.set_npc_game(id1, "game-123")
        available = db.get_available_npcs(10)
        names = [r['name'] for r in available]
        self.assertNotIn("Alice", names)
        self.assertIn("Bob", names)

    def test_get_available_npcs_excludes_personalities(self):
        db = self._make_sqlite_db()
        db.create_npc("Alice", "The Card Sharp", 400)
        db.create_npc("Bob", "The Railroad Baron", 500)
        available = db.get_available_npcs(10, exclude_personality_names={"The Card Sharp"})
        names = [r['name'] for r in available]
        self.assertNotIn("Alice", names)
        self.assertIn("Bob", names)

    def test_update_npc_wallet(self):
        db = self._make_sqlite_db()
        npc_id = db.create_npc("Carla", "The Saloon Singer", 200)
        db.update_npc_wallet(npc_id, 50)
        self.assertEqual(db.get_npc_wallet(npc_id), 250.0)

    def test_update_npc_wallet_insufficient_funds(self):
        db = self._make_sqlite_db()
        npc_id = db.create_npc("Drifter", "The Half-Broke Drifter", 50)
        result = db.update_npc_wallet(npc_id, -100)
        self.assertFalse(result)
        self.assertEqual(db.get_npc_wallet(npc_id), 50.0)

    def test_set_and_clear_npc_game(self):
        db = self._make_sqlite_db()
        npc_id = db.create_npc("Eli", "The Bounty Hunter", 250)
        db.set_npc_game(npc_id, "game-abc")
        npc = db.get_npc_by_id(npc_id)
        self.assertEqual(npc['current_game_id'], "game-abc")
        db.clear_npc_game(npc_id)
        npc = db.get_npc_by_id(npc_id)
        self.assertIsNone(npc['current_game_id'])

    def test_count_npcs(self):
        db = self._make_sqlite_db()
        self.assertEqual(db.count_npcs(), 0)
        db.create_npc("One", "The Drunk Cowboy", 75)
        db.create_npc("Two", "The Railroad Cook", 100)
        self.assertEqual(db.count_npcs(), 2)

    def test_clear_stale_npc_games(self):
        db = self._make_sqlite_db()
        id1 = db.create_npc("Frank", "The Card Sharp", 400)
        id2 = db.create_npc("Grace", "The Saloon Singer", 200)
        db.set_npc_game(id1, "active-game")
        db.set_npc_game(id2, "dead-game")
        db.clear_stale_npc_games({"active-game"})
        self.assertEqual(db.get_npc_by_id(id1)['current_game_id'], "active-game")
        self.assertIsNone(db.get_npc_by_id(id2)['current_game_id'])

    def test_personality_starting_wallet(self):
        from cardgames.personalities import get_personality
        self.assertEqual(get_personality("The Railroad Baron").starting_wallet, 500)
        self.assertEqual(get_personality("The Half-Broke Drifter").starting_wallet, 50)
        self.assertEqual(get_personality("The Card Sharp").starting_wallet, 400)

    def test_npc_base_class_has_db_fields(self):
        npc = SimpleBlackjackNPC("TestNPC", npc_db_id=42, backstory="Old timer")
        self.assertEqual(npc.npc_db_id, 42)
        self.assertEqual(npc.backstory, "Old timer")

    def test_npc_db_id_defaults_to_none(self):
        npc = SimpleBlackjackNPC("TestNPC")
        self.assertIsNone(npc.npc_db_id)
        self.assertEqual(npc.backstory, '')

    def test_serialize_player_includes_npc_db_id(self):
        npc = SimpleBlackjackNPC("BotBob", npc_db_id=7)
        data = serialize_player(npc)
        self.assertEqual(data['npc_db_id'], 7)

    def test_deserialize_npc_with_db_id(self):
        db = self._make_sqlite_db()
        npc_id = db.create_npc("Hank", "The Snake Oil Salesman", 300)

        mock_casino = MagicMock()
        mock_casino.db = db
        mock_casino.llm_client = None
        mock_casino.get_wallet.return_value = 300.0
        mock_casino.update_wallet.return_value = True

        data = {'name': 'Hank', 'hand': [], 'is_npc': True,
                'npc_type': 'simple', 'npc_personality': None, 'npc_db_id': npc_id}
        player = deserialize_player(data, casino=mock_casino)
        self.assertTrue(player.is_npc)
        self.assertEqual(player.npc_db_id, npc_id)

    def test_casino_wallet_dispatcher_human(self):
        from cardgames.casino import Casino
        mock_db = MagicMock()
        mock_db.get_user_wallet.return_value = 500.0
        mock_db.update_wallet.return_value = True
        casino = Casino(redis_host="localhost", redis_port=6379, db=mock_db)
        player = Player("Alice")
        self.assertEqual(casino.get_wallet(player), 500.0)
        casino.update_wallet(player, -20)
        mock_db.update_wallet.assert_called_with("Alice", -20)

    def test_casino_wallet_dispatcher_npc_with_db_id(self):
        from cardgames.casino import Casino
        mock_db = MagicMock()
        mock_db.get_npc_wallet.return_value = 150.0
        mock_db.update_npc_wallet.return_value = True
        casino = Casino(redis_host="localhost", redis_port=6379, db=mock_db)
        npc = SimpleBlackjackNPC("BotBob", npc_db_id=42)
        self.assertEqual(casino.get_wallet(npc), 150.0)
        mock_db.get_npc_wallet.assert_called_with(42)
        casino.update_wallet(npc, -10)
        mock_db.update_npc_wallet.assert_called_with(42, -10)

    def test_casino_wallet_dispatcher_npc_no_db_id(self):
        """NPC without npc_db_id falls back to user wallet route."""
        from cardgames.casino import Casino
        mock_db = MagicMock()
        mock_db.get_user_wallet.return_value = 200.0
        casino = Casino(redis_host="localhost", redis_port=6379, db=mock_db)
        npc = SimpleBlackjackNPC("EphemeralBot")
        casino.get_wallet(npc)
        mock_db.get_user_wallet.assert_called_with("EphemeralBot")

    def test_add_pending_bots_uses_db_roster(self):
        """_add_pending_bots should pull from DB roster and set current_game_id."""
        from cardgames.casino import Casino
        mock_db = MagicMock()
        mock_db.get_available_npcs.return_value = [
            {'id': 5, 'name': 'Clem', 'personality_name': 'The Card Sharp',
             'backstory': '', 'wallet': 400},
        ]
        mock_db.count_npcs.return_value = 20
        casino = Casino(redis_host="localhost", redis_port=6379, db=mock_db)
        casino.redis = MagicMock()
        game_id = casino.new_game(num_bots=1)
        game = casino.games[game_id]
        game.join(Player("Human"))
        # Trigger bot seating
        casino._add_pending_bots(game_id)
        # NPC should be in the game
        all_players = game.players + game.players_waiting
        npc_names = [p.name for p in all_players if p.is_npc]
        self.assertIn("Clem", npc_names)
        # current_game_id should have been set
        mock_db.set_npc_game.assert_called_with(5, game_id)

    def test_delete_game_clears_npc_game(self):
        """_delete_game() should clear current_game_id for all NPCs in the game."""
        from cardgames.casino import Casino
        mock_db = MagicMock()
        casino = Casino(redis_host="localhost", redis_port=6379, db=mock_db)
        casino.redis = MagicMock()
        game_id = casino.new_game()
        game = casino.games[game_id]
        npc = SimpleBlackjackNPC("BotPlayer", npc_db_id=99)
        game.players_waiting.append(npc)
        casino._delete_game(game_id)
        mock_db.clear_npc_game.assert_called_with(99)


class TestM2LLMUsageTracking(unittest.TestCase):
    """Tests for M2 LLM usage tracking."""

    def _make_sqlite_db(self):
        from cardgames.sqlite_database import SqliteDatabase
        return SqliteDatabase(":memory:")

    def test_log_and_summarize_usage(self):
        db = self._make_sqlite_db()
        db.log_llm_usage('npc_action', 'claude-haiku-4-5', 100, 50, npc_id=1)
        db.log_llm_usage('npc_action', 'claude-haiku-4-5', 200, 80, npc_id=2)
        db.log_llm_usage('npc_bet', 'claude-haiku-4-5', 150, 60)
        rows = db.get_llm_usage_summary(days=7)
        purposes = {r['purpose'] for r in rows}
        self.assertIn('npc_action', purposes)
        self.assertIn('npc_bet', purposes)
        for r in rows:
            if r['purpose'] == 'npc_action':
                self.assertEqual(r['total_input'], 300)
                self.assertEqual(r['total_output'], 130)
                self.assertEqual(r['call_count'], 2)

    def test_update_npc_backstory(self):
        db = self._make_sqlite_db()
        npc_id = db.create_npc("Clara", "The Saloon Singer", 200)
        db.update_npc_backstory(npc_id, "She came from New Orleans with a voice like honeysuckle.")
        npc = db.get_npc_by_id(npc_id)
        self.assertEqual(npc['backstory'], "She came from New Orleans with a voice like honeysuckle.")

    def test_log_usage_no_db_silent(self):
        from cardgames.casino import Casino
        casino = Casino(redis_host="localhost", redis_port=6379, db=None)
        casino._log_usage('npc_action', 'claude-haiku-4-5', 100, 50)  # should not raise

    def test_log_usage_db_failure_silent(self):
        from cardgames.casino import Casino
        mock_db = MagicMock()
        mock_db.log_llm_usage.side_effect = Exception("DB error")
        casino = Casino(redis_host="localhost", redis_port=6379, db=mock_db)
        casino._log_usage('npc_action', 'claude-haiku-4-5', 100, 50)  # should not raise


class TestM2SaloonContext(unittest.TestCase):
    """Tests for M2 saloon context injection into LLM prompts."""

    def _make_npc(self, detail_level='medium', backstory='', table_context_fn=None):
        from cardgames.llm_npc import LLMBlackjackNPC
        from cardgames.personalities import get_personality
        mock_llm = MagicMock()
        mock_llm.model = 'claude-haiku-4-5'
        mock_llm.complete.return_value = ('{"action": "stand", "quip": "Steady."}', 100, 50)
        personality = get_personality("The Grizzled Prospector")
        return LLMBlackjackNPC(
            "TestNPC", personality, mock_llm,
            saloon_name="The Golden Nugget", saloon_town="Dusty Creek, Nevada",
            detail_level=detail_level, backstory=backstory,
            table_context_fn=table_context_fn,
        )

    def test_action_prompt_includes_saloon_name(self):
        npc = self._make_npc()
        prompt = npc._build_action_system_prompt()
        self.assertIn("The Golden Nugget", prompt)
        self.assertIn("Dusty Creek, Nevada", prompt)

    def test_action_prompt_includes_backstory_medium(self):
        npc = self._make_npc(detail_level='medium', backstory='Old miner with a limp.')
        prompt = npc._build_action_system_prompt()
        self.assertIn("Old miner with a limp.", prompt)

    def test_action_prompt_omits_backstory_low(self):
        npc = self._make_npc(detail_level='low', backstory='Old miner with a limp.')
        prompt = npc._build_action_system_prompt()
        self.assertNotIn("Old miner with a limp.", prompt)

    def test_action_prompt_includes_other_players_medium(self):
        def table_fn():
            return [{'name': 'Alice', 'archetype': 'The Card Sharp'}]
        npc = self._make_npc(detail_level='medium', table_context_fn=table_fn)
        prompt = npc._build_action_system_prompt()
        self.assertIn("Alice", prompt)
        self.assertIn("The Card Sharp", prompt)

    def test_action_prompt_low_lists_names_only(self):
        def table_fn():
            return [{'name': 'Bob', 'archetype': 'The Railroad Baron'}]
        npc = self._make_npc(detail_level='low', table_context_fn=table_fn)
        prompt = npc._build_action_system_prompt()
        self.assertIn("Bob", prompt)
        # archetype not included for low detail
        self.assertNotIn("The Railroad Baron", prompt)

    def test_usage_callback_called_on_action(self):
        from cardgames.llm_npc import LLMBlackjackNPC
        from cardgames.personalities import get_personality
        mock_llm = MagicMock()
        mock_llm.model = 'claude-haiku-4-5'
        mock_llm.complete.return_value = ('{"action": "stand", "quip": ""}', 120, 60)
        personality = get_personality("The Grizzled Prospector")
        usage_calls = []

        def record_usage(*a, **kw):
            usage_calls.append((a, kw))

        npc = LLMBlackjackNPC("Bot", personality, mock_llm,
                              npc_db_id=7, usage_callback=record_usage)
        hand = [Card("H", 10), Card("H", 8)]
        dealer_card = Card("S", 7)
        npc.decide_action(hand, dealer_card, 18)
        npc._pending_action_future.result(timeout=2.0)
        self.assertEqual(len(usage_calls), 1)
        args, kwargs = usage_calls[0]
        self.assertEqual(args[0], 'npc_action')
        self.assertEqual(kwargs.get('npc_id'), 7)

    def test_table_context_fn_error_returns_empty(self):
        def bad_fn():
            raise RuntimeError("boom")
        npc = self._make_npc(table_context_fn=bad_fn)
        result = npc._get_table_players()
        self.assertEqual(result, [])


class TestM3PlayerStatsFame(unittest.TestCase):
    """Tests for M3 Player Statistics & Fame."""

    def _make_sqlite_db(self):
        from cardgames.sqlite_database import SqliteDatabase
        return SqliteDatabase(":memory:")

    # --- fame label ---

    def test_fame_label_below_threshold_is_unknown(self):
        from cardgames.casino import _fame_label
        self.assertEqual(_fame_label(0), "unknown stranger")
        self.assertEqual(_fame_label(2), "unknown stranger")

    def test_fame_label_at_lower_threshold_is_regular(self):
        from cardgames.casino import _fame_label
        self.assertEqual(_fame_label(3), "known regular")
        self.assertEqual(_fame_label(14), "known regular")

    def test_fame_label_at_upper_threshold_is_notorious(self):
        from cardgames.casino import _fame_label
        self.assertEqual(_fame_label(15), "notorious gambler")
        self.assertEqual(_fame_label(1000), "notorious gambler")

    # --- DB stats ---

    def test_update_and_get_player_stats(self):
        db = self._make_sqlite_db()
        db.add_user("alice")
        db.update_player_stats("alice", won=50.0, lost=0.0)
        db.update_player_stats("alice", won=0.0, lost=20.0)
        stats = db.get_player_stats("alice")
        self.assertEqual(stats['hands_played'], 2)
        self.assertEqual(stats['total_won'], 50.0)
        self.assertEqual(stats['total_lost'], 20.0)
        self.assertEqual(stats['biggest_win'], 50.0)

    def test_biggest_win_tracks_maximum(self):
        db = self._make_sqlite_db()
        db.add_user("bob")
        db.update_player_stats("bob", won=10.0, lost=0.0)
        db.update_player_stats("bob", won=75.0, lost=0.0)
        db.update_player_stats("bob", won=30.0, lost=0.0)
        stats = db.get_player_stats("bob")
        self.assertEqual(stats['biggest_win'], 75.0)

    def test_get_player_stats_returns_none_for_unknown_player(self):
        db = self._make_sqlite_db()
        self.assertIsNone(db.get_player_stats("nobody"))

    def test_increment_games_played(self):
        db = self._make_sqlite_db()
        db.add_user("carol")
        db.increment_games_played("carol")
        db.increment_games_played("carol")
        stats = db.get_player_stats("carol")
        self.assertEqual(stats['games_played'], 2)

    # --- Casino record_hand_result ---

    def test_record_hand_result_calls_db_for_human(self):
        from cardgames.casino import Casino
        mock_db = MagicMock()
        casino = Casino(redis_host="localhost", redis_port=6379, db=mock_db)
        player = Player("dave")
        casino.record_hand_result(player, won=50.0, lost=0.0)
        mock_db.update_player_stats.assert_called_once_with("dave", won=50.0, lost=0.0)

    def test_record_hand_result_skips_npc(self):
        from cardgames.casino import Casino
        from cardgames.simple_npc import SimpleBlackjackNPC
        mock_db = MagicMock()
        casino = Casino(redis_host="localhost", redis_port=6379, db=mock_db)
        npc = SimpleBlackjackNPC("Bot")
        casino.record_hand_result(npc, won=50.0, lost=0.0)
        mock_db.update_player_stats.assert_not_called()

    def test_record_hand_result_no_db_silent(self):
        from cardgames.casino import Casino
        casino = Casino(redis_host="localhost", redis_port=6379, db=None)
        player = Player("eve")
        casino.record_hand_result(player, won=10.0, lost=0.0)  # should not raise

    def test_record_hand_result_db_failure_silent(self):
        from cardgames.casino import Casino
        mock_db = MagicMock()
        mock_db.update_player_stats.side_effect = Exception("DB down")
        casino = Casino(redis_host="localhost", redis_port=6379, db=mock_db)
        player = Player("frank")
        casino.record_hand_result(player, won=10.0, lost=0.0)  # should not raise

    # --- Fame in table context ---

    def test_table_context_includes_fame_for_human(self):
        from cardgames.casino import Casino
        mock_db = MagicMock()
        mock_db.get_player_stats.return_value = {'games_played': 20, 'hands_played': 50,
                                                 'total_won': 200.0, 'total_lost': 100.0,
                                                 'biggest_win': 75.0, 'last_seen': None}
        casino = Casino(redis_host="localhost", redis_port=6379, db=mock_db)
        game = MagicMock()
        human = Player("grace")
        game.players = [human]
        game.players_waiting = []
        casino.games['g1'] = game
        ctx_fn = casino._make_table_context_fn('g1', 'SomeNPC')
        result = ctx_fn()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['name'], 'grace')
        self.assertEqual(result[0]['fame'], 'notorious gambler')

    def test_table_context_fame_none_for_npc(self):
        from cardgames.casino import Casino
        from cardgames.simple_npc import SimpleBlackjackNPC
        mock_db = MagicMock()
        casino = Casino(redis_host="localhost", redis_port=6379, db=mock_db)
        game = MagicMock()
        npc = SimpleBlackjackNPC("Bot")
        game.players = [npc]
        game.players_waiting = []
        casino.games['g2'] = game
        ctx_fn = casino._make_table_context_fn('g2', 'SomeOtherNPC')
        result = ctx_fn()
        self.assertEqual(result[0]['fame'], None)
        mock_db.get_player_stats.assert_not_called()


class TestNPCAutofill(unittest.TestCase):
    """AM3: NPC autofill limit clamping and _autofill_npcs count logic."""

    def _make_casino(self, npc_min=0, npc_max=4, db=None):
        """Create a Casino with Redis mocked out and preset limits."""
        with patch('cardgames.casino.redis.Redis'):
            casino = Casino(redis_host='localhost', redis_port=6379, db=db)
        casino.npc_min = npc_min
        casino.npc_max = npc_max
        return casino

    def _make_game(self, state, npcs=0, humans=0):
        """Return a mock game with the given state and player counts."""
        game = MagicMock()
        game.state = state
        npc_players = [MagicMock(is_npc=True) for _ in range(npcs)]
        human_players = [MagicMock(is_npc=False) for _ in range(humans)]
        game.players = npc_players + human_players
        game.players_waiting = []
        return game

    # --- _load_npc_limits clamping ---

    def test_load_npc_limits_defaults_when_no_settings(self):
        db = SqliteDatabase(':memory:')
        casino = self._make_casino(db=db)
        casino._load_npc_limits()
        self.assertEqual(casino.npc_min, DEFAULT_NPC_AUTOFILL_MIN)
        self.assertEqual(casino.npc_max, DEFAULT_NPC_AUTOFILL_MAX)
        db.close()

    def test_load_npc_limits_reads_persisted_values(self):
        db = SqliteDatabase(':memory:')
        db.set_setting('npc_autofill_min', '2')
        db.set_setting('npc_autofill_max', '5')
        casino = self._make_casino(db=db)
        casino._load_npc_limits()
        self.assertEqual(casino.npc_min, 2)
        self.assertEqual(casino.npc_max, 5)
        db.close()

    def test_load_npc_limits_clamps_above_max(self):
        db = SqliteDatabase(':memory:')
        db.set_setting('npc_autofill_min', '99')
        db.set_setting('npc_autofill_max', '99')
        casino = self._make_casino(db=db)
        casino._load_npc_limits()
        self.assertEqual(casino.npc_min, MAX_NPCS_PER_TABLE)
        self.assertEqual(casino.npc_max, MAX_NPCS_PER_TABLE)
        db.close()

    def test_load_npc_limits_clamps_below_zero(self):
        db = SqliteDatabase(':memory:')
        db.set_setting('npc_autofill_min', '-5')
        db.set_setting('npc_autofill_max', '-1')
        casino = self._make_casino(db=db)
        casino._load_npc_limits()
        self.assertEqual(casino.npc_min, 0)
        self.assertEqual(casino.npc_max, 0)
        db.close()

    def test_load_npc_limits_min_clamped_to_max(self):
        db = SqliteDatabase(':memory:')
        db.set_setting('npc_autofill_min', '5')
        db.set_setting('npc_autofill_max', '2')
        casino = self._make_casino(db=db)
        casino._load_npc_limits()
        # min > max: min is clamped down to max
        self.assertLessEqual(casino.npc_min, casino.npc_max)
        db.close()

    # --- _autofill_npcs state guards ---

    def test_autofill_no_op_during_active_hand(self):
        casino = self._make_casino(npc_min=2)
        casino._spawn_npcs_into_game = MagicMock()
        game = self._make_game(HandState.PLAYING, npcs=0)
        casino.games['g1'] = game
        casino._autofill_npcs('g1', game)
        casino._spawn_npcs_into_game.assert_not_called()

    def test_autofill_no_op_during_betting(self):
        casino = self._make_casino(npc_min=2)
        casino._spawn_npcs_into_game = MagicMock()
        game = self._make_game(HandState.BETTING, npcs=0)
        casino.games['g1'] = game
        casino._autofill_npcs('g1', game)
        casino._spawn_npcs_into_game.assert_not_called()

    # --- _autofill_npcs fill logic ---

    def test_autofill_spawns_when_below_min(self):
        casino = self._make_casino(npc_min=2)
        casino._spawn_npcs_into_game = MagicMock()
        casino._mark_dirty = MagicMock()
        game = self._make_game(HandState.WAITING, npcs=0, humans=1)
        casino.games['g1'] = game
        casino._autofill_npcs('g1', game)
        casino._spawn_npcs_into_game.assert_called_once_with('g1', 2)
        casino._mark_dirty.assert_called()

    def test_autofill_no_op_when_at_min(self):
        casino = self._make_casino(npc_min=2)
        casino._spawn_npcs_into_game = MagicMock()
        game = self._make_game(HandState.WAITING, npcs=2)
        casino.games['g1'] = game
        casino._autofill_npcs('g1', game)
        casino._spawn_npcs_into_game.assert_not_called()

    def test_autofill_capped_by_max_npcs_per_table(self):
        """Won't overfill past MAX_NPCS_PER_TABLE even if npc_min demands more."""
        casino = self._make_casino(npc_min=MAX_NPCS_PER_TABLE)
        casino._spawn_npcs_into_game = MagicMock()
        casino._mark_dirty = MagicMock()
        # 4 humans already at the table, MAX=6, so only 2 NPC slots remain
        game = self._make_game(HandState.WAITING, npcs=0, humans=4)
        casino.games['g1'] = game
        casino._autofill_npcs('g1', game)
        casino._spawn_npcs_into_game.assert_called_once_with('g1', 2)

    # --- _autofill_npcs trim logic ---

    def test_autofill_trims_when_above_max(self):
        casino = self._make_casino(npc_min=0, npc_max=1)
        casino._mark_dirty = MagicMock()
        npc1 = MagicMock(is_npc=True, npc_db_id=None)
        npc2 = MagicMock(is_npc=True, npc_db_id=None)
        game = MagicMock()
        game.state = HandState.WAITING
        game.players = []
        game.players_waiting = [npc1, npc2]
        casino.games['g1'] = game
        casino._autofill_npcs('g1', game)
        game.leave.assert_called_once_with(npc1)
        casino._mark_dirty.assert_called()

    def test_autofill_trim_fires_shared_hook_exactly_once(self):
        """M4.4: autofill's trim no longer clears npc_game itself — it relies on
        the shared on_npc_departed hook fired from within Blackjack.leave()."""
        db = MagicMock()
        casino = self._make_casino(npc_min=0, npc_max=1, db=db)
        game_id = casino.new_game()
        game = casino.games[game_id]
        npc1 = SimpleBlackjackNPC("NPC1", npc_db_id=1)
        npc2 = SimpleBlackjackNPC("NPC2", npc_db_id=2)
        game.join(npc1)
        game.join(npc2)
        casino._autofill_npcs(game_id, game)
        db.clear_npc_game.assert_called_once_with(1)

    def test_autofill_no_op_when_at_max(self):
        casino = self._make_casino(npc_min=0, npc_max=2)
        casino._mark_dirty = MagicMock()
        game = self._make_game(HandState.WAITING, npcs=2)
        casino.games['g1'] = game
        casino._autofill_npcs('g1', game)
        casino._mark_dirty.assert_not_called()

    # --- _autofill_npcs throttle ---

    def test_autofill_throttled_within_interval(self):
        casino = self._make_casino(npc_min=2)
        casino._spawn_npcs_into_game = MagicMock()
        game = self._make_game(HandState.WAITING, npcs=0)
        casino.games['g1'] = game
        casino._last_autofill['g1'] = time.time()  # set recent timestamp
        casino._autofill_npcs('g1', game)
        casino._spawn_npcs_into_game.assert_not_called()


if __name__ == '__main__':
    unittest.main()
