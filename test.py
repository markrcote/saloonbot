import time
import unittest
from unittest.mock import MagicMock, patch

from cardgames.blackjack import (
    Action, Blackjack, HandState, InvalidActionError, InvalidBetError
)
from cardgames.bot_player import BotPlayer
from cardgames.card_game import Card, CardGame, CardGameError
from cardgames.casino import BOT_TYPES, Casino
from cardgames.player import Player
from cardgames.simple_bot import SimpleBlackjackBot

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


class TestBotPlayer(unittest.TestCase):
    def test_bot_player_is_abstract(self):
        """BotPlayer cannot be instantiated directly."""
        with self.assertRaises(TypeError):
            BotPlayer("AbstractBot")

    def test_player_is_not_bot(self):
        """Regular Player should not be a bot."""
        player = Player("Human")
        self.assertFalse(player.is_bot)

    def test_simple_bot_is_bot(self):
        """SimpleBlackjackBot should be identified as a bot."""
        bot = SimpleBlackjackBot("TestBot")
        self.assertTrue(bot.is_bot)

    def test_simple_bot_is_player(self):
        """SimpleBlackjackBot should be a Player instance."""
        bot = SimpleBlackjackBot("TestBot")
        self.assertIsInstance(bot, Player)


class TestSimpleBlackjackBot(unittest.TestCase):
    def setUp(self):
        self.bot = SimpleBlackjackBot("TestBot")

    def test_bet_returns_minimum(self):
        self.assertEqual(self.bot.decide_bet(5, 100, 200), 5)

    def test_hit_on_low_score_strong_dealer(self):
        """Bot should hit when score is below 17 against strong dealer card."""
        card = Card("H", 10)
        self.assertEqual(self.bot.decide_action([], card, 15), "hit")

    def test_stand_on_17_strong_dealer(self):
        """Bot should stand on 17 against strong dealer card."""
        card = Card("H", 10)
        self.assertEqual(self.bot.decide_action([], card, 17), "stand")

    def test_stand_on_12_weak_dealer(self):
        """Bot should stand on 12+ against weak dealer card (2-6)."""
        card = Card("H", 5)
        self.assertEqual(self.bot.decide_action([], card, 12), "stand")

    def test_hit_on_11_weak_dealer(self):
        """Bot should hit on 11 against weak dealer card."""
        card = Card("H", 5)
        self.assertEqual(self.bot.decide_action([], card, 11), "hit")

    def test_hit_on_low_score_moderate_dealer(self):
        """Bot should hit below 17 against moderate dealer card (7-9)."""
        card = Card("H", 8)
        self.assertEqual(self.bot.decide_action([], card, 16), "hit")

    def test_stand_on_17_moderate_dealer(self):
        """Bot should stand on 17 against moderate dealer card."""
        card = Card("H", 8)
        self.assertEqual(self.bot.decide_action([], card, 17), "stand")

    def test_hit_against_dealer_ace(self):
        """Bot should hit below 17 against dealer ace (strong card)."""
        card = Card("H", 14)
        self.assertEqual(self.bot.decide_action([], card, 16), "hit")


