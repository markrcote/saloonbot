import unittest
from card_game import CardGame


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
        self.game.discard("Player 1", card_to_discard)
        self.assertEqual(len(self.game.hands["Player 1"]), 2)  # Check if the discarded card was removed from the player's hand

    def test_discard_all(self):
        self.game.create_deck()
        self.game.hands = {"Player 1": [], "Player 2": []}
        self.game.deal_all(7)
        self.game.discard_all()
        self.assertEqual(len(self.game.deck), 52)
        # Check if each hand is empty
        for hand in self.game.hands.values():
            self.assertEqual(len(hand), 0)


if __name__ == '__main__':
    unittest.main()
