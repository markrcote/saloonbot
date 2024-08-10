import random


class CardGame:
    def __init__(self):
        self.deck = []
        self.hands = {}
        self.create_deck()

    def create_deck(self):
        # Initialize self.deck to a random deck of cards
        self.deck = []
        for suit in ['H', 'D', 'C', 'S']:
            for value in range(2, 15):
                self.deck.append((suit, value))

    def shuffle(self):
        random.shuffle(self.deck)

    def deal(self, player, cards=1):
        # Deal cards to player
        if player not in self.hands:
            self.hands[player] = []
        for _ in range(cards):
            self.hands[player].append(self.deck.pop())

    def deal_all(self, cards=1):
        # Deal cards to all players
        for player in self.hands:
            self.deal(player, cards)

    def discard(self, player, card):
        # Discard a card from player's hand
        if player in self.hands:
            self.hands[player].remove(card)
            self.deck.append(card)

    def discard_all(self):
        # Discard all cards from all players
        for player in self.hands:
            self.deck.extend(self.hands[player])
            self.hands[player] = []
