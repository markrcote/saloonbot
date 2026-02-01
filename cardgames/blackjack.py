import logging
import os
import time
from enum import Enum

import mysql.connector

from .card_game import CardGame, CardGameError
from .player import Player, registry as player_registry


class HandState(Enum):
    """Explicit states for a blackjack hand."""
    WAITING = "waiting"              # No hand, players can join/leave
    PLAYING = "playing"              # Player turns (hit/stand)
    DEALER_TURN = "dealer_turn"      # Dealer plays automatically
    RESOLVING = "resolving"          # Announce winners, handle payouts
    BETWEEN_HANDS = "between_hands"  # Wait period before next hand


class Action:
    """Player action constants."""
    JOIN = "join"
    LEAVE = "leave"
    HIT = "hit"
    STAND = "stand"


class NotPlayerTurnError(CardGameError):
    def __init__(self, player):
        self.player = player

    def __str__(self):
        return f"It is not {self.player}'s turn"


class InvalidActionError(CardGameError):
    def __init__(self, action, state):
        self.action = action
        self.state = state

    def __str__(self):
        return f"Action '{self.action}' is not valid in state '{self.state.value}'"


class Dealer(Player):
    def __init__(self):
        super().__init__("Dealer")


class Blackjack(CardGame):

    PERIOD_REMINDER_PLAYER_TURN = int(os.getenv('BLACKJACK_REMINDER_PERIOD', '30'))
    TIME_BETWEEN_HANDS = int(os.getenv('BLACKJACK_TIME_BETWEEN_HANDS', '10'))

    # Valid actions for each state
    VALID_ACTIONS = {
        HandState.WAITING: {Action.JOIN, Action.LEAVE},
        HandState.PLAYING: {Action.HIT, Action.STAND, Action.LEAVE},
        HandState.DEALER_TURN: {Action.LEAVE},
        HandState.RESOLVING: {Action.LEAVE},
        HandState.BETWEEN_HANDS: {Action.JOIN, Action.LEAVE},
    }

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

        # Explicit game state
        self.state = HandState.WAITING

        # Index of current player during PLAYING state
        # None when not in PLAYING state
        self.current_player_idx = None

        self.time_last_hand_ended = None
        self.time_last_event = time.time()

    def output(self, output):
        if self.casino:
            self.casino.game_output(self.game_id, output)

    def _check_turn(self, player):
        if self.players[self.current_player_idx] != player:
            raise NotPlayerTurnError(player)

    def _check_playing_state(self):
        '''Raise exception if not in playing state.'''
        if self.state != HandState.PLAYING:
            raise CardGameError("No hand in progress")

    def _validate_action(self, action):
        '''Raise exception if action is not valid for current state.'''
        valid_actions = self.VALID_ACTIONS.get(self.state, set())
        if action not in valid_actions:
            raise InvalidActionError(action, self.state)

    def _update_time_last_event(self):
        self.time_last_event = time.time()

    def join(self, player):
        if player in self.players or player in self.players_waiting:
            raise CardGameError(f"{player} is already sitting down")

        # Add user to database if casino has a database connection
        if self.casino and self.casino.db:
            try:
                self.casino.db.add_user(player.name)
            except mysql.connector.Error as e:
                logging.error(f"Failed to add user to database: {e}")

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

        self.deal(self.dealer, 2)
        self.output(f"{self.dealer} shows {self.dealer.hand[0]}")

        if self.get_score(self.dealer) == 21:
            self.output(
                f"{self.dealer} reveals {self.dealer.hand[1]}. Dealer wins."
            )
            self.state = HandState.RESOLVING
            return

        # Deal two cards to each player
        for player in self.players:
            self.deal(player, 2)
            self.output(f"{player} has {player.hand_str()}")

        # Transition to playing state
        self.state = HandState.PLAYING
        self.current_player_idx = 0

    def end_hand(self):
        """Resolve the hand: compare scores and announce winners."""
        wins = []
        ties = []
        losses = []
        self.output("!---- End of hand. ----!")
        self.output(f"Dealer has {self.get_score(self.dealer)}.")
        for player in self.players:
            if self.get_score(player) > 21:
                self.output(f"{player} busted out.")
                losses.append(player)
            else:
                self.output(f"{player} has {self.get_score(player)}.")
                if self.get_score(self.dealer) > 21 or self.get_score(player) > self.get_score(self.dealer):
                    self.output(f"{player} wins!!!")
                    wins.append(player)
                elif self.get_score(player) == self.get_score(self.dealer):
                    self.output(f"{player} ties with dealer.")
                    ties.append(player)
                else:
                    self.output(f"{player} loses.")
                    losses.append(player)

        self.current_player_idx = None
        self.state = HandState.BETWEEN_HANDS
        self.time_last_hand_ended = time.time()

    def hit(self, player):
        self._check_playing_state()
        self._check_turn(player)
        self._update_time_last_event()
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
        self._check_playing_state()
        self._check_turn(player)
        self._update_time_last_event()
        self.output(f"{player} stands.")
        self.next_turn()

    def hand_in_progress(self):
        return self.state in (HandState.PLAYING, HandState.DEALER_TURN)

    def is_player_turn(self):
        return self.state == HandState.PLAYING

    def is_dealer_turn(self):
        return self.state == HandState.DEALER_TURN

    def next_turn(self):
        if self.state != HandState.PLAYING:
            raise CardGameError("No hand in progress")

        self.current_player_idx += 1
        if self.current_player_idx >= len(self.players):
            # All players have played, transition to dealer's turn
            self.state = HandState.DEALER_TURN
            self.current_player_idx = None

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
        """Execute dealer's play: hit until 17 or higher."""
        if self.state != HandState.DEALER_TURN:
            raise CardGameError("Not dealer's turn")

        self.output(f"Dealer is showing {self.dealer.hand[0]}.")
        self.output("Dealer flips over the second card.")
        self.output(f"Dealer has {self.dealer.hand_str()}")

        while self.get_score(self.dealer) < 17:
            self.deal(self.dealer)
            self.output(
                f"Dealer is dealt {self.dealer.hand[-1]}"
            )

        if self.get_score(self.dealer) == 21:
            self.output("Dealer has 21.")
        elif self.get_score(self.dealer) > 21:
            self.output("Dealer busts.")
        else:
            self.output(f"Dealer stands with {self.get_score(self.dealer)}.")

        self.state = HandState.RESOLVING

    def action(self, data):
        if data['event_type'] == 'player_action':
            player = player_registry.get_player(data['player'], add=True)
            action = data['action']

            # Validate action is allowed in current state
            self._validate_action(action)

            if action == Action.JOIN:
                self.join(player)
            elif action == Action.LEAVE:
                self.leave(player)
            elif action == Action.HIT:
                self.hit(player)
            elif action == Action.STAND:
                self.stand(player)

    def tick(self):
        logging.debug(f"tick: state={self.state.value}")

        if self.state == HandState.WAITING:
            self._tick_waiting()
        elif self.state == HandState.PLAYING:
            self._tick_playing()
        elif self.state == HandState.DEALER_TURN:
            self._tick_dealer_turn()
        elif self.state == HandState.RESOLVING:
            self._tick_resolving()
        elif self.state == HandState.BETWEEN_HANDS:
            self._tick_between_hands()

    def _tick_waiting(self):
        """Handle WAITING state: start new hand when players are ready."""
        if self.players or self.players_waiting:
            self.new_hand()

    def _tick_playing(self):
        """Handle PLAYING state: check for empty table, remind current player."""
        if not self.players:
            self.output("All players have left the table.")
            # TODO: clean up bets and cards.
            self.state = HandState.WAITING
            self.current_player_idx = None
            return

        # Remind current player if they're taking too long
        if time.time() > self.time_last_event + self.PERIOD_REMINDER_PLAYER_TURN:
            current_player = self.players[self.current_player_idx]
            self.output(f"{current_player}, it's your turn.")
            self._update_time_last_event()

    def _tick_dealer_turn(self):
        """Handle DEALER_TURN state: execute dealer's turn."""
        self.output("Dealer's turn")
        self.dealer_turn()

    def _tick_resolving(self):
        """Handle RESOLVING state: resolve the hand."""
        self.end_hand()

    def _tick_between_hands(self):
        """Handle BETWEEN_HANDS state: wait then transition to WAITING."""
        if time.time() > self.time_last_hand_ended + self.TIME_BETWEEN_HANDS:
            self.state = HandState.WAITING
