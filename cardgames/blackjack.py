from .card_game import CardGame, CardGameError, Player


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
        self.current_player_idx = None

    def _check_turn(self, player):
        if self.players[self.current_player_idx] != player:
            raise NotPlayerTurnError(player)

    def _check_game_in_progress(self):
        if self.current_player_idx is None:
            raise CardGameError('No game in progress')

    def sit_down(self, player):
        self.players.append(player)

    def new_hand(self):
        if not self.players:
            raise CardGameError('No players')

        for player in self.players:
            self.discard_all(player)
        self.discard_all(self.dealer)

        self.current_player_idx = 0
        self.deal(self.dealer, 2)
        self.message_queue.append(f'{self.dealer} shows {self.dealer.hand[0]}')
        if self.get_score(self.dealer) == 21:
            self.message_queue.append(
                f'{self.dealer} reveals {self.dealer.hand[1]}. Dealer wins.'
            )
            self.end_hand()
            return

        # Deal two cards to each player
        for player in self.players:
            self.deal(player, 2)

    def end_hand(self):
        self.current_player_idx = None

    def hit(self, player):
        self._check_game_in_progress()
        self._check_turn(player)
        self.deal(player)
        self.message_queue.append(f'{player} is dealt {player.hand[-1]}')

        if self.get_score(player) <= 21:
            return

        if self.get_score(player) == 21:
            self.message_queue.append(f'{player} has 21.')
        else:
            self.message_queue.append(f'{player} busts.')

    def stand(self, player):
        self._check_game_in_progress()
        self._check_turn(player)

    def next_turn(self):
        if self.current_player_idx is None:
            raise CardGameError('No game in progress')

        self.current_player_idx += 1
        if self.current_player_idx >= len(self.players):
            self.current_player_idx = None
            self.dealer_turn()

    def get_score(self, player):
        sorted_hand = sorted(player.hand, key=lambda card: card.value)
        score = 0
        for card in sorted_hand:
            if card.value < 10:
                score += card.value
            elif card.value >= 10 and card.value <= 13:
                score += 10
            else:
                if score + 11 > 21:
                    score += 1
                else:
                    score += 11

        return score

    def dealer_turn(self):
        while self.get_score(self.dealer) < 17:
            self.deal(self.dealer)
            self.message_queue.append(
                f'Dealer is dealt {self.dealer.hand[-1]}'
            )

        if self.get_score(self.dealer) == 21:
            self.message_queue.append('Dealer has 21.')
            self.end_hand()
            return
        elif self.get_score(self.dealer) > 21:
            self.message_queue.append('Dealer busts.')
            self.end_hand()
            return

        self.message_queue.append('Dealer stands.')
        self.end_hand()
