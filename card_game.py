import random


class Card:
    SUIT_EMOJIS = {'H': '♥', 'D': '♦', 'C': '♣', 'S': '♠'}
    SUIT_STRINGS = {'H': 'Hearts', 'D': 'Diamonds', 'C': 'Clubs', 'S': 'Spades'}
    SUIT_FACE_CARDS = {11: 'Jack', 12: 'Queen', 13: 'King', 14: 'Ace'}

    def __init__(self, suit, value):
        self.suit = suit.upper()[0]
        assert self.suit in self.SUIT_EMOJIS, f'Invalid suit: {self.suit}'
        self.value = value
        assert self.value in range(2, 15), f'Invalid value: {self.value}'

    def __repr__(self):
        return f'{self.valuestr()} of {self.SUIT_STRINGS[self.suit]}'

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
        return f'{self.valuestr(short=True)}{self.SUIT_EMOJIS[self.suit]}'

    def str(self, short=False):
        return self.shortstr() if short else str(self)


class Player:
    def __init__(self, name):
        self.name = name
        self.hand = []

    def __repr__(self):
        return f'Player {self.name}'

    def __str__(self):
        return f'Player {self.name}'


class CardGame:
    def __init__(self):
        self.deck = []
        self.players = []
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

    def remove_player(self, playername):
        for player in self.players:
            if player.name == playername:
                self.players.remove(player)
                return
        raise ValueError(f'Player {playername} not found')

    def get_player(self, playername, add_player=True):
        for player in self.players:
            if player.name == playername:
                return player
        if not add_player:
            raise ValueError(f'Player {playername} not found')
        player = Player(playername)
        self.players.append(player)
        return player

    def deal(self, playername, cards=1, add_player=True):
        # Deal cards to player
        player = self.get_player(playername, add_player)
        for _ in range(cards):
            player.hand.append(self.deck.pop())

    def deal_all(self, cards=1):
        # Deal cards to all players
        for player in self.players:
            self.deal(player.name, cards, add_player=False)

    def discard(self, playername, card):
        # Discard a card from player's hand
        player = self.get_player(playername, add_player=False)
        player.hand.remove(card)
        self.deck.append(card)

    def discard_all(self):
        # Discard all cards from all players
        for player in self.players:
            self.deck.extend(player.hand)
            player.hand = []
