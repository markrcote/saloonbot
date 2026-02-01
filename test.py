import time
import unittest
from unittest.mock import MagicMock, patch

from cardgames.blackjack import Action, Blackjack, HandState, InvalidActionError
from cardgames.card_game import Card, CardGame, CardGameError
from cardgames.player import Player

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
        self.game = Blackjack(game_id="test_game", casino=None)

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
        self.game = Blackjack(game_id="test_game", casino=None)

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

    def test_join_game_without_database(self):
        # Create a casino without a database
        mock_casino = MagicMock()
        mock_casino.db = None
        mock_casino.game_output = MagicMock()

        # Create a blackjack game
        game = Blackjack(game_id="test_game", casino=mock_casino)

        # Join a player (should not raise an exception)
        player = Player("TestPlayer")
        game.join(player)

        # Verify player was added to waiting list
        self.assertIn(player, game.players_waiting)


if __name__ == "__main__":
    unittest.main()
