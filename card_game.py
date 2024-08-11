import random


class Card:
    SUIT_EMOJIS = {'H': '♥', 'D': '♦', 'C': '♣', 'S': '♠'}
    SUIT_STRINGS = {'H': 'Hearts', 'D': 'Diamonds', 'C': 'Clubs', 'S': 'Spades'}

    def __init__(self, suit, value):
        self.suit = suit.upper()[0]
        assert self.suit in self.SUIT_EMOJIS, f'Invalid suit: {self.suit}'
        self.value = value
        assert self.value in range(2, 15), f'Invalid value: {self.value}'

    def __repr__(self):
        return f'{self.value} of {self.SUIT_STRINGS[self.suit]}'

    def __eq__(self, other):
        if isinstance(other, Card):
            return self.suit == other.suit and self.value == other.value
        return False

    def __ne__(self, other):
        return not self.__eq__(other)

    def __gt__(self, other):
        if self.value == other.value:
            return ord(self.suit) > ord(other.suit)
        return self.value > other.value

    def __lt__(self, other):
        if self.value == other.value:
            return ord(self.suit) < ord(other.suit)
        return self.value < other.value

    def __ge__(self, other):
        return self == other or self > other

    def __le__(self, other):
        return self == other or self < other

    def short_string(self):
        return f'{self.value}{self.SUIT_EMOJIS[self.suit]}'


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
                self.deck.append(Card(suit, value))
        self.shuffle()

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
