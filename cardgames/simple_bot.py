from .bot_player import BotPlayer


class SimpleBlackjackBot(BotPlayer):
    """A bot that plays basic blackjack strategy.

    Strategy:
    - Always bets the minimum amount.
    - Hits on 16 or below, stands on 17 or above.
    - Takes the dealer's visible card into account: if the dealer shows
      a weak card (2-6), the bot stands on 12+ to let the dealer bust.
    """

    def decide_bet(self, min_bet, max_bet, wallet):
        return min_bet

    def decide_action(self, hand, dealer_visible_card, score):
        dealer_value = dealer_visible_card.value
        if dealer_value >= 10 or dealer_value == 14:
            # Dealer shows 10/J/Q/K/A — strong card, play more aggressively
            if score < 17:
                return "hit"
            return "stand"

        if dealer_value <= 6:
            # Dealer shows 2-6 — weak card, let them bust
            if score < 12:
                return "hit"
            return "stand"

        # Dealer shows 7-9 — moderate card
        if score < 17:
            return "hit"
        return "stand"
