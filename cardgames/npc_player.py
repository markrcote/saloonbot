from abc import ABC, abstractmethod

from .player import Player


class NPCPlayer(Player, ABC):
    """Abstract base class for NPC players with automated game strategies.

    Subclass this and implement decide_bet() and decide_action() to create
    an NPC with a specific blackjack strategy.
    """

    is_npc = True

    @abstractmethod
    def decide_bet(self, min_bet, max_bet, wallet):
        """Decide how much to bet.

        Args:
            min_bet: Minimum allowed bet.
            max_bet: Maximum allowed bet.
            wallet: Current wallet balance.

        Returns:
            int: The bet amount, between min_bet and max_bet.
            None: Decision is still pending (caller should retry next tick).
        """
        pass

    @abstractmethod
    def decide_action(self, hand, dealer_visible_card, score):
        """Decide whether to hit or stand.

        Args:
            hand: List of Card objects in the NPC's hand.
            dealer_visible_card: The dealer's face-up Card.
            score: Current hand score.

        Returns:
            str: "hit" or "stand".
            None: Decision is still pending (caller should retry next tick).
        """
        pass
