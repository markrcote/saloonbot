import json
import logging
import os
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor

from .llm_client import LLMClient, LLMError
from .money import cents_to_dollars, dollars_to_cents
from .npc_player import NPCPlayer
from .personalities import Personality
from .simple_npc import SimpleBlackjackNPC

logger = logging.getLogger(__name__)

_ACTION_VALID = {"hit", "stand"}

# Max table events buffered per session; oldest are evicted first.
SESSION_EVENT_BUFFER_SIZE = 40

# How many recent session memories to surface in prompts, by detail level.
MEMORY_RECALL_BY_DETAIL = {'low': 0, 'medium': 1, 'high': 3}

# How many of the latest buffered table events to recap in prompts.
RECENT_EVENTS_IN_PROMPT = 5


class LLMBlackjackNPC(NPCPlayer):

    npc_type = "llm"

    def __init__(self, name: str, personality: Personality, llm_client: LLMClient,
                 npc_db_id=None, backstory='',
                 saloon_name='The Rusty Spur', saloon_town='Redemption, Texas',
                 detail_level='medium', table_context_fn=None, usage_callback=None,
                 memories=None):
        super().__init__(name, npc_db_id=npc_db_id, backstory=backstory)
        self.personality = personality
        self._llm_client = llm_client
        self.last_quip: str | None = None
        self._executor = ThreadPoolExecutor(max_workers=1)
        self._pending_action_future = None
        self._pending_bet_future = None
        self._fallback = SimpleBlackjackNPC(name)
        self._saloon_name = saloon_name
        self._saloon_town = saloon_town
        self._detail_level = detail_level
        self._table_context_fn = table_context_fn
        self._usage_callback = usage_callback
        # One session = this NPC's tenure at a table; the buffer lives and
        # dies with the instance and is condensed into a memory on departure.
        self._session_events = deque(maxlen=SESSION_EVENT_BUFFER_SIZE)
        # Session memories loaded once at seating, newest first.
        self._memories = list(memories or [])

    def observe_table_event(self, event):
        if self._detail_level == 'low':
            return
        self._session_events.append(event)

    @property
    def session_events(self):
        return list(self._session_events)

    @property
    def session_fill(self):
        """Fraction of the session event buffer currently filled (0.0–1.0)."""
        return len(self._session_events) / (self._session_events.maxlen or 1)

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
        """min_bet, max_bet, wallet, and the returned amount are all in cents."""
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

    def _get_table_players(self):
        """Return list of other players at the table (name, archetype)."""
        if self._table_context_fn is None:
            return []
        try:
            return self._table_context_fn()
        except Exception:
            return []

    def _build_action_system_prompt(self) -> str:
        base = self.personality.system_prompt
        context = self._build_context_block()
        if context:
            marker = "Respond ONLY with valid JSON:"
            idx = base.rfind(marker)
            if idx >= 0:
                base = base[:idx].rstrip() + "\n\n" + context + "\n\n" + base[idx:]
        return base

    def _build_betting_system_prompt(self) -> str:
        base = self.personality.system_prompt
        context = self._build_context_block()
        marker = "Respond ONLY with valid JSON:"
        idx = base.rfind(marker)
        if idx >= 0:
            base = base[:idx].rstrip()
        if context:
            base = base + "\n\n" + context
        return (
            base + " "
            "Respond ONLY with valid JSON: "
            '{"amount": <integer bet amount>, "quip": "<in-character remark under 20 words>"}'
        )

    def _build_context_block(self) -> str:
        parts = []

        parts.append(
            f"You are playing blackjack at {self._saloon_name} in {self._saloon_town}."
        )

        if self._detail_level != 'low' and self.backstory:
            parts.append(f"Your backstory: {self.backstory}")

        recall = MEMORY_RECALL_BY_DETAIL.get(self._detail_level, 1)
        if recall and self._memories:
            parts.append(
                "You remember from previous nights here: "
                + " ".join(self._memories[:recall])
            )

        table_players = self._get_table_players()
        if table_players:
            if self._detail_level == 'low':
                names = ", ".join(p['name'] for p in table_players)
                parts.append(f"Others at the table: {names}.")
            else:
                descriptions = []
                for p in table_players:
                    archetype = p.get('archetype')
                    fame = p.get('fame') if self._detail_level == 'high' else None
                    desc = p['name']
                    if archetype:
                        desc += f" ({archetype})"
                    if fame:
                        desc += f", a {fame}"
                    descriptions.append(desc)
                parts.append(f"Others at the table: {', '.join(descriptions)}.")

        if self._detail_level != 'low' and self._session_events:
            recent = list(self._session_events)[-RECENT_EVENTS_IN_PROMPT:]
            parts.append(f"Moments ago at the table: {'; '.join(recent)}.")

        return " ".join(parts)

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
            raw, in_tok, out_tok = self._llm_client.complete(
                system=self._build_action_system_prompt(),
                user=user_msg,
                timeout=timeout,
            )
            result = json.loads(raw)
            if result.get("action") not in _ACTION_VALID:
                raise ValueError(f"Invalid action: {result.get('action')!r}")
            logger.info("LLM action for %s: %.1fs → %s", self.name, time.time() - t0, result["action"])
            self._record_usage('npc_action', in_tok, out_tok)
            return result
        except (LLMError, json.JSONDecodeError, ValueError, KeyError) as e:
            logger.warning("LLM action fallback for %s after %.1fs: %s", self.name, time.time() - t0, e)
            action = self._fallback.decide_action(hand, dealer_visible_card, score)
            return {"action": action, "quip": None}

    def _llm_decide_bet(self, min_bet, max_bet, wallet) -> dict:
        """min_bet, max_bet, and wallet are all in cents; the LLM reasons in whole dollars."""
        timeout = float(os.environ.get("LLM_TIMEOUT", "5"))
        system = self._build_betting_system_prompt()
        user_msg = (
            f"You have ${cents_to_dollars(wallet)} in your wallet. "
            f"The bet range is ${cents_to_dollars(min_bet)}–${cents_to_dollars(max_bet)}. "
            "How much do you bet?"
        )
        t0 = time.time()
        try:
            raw, in_tok, out_tok = self._llm_client.complete(
                system=system,
                user=user_msg,
                timeout=timeout,
            )
            result = json.loads(raw)
            amount_cents = dollars_to_cents(int(result["amount"]))
            logger.info("LLM bet for %s: %.1fs → $%d", self.name, time.time() - t0, result["amount"])
            self._record_usage('npc_bet', in_tok, out_tok)
            return {"amount": max(min_bet, min(max_bet, amount_cents)), "quip": result.get("quip")}
        except (LLMError, json.JSONDecodeError, ValueError, KeyError) as e:
            logger.warning("LLM bet fallback for %s after %.1fs: %s", self.name, time.time() - t0, e)
            return {"amount": min_bet, "quip": None}

    def submit_session_condensation(self, game_id, save_callback):
        """Fire-and-forget: summarize this session's event buffer into a short
        first-person memory and hand it to save_callback(npc_db_id, game_id, text).

        Runs on this NPC's own single-worker executor; nothing blocks on the
        result — the seat frees up regardless of whether the write finishes.
        """
        events = list(self._session_events)
        self._executor.submit(self._condense_session, game_id, events, save_callback)

    def _condense_session(self, game_id, events, save_callback):
        timeout = float(os.environ.get("LLM_SESSION_MEMORY_TIMEOUT", "15"))
        system = self.personality.system_prompt
        marker = "Respond ONLY with valid JSON:"
        idx = system.rfind(marker)
        if idx >= 0:
            system = system[:idx].rstrip()
        system += (
            f" You just finished a session of blackjack at {self._saloon_name}"
            f" in {self._saloon_town}."
        )
        event_lines = "\n".join(f"- {e}" for e in events)
        user_msg = (
            "Here is what happened at the table during your session:\n"
            f"{event_lines}\n\n"
            "Summarize the session from your point of view in 2-4 sentences, "
            "in the first person: what happened, anything it revealed about you, "
            "and standout interactions with others by name. "
            "Respond with plain text only."
        )
        t0 = time.time()
        try:
            raw, in_tok, out_tok = self._llm_client.complete(
                system=system, user=user_msg, timeout=timeout,
            )
            summary = raw.strip()
            if not summary:
                raise LLMError("empty session summary")
            logger.info("LLM session memory for %s: %.1fs, %d chars", self.name, time.time() - t0, len(summary))
            self._record_usage('session_memory', in_tok, out_tok)
            save_callback(self.npc_db_id, game_id, summary)
        except Exception as e:
            logger.warning("Session condensation failed for %s after %.1fs: %s", self.name, time.time() - t0, e)

    def _record_usage(self, purpose, input_tokens, output_tokens):
        if self._usage_callback is not None:
            try:
                self._usage_callback(
                    purpose, self._llm_client.model, input_tokens, output_tokens,
                    npc_id=self.npc_db_id
                )
            except Exception as e:
                logger.warning("Failed to record LLM usage: %s", e)

    def shutdown(self):
        self._executor.shutdown(wait=False)
