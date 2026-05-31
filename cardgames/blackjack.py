import logging
import os
import time
from enum import Enum

from .card_game import Card, CardGame, CardGameError
from .player import Player


# Serialization helpers for game persistence

def card_to_str(card):
    """Serialize a card to string format: "{suit}{value}" e.g., "H10", "S14"."""
    return f"{card.suit}{card.value}"


def str_to_card(s):
    """Deserialize a card from string format."""
    suit = s[0]
    value = int(s[1:])
    return Card(suit, value)


def serialize_hand(cards):
    """Serialize a list of cards to a list of strings."""
    return [card_to_str(card) for card in cards]


def deserialize_hand(data):
    """Deserialize a list of strings to a list of cards."""
    return [str_to_card(s) for s in data]


def _player_label(player):
    """Return display name with NPC type indicator if applicable."""
    npc_type = getattr(player, 'npc_type', None)
    if npc_type == 'llm':
        return f"{player.name} (AI)"
    if npc_type == 'simple':
        return f"{player.name} (bot)"
    return player.name


def serialize_player(player):
    """Serialize a player's state for persistence."""
    is_npc = getattr(player, 'is_npc', False)
    npc_type = getattr(player, 'npc_type', None) if is_npc else None
    npc_personality = None
    npc_db_id = None
    if is_npc:
        npc_db_id = getattr(player, 'npc_db_id', None)
        if npc_type == 'llm':
            personality = getattr(player, 'personality', None)
            npc_personality = personality.name if personality else None
    return {
        'name': player.name,
        'hand': serialize_hand(player.hand),
        'is_npc': is_npc,
        'npc_type': npc_type,
        'npc_personality': npc_personality,
        'npc_db_id': npc_db_id,
    }


