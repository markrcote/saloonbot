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
    BETTING = "betting"              # Players place bets
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
    BET = "bet"


class NotPlayerTurnError(CardGameError):
    def __init__(self, player):
        self.player = player

    def __str__(self):
        return f"It is not {self.player}'s turn"

    def user_message(self):
        return "It's not your turn."


class InvalidActionError(CardGameError):
    def __init__(self, action, state):
        self.action = action
        self.state = state

    def __str__(self):
        return f"Action '{self.action}' is not valid in state '{self.state.value}'"

    def user_message(self):
        return f"You can't use '{self.action}' right now."


class InsufficientFundsError(CardGameError):
    def __init__(self, player, balance, bet_amount):
        self.player = player
        self.balance = balance
        self.bet_amount = bet_amount

    def __str__(self):
        return f"{self.player} has insufficient funds (${self.balance:.2f}) for bet of ${self.bet_amount:.2f}"

    def user_message(self):
        return f"You don't have enough funds for that bet. Your balance is ${self.balance:.2f}."


class InvalidBetError(CardGameError):
    def __init__(self, message):
        self.message = message

    def __str__(self):
        return self.message

    def user_message(self):
        return self.message


class Dealer(Player):
    def __init__(self):
        super().__init__("Dealer")


class Blackjack(CardGame):

    PERIOD_REMINDER_PLAYER_TURN = int(os.getenv('BLACKJACK_REMINDER_PERIOD', '30'))
    TIME_BETWEEN_HANDS = int(os.getenv('BLACKJACK_TIME_BETWEEN_HANDS', '10'))
    MIN_BET = int(os.getenv('BLACKJACK_MIN_BET', '5'))
    MAX_BET = int(os.getenv('BLACKJACK_MAX_BET', '100'))
    TIME_FOR_BETTING = int(os.getenv('BLACKJACK_TIME_FOR_BETTING', '30'))

    # Valid actions for each state
    VALID_ACTIONS = {
        HandState.WAITING: {Action.JOIN, Action.LEAVE},
        HandState.BETTING: {Action.BET, Action.LEAVE},
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

        # Betting state
        self.bets = {}  # Player -> bet amount
        self.time_betting_started = None

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
            if player in self.players_waiting:
                self.players_waiting.remove(player)
                self.output(f"{player} left the waiting list.")
                return
            raise CardGameError(f"{player} is not at the table")

        # If player had a bet, they forfeit it
        if player.name in self.bets:
            forfeited = self.bets[player.name]
            self.output(f"{player} left the game. Bet of ${forfeited:.2f} forfeited.")
            del self.bets[player.name]
        else:
            self.output(f"{player} left the game.")

        self.players.remove(player)

        # Handle current player leaving during PLAYING state
        if self.state == HandState.PLAYING and self.current_player_idx is not None:
            if self.current_player_idx >= len(self.players):
                self.current_player_idx = len(self.players) - 1
                if self.current_player_idx < 0:
                    self.state = HandState.DEALER_TURN
                    self.current_player_idx = None

    def start_betting(self):
        """Transition from WAITING to BETTING state."""
        # Move waiting players to active players
        self.players.extend(self.players_waiting)
        self.players_waiting = []

        if not self.players:
            raise CardGameError("No players")

        self.bets = {}
        self.time_betting_started = time.time()
        self.state = HandState.BETTING

        self.output("Place your bets!")
        self.output(f"Minimum bet: ${self.MIN_BET}, Maximum bet: ${self.MAX_BET}")
        self.output(f"You have {self.TIME_FOR_BETTING} seconds.")

    def bet(self, player, amount):
        """Place a bet for a player."""
        if self.state != HandState.BETTING:
            raise CardGameError("Betting is not open")

        if player not in self.players:
            raise CardGameError(f"{player} is not at the table")

        if player.name in self.bets:
            raise CardGameError(f"{player} has already placed a bet")

        # Validate bet amount
        if amount < self.MIN_BET:
            raise InvalidBetError(f"Minimum bet is ${self.MIN_BET}")

        if amount > self.MAX_BET:
            raise InvalidBetError(f"Maximum bet is ${self.MAX_BET}")

        # Check wallet balance
        if self.casino and self.casino.db:
            wallet = self.casino.db.get_user_wallet(player.name)
            if wallet is None or wallet < amount:
                balance = wallet if wallet else 0
                raise InsufficientFundsError(player, balance, amount)

            # Deduct bet from wallet immediately (escrow)
            self.casino.db.update_wallet(player.name, -amount)

        self.bets[player.name] = amount
        self._update_time_last_event()
        self.output(f"{player} bets ${amount:.2f}")

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

        # Transition to playing state before announcing hands
        # This ensures actions can be processed as soon as clients see hands
        self.state = HandState.PLAYING
        self.current_player_idx = 0

        for player in self.players:
            self.output(f"{player} has {player.hand_str()}")

        self.output(f"{self.players[0]}, it's your turn.")

    def end_hand(self):
        """Resolve the hand: compare scores and announce winners."""
        wins = []
        ties = []
        losses = []
        self.output("!---- End of hand. ----!")
        self.output(f"Dealer has {self.get_score(self.dealer)}.")
        for player in self.players:
            bet_amount = self.bets.get(player.name, 0)

            if self.get_score(player) > 21:
                self.output(f"{player} busted out. Lost ${bet_amount:.2f}")
                losses.append(player)
                # Bet already deducted, nothing to do
            else:
                self.output(f"{player} has {self.get_score(player)}.")
                if self.get_score(self.dealer) > 21 or \
                   self.get_score(player) > self.get_score(self.dealer):
                    winnings = bet_amount * 2  # Return bet + win equal amount
                    self.output(f"{player} wins!!! Payout: ${winnings:.2f}")
                    wins.append(player)
                    if self.casino and self.casino.db:
                        self.casino.db.update_wallet(player.name, winnings)
                elif self.get_score(player) == self.get_score(self.dealer):
                    self.output(f"{player} ties with dealer. Bet returned: ${bet_amount:.2f}")
                    ties.append(player)
                    if self.casino and self.casino.db:
                        self.casino.db.update_wallet(player.name, bet_amount)
                else:
                    self.output(f"{player} loses. Lost ${bet_amount:.2f}")
                    losses.append(player)
                    # Bet already deducted, nothing to do

        self.bets = {}  # Clear bets for next hand
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
            elif action == Action.BET:
                if 'amount' not in data:
                    raise CardGameError("Bet amount is required")
                self.bet(player, data['amount'])

    def tick(self):
        logging.debug(f"tick: state={self.state.value}")

        if self.state == HandState.WAITING:
            self._tick_waiting()
        elif self.state == HandState.BETTING:
            self._tick_betting()
        elif self.state == HandState.PLAYING:
            self._tick_playing()
        elif self.state == HandState.DEALER_TURN:
            self._tick_dealer_turn()
        elif self.state == HandState.RESOLVING:
            self._tick_resolving()
        elif self.state == HandState.BETWEEN_HANDS:
            self._tick_between_hands()

    def _tick_waiting(self):
        """Handle WAITING state: start betting when players are ready."""
        if self.players or self.players_waiting:
            self.start_betting()

    def _tick_betting(self):
        """Handle BETTING state: wait for bets or timeout."""
        if not self.players:
            self.output("All players have left the table.")
            self.state = HandState.WAITING
            return

        # Check if all players have bet
        all_bet = all(player.name in self.bets for player in self.players)

        # Check if betting time has expired
        time_expired = time.time() > self.time_betting_started + self.TIME_FOR_BETTING

        if all_bet or time_expired:
            if time_expired and not all_bet:
                self.output("Betting time expired.")
                # Remove players who didn't bet
                players_without_bets = [p for p in self.players if p.name not in self.bets]
                for player in players_without_bets:
                    self.output(f"{player} did not place a bet and is removed from the hand.")
                    self.players.remove(player)

            if not self.players:
                self.output("No players with valid bets. Returning to waiting.")
                self.state = HandState.WAITING
                return

            self.new_hand()

    def _tick_playing(self):
        """Handle PLAYING state: check for empty table, remind current player."""
        if not self.players:
            self.output("All players have left the table.")
            self.bets = {}
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
