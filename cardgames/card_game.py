import random


class CardGameError(Exception):
    pass


class PlayerNotFoundError(CardGameError):

    def __init__(self, playername):
        self.playername = playername

    def __str__(self):
        return f"Player {self.playername} not found"


class Card:
    SUIT_EMOJIS = {"H": "♥", "D": "♦", "C": "♣", "S": "♠"}
    SUIT_STRINGS = {"H": "Hearts", "D": "Diamonds", "C": "Clubs",
                    "S": "Spades"}
    SUIT_FACE_CARDS = {11: "Jack", 12: "Queen", 13: "King", 14: "Ace"}

    def __init__(self, suit, value):
        self.suit = suit.upper()[0]
        self.value = value

        if self.suit not in self.SUIT_EMOJIS:
            raise CardGameError(f"Invalid suit: {suit}")
        if self.value not in range(2, 15):
            raise CardGameError(f"Invalid value: {self.value}")

    def __repr__(self):
        return f"{self.valuestr()} of {self.SUIT_STRINGS[self.suit]}"

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

    def valuestr(self, short=False):
        return self.value if self.value < 11 \
            else self.SUIT_FACE_CARDS[self.value][:1 if short else None]

    def shortstr(self):
        return f"{self.valuestr(short=True)}{self.SUIT_EMOJIS[self.suit]}"

    def str(self, short=False):
        return self.shortstr() if short else str(self)


class Player:
    def __init__(self, name):
        self.name = name
        self.hand = []

    def __repr__(self):
        return f"{self.name}"

    def __str__(self):
        return f"{self.name}"

    def hand_str(self):
        return ", ".join([card.str() for card in self.hand])


class CardGame:
    def __init__(self):
        self.deck = []
        self.discards = []
        self.players = []
        self.create_deck()

    def get_player(self, name, add=False):
        for player in self.players:
            if player.name == name:
                return player
        if add:
            self.players.append(Player(name))
            return self.players[-1]
        raise PlayerNotFoundError(name)

    def create_deck(self):
        # Initialize self.deck to a random deck of cards
        self.deck = []
        self.discards = []
        for suit in ["H", "D", "C", "S"]:
            for value in range(2, 15):
                self.deck.append(Card(suit, value))
        self.shuffle()

    def shuffle(self):
        self.deck.extend(self.discards)
        self.discards = []
        random.shuffle(self.deck)

    def has_card(self, player, card):
        return card in player.hand

    def deal(self, player, cards=1):
        assert len(self.deck) + len(self.discards) >= cards
        # Deal cards to player
        for _ in range(cards):
            if not self.deck:
                self.shuffle()
            player.hand.append(self.deck.pop())

    def discard(self, player, card):
        # Discard a card from player"s hand
        if self.has_card(player, card):
            player.hand.remove(card)
            self.discards.append(card)

    def discard_all(self, player):
        # Discard all cards from player
        for card in player.hand:
            self.discards.append(card)
        player.hand = []
