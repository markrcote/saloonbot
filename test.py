import unittest
from unittest.mock import patch

from card_game import Card, CardGame
from wwnames import WildWestNames


class TestWildWestNames(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.wild_west_names = WildWestNames()

    @patch('random.choice')
    def test_random_name_male(self, mock_choice):
        mock_choice.side_effect = ['John', 'Doe']
        result = self.wild_west_names.random_name(gender='M')
        self.assertEqual(result, '♂ John Doe')

    @patch('random.choice')
    def test_random_name_female(self, mock_choice):
        mock_choice.side_effect = ['Jane', 'Smith']
        result = self.wild_west_names.random_name(gender='F')
        self.assertEqual(result, '♀ Jane Smith')

    @patch('random.choice')
    def test_random_name_random_gender(self, mock_choice):
        mock_choice.side_effect = ['F', 'Mary', 'Brown']
        result = self.wild_west_names.random_name()
        self.assertEqual(result, '♀ Mary Brown')

    @patch('random.choice')
    def test_multiple_random_name_random_gender(self, mock_choice):
        mock_choice.side_effect = ['F', 'Mary', 'Brown', 'M', 'Aiden', 'Patel']
        result = self.wild_west_names.random_name(number=2)
        self.assertEqual(result, '♀ Mary Brown\n♂ Aiden Patel')


class TestCardGame(unittest.TestCase):
    def setUp(self):
        self.game = CardGame()

    def test_create_deck(self):
        self.game.create_deck()
        self.assertEqual(len(self.game.deck), 52)  # Check if the deck has 52 cards

    def test_deal(self):
        self.game.create_deck()
        self.game.deal("Player 1", 5)
        self.assertEqual(len(self.game.deck), 47)  # Check if 5 cards were removed from the deck
        self.assertEqual(len(self.game.hands["Player 1"]), 5)  # Check if 5 cards were added to the player's hand

    def test_deal_all(self):
        self.game.create_deck()
        self.game.hands = {"Player 1": [], "Player 2": []}
        self.game.deal_all(7)
        self.assertEqual(len(self.game.deck), 38)  # Check if 14 cards were removed from the deck
        for player, hand in self.game.hands.items():
            self.assertEqual(len(hand), 7)  # Check if 7 cards were added to each player's hand

    def test_discard(self):
        self.game.create_deck()
        self.game.deal("Player 1", 3)
        card_to_discard = self.game.hands["Player 1"][0]
        discarded_value = card_to_discard.value
        discarded_suit = card_to_discard.suit
        self.game.discard("Player 1", card_to_discard)
        self.assertEqual(len(self.game.hands["Player 1"]), 2)  # Check if the discarded card was removed from the player's hand
        self.assertEqual(self.game.deck[-1].suit, discarded_suit)
        self.assertEqual(self.game.deck[-1].value, discarded_value)

    def test_discard_all(self):
        self.game.create_deck()
        self.game.hands = {"Player 1": [], "Player 2": []}
        self.game.deal_all(7)
        self.game.discard_all()
        self.assertEqual(len(self.game.deck), 52)
        # Check if each hand is empty
        for hand in self.game.hands.values():
            self.assertEqual(len(hand), 0)

    def test_compare(self):
        card1 = Card('H', 5)
        card2 = Card('H', 5)
        card3 = Card('S', 5)
        card4 = Card('S', 7)
        self.assertGreater(card4, card3)
        self.assertLess(card2, card3)
        self.assertEqual(card1, card2)

    def test_card_strings(self):
        self.assertEqual("5 of Hearts", str(Card('H', 5)))
        self.assertEqual("Jack of Spades", str(Card('S', 11)))
        self.assertEqual("A♥", Card('H', 14).shortstr())
        self.assertEqual("2♦", Card('D', 2).shortstr())


if __name__ == '__main__':
    unittest.main()
