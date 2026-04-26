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
from cardgames.casino import NPC_TYPES, Casino
from cardgames.player import Player
from cardgames.simple_npc import SimpleBlackjackNPC

from wwnames.wwnames import WildWestNames


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
        mock_casino.db.get_user_wallet.return_value = 1000.0
        self.game = Blackjack(game_id="test_game", casino=mock_casino)

    def test_new_hand(self):
        # Set up a mock deck to ensure that the dealer never has 21.
        self.game.deck = [Card("H", 3), Card("H", 2), Card("H", 14),
                          Card("H", 10)]

        # Verify that an error is raised when no players are present
        with self.assertRaises(CardGameError):
            self.game.new_hand()

        self.game.join(Player("Player 1"))
        self.game.join(Player("Player 2"))
        self.game.new_hand()
        self.assertEqual(len(self.game.players), 2)
        self.assertEqual(len(self.game.deck), 2)

    def test_dealer_has_21(self):
        self.game.deck = [Card("D", 4), Card("D", 5), Card("H", 3), Card("H", 2),
                          Card("H", 14), Card("H", 10)]
        self.game.join(Player("Player 1"))
        self.game.new_hand()
        self.assertEqual(self.game.get_score(self.game.dealer), 21)
        self.assertEqual(self.game.current_player_idx, None)
        self.game.new_hand()
        self.assertEqual(self.game.get_score(self.game.dealer), 5)
        self.assertEqual(self.game.get_score(self.game.players[0]), 9)

    def test_hit(self):
        self.game.deck = [Card("H", 13), Card("H", 3), Card("H", 4),
                          Card("H", 5), Card("H", 6), Card("H", 7)]

        self.game.join(Player("Player 1"))
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

    def test_dealer_turn(self):
        self.assertFalse(self.game.is_dealer_turn())
        self.game.deck = [Card("H", 13), Card("H", 3), Card("H", 4),
                          Card("H", 5), Card("H", 6), Card("H", 7)]
        self.game.join(Player("Player 1"))
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

        self.game.join(Player("Player 1"))
        self.game.new_hand()
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
        mock_casino.db.get_user_wallet.return_value = 1000.0
        self.game = Blackjack(game_id="test_game", casino=mock_casino)

    def test_initial_state_is_waiting(self):
        self.assertEqual(self.game.state, HandState.WAITING)

    def test_state_transitions_to_playing_on_new_hand(self):
        self.game.deck = [Card("H", 3), Card("H", 2), Card("H", 5), Card("H", 6)]
        self.game.join(Player("Player 1"))
        self.game.new_hand()
        self.assertEqual(self.game.state, HandState.PLAYING)

    def test_state_transitions_to_dealer_turn_after_all_players_stand(self):
        self.game.deck = [Card("H", 3), Card("H", 2), Card("H", 5), Card("H", 6)]
        self.game.join(Player("Player 1"))
        self.game.new_hand()
        self.game.stand(self.game.players[0])
        self.assertEqual(self.game.state, HandState.DEALER_TURN)

    def test_state_transitions_to_resolving_after_dealer_turn(self):
        # Need enough cards for dealer to potentially hit multiple times
        self.game.deck = [Card("H", 3), Card("H", 2), Card("H", 5), Card("H", 6),
                          Card("H", 7), Card("H", 8), Card("H", 9)]
        self.game.join(Player("Player 1"))
        self.game.new_hand()
        self.game.stand(self.game.players[0])
        self.game.dealer_turn()
        self.assertEqual(self.game.state, HandState.RESOLVING)

    def test_state_transitions_to_between_hands_after_resolving(self):
        self.game.deck = [Card("H", 3), Card("H", 2), Card("H", 5), Card("H", 6),
                          Card("H", 7), Card("H", 8), Card("H", 9)]
        self.game.join(Player("Player 1"))
        self.game.new_hand()
        self.game.stand(self.game.players[0])
        self.game.dealer_turn()
        self.assertEqual(self.game.state, HandState.RESOLVING)
        # Tick resolves the hand and transitions to BETWEEN_HANDS
        self.game.tick()
        self.assertEqual(self.game.state, HandState.BETWEEN_HANDS)

    def test_state_transitions_to_waiting_after_time_between_hands(self):
        self.game.deck = [Card("H", 3), Card("H", 2), Card("H", 5), Card("H", 6),
                          Card("H", 7), Card("H", 8), Card("H", 9)]
        self.game.join(Player("Player 1"))
        self.game.new_hand()
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
        self.game.join(Player("Player 1"))
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