def deserialize_player(data, casino=None):
    """Deserialize a player from persisted state."""
    name = data['name']
    hand = deserialize_hand(data['hand'])

    if not data.get('is_npc'):
        player = Player(name)
        player.hand = hand
        return player

    npc_db_id = data.get('npc_db_id')

    # Load NPC record from DB if we have an id
    npc_record = None
    if npc_db_id is not None and casino is not None and getattr(casino, 'db', None) is not None:
        try:
            npc_record = casino.db.get_npc_by_id(npc_db_id)
        except Exception:
            pass

    backstory = npc_record.get('backstory', '') if npc_record else ''
    personality_name = (npc_record.get('personality_name') if npc_record
                        else data.get('npc_personality'))

    if personality_name:
        from .llm_npc import LLMBlackjackNPC
        from .personalities import get_personality
        llm_client = getattr(casino, 'llm_client', None)
        if llm_client is not None:
            try:
                personality = get_personality(personality_name)
                player = LLMBlackjackNPC(name, personality, llm_client,
                                         npc_db_id=npc_db_id, backstory=backstory)
                player.hand = hand
                return player
            except Exception:
                pass

    from .simple_npc import SimpleBlackjackNPC
    player = SimpleBlackjackNPC(name, npc_db_id=npc_db_id, backstory=backstory)
    player.hand = hand
    return player


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
    TIME_WAIT_FOR_PLAYERS = int(os.getenv('BLACKJACK_TIME_WAIT_FOR_PLAYERS', '5'))
    MIN_BET = int(os.getenv('BLACKJACK_MIN_BET', '5'))
    MAX_BET = int(os.getenv('BLACKJACK_MAX_BET', '100'))
    TIME_FOR_BETTING = int(os.getenv('BLACKJACK_TIME_FOR_BETTING', '30'))
    DRAMATIC_PAUSE = float(os.getenv('BLACKJACK_DRAMATIC_PAUSE', '1.5'))
    DEALER_CARD_PAUSE = float(os.getenv('BLACKJACK_DEALER_CARD_PAUSE', '1.0'))
    RESULT_PAUSE = float(os.getenv('BLACKJACK_RESULT_PAUSE', '0.8'))

    # Valid actions for each state
    VALID_ACTIONS = {
        HandState.WAITING: {Action.JOIN, Action.LEAVE},
        HandState.BETTING: {Action.BET, Action.JOIN, Action.LEAVE},
        HandState.PLAYING: {Action.HIT, Action.STAND, Action.LEAVE},
        HandState.DEALER_TURN: {Action.LEAVE},
        HandState.RESOLVING: {Action.LEAVE},
        HandState.BETWEEN_HANDS: {Action.JOIN, Action.LEAVE},
    }

    def __init__(self, game_id, casino, initial_deck=None):
        """ Initialize a new Blackjack game.
        :param game_id: Unique identifier for the game.
        :param casino: The casino managing this game (required).
        :param initial_deck: Optional pre-ordered list of Card objects; skips shuffle.
        """
        super().__init__(initial_deck=initial_deck)
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
        self._bets_dirty = False
        self.time_betting_started = None
        self.time_first_player_joined = None

        # Players who left mid-hand after acting; resolved at end_hand()
        self.departed_players = []

    def output(self, output):
        self.casino.game_output(self.game_id, output)

    def _output_player_result(self, player, result):
        """Output a player's result with their current wallet balance."""
        balance = self.casino.get_wallet(player)
        self.output(f"{player} {result} 💰 Wallet: ${balance:.2f}")

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

        if not getattr(player, 'is_npc', False):
            try:
                self.casino.db.add_user(player.name)
            except Exception as e:
                logging.error(f"Failed to add user to database: {e}")

        if self.state == HandState.BETTING:
            self.output(f"🪑 {_player_label(player)} pulls up a chair. They're in for this round!")
            self.players.append(player)
            logging.info(f"[{self.game_id[:8]}] {_player_label(player)} joins mid-hand")
        else:
            self.output(f"🪑 {_player_label(player)} pulls up a chair. They'll join the next hand.")
            self.players_waiting.append(player)
            logging.info(f"[{self.game_id[:8]}] {_player_label(player)} joins (next hand)")

    def leave(self, player):
        if player not in self.players:
            if player in self.players_waiting:
                self.players_waiting.remove(player)
                self.output(f"👋 {player} tips their hat and moseys on.")
                return
            raise CardGameError(f"{player} is not at the table")

        leaving_idx = self.players.index(player)

        if player.name in self.bets:
            bet_amount = self.bets[player.name]
            already_played = (self.state == HandState.PLAYING and
                              self.current_player_idx is not None and
                              leaving_idx < self.current_player_idx)
            if self.state == HandState.BETTING:
                # Cards not yet dealt; bet is unlocked and returned
                self.casino.update_wallet(player, bet_amount)
                del self.bets[player.name]
                self.output(f"💨 {player} hightails it before the deal! Their ${bet_amount:.2f} bet is returned.")
            elif already_played or self.state in (HandState.DEALER_TURN, HandState.RESOLVING):
                # Already acted or waiting on dealer: hand resolves at end_hand()
                self.departed_players.append(player)
                self.output(f"💨 {player} hightails it outta here! Their hand will be settled when the dust clears.")
            else:
                # Haven't played yet (or it's their turn now): bet forfeited
                del self.bets[player.name]
                self.output(f"💨 {player} hightails it outta here! Their ${bet_amount:.2f} stays with the house.")
        else:
            self.output(f"👋 {player} tips their hat and leaves the table.")

        self.players.remove(player)
        logging.info(f"[{self.game_id[:8]}] {_player_label(player)} leaves (state: {self.state.value})")

        # Handle current player leaving during PLAYING state
        if self.state == HandState.PLAYING and self.current_player_idx is not None:
            if leaving_idx < self.current_player_idx:
                self.current_player_idx -= 1
            if self.current_player_idx >= len(self.players):
                if not self.players and not self.departed_players:
                    self.output("🌵 Table's empty. Everyone's skedaddled.")
                    self.state = HandState.WAITING
                else:
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
        logging.info(f"[{self.game_id[:8]}] Betting opens — {', '.join(_player_label(p) for p in self.players)}")

        self.output("💰 Ante up, folks! Place your bets!")
        self.output(f"🎰 Table limits: ${self.MIN_BET} to ${self.MAX_BET}")
        self.output(f"⏱️ You've got {self.TIME_FOR_BETTING} seconds before the cards fly.")

        # Output all players' wallets before betting
        wallet_lines = []
        for p in self.players:
            balance = self.casino.get_wallet(p)
            wallet_lines.append(f"{p}: ${balance:.2f}")
        self.output("👛 Coin purses: " + ", ".join(wallet_lines))

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

        # Atomically deduct bet; returns False if wallet has insufficient funds
        if not self.casino.update_wallet(player, -amount):
            balance = self.casino.get_wallet(player)
            raise InsufficientFundsError(player, balance, amount)

        self.bets[player.name] = amount
        self._bets_dirty = True
        self._update_time_last_event()
        logging.info(f"[{self.game_id[:8]}] {_player_label(player)} bets ${amount:.2f}")

        # Output bet and updated wallet
        new_balance = self.casino.get_wallet(player)
        self.output(f"💵 {player} throws ${amount:.2f} on the table. 👛 Coin purse: ${new_balance:.2f}")

    def new_hand(self):
        if not self.players:
            raise CardGameError("No players")

        self.output("🃏 The dealer shuffles and deals...")
        self.output(f"🎲 At the table: {', '.join([_player_label(x) for x in self.players])}")

        for player in self.players:
            self.discard_all(player)
        self.discard_all(self.dealer)

        self.deal(self.dealer, 2)

        # Deal to players before checking dealer blackjack so they always see their hand
        for player in self.players:
            self.deal(player, 2)

        self.output(f"👀 Dealer's showing {self.dealer.hand[0]}")

        if self.get_score(self.dealer) == 21:
            for player in self.players:
                self.output(f"🎴 {player} has {player.hand_str()}")
            self.output(
                f"🎰 Dealer flips {self.dealer.hand[1]}. Blackjack! House wins."
            )
            logging.info(
                f"[{self.game_id[:8]}] Hand begins — dealer blackjack {self.dealer.hand_str()} | "
                + " | ".join(f"{_player_label(p)}: {p.hand_str()} ({self.get_score(p)})" for p in self.players)
            )
            self.state = HandState.RESOLVING
            return

        # Transition to playing state before announcing hands
        # This ensures actions can be processed as soon as clients see hands
        self.state = HandState.PLAYING
        self.current_player_idx = 0
        logging.info(
            f"[{self.game_id[:8]}] Hand begins — dealer shows {self.dealer.hand[0]} | "
            + " | ".join(f"{_player_label(p)}: {p.hand_str()} ({self.get_score(p)})" for p in self.players)
        )

        for player in self.players:
            self.output(f"🎴 {player} has {player.hand_str()} ({self.get_score(player)})")

        time.sleep(self.DRAMATIC_PAUSE)
        first_player = self.players[0]
        self.output(f"👉 {first_player}, you're up, partner. Hit or stand?")

    def _resolve_player(self, player, departed=False):
        """Resolve a single player's hand against the dealer and update their wallet."""
        tag = "(already left) " if departed else ""
        bet_amount = self.bets.get(player.name)
        if bet_amount is None:
            logging.error(f"Player {player.name} has no bet at resolution time")
            bet_amount = 0

        if self.get_score(player) > 21:
            self._output_player_result(player, f"💥 {tag}went bust! ${bet_amount:.2f} lost to the house.")
            logging.info(f"[{self.game_id[:8]}] {_player_label(player)}: bust — loses ${bet_amount:.2f}")
        else:
            if self.get_score(self.dealer) > 21 or self.get_score(player) > self.get_score(self.dealer):
                winnings = bet_amount * 2
                self.casino.update_wallet(player, winnings)
                self._output_player_result(player, f"🏆 {tag}strikes gold! Payout: ${winnings:.2f}")
                logging.info(f"[{self.game_id[:8]}] {_player_label(player)}: wins ${winnings:.2f} (held {self.get_score(player)} vs dealer {self.get_score(self.dealer)})")
            elif self.get_score(player) == self.get_score(self.dealer):
                self.casino.update_wallet(player, bet_amount)
                self._output_player_result(player, f"🤝 {tag}pushes with the dealer. ${bet_amount:.2f} returned.")
                logging.info(f"[{self.game_id[:8]}] {_player_label(player)}: push at {self.get_score(player)}")
            else:
                self._output_player_result(player, f"❌ {tag}loses to the house. ${bet_amount:.2f} gone.")
                logging.info(f"[{self.game_id[:8]}] {_player_label(player)}: loses ${bet_amount:.2f} (held {self.get_score(player)} vs dealer {self.get_score(self.dealer)})")

    def end_hand(self):
        """Resolve the hand: compare scores and announce winners."""
        self.output("✨ ~*~ The dust settles... ~*~ ✨")
        self.output(f"Dealer's sitting at {self.get_score(self.dealer)}.")
        for player in self.players:
            time.sleep(self.RESULT_PAUSE)
            self._resolve_player(player)
        for player in self.departed_players:
            time.sleep(self.RESULT_PAUSE)
            self._resolve_player(player, departed=True)

        self.bets = {}
        self.departed_players = []
        self.current_player_idx = None
        self.state = HandState.BETWEEN_HANDS
        self.time_last_hand_ended = time.time()

    def hit(self, player):
        self._check_playing_state()
        self._check_turn(player)
        self._update_time_last_event()
        self.deal(player)
        self.output(f"🃏 {player} draws... {player.hand[-1]}")
        self.output(f"🎴 {player}'s showing {player.hand_str()}")
        logging.info(f"[{self.game_id[:8]}] {_player_label(player)} hits — draws {player.hand[-1]}, hand: {player.hand_str()} ({self.get_score(player)})")

        score = self.get_score(player)
        if score == 21:
            self.output(f"🎯 {player} hits 21!")
            self.next_turn()
        elif score > 21:
            self.output(f"💥 {player} busts! Too greedy, partner.")
            self.next_turn()
        # else: score < 21, player can hit again

    def stand(self, player):
        self._check_playing_state()
        self._check_turn(player)
        self._update_time_last_event()
        self.output(f"✋ {player} stands pat.")
        logging.info(f"[{self.game_id[:8]}] {_player_label(player)} stands at {self.get_score(player)}")
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
        elif not self.players[self.current_player_idx].is_npc:
            player = self.players[self.current_player_idx]
            self.output(f"🎴 {player}'s got {player.hand_str()} ({self.get_score(player)})")
            self.output(f"👉 {player}, you're up, partner. Hit or stand?")

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

        self.output(f"👀 Dealer's showing {self.dealer.hand[0]}.")
        self.output("🔄 Dealer flips the hole card...")
        time.sleep(self.DEALER_CARD_PAUSE)
        self.output(f"🎴 Dealer's got {self.dealer.hand_str()}")
        logging.info(f"[{self.game_id[:8]}] Dealer reveals {self.dealer.hand_str()} ({self.get_score(self.dealer)})")

        while self.get_score(self.dealer) < 17:
            time.sleep(self.DEALER_CARD_PAUSE)
            self.deal(self.dealer)
            self.output(f"🃏 Dealer draws... {self.dealer.hand[-1]}")
            logging.info(f"[{self.game_id[:8]}] Dealer draws {self.dealer.hand[-1]} → {self.dealer.hand_str()} ({self.get_score(self.dealer)})")

        if self.get_score(self.dealer) == 21:
            self.output("🎯 Dealer hits 21!")
            logging.info(f"[{self.game_id[:8]}] Dealer hits 21")
        elif self.get_score(self.dealer) > 21:
            self.output("💥 Dealer busts! The house crumbles!")
            logging.info(f"[{self.game_id[:8]}] Dealer busts at {self.get_score(self.dealer)}")
        else:
            self.output(f"✋ Dealer stands at {self.get_score(self.dealer)}.")
            logging.info(f"[{self.game_id[:8]}] Dealer stands at {self.get_score(self.dealer)}")

        self.state = HandState.RESOLVING

    def action(self, data):
        if data['event_type'] == 'player_action':
            player_name = data['player']
            action = data['action']

            # Validate action is allowed in current state
            self._validate_action(action)

            if action == Action.JOIN:
                # Create a fresh Player scoped to this game; join() guards against duplicates
                player = Player(player_name)
            else:
                all_players = self.players + self.players_waiting
                player = next((p for p in all_players if p.name == player_name), None)
                if player is None:
                    raise CardGameError(f"Player {player_name} not found in this game")

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
        if self.players:
            # Returning players from BETWEEN_HANDS — start immediately
            self.start_betting()
        elif self.players_waiting:
            # Fresh game — start a brief wait on first tick so late joiners can sit down
            if self.time_first_player_joined is None:
                self.time_first_player_joined = time.time()
                if self.TIME_WAIT_FOR_PLAYERS > 0:
                    self.output(f"🕐 Betting starts in {self.TIME_WAIT_FOR_PLAYERS} seconds — get your chips ready!")
            if time.time() >= self.time_first_player_joined + self.TIME_WAIT_FOR_PLAYERS:
                self.start_betting()

    def _tick_betting(self):
        """Handle BETTING state: wait for bets or timeout."""
        if not self.players:
            self.output("🌵 The table's gone quiet... everyone's vamoosed.")
            self.state = HandState.WAITING
            self.time_first_player_joined = None
            return

        # Auto-bet for any NPCs that haven't bet yet; drop broke ones immediately
        broke_npcs = []
        for player in self.players:
            if player.is_npc and player.name not in self.bets:
                wallet = self.casino.get_wallet(player)
                if wallet < self.MIN_BET:
                    broke_npcs.append(player)
                    continue
                amount = player.decide_bet(self.MIN_BET, self.MAX_BET, wallet)
                if amount is None:
                    logging.info(f"[{self.game_id[:8]}] NPC {player.name}: bet pending (LLM thinking)")
                    continue
                quip = getattr(player, 'last_quip', None)
                if quip:
                    self.output(f"🤠 {player.name}: \"{quip}\"")
                    player.last_quip = None
                amount = max(self.MIN_BET, min(amount, self.MAX_BET, int(wallet)))
                self.bet(player, amount)
        for player in broke_npcs:
            self.output(f"💸 {player.name} is tapped out and tips their hat goodbye.")
            logging.info(f"[{self.game_id[:8]}] NPC {player.name} removed — insufficient funds")
            self.players.remove(player)

        # Check if all players have bet
        all_bet = all(player.name in self.bets for player in self.players)

        # Check if betting time has expired
        time_expired = time.time() > self.time_betting_started + self.TIME_FOR_BETTING

        if all_bet or time_expired:
            if all_bet:
                logging.info(f"[{self.game_id[:8]}] All {len(self.players)} players bet — starting hand")
            if time_expired and not all_bet:
                self.output("⏰ Time's up! The clock don't wait for nobody.")
                logging.info(f"[{self.game_id[:8]}] Betting timeout — {len(self.bets)}/{len(self.players)} players bet")
                # Remove players who didn't bet
                players_without_bets = [p for p in self.players if p.name not in self.bets]
                for player in players_without_bets:
                    self.output(f"⏭️ {player} didn't put up any coin. They're sittin' this one out.")
                self.players = [p for p in self.players if p.name in self.bets]

            if not self.players:
                self.output("⏸️ Nobody's got skin in the game. Dealer waits...")
                self.state = HandState.WAITING
                return

            self.new_hand()

    def _tick_playing(self):
        """Handle PLAYING state: check for empty table, auto-play NPCs, remind humans."""
        if not self.players:
            self.output("🌵 Table's empty. Everyone's skedaddled.")
            self.bets = {}
            self.state = HandState.WAITING
            self.current_player_idx = None
            return

        current_player = self.players[self.current_player_idx]

        # Auto-play NPC turns
        if current_player.is_npc:
            score = self.get_score(current_player)
            dealer_visible_card = self.dealer.hand[0]
            action = current_player.decide_action(
                current_player.hand, dealer_visible_card, score
            )
            if action is None:
                return
            quip = getattr(current_player, 'last_quip', None)
            if quip:
                self.output(f"🤠 {current_player.name}: \"{quip}\"")
                current_player.last_quip = None
            if action == "hit":
                self.hit(current_player)
            else:
                self.stand(current_player)
            return

        # Remind current player if they're taking too long
        if time.time() > self.time_last_event + self.PERIOD_REMINDER_PLAYER_TURN:
            self.output(f"⏱️ Hey {current_player}! We ain't got all day. Hit or stand?")
            self._update_time_last_event()

    def _tick_dealer_turn(self):
        """Handle DEALER_TURN state: execute dealer's turn."""
        self.output("👁️ All eyes on the dealer...")
        time.sleep(self.DRAMATIC_PAUSE)
        self.dealer_turn()

    def _tick_resolving(self):
        """Handle RESOLVING state: resolve the hand."""
        self.end_hand()

    def _tick_between_hands(self):
        """Handle BETWEEN_HANDS state: wait then transition to WAITING."""
        if time.time() > self.time_last_hand_ended + self.TIME_BETWEEN_HANDS:
            self.state = HandState.WAITING

    def to_dict(self):
        """Serialize game state for persistence."""
        return {
            'game_id': self.game_id,
            'state': self.state.value,
            'current_player_idx': self.current_player_idx,
            'time_betting_started': self.time_betting_started,
            'time_last_hand_ended': self.time_last_hand_ended,
            'time_last_event': self.time_last_event,
            'time_first_player_joined': self.time_first_player_joined,
            'deck': serialize_hand(self.deck),
            'discards': serialize_hand(self.discards),
            'dealer_hand': serialize_hand(self.dealer.hand),
            'players': [serialize_player(p) for p in self.players],
            'players_waiting': [serialize_player(p) for p in self.players_waiting],
            'departed_players': [serialize_player(p) for p in self.departed_players],
            'bets': self.bets.copy(),
        }

    @classmethod
    def from_dict(cls, data, casino):
        """Restore game from serialized state."""
        game = cls(data['game_id'], casino)

        # Restore state
        game.state = HandState(data['state'])
        game.current_player_idx = data['current_player_idx']

        # Restore timing fields — keep original absolute timestamps so timers
        # continue from where they left off, not reset on restore.
        game.time_last_event = time.time()

        if data['time_betting_started'] is not None:
            game.time_betting_started = data['time_betting_started']

        if data['time_last_hand_ended'] is not None:
            game.time_last_hand_ended = data['time_last_hand_ended']

        if data.get('time_first_player_joined') is not None:
            game.time_first_player_joined = data['time_first_player_joined']

        # Restore deck and discards
        game.deck = deserialize_hand(data['deck'])
        game.discards = deserialize_hand(data['discards'])

        # Restore dealer hand
        game.dealer.hand = deserialize_hand(data['dealer_hand'])

        # Restore players
        game.players = [deserialize_player(p, casino) for p in data['players']]
        game.players_waiting = [deserialize_player(p, casino) for p in data['players_waiting']]
        game.departed_players = [deserialize_player(p, casino) for p in data.get('departed_players', [])]

        # Restore bets
        game.bets = data['bets'].copy()

        return game
