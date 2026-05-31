import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor

from .llm_client import LLMClient, LLMError
from .npc_player import NPCPlayer
from .personalities import Personality
from .simple_npc import SimpleBlackjackNPC

logger = logging.getLogger(__name__)

_ACTION_VALID = {"hit", "stand"}


class LLMBlackjackNPC(NPCPlayer):

    npc_type = "llm"

    def __init__(self, name: str, personality: Personality, llm_client: LLMClient,
                 npc_db_id=None, backstory=''):
        super().__init__(name, npc_db_id=npc_db_id, backstory=backstory)
        self.personality = personality
        self._llm_client = llm_client
        self.last_quip: str | None = None
        self._executor = ThreadPoolExecutor(max_workers=1)
        self._pending_action_future = None
        self._pending_bet_future = None
        self._fallback = SimpleBlackjackNPC(name)

    def decide_action(self, hand, dealer_visible_card, score):
        if self._pending_action_future is None:
            logger.info("LLM action call submitted for %s", self.name)
            self._pending_action_future = self._executor.submit(
                self._llm_decide_action, list(hand), dealer_visible_card, score
            )
            return None

        if not self._pending_action_future.done():
            return None

        future = self._pending_action_future
        self._pending_action_future = None

        result = future.result()
        self.last_quip = result.get("quip") or None
        return result["action"]

    def decide_bet(self, min_bet, max_bet, wallet):
        if self._pending_bet_future is None:
            logger.info("LLM bet call submitted for %s", self.name)
            self._pending_bet_future = self._executor.submit(
                self._llm_decide_bet, min_bet, max_bet, wallet
            )
            return None

        if not self._pending_bet_future.done():
            return None

        future = self._pending_bet_future
        self._pending_bet_future = None

        try:
            result = future.result()
            self.last_quip = result.get("quip") or None
            amount = int(result["amount"])
            return max(min_bet, min(max_bet, amount))
        except Exception as e:
            logger.warning("LLM bet decision failed for %s: %s", self.name, e)
            return min_bet

    def _llm_decide_action(self, hand, dealer_visible_card, score) -> dict:
        timeout = float(os.environ.get("LLM_TIMEOUT", "5"))
        hand_str = ", ".join(c.str(short=True) for c in hand)
        user_msg = (
            f"Your hand: {hand_str} (score: {score}). "
            f"Dealer shows: {dealer_visible_card.str(short=True)}. "
            "Hit or stand?"
        )
        t0 = time.time()
        try:
            raw = self._llm_client.complete(
                system=self.personality.system_prompt,
                user=user_msg,
                timeout=timeout,
            )
            result = json.loads(raw)
            if result.get("action") not in _ACTION_VALID:
                raise ValueError(f"Invalid action: {result.get('action')!r}")
            logger.info("LLM action for %s: %.1fs → %s", self.name, time.time() - t0, result["action"])
            return result
        except (LLMError, json.JSONDecodeError, ValueError, KeyError) as e:
            logger.warning("LLM action fallback for %s after %.1fs: %s", self.name, time.time() - t0, e)
            action = self._fallback.decide_action(hand, dealer_visible_card, score)
            return {"action": action, "quip": None}

    def _llm_decide_bet(self, min_bet, max_bet, wallet) -> dict:
        timeout = float(os.environ.get("LLM_TIMEOUT", "5"))
        system = self._build_betting_system_prompt()
        user_msg = (
            f"You have ${wallet:.0f} in your wallet. "
            f"The bet range is ${min_bet}–${max_bet}. "
            "How much do you bet?"
        )
        t0 = time.time()
        try:
            raw = self._llm_client.complete(
                system=system,
                user=user_msg,
                timeout=timeout,
            )
            result = json.loads(raw)
            amount = int(result["amount"])
            logger.info("LLM bet for %s: %.1fs → $%d", self.name, time.time() - t0, amount)
            return {"amount": max(min_bet, min(max_bet, amount)), "quip": result.get("quip")}
        except (LLMError, json.JSONDecodeError, ValueError, KeyError) as e:
            logger.warning("LLM bet fallback for %s after %.1fs: %s", self.name, time.time() - t0, e)
            return {"amount": min_bet, "quip": None}

    def shutdown(self):
        self._executor.shutdown(wait=False)

    def _build_betting_system_prompt(self) -> str:
        base = self.personality.system_prompt
        marker = "Respond ONLY with valid JSON:"
        idx = base.rfind(marker)
        if idx >= 0:
            base = base[:idx].rstrip()
        return (
            base + " "
            "Respond ONLY with valid JSON: "
            '{"amount": <integer bet amount>, "quip": "<in-character remark under 20 words>"}'
        )
