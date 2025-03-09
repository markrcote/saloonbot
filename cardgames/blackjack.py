import asyncio
import logging
import time
from .card_game import CardGame, CardGameError, Player


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

    def __init__(self):
        super().__init__()
        self.dealer = Dealer()
        self.players_waiting = []
        self.current_player_idx = None
        self.time_last_hand_ended = None
        self.time_last_ambient = time.time()
        self.output_func = None

    async def output(self, output):
        if self.output_func:
            self.output_func(output)
            await asyncio.sleep(0.5)

    def _check_turn(self, player):
        if self.players[self.current_player_idx] != player:
            raise NotPlayerTurnError(player)

    def _check_game_in_progress(self):
        if self.current_player_idx is None:
            raise CardGameError("No game in progress")

    async def sit_down(self, player):
        if player in self.players or player in self.players_waiting:
            raise CardGameError(f"{player} is already sitting down")

        self.players_waiting.append(player)
        await self.output(f"{player} sits down and will join the next game.")

    async def stand_up(self, player):
        if player not in self.players:
            raise CardGameError(f"{player} is not at the table")

        if player in self.players_waiting:
            self.players_waiting.remove(player)
        else:
            self.players.remove(player)

        await self.output(f"{player} leaves the table.")

    async def new_hand(self):
        self.players.extend(self.players_waiting)
        self.players_waiting = []
        if not self.players:
            raise CardGameError("No players")

        await self.output("New hand started.")
        await self.output(f"Players: {', '.join([str(x) for x in self.players])}")

        for player in self.players:
            self.discard_all(player)
        self.discard_all(self.dealer)

        self.current_player_idx = 0
        self.deal(self.dealer, 2)
        await self.output(f"{self.dealer} shows {self.dealer.hand[0]}")

        if self.get_score(self.dealer) == 21:
            await self.output(
                f"{self.dealer} reveals {self.dealer.hand[1]}. Dealer wins."
            )
            await self.end_hand()
            return

        # Deal two cards to each player
        for player in self.players:
            self.deal(player, 2)
            await self.output(f"{player} has {player.hand_str()}")

    async def end_hand(self):
        wins = []
        ties = []
        losses = []
        await self.output("End of hand.")
        await self.output(f"Dealer has {self.get_score(self.dealer)}.")
        for player in self.players:
            if self.get_score(player) > 21:
                await self.output(f"{player} busted out.")
                losses.append(player)
            else:
                await self.output(f"{player} has {self.get_score(player)}.")
                if self.get_score(self.dealer) > 21 or self.get_score(player) > self.get_score(self.dealer):
                    await self.output(f"{player} wins.")
                    wins.append(player)
                elif self.get_score(player) == self.get_score(self.dealer):
                    await self.output(f"{player} ties with dealer.")
                    ties.append(player)
                else:
                    await self.output(f"{player} loses.")
                    losses.append(player)
        self.current_player_idx = None

    async def hit(self, player):
        self._check_game_in_progress()
        self._check_turn(player)
        self.deal(player)
        await self.output(f"{player} is dealt {player.hand[-1]}")
        await self.output(f"{player} has {player.hand_str()}")

        if self.get_score(player) <= 21:
            return

        if self.get_score(player) == 21:
            await self.output(f"{player} has 21.")
        else:
            await self.output(f"{player} busts.")
        self.next_turn()

    async def stand(self, player):
        self._check_game_in_progress()
        self._check_turn(player)
        await self.output(f"{player} stands.")
        self.next_turn()

    def game_in_progress(self):
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

    async def dealer_turn(self):
        if self.current_player_idx is None:
            raise CardGameError("No game in progress")

        if self.current_player_idx < len(self.players):
            raise CardGameError("Players still have turns")

        await self.output(f"Dealer flips over the second card: {self.dealer.hand[-1]}")

        while self.get_score(self.dealer) < 17:
            self.deal(self.dealer)
            await self.output(
                f"Dealer is dealt {self.dealer.hand[-1]}"
            )

        if self.get_score(self.dealer) == 21:
            await self.output("Dealer has 21.")
            await self.end_hand()
            return
        elif self.get_score(self.dealer) > 21:
            await self.output("Dealer busts.")
            await self.end_hand()
            return

        await self.output("Dealer stands.")
        await self.end_hand()

    async def tick(self):
        logging.debug('tick')
        if self.game_in_progress():
            if not self.players:
                await self.output("All players have left the table.")
                self.current_player_idx = None
            elif self.is_dealer_turn():
                await self.output("Dealer's turn")
                await self.dealer_turn()

        if not self.game_in_progress() and (self.players or self.players_waiting):
            if self.time_last_hand_ended is None:
                self.time_last_hand_ended = time.time()

            if time.time() > self.time_last_hand_ended + self.TIME_BETWEEN_HANDS:
                self.time_last_hand_ended = None
                await self.new_hand()

        if time.time() > self.time_last_ambient + self.PERIOD_LAST_AMBIENT:
            # await self.output("The dealer clears his throat.")
            self.time_last_ambient = time.time()
