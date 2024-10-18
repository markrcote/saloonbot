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
        self.players_waiting  = []
        self.current_player_idx = None

    def _check_turn(self, player):
        if self.players[self.current_player_idx] != player:
            raise NotPlayerTurnError(player)

    def _check_game_in_progress(self):
        if self.current_player_idx is None:
            raise CardGameError('No game in progress')

    def sit_down(self, player):
        if player in self.players or player in self.players_waiting:
            raise CardGameError(f'{player} is already sitting down')

        if self.current_player_idx is None:
            self.players.append(player)
        else:
            self.players_waiting.append(player)
        self.message_queue.append(f'{player} sits down and will join the next game.')

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
            self.message_queue.append(f'{player} has f{player.hand_str()}')

    def end_hand(self):
        self.current_player_idx = None

    def hit(self, player):
        self._check_game_in_progress()
        self._check_turn(player)
        self.deal(player)
        self.message_queue.append(f'{player} is dealt {player.hand[-1]}')
        self.message_queue.append(f'{player} has {player.hand_str()}')

        if self.get_score(player) <= 21:
            return

        if self.get_score(player) == 21:
            self.message_queue.append(f'{player} has 21.')
        else:
            self.message_queue.append(f'{player} busts.')
        self.next_turn()

    def stand(self, player):
        self._check_game_in_progress()
        self._check_turn(player)
        self.message_queue.append(f'{player} stands.')
        self.next_turn()

    def game_in_progress(self):
        return self.current_player_idx is not None

    def is_player_turn(self):
        return self.current_player_idx is not None and self.current_player_idx < len(self.players)

    def is_dealer_turn(self):
        return self.current_player_idx == len(self.players)

    def next_turn(self):
        if self.current_player_idx is None:
            raise CardGameError('No game in progress')

        if self.current_player_idx < len(self.players):
            self.current_player_idx += 1
        else:
            raise CardGameError('All players have played this hand')

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
        if self.current_player_idx is None:
            raise CardGameError('No game in progress')

        if self.current_player_idx < len(self.players):
            raise CardGameError('Players still have turns')

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

    def tick(self):
        # States of the game:
        # 1. No game in progress
        # Event: game starts after timeout/interaction.
        # Dealer dealt cards. Hand may end.
        # Player dealt cards.
        # 2. Wait for each player turn.
        # Player takes action(s); ends when standing, 21, or bust.
        # 3. Wait for dealer turn (after timeout/interaction).
        # Dealer takes action(s); ends when standing, 21, or bust.
        # Adjust player scores.
        # Take all cards back and shuffle.

        # End of every tick or action, we look for messages to display.
        if self.game_in_progress():
            if self.is_dealer_turn():
                self.message_queue.append('Dealer\'s turn')
                self.dealer_turn()

        return_queue = self.message_queue[:]

        self.message_queue.clear()
        return return_queue