class TestBotBlackjackIntegration(unittest.TestCase):
    def setUp(self):
        mock_casino = MagicMock()
        mock_casino.db = MagicMock()
        mock_casino.db.get_user_wallet.return_value = 1000.0
        self.game = Blackjack(game_id="test_game", casino=mock_casino)

    def test_bot_auto_bets_during_tick(self):
        """Bot should automatically place a bet during the betting phase."""
        self.game.deck = [Card("H", 3), Card("H", 2), Card("H", 5), Card("H", 6),
                          Card("H", 7), Card("H", 8)]
        bot = SimpleBlackjackBot("AutoBetBot")
        self.game.join(bot)
        self.game.tick()  # WAITING -> BETTING
        self.assertEqual(self.game.state, HandState.BETTING)
        self.game.tick()  # BETTING: bot auto-bets, all bets in -> deals
        self.assertIn("AutoBetBot", self.game.bets)
        self.assertEqual(self.game.bets["AutoBetBot"], self.game.MIN_BET)

    def test_bot_auto_bets_then_deals(self):
        """After bot auto-bets, the same tick should deal cards."""
        self.game.deck = [Card("H", 3), Card("H", 2), Card("H", 5), Card("H", 6),
                          Card("H", 7), Card("H", 8)]
        bot = SimpleBlackjackBot("DealBot")
        self.game.join(bot)
        self.game.tick()  # WAITING -> BETTING
        self.game.tick()  # BETTING: bot auto-bets -> PLAYING
        self.assertEqual(self.game.state, HandState.PLAYING)

    def test_bot_auto_plays_turn(self):
        """Bot should automatically play during its turn."""
        # Stack the deck: dealer gets 10+6=16, bot gets 10+8=18 -> stands
        self.game.deck = [Card("H", 8), Card("H", 10), Card("H", 6), Card("H", 10)]
        bot = SimpleBlackjackBot("PlayBot")
        self.game.join(bot)
        self.game.tick()  # WAITING -> BETTING
        self.game.tick()  # BETTING -> PLAYING
        self.assertEqual(self.game.state, HandState.PLAYING)
        self.game.tick()  # Bot auto-plays (score 18 -> stand)
        self.assertEqual(self.game.state, HandState.DEALER_TURN)

    def test_bot_hits_on_low_score(self):
        """Bot should hit when score is low."""
        # Deck: dealer 10+7=17, bot 3+2=5 -> bot hits, gets 10 -> 15, hits again, gets 5 -> 20
        self.game.deck = [Card("H", 5), Card("H", 10), Card("H", 2), Card("H", 3),
                          Card("H", 7), Card("H", 10)]
        bot = SimpleBlackjackBot("HitBot")
        self.game.join(bot)
        self.game.tick()  # WAITING -> BETTING
        self.game.tick()  # BETTING -> PLAYING
        # Bot has 5, dealer shows 10 (strong) -> hit
        self.assertEqual(self.game.get_score(bot), 5)
        self.game.tick()  # Bot hits -> 15
        self.assertEqual(self.game.get_score(bot), 15)
        self.assertEqual(self.game.state, HandState.PLAYING)
        self.game.tick()  # Bot hits again -> 20
        self.assertEqual(self.game.get_score(bot), 20)
        self.assertEqual(self.game.state, HandState.PLAYING)
        self.game.tick()  # Bot stands on 20
        self.assertEqual(self.game.state, HandState.DEALER_TURN)

    def test_bot_complete_game(self):
        """Bot should play a complete game through all state transitions."""
        # Dealer: 10+7=17, bot: 10+8=18 -> bot stands -> dealer stands -> resolve
        self.game.deck = [Card("H", 8), Card("H", 10), Card("H", 7), Card("H", 10)]
        bot = SimpleBlackjackBot("FullGameBot")
        self.game.join(bot)
        self.game.tick()  # WAITING -> BETTING
        self.game.tick()  # BETTING -> PLAYING
        self.game.tick()  # Bot stands (18)
        self.assertEqual(self.game.state, HandState.DEALER_TURN)
        self.game.tick()  # Dealer plays
        self.assertEqual(self.game.state, HandState.RESOLVING)
        self.game.tick()  # Resolve
        self.assertEqual(self.game.state, HandState.BETWEEN_HANDS)

    def test_bot_and_human_together(self):
        """Bot and human player should coexist in the same game."""
        # Dealer: 10+6=16, Human: 10+8=18, Bot: 10+7=17
        self.game.deck = [Card("H", 7), Card("H", 8), Card("H", 10), Card("H", 10),
                          Card("H", 6), Card("H", 10), Card("H", 10)]
        human = Player("Human")
        bot = SimpleBlackjackBot("BotFriend")
        self.game.join(human)
        self.game.join(bot)
        self.game.tick()  # WAITING -> BETTING
        self.assertNotIn("BotFriend", self.game.bets)
        self.assertNotIn("Human", self.game.bets)
        # Human places bet; bot will auto-bet on next tick
        self.game.bet(human, 10)
        self.game.tick()  # BETTING: bot auto-bets, all bets in -> PLAYING
        self.assertIn("BotFriend", self.game.bets)
        self.assertEqual(self.game.state, HandState.PLAYING)
        # Human is first, should be their turn
        self.assertEqual(self.game.players[self.game.current_player_idx], human)
        self.game.stand(human)
        # Now it's bot's turn - bot auto-plays on tick
        self.assertEqual(self.game.players[self.game.current_player_idx], bot)
        self.game.tick()  # Bot auto-stands (17, dealer shows 10=strong, 17 >= 17)
        self.assertEqual(self.game.state, HandState.DEALER_TURN)


class TestCasinoBotManagement(unittest.TestCase):
    def setUp(self):
        self.mock_redis = MagicMock()
        self.mock_db = MagicMock()
        self.mock_db.get_user_wallet.return_value = 1000.0
        self.casino = Casino(redis_host="localhost", redis_port=6379)
        self.casino.redis = self.mock_redis
        self.casino.db = self.mock_db

    def test_add_bot_to_game(self):
        game_id = self.casino.new_game()
        bot = self.casino.add_bot(game_id, "TestBot", "simple")
        self.assertTrue(bot.is_bot)
        self.assertEqual(bot.name, "TestBot")
        game = self.casino.games[game_id]
        self.assertIn(bot, game.players_waiting)

    def test_add_bot_unknown_type(self):
        game_id = self.casino.new_game()
        with self.assertRaises(CardGameError):
            self.casino.add_bot(game_id, "TestBot", "unknown")

    def test_add_bot_invalid_game(self):
        with self.assertRaises(CardGameError):
            self.casino.add_bot("nonexistent", "TestBot")

    def test_remove_bot_from_waiting(self):
        game_id = self.casino.new_game()
        self.casino.add_bot(game_id, "RemoveBot", "simple")
        game = self.casino.games[game_id]
        self.assertEqual(len(game.players_waiting), 1)
        self.casino.remove_bot(game_id, "RemoveBot")
        self.assertEqual(len(game.players_waiting), 0)

    def test_remove_bot_not_found(self):
        game_id = self.casino.new_game()
        with self.assertRaises(CardGameError):
            self.casino.remove_bot(game_id, "Ghost")

    def test_remove_bot_does_not_remove_human(self):
        """remove_bot should not remove a human player with the same name."""
        game_id = self.casino.new_game()
        game = self.casino.games[game_id]
        human = Player("SameName")
        game.join(human)
        with self.assertRaises(CardGameError):
            self.casino.remove_bot(game_id, "SameName")
        self.assertIn(human, game.players_waiting)

    def test_bot_types_registry(self):
        self.assertIn('simple', BOT_TYPES)
        self.assertEqual(BOT_TYPES['simple'], SimpleBlackjackBot)


if __name__ == "__main__":
    unittest.main()