class TestBlackjackBetting(unittest.TestCase):
    def setUp(self):
        mock_casino = MagicMock()
        mock_casino.db = MagicMock()
        mock_casino.db.get_user_wallet.return_value = 1000.0
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
        mock_db = MagicMock()
        mock_db.get_user_wallet.return_value = 200.0
        mock_db.update_wallet.return_value = True
        mock_casino = MagicMock()
        mock_casino.db = mock_db
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
        payout_calls = [call for call in mock_db.update_wallet.call_args_list
                        if call[0][1] > 0]  # Positive amount = payout
        self.assertEqual(len(payout_calls), 1)
        self.assertEqual(payout_calls[0][0], ("Player 1", 40))

    def test_tie_returns_bet(self):
        mock_db = MagicMock()
        mock_db.get_user_wallet.return_value = 200.0
        mock_db.update_wallet.return_value = True
        mock_casino = MagicMock()
        mock_casino.db = mock_db
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
        payout_calls = [call for call in mock_db.update_wallet.call_args_list
                        if call[0][1] > 0]  # Positive amount = payout
        self.assertEqual(len(payout_calls), 1)
        self.assertEqual(payout_calls[0][0], ("Player 1", 20))

    def test_loser_forfeits_bet(self):
        mock_db = MagicMock()
        mock_db.get_user_wallet.return_value = 200.0
        mock_db.update_wallet.return_value = True
        mock_casino = MagicMock()
        mock_casino.db = mock_db
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
        payout_calls = [call for call in mock_db.update_wallet.call_args_list
                        if call[0][1] > 0]  # Positive amount = payout
        self.assertEqual(len(payout_calls), 0)

    def test_leave_forfeits_bet(self):
        mock_db = MagicMock()
        mock_db.get_user_wallet.return_value = 200.0
        mock_db.update_wallet.return_value = True
        mock_casino = MagicMock()
        mock_casino.db = mock_db
        mock_casino.game_output = MagicMock()

        game = Blackjack(game_id="test", casino=mock_casino)
        game.deck = [Card("H", 3), Card("H", 2), Card("H", 5), Card("H", 6)]
        game.join(Player("Player 1"))
        game.tick()  # WAITING -> BETTING
        player = game.players[0]
        game.bet(player, 20)
        game.leave(player)

        # Should not have any refund calls (bet forfeited)
        refund_calls = [call for call in mock_db.update_wallet.call_args_list
                        if call[0][1] > 0]  # Positive amount = refund
        self.assertEqual(len(refund_calls), 0)


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
        mock_casino.db.get_user_wallet.return_value = 1000.0

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
        mock_casino.db.get_user_wallet.return_value = 1000.0

        game = Blackjack(game_id="test_game", casino=mock_casino)
        game.deck = [Card("H", 3), Card("H", 2), Card("H", 5), Card("H", 6)]

        # Start betting
        game.join(Player("Player1"))
        game.tick()  # WAITING -> BETTING

        # Serialize with a fake "old" time_last_event
        game_data = game.to_dict()
        fake_save_time = time.time() - 5  # Pretend saved 5 seconds ago
        game_data['time_last_event'] = fake_save_time
        game_data['time_betting_started'] = fake_save_time - 2  # Betting started 2s before save

        # Restore
        before_restore = time.time()
        restored_game = Blackjack.from_dict(game_data, mock_casino)
        after_restore = time.time()

        # time_last_event should be approximately now
        self.assertGreaterEqual(restored_game.time_last_event, before_restore)
        self.assertLessEqual(restored_game.time_last_event, after_restore)

        # time_betting_started should preserve the 2 second difference
        time_diff = restored_game.time_last_event - restored_game.time_betting_started
        self.assertAlmostEqual(time_diff, 2.0, places=1)

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
        mock_casino.db.get_user_wallet.return_value = 1000.0
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
        game_id = self.casino.new_game()
        npc = self.casino.add_npc(game_id, "TestNPC", "simple")
        self.assertTrue(npc.is_npc)
        self.assertEqual(npc.name, "TestNPC")
        game = self.casino.games[game_id]
        self.assertIn(npc, game.players_waiting)

    def test_add_npc_unknown_type(self):
        game_id = self.casino.new_game()
        with self.assertRaises(CardGameError):
            self.casino.add_npc(game_id, "TestNPC", "unknown")

    def test_add_npc_invalid_game(self):
        with self.assertRaises(CardGameError):
            self.casino.add_npc("nonexistent", "TestNPC")

    def test_remove_npc_from_waiting(self):
        game_id = self.casino.new_game()
        self.casino.add_npc(game_id, "RemoveNPC", "simple")
        game = self.casino.games[game_id]
        self.assertEqual(len(game.players_waiting), 1)
        self.casino.remove_npc(game_id, "RemoveNPC")
        self.assertEqual(len(game.players_waiting), 0)

    def test_remove_npc_not_found(self):
        game_id = self.casino.new_game()
        with self.assertRaises(CardGameError):
            self.casino.remove_npc(game_id, "Ghost")

    def test_remove_npc_does_not_remove_human(self):
        """remove_npc should not remove a human player with the same name."""
        game_id = self.casino.new_game()
        game = self.casino.games[game_id]
        human = Player("SameName")
        game.join(human)
        with self.assertRaises(CardGameError):
            self.casino.remove_npc(game_id, "SameName")
        self.assertIn(human, game.players_waiting)

    def test_npc_types_registry(self):
        self.assertIn('simple', NPC_TYPES)
        self.assertEqual(NPC_TYPES['simple'], SimpleBlackjackNPC)


class TestLLMBlackjackNPC(unittest.TestCase):
    def _make_npc(self, llm_response):
        from cardgames.llm_npc import LLMBlackjackNPC
        from cardgames.personalities import get_personality
        mock_llm = MagicMock()
        mock_llm.complete.return_value = llm_response
        personality = get_personality("The Grizzled Prospector")
        return LLMBlackjackNPC("TestNPC", personality, mock_llm)

    def test_is_npc_player(self):
        from cardgames.llm_npc import LLMBlackjackNPC
        npc = self._make_npc('{"action": "stand", "quip": "I reckon."}')
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
        mock_llm.complete.return_value = "not valid json at all"
        personality = get_personality("The Grizzled Prospector")
        npc = LLMBlackjackNPC("TestNPC", personality, mock_llm)
        npc.decide_bet(5, 100, 200)
        npc._pending_bet_future.result(timeout=2.0)
        result = npc.decide_bet(5, 100, 200)
        # Fallback is min_bet
        self.assertEqual(result, 5)


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
        self.mock_casino.db.get_user_wallet.return_value = 1000.0
        self.game = Blackjack(game_id="test_game", casino=self.mock_casino)

    def _make_llm_npc(self, llm_response):
        from cardgames.llm_npc import LLMBlackjackNPC
        from cardgames.personalities import get_personality
        mock_llm = MagicMock()
        mock_llm.complete.return_value = llm_response
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


if __name__ == "__main__":
    unittest.main()
