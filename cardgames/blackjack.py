import json
import logging
import time

from .card_game import CardGame, CardGameError
from .player import Player, PlayerNotFoundError, registry as player_registry


class NotPlayerTurnError(CardGameError):
    def __init__(self, player):
        self.player = player

    def __str__(self):
        return f"It is not {self.player}'s turn"


class Dealer(Player):
    def __init__(self):
        super().__init__("Dealer")


class Blackjack(CardGame):

    dealer = "dealer"

    PERIOD_LAST_AMBIENT = 10
    TIME_BETWEEN_HANDS = 5

    def __init__(self, game_id, casino):
        """ Initialize a new Blackjack game.
        :param game_id: Unique identifier for the game.
        :param casino: The casino managing this game.

        If casino is None, this game will not output to a casino.
        """
        super().__init__()
        self.game_id = game_id
        self.casino = casino
        self.dealer = Dealer()
        self.players_waiting = []

        # `current_player_idx` is one of the following:
        #  None: no hand is in progress.
        #  int < len(self.players): that player's turn
        #  int == len(self.players): dealer's turn
        self.current_player_idx = None

        self.time_last_hand_ended = None
        self.time_last_ambient = time.time()

    def output(self, output):
        if self.casino:
            self.casino.game_output(self.game_id, output)

    def _check_turn(self, player):
        if self.players[self.current_player_idx] != player:
            raise NotPlayerTurnError(player)

    def _check_hand_in_progress(self):
        '''Raise exception if no hand in progress.'''
        if self.current_player_idx is None:
            raise CardGameError("No game in progress")

    def join(self, player):
        if player in self.players or player in self.players_waiting:
            raise CardGameError(f"{player} is already sitting down")

        self.output(f"Player {player} will join the next game.")
        self.players_waiting.append(player)

    def leave(self, player):
        if player not in self.players:
            raise CardGameError(f"{player} is not at the table")

        if player in self.players_waiting:
            self.players_waiting.remove(player)
        else:
            self.players.remove(player)

    def new_hand(self):
        self.players.extend(self.players_waiting)
        self.players_waiting = []

        if not self.players:
            raise CardGameError("No players")

        self.output("New hand started.")
        self.output(f"Players: {', '.join([str(x) for x in self.players])}")

        for player in self.players:
            self.discard_all(player)
        self.discard_all(self.dealer)

        self.current_player_idx = 0
        self.deal(self.dealer, 2)
        self.output(f"{self.dealer} shows {self.dealer.hand[0]}")

        if self.get_score(self.dealer) == 21:
            self.output(
                f"{self.dealer} reveals {self.dealer.hand[1]}. Dealer wins."
            )
            self.end_hand()
            return

        # Deal two cards to each player
        for player in self.players:
            self.deal(player, 2)
            self.output(f"{player} has {player.hand_str()}")

    def end_hand(self):
        wins = []
        ties = []
        losses = []
        self.output("End of hand.")
        self.output(f"Dealer has {self.get_score(self.dealer)}.")
        for player in self.players:
            if self.get_score(player) > 21:
                self.output(f"{player} busted out.")
                losses.append(player)
            else:
                self.output(f"{player} has {self.get_score(player)}.")
                if self.get_score(self.dealer) > 21 or self.get_score(player) > self.get_score(self.dealer):
                    self.output(f"{player} wins.")
                    wins.append(player)
                elif self.get_score(player) == self.get_score(self.dealer):
                    self.output(f"{player} ties with dealer.")
                    ties.append(player)
                else:
                    self.output(f"{player} loses.")
                    losses.append(player)
        self.current_player_idx = None

    def hit(self, player):
        self._check_hand_in_progress()
        self._check_turn(player)
        self.deal(player)
        self.output(f"{player} is dealt {player.hand[-1]}")
        self.output(f"{player} has {player.hand_str()}")

        if self.get_score(player) <= 21:
            return

        if self.get_score(player) == 21:
            self.output(f"{player} has 21.")
        else:
            self.output(f"{player} busts.")
        self.next_turn()

    def stand(self, player):
        self._check_hand_in_progress()
        self._check_turn(player)
        self.output(f"{player} stands.")
        self.next_turn()

    def hand_in_progress(self):
        return self.current_player_idx is not None

    def is_player_turn(self):
        return self.current_player_idx is not None and self.current_player_idx < len(self.players)

    def is_dealer_turn(self):
        return self.current_player_idx == len(self.players)

    def next_turn(self):
        if self.current_player_idx is None:
            raise CardGameError("No game in progress")

        if self.current_player_idx < len(self.players):
            self.current_player_idx += 1
        else:
            raise CardGameError("All players have played this hand")

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
            raise CardGameError("No game in progress")

        if self.current_player_idx < len(self.players):
            raise CardGameError("Players still have turns")

        self.output(f"Dealer is showing {self.dealer.hand[0]}.")
        self.output(f"Dealer flips over the second card: {self.dealer.hand[-1]}")

        while self.get_score(self.dealer) < 17:
            self.deal(self.dealer)
            self.output(
                f"Dealer is dealt {self.dealer.hand[-1]}"
            )

        if self.get_score(self.dealer) == 21:
            self.output("Dealer has 21.")
            self.end_hand()
            return
        elif self.get_score(self.dealer) > 21:
            self.output("Dealer busts.")
            self.end_hand()
            return

        self.output("Dealer stands.")
        self.end_hand()

    def action(self, data):
        if data['event_type'] == 'player_action':
            # Eventually we'll want to manage players properly with a datastore
            # but for now always add them.
            player = player_registry.get_player(data['player'], add=True)

            if data['action'] == 'join':
                self.join(player)
            elif data['action'] == 'leave':
                self.leave(player)
            elif data['action'] == 'hit':
                self.hit(player)
            elif data['action'] == 'stand':
                self.stand(player)

    def tick(self):
        logging.debug("tick")
        if self.hand_in_progress():
            if not self.players:
                self.output("All players have left the table.")
                # TODO: clean up bets and cards.
                self.current_player_idx = None
            elif self.is_dealer_turn():
                self.output("Dealer's turn")
                self.dealer_turn()

        if not self.hand_in_progress() and (self.players or self.players_waiting):
            if self.time_last_hand_ended is None:
                self.time_last_hand_ended = time.time()

            if time.time() > self.time_last_hand_ended + self.TIME_BETWEEN_HANDS:
                if self.players or self.players_waiting:
                    self.time_last_hand_ended = None
                    self.new_hand()
                else:
                    # Wait another period for one or more players to join.
                    self.time_last_hand_ended = time.time()

        if time.time() > self.time_last_ambient + self.PERIOD_LAST_AMBIENT:
            # self.output("The dealer clears his throat.")
            self.time_last_ambient = time.time()
