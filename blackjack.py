import random

from card_game import CardGame, CardGameError, Player


class NotPlayerTurnError(CardGameError):
    def __init__(self, player):
        self.player = player

    def __str__(self):
        return f'It is not {self.player}\'s turn'


class Dealer(Player):
    def __init__(self):
        super().__init__('Dealer')


class Blackjack(CardGame):

    dealer = 'dealer'

    def __init__(self):
        super().__init__()
        self.dealer = Dealer()
        self.current_player_idx = 0

    def _check_turn(self, player):
        if self.players[self.current_player_idx] != player:
            raise NotPlayerTurnError(player)

    def sit_down(self, player):
        self.players.append(player)

    def new_game(self):
        if not self.players:
            raise CardGameError('No players')

        # Shuffle players
        random.shuffle(self.players)
        self.create_deck()
        self.deal(self.dealer, 2)

    def hit(self, player):
        self._check_turn(player)
        self.game.deal(player)
        if self.get_score(player) >= 21:
            self.current_player_idx += 1
            if self.current_player_idx >= len(self.players):
                self.current_player_idx = 0
                self.dealer_turn()

    def get_score(self, player):
        return sum(card.value for card in self.game.hands[player])

    def dealer_turn(self):
        pass
