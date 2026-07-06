import json
import logging
import os
import time
import uuid

import redis

from .blackjack import Blackjack, HandState, deserialize_hand
from .card_game import CardGameError
from .llm_client import create_llm_client, LLMError
from .llm_npc import LLMBlackjackNPC
from .money import format_cents
from .personalities import get_personality, get_random as get_random_personality
from .simple_npc import SimpleBlackjackNPC
from wwnames.wwnames import WildWestNames

NPC_TYPES = {
    'simple': SimpleBlackjackNPC,
    'llm': LLMBlackjackNPC,
}


MIN_NPC_ROSTER = 20

DEFAULT_NPC_AUTOFILL_MIN = 0   # auto-fill off by default
DEFAULT_NPC_AUTOFILL_MAX = 4
MAX_NPCS_PER_TABLE = 6         # hard cap regardless of limits
AUTOFILL_INTERVAL = 15         # seconds between autofill checks per game

SALOON_NAME = os.environ.get("SALOON_NAME", "The Rusty Spur")
SALOON_TOWN = os.environ.get("SALOON_TOWN", "Redemption, Texas")
SALOON_DETAIL_LEVEL = os.environ.get("SALOON_DETAIL_LEVEL", "medium").lower()

_VALID_DETAIL_LEVELS = {"low", "medium", "high"}
if SALOON_DETAIL_LEVEL not in _VALID_DETAIL_LEVELS:
    logging.warning(
        f"Invalid SALOON_DETAIL_LEVEL {SALOON_DETAIL_LEVEL!r}; defaulting to 'medium'"
    )
    SALOON_DETAIL_LEVEL = "medium"

_BACKSTORY_SENTENCES = {"low": 0, "medium": 2, "high": 4}

_FAME_THRESHOLDS = [
    (3, "unknown stranger"),
    (15, "known regular"),
    (None, "notorious gambler"),
]


def _fame_label(games_played):
    for threshold, label in _FAME_THRESHOLDS:
        if threshold is None or games_played < threshold:
            return label
    return "notorious gambler"


class Casino:
    def __init__(self, redis_host, redis_port, db=None):
        self.games = {}
        self.redis = redis.Redis(host=redis_host, port=redis_port)
        self.db = db
        self._pending_bots = {}  # game_id -> num_bots to add on first human join
        self._dirty_games = set()  # game_ids pending a DB write
        self._llm_client = None
        self._llm_client_tried = False
        self._name_generator = WildWestNames()
        self.npc_min = DEFAULT_NPC_AUTOFILL_MIN
        self.npc_max = DEFAULT_NPC_AUTOFILL_MAX
        self._last_autofill = {}  # game_id -> timestamp of last autofill check

    @property
    def llm_client(self):
        if not self._llm_client_tried:
            self._llm_client_tried = True
            try:
                client = create_llm_client()
                client.probe()
                self._llm_client = client
                logging.info(
                    f"LLM client ready: {client.provider} (model={client.model})."
                    " Bot players will use AI strategy."
                )
            except Exception as e:
                logging.warning(f"LLM client unavailable: {e}. Bot players will use simple strategy.")
        return self._llm_client

    def get_wallet(self, player):
        """Get a player's wallet balance in cents (routes to users or npcs table)."""
        if self.db is None:
            return 0
        npc_db_id = getattr(player, 'npc_db_id', None)
        if getattr(player, 'is_npc', False) and npc_db_id is not None:
            return self.db.get_npc_wallet(npc_db_id) or 0
        return self.db.get_user_wallet(player.name) or 0

    def update_wallet(self, player, amount_cents):
        """Update a player's wallet by an amount in cents (routes to users or npcs table).

        Returns True on success, False if the update would make the wallet negative.
        """
        if self.db is None:
            return True
        npc_db_id = getattr(player, 'npc_db_id', None)
        if getattr(player, 'is_npc', False) and npc_db_id is not None:
            return self.db.update_npc_wallet(npc_db_id, amount_cents)
        return self.db.update_wallet(player.name, amount_cents)

    def _log_usage(self, purpose, model, input_tokens, output_tokens, npc_id=None, game_id=None):
        """Write an LLM usage record to DB. Silently ignores failures."""
        if self.db is None:
            return
        try:
            self.db.log_llm_usage(purpose, model, input_tokens, output_tokens, npc_id, game_id)
        except Exception as e:
            logging.warning(f"Failed to log LLM usage ({purpose}): {e}")

    def _generate_backstory(self, npc_id, personality, name):
        """Generate and persist a backstory for a new NPC. Returns the backstory string."""
        n_sentences = _BACKSTORY_SENTENCES.get(SALOON_DETAIL_LEVEL, 2)
        if n_sentences == 0 or self.llm_client is None:
            return ''

        system = (
            f"{personality.system_prompt}\n\n"
            f"You are {name}, a character in the Old West frontier town of {SALOON_TOWN}. "
            f"Write your backstory in {n_sentences} sentences, in first person, "
            "focusing on what brought you to this life and what you're known for. "
            "Be vivid and specific. Respond with only the backstory text, no JSON."
        )
        try:
            timeout = float(os.environ.get("LLM_TIMEOUT", "5")) * 3  # more time for backstory
            text, in_tok, out_tok = self.llm_client.complete(
                system=system,
                user="Tell me your backstory.",
                timeout=timeout,
            )
            backstory = text.strip()
            self._log_usage('backstory_gen', self.llm_client.model, in_tok, out_tok, npc_id=npc_id)
            if self.db is not None and npc_id is not None:
                try:
                    self.db.update_npc_backstory(npc_id, backstory)
                except Exception as e:
                    logging.warning(f"Failed to save backstory for NPC {npc_id}: {e}")
            logging.info(f"Generated backstory for {name} ({npc_id})")
            return backstory
        except (LLMError, Exception) as e:
            logging.warning(f"Backstory generation failed for {name}: {e}")
            return ''

    def _generate_npc_name(self):
        """Generate a Wild West name for a new NPC, stripping the gender symbol."""
        raw = self._name_generator.random_name()
        # raw is like "♀ Jane McCready" — strip the leading symbol and space
        parts = raw.split(' ', 1)
        return parts[1] if len(parts) > 1 else raw

    def record_hand_result(self, player, won_cents, lost_cents):
        """Record a hand outcome (in cents) for a human player. Fire-and-forget; ignores failures."""
        if getattr(player, 'is_npc', False) or self.db is None:
            return
        try:
            self.db.update_player_stats(player.name, won_cents=won_cents, lost_cents=lost_cents)
        except Exception as e:
            logging.warning(f"Failed to update player stats for {player.name}: {e}")

    def _resolve_wallet_target(self, name):
        """Resolve a name to (kind, ref) for wallet operations.

        Returns ('player', username), ('npc', npc_id), or (None, None) if not found.
        Searches users first, then NPCs (case-insensitive).
        """
        if self.db is None:
            return (None, None)
        try:
            balance = self.db.get_user_wallet(name)
            if balance is not None:
                return ('player', name)
        except Exception as e:
            logging.warning(f"Error resolving wallet target {name!r} as player: {e}")
        try:
            npc = self.db.find_npc_by_name(name)
            if npc is not None:
                return ('npc', npc['id'])
        except Exception as e:
            logging.warning(f"Error resolving wallet target {name!r} as NPC: {e}")
        return (None, None)

    def _handle_lookup_wallet(self, request_id, target):
        """Handle a lookup_wallet request: search users then NPCs and publish wallet_info."""
        kind, ref = self._resolve_wallet_target(target)
        balance = None
        if kind == 'player':
            try:
                balance = self.db.get_user_wallet(ref)
            except Exception as e:
                logging.error(f"Error getting player wallet for {target}: {e}")
        elif kind == 'npc':
            try:
                balance = self.db.get_npc_wallet(ref)
            except Exception as e:
                logging.error(f"Error getting NPC wallet for {target}: {e}")

        self.publish_event(
            'casino_update',
            {
                'event_type': 'wallet_info',
                'request_id': request_id,
                'target': target,
                'kind': kind,
                'balance_cents': balance,
            }
        )

    def _handle_set_wallet(self, request_id, target, mode, amount_cents):
        """Handle a set_wallet request: resolve target, apply change, publish wallet_set.

        amount_cents is in cents.
        """
        kind, ref = self._resolve_wallet_target(target)
        ok = False
        message = ''
        new_balance = None

        if kind is None:
            message = f"No player or NPC named '{target}' found."
        elif mode == 'set':
            if amount_cents < 0:
                message = "Cannot set wallet to a negative amount."
            else:
                try:
                    if kind == 'player':
                        ok = self.db.set_user_wallet(ref, amount_cents)
                    else:
                        ok = self.db.set_npc_wallet(ref, amount_cents)
                except Exception as e:
                    logging.error(f"Error setting wallet for {target}: {e}")
                if ok:
                    new_balance = int(amount_cents)
                    message = f"Wallet set to ${format_cents(amount_cents)}."
                else:
                    message = "Failed to update wallet."
        elif mode == 'adjust':
            try:
                if kind == 'player':
                    ok = self.db.update_wallet(ref, amount_cents)
                else:
                    ok = self.db.update_npc_wallet(ref, amount_cents)
            except Exception as e:
                logging.error(f"Error adjusting wallet for {target}: {e}")
            if ok:
                try:
                    new_balance = (self.db.get_user_wallet(ref) if kind == 'player'
                                   else self.db.get_npc_wallet(ref))
                except Exception:
                    pass
                sign = '+' if amount_cents >= 0 else '-'
                message = (f"Wallet adjusted by {sign}${format_cents(abs(amount_cents))}. "
                           f"New balance: ${format_cents(new_balance)}.")
            else:
                message = "Adjustment would make balance negative — rejected."
        else:
            message = f"Unknown mode '{mode}'."

        self.publish_event(
            'casino_update',
            {
                'event_type': 'wallet_set',
                'request_id': request_id,
                'target': target,
                'kind': kind,
                'new_balance_cents': new_balance,
                'ok': ok,
                'message': message,
            }
        )

    def _handle_get_stats(self, request_id, player_name):
        """Handle a get_stats request: query DB and publish player stats."""
        stats = None
        if self.db is not None:
            try:
                stats = self.db.get_player_stats(player_name)
                if stats:
                    stats['fame'] = _fame_label(stats['games_played'])
            except Exception as e:
                logging.error(f"Error getting player stats for {player_name}: {e}")

        self.publish_event(
            'casino_update',
            {
                'event_type': 'player_stats',
                'request_id': request_id,
                'player': player_name,
                'stats': stats,
            }
        )

    def _handle_get_wallet(self, request_id, player_name):
        """Handle a get_wallet request: query DB and publish user wallet balance."""
        balance = None
        if self.db is not None:
            try:
                balance = self.db.get_user_wallet(player_name)
            except Exception as e:
                logging.error(f"Error getting wallet for {player_name}: {e}")

        self.publish_event(
            'casino_update',
            {
                'event_type': 'player_wallet',
                'request_id': request_id,
                'player': player_name,
                'balance_cents': balance,
            }
        )

    def _make_table_context_fn(self, game_id, npc_name):
        """Return a callable that yields other players at the table when invoked."""
        def get_table_context():
            game = self.games.get(game_id)
            if game is None:
                return []
            result = []
            for p in game.players + game.players_waiting:
                if p.name == npc_name:
                    continue
                archetype = getattr(getattr(p, 'personality', None), 'name', None)
                fame = None
                if not getattr(p, 'is_npc', False) and self.db is not None:
                    try:
                        player_stats = self.db.get_player_stats(p.name)
                        if player_stats:
                            fame = _fame_label(player_stats['games_played'])
                    except Exception:
                        pass
                result.append({'name': p.name, 'archetype': archetype, 'fame': fame})
            return result
        return get_table_context

    def _load_npc_limits(self):
        """Load npc_autofill_min/max from settings, clamping to valid range."""
        if self.db is None:
            return
        try:
            raw_min = self.db.get_setting('npc_autofill_min')
            raw_max = self.db.get_setting('npc_autofill_max')
            npc_min = int(raw_min) if raw_min is not None else DEFAULT_NPC_AUTOFILL_MIN
            npc_max = int(raw_max) if raw_max is not None else DEFAULT_NPC_AUTOFILL_MAX
            npc_min = max(0, min(npc_min, MAX_NPCS_PER_TABLE))
            npc_max = max(0, min(npc_max, MAX_NPCS_PER_TABLE))
            if npc_min > npc_max:
                npc_min = npc_max
            self.npc_min = npc_min
            self.npc_max = npc_max
            logging.info(f"NPC autofill limits loaded: min={npc_min}, max={npc_max}")
        except Exception as e:
            logging.warning(f"Failed to load NPC limits from settings: {e}")

    def _ensure_npc_roster(self):
        """Fill the NPC roster up to MIN_NPC_ROSTER if it's below that threshold."""
        if self.db is None:
            return
        current = self.db.count_npcs()
        if current >= MIN_NPC_ROSTER:
            return
        to_create = MIN_NPC_ROSTER - current
        for _ in range(to_create):
            personality = get_random_personality()
            name = self._generate_npc_name()
            self.db.create_npc(name, personality.name, personality.starting_wallet_cents)
        logging.info(f"NPC roster: created {to_create} NPCs (roster was {current})")

    def _get_or_create_npcs(self, n, exclude_personalities):
        """Return n NPC records for a game, creating new ones if the roster is thin."""
        if self.db is None:
            # No DB: return ephemeral placeholder dicts
            result = []
            excl = set(exclude_personalities)
            for _ in range(n):
                personality = get_random_personality(exclude_names=excl)
                excl.add(personality.name)
                result.append({
                    'id': None,
                    'name': personality.name,
                    'personality_name': personality.name,
                    'backstory': '',
                    'wallet_cents': personality.starting_wallet_cents,
                })
            return result

        available = self.db.get_available_npcs(n, exclude_personality_names=exclude_personalities)

        # Create more if still not enough
        while len(available) < n:
            cur_excl = set(exclude_personalities) | {r['personality_name'] for r in available}
            personality = get_random_personality(exclude_names=cur_excl)
            name = self._generate_npc_name()
            npc_id = self.db.create_npc(name, personality.name, personality.starting_wallet_cents)
            backstory = self._generate_backstory(npc_id, personality, name)
            available.append({
                'id': npc_id,
                'name': name,
                'personality_name': personality.name,
                'backstory': backstory,
                'wallet_cents': personality.starting_wallet_cents,
            })

        return available[:n]

    def _load_games_from_db(self):
        """Load all active games from database on startup."""
        if self.db is None:
            return

        try:
            game_data_list = self.db.load_all_active_games()
            for game_data in game_data_list:
                game_id = game_data['game_id']
                game = Blackjack.from_dict(game_data, self, on_npc_departed=self._on_npc_departed)
                self.games[game_id] = game
                logging.info(f"Restored game {game_id} in state {game.state.value}")
        except Exception as e:
            logging.error(f"Error loading games from database: {e}")

        # Clear current_game_id for NPCs in games that no longer exist
        try:
            self.db.clear_stale_npc_games(set(self.games.keys()))
        except Exception as e:
            logging.error(f"Error clearing stale NPC games: {e}")

        # Ensure the NPC roster is populated
        try:
            self._ensure_npc_roster()
        except Exception as e:
            logging.error(f"Error ensuring NPC roster: {e}")

        # Load persisted NPC autofill limits
        self._load_npc_limits()

    def _on_npc_departed(self, game, player):
        """Shared hook, fired by Blackjack.leave() whenever an NPC leaves a table —
        via a broke departure, remove_npc, autofill trim, or a normal leave alike."""
        npc_db_id = getattr(player, 'npc_db_id', None)
        if npc_db_id is not None and self.db is not None:
            try:
                self.db.clear_npc_game(npc_db_id)
            except Exception as e:
                logging.error(f"Error clearing NPC game for {player.name}: {e}")

    def _mark_dirty(self, game_id):
        """Mark a game as needing a DB write on the next flush."""
        self._dirty_games.add(game_id)

    def _flush_dirty_games(self):
        """Write all dirty games to DB and clear the dirty set."""
        if self.db is None or not self._dirty_games:
            return
        for game_id in list(self._dirty_games):
            self._save_game(game_id)
        self._dirty_games.clear()

    def _save_game(self, game_id):
        """Save a game's current state to database."""
        if self.db is None:
            return

        game = self.games.get(game_id)
        if game is None:
            return

        try:
            game_data = game.to_dict()
            self.db.save_game(game_id, game_data)
        except Exception as e:
            logging.error(f"Error saving game {game_id}: {e}")

    def _delete_game(self, game_id):
        """Delete a game from database."""
        self._dirty_games.discard(game_id)  # no point writing then deleting
        self._last_autofill.pop(game_id, None)

        game = self.games.get(game_id)
        if game is not None:
            for player in game.players + game.players_waiting + game.departed_players:
                if isinstance(player, LLMBlackjackNPC):
                    player.shutdown()
                npc_db_id = getattr(player, 'npc_db_id', None)
                if npc_db_id is not None and self.db is not None:
                    try:
                        self.db.clear_npc_game(npc_db_id)
                    except Exception as e:
                        logging.error(f"Error clearing NPC game for {player.name}: {e}")

        if self.db is None:
            return

        try:
            self.db.delete_game(game_id)
            self.db.delete_game_channel(game_id)
        except Exception as e:
            logging.error(f"Error deleting game {game_id}: {e}")

    def new_game(self, guild_id=None, channel_id=None, num_bots=0, initial_deck=None):
        while True:
            game_id = str(uuid.uuid4())
            if game_id not in self.games.keys():
                break
        self.games[game_id] = Blackjack(
            game_id, self, initial_deck=initial_deck, on_npc_departed=self._on_npc_departed
        )
        logging.info(f"New game {game_id[:8]} created (bots: {num_bots})")

        if num_bots > 0:
            self._pending_bots[game_id] = num_bots

        # Save game and channel info to database
        self._save_game(game_id)
        if guild_id is not None and channel_id is not None and self.db is not None:
            try:
                self.db.save_game_channel(game_id, guild_id, channel_id)
            except Exception as e:
                logging.error(f"Error saving game channel {game_id}: {e}")

        return game_id

    def _spawn_npcs_into_game(self, game_id, count, exclude_personalities=None):
        """Spawn `count` roster NPCs into a game.

        Draws from the persistent NPC roster (via `_get_or_create_npcs`), builds
        the appropriate NPC objects, assigns them to the game in the DB, and calls
        `game.join`. Caller is responsible for marking the game dirty.
        """
        game = self.games.get(game_id)
        if game is None or count <= 0:
            return

        llm_client = self.llm_client
        all_players = game.players + game.players_waiting
        used_names = {p.name for p in all_players}
        used_personalities: set[str] = {
            getattr(p, 'personality', None).name
            for p in all_players
            if getattr(p, 'personality', None) is not None
        }
        if exclude_personalities:
            used_personalities |= set(exclude_personalities)

        npc_records = self._get_or_create_npcs(count, used_personalities)
        arrivals = []

        for npc_record in npc_records:
            used_personalities.add(npc_record['personality_name'])
            name = npc_record['name']
            if name in used_names:
                i = 2
                while f"{name} #{i}" in used_names:
                    i += 1
                name = f"{name} #{i}"
            used_names.add(name)

            npc_db_id = npc_record.get('id')
            backstory = npc_record.get('backstory', '')

            if npc_db_id is not None and self.db is not None:
                try:
                    self.db.set_npc_game(npc_db_id, game_id)
                except Exception as e:
                    logging.error(f"Error setting NPC game for {name}: {e}")

            try:
                personality = get_personality(npc_record['personality_name'])
            except ValueError:
                personality = get_random_personality(exclude_names=used_personalities)

            if llm_client is not None:
                table_ctx = self._make_table_context_fn(game_id, name)
                npc = LLMBlackjackNPC(
                    name, personality, llm_client,
                    npc_db_id=npc_db_id, backstory=backstory,
                    saloon_name=SALOON_NAME, saloon_town=SALOON_TOWN,
                    detail_level=SALOON_DETAIL_LEVEL,
                    table_context_fn=table_ctx,
                    usage_callback=self._log_usage,
                )
            else:
                npc = SimpleBlackjackNPC(name, npc_db_id=npc_db_id, backstory=backstory)
            game.join(npc, announce=False)
            arrivals.append(f"{personality.emoji} {name}")

        if arrivals:
            if game.state == HandState.BETTING:
                game.output(f"🎭 New arrivals: {', '.join(arrivals)}. They're in for this round!")
            else:
                game.output(f"🎭 New arrivals: {', '.join(arrivals)}. They'll join the next hand.")

    def _add_pending_bots(self, game_id):
        """Add any pending bots to the game when the first human player joins."""
        num_bots = self._pending_bots.pop(game_id, 0)
        if num_bots <= 0:
            return
        if game_id not in self.games:
            return
        self._spawn_npcs_into_game(game_id, num_bots)

    def _autofill_npcs(self, game_id, game):
        """Fill or trim NPCs in a game to stay within npc_min/npc_max.

        Only acts in WAITING or BETWEEN_HANDS states; throttled to at most once
        per AUTOFILL_INTERVAL seconds per game.
        """
        if game.state not in (HandState.WAITING, HandState.BETWEEN_HANDS):
            return

        now = time.time()
        if now - self._last_autofill.get(game_id, 0) < AUTOFILL_INTERVAL:
            return
        self._last_autofill[game_id] = now

        all_players = game.players + game.players_waiting
        npc_count = sum(1 for p in all_players if getattr(p, 'is_npc', False))
        total_count = len(all_players)

        changed = False

        if npc_count < self.npc_min:
            to_add = min(self.npc_min - npc_count, MAX_NPCS_PER_TABLE - total_count)
            if to_add > 0:
                logging.info(f"[{game_id[:8]}] Autofill: adding {to_add} NPC(s) "
                             f"(have {npc_count}, min={self.npc_min})")
                self._spawn_npcs_into_game(game_id, to_add)
                changed = True

        elif npc_count > self.npc_max:
            to_remove = npc_count - self.npc_max
            # Prefer removing from players_waiting before players
            candidates = (
                [p for p in game.players_waiting if getattr(p, 'is_npc', False)]
                + [p for p in game.players if getattr(p, 'is_npc', False)]
            )
            for npc in candidates[:to_remove]:
                logging.info(f"[{game_id[:8]}] Autofill: removing NPC {npc.name!r} "
                             f"(have {npc_count}, max={self.npc_max})")
                game.leave(npc)
                changed = True

        if changed:
            self._mark_dirty(game_id)

    def _handle_npc_limits(self, request_id, min_val=None, max_val=None):
        """Handle an npc_limits request: view or update autofill min/max."""
        ok = True
        message = ''

        if min_val is not None or max_val is not None:
            new_min = self.npc_min if min_val is None else min_val
            new_max = self.npc_max if max_val is None else max_val

            # Clamp to valid range
            new_min = max(0, min(int(new_min), MAX_NPCS_PER_TABLE))
            new_max = max(0, min(int(new_max), MAX_NPCS_PER_TABLE))
            if new_min > new_max:
                ok = False
                message = f"min ({new_min}) cannot exceed max ({new_max})."
            else:
                self.npc_min = new_min
                self.npc_max = new_max
                if self.db is not None:
                    try:
                        self.db.set_setting('npc_autofill_min', str(new_min))
                        self.db.set_setting('npc_autofill_max', str(new_max))
                    except Exception as e:
                        logging.error(f"Error persisting NPC limits: {e}")
                        ok = False
                        message = "Limits updated in memory but failed to persist to DB."
                if ok:
                    message = f"NPC limits set: min={new_min}, max={new_max}."
                    logging.info(message)

        self.publish_event(
            'casino_update',
            {
                'event_type': 'npc_limits',
                'request_id': request_id,
                'min': self.npc_min,
                'max': self.npc_max,
                'ok': ok,
                'message': message,
            }
        )

    def _handle_list_games(self, request_id):
        """Handle a list_games request from the bot."""
        games_info = []

        # Get channel info from database
        channel_map = {}
        if self.db is not None:
            try:
                channels = self.db.load_game_channels()
                channel_map = {c['game_id']: c for c in channels}
            except Exception as e:
                logging.error(f"Error loading game channels: {e}")

        for game_id, game in self.games.items():
            game_info = {
                'game_id': game_id,
                'state': game.state.value,
            }
            if game_id in channel_map:
                game_info['guild_id'] = channel_map[game_id]['guild_id']
                game_info['channel_id'] = channel_map[game_id]['channel_id']
            games_info.append(game_info)

        self.publish_event(
            'casino_update',
            {
                'event_type': 'list_games',
                'request_id': request_id,
                'games': games_info
            }
        )
        logging.info(f"Responded to list_games with {len(games_info)} games")

    def _handle_get_usage(self, request_id):
        """Handle a get_usage request: query DB and publish 7-day summary."""
        rows = []
        if self.db is not None:
            try:
                rows = self.db.get_llm_usage_summary(days=7)
            except Exception as e:
                logging.error(f"Error getting LLM usage summary: {e}")

        self.publish_event(
            'casino_update',
            {
                'event_type': 'usage_stats',
                'request_id': request_id,
                'rows': [dict(r) for r in rows],
            }
        )

    def _handle_get_debug(self, request_id):
        """Gather full internal state and publish as debug_state response."""
        from .blackjack import serialize_hand

        games_debug = []
        for game_id, game in self.games.items():
            def player_info(p):
                return {
                    'name': p.name,
                    'is_npc': getattr(p, 'is_npc', False),
                    'npc_type': getattr(p, 'npc_type', None),
                    'personality': getattr(getattr(p, 'personality', None), 'name', None),
                    'hand': serialize_hand(p.hand),
                    'bet': game.bets.get(p.name, 0),
                }
            games_debug.append({
                'game_id': game_id,
                'state': game.state.value,
                'current_player_idx': game.current_player_idx,
                'pending_bots': self._pending_bots.get(game_id, 0),
                'dirty': game_id in self._dirty_games,
                'deck_remaining': len(game.deck),
                'discards': len(game.discards),
                'dealer_hand': serialize_hand(game.dealer.hand),
                'players': [player_info(p) for p in game.players],
                'players_waiting': [player_info(p) for p in game.players_waiting],
            })

        npcs = []
        if self.db is not None:
            try:
                from datetime import datetime

                def sanitize(row):
                    return {k: v.isoformat() if isinstance(v, datetime) else v
                            for k, v in row.items()}
                npcs = [sanitize(dict(r)) for r in self.db.get_all_npcs()]
            except Exception as e:
                logging.error(f"Error fetching NPC roster for debug: {e}")

        self.publish_event(
            'casino_update',
            {
                'event_type': 'debug_state',
                'request_id': request_id,
                'games': games_debug,
                'npcs': npcs,
                'dirty_games': list(self._dirty_games),
            }
        )

    def add_npc(self, game_id, count=1):
        """Add `count` roster NPCs to a game, respecting MAX_NPCS_PER_TABLE.

        Raises:
            CardGameError: If game_id is invalid.
        """
        if game_id not in self.games:
            raise CardGameError(f"Game {game_id} not found")

        game = self.games[game_id]
        total = len(game.players) + len(game.players_waiting)
        available = max(0, MAX_NPCS_PER_TABLE - total)
        to_add = min(count, available)
        if to_add <= 0:
            return
        self._spawn_npcs_into_game(game_id, to_add)
        self._dirty_games.add(game_id)

    def remove_npc(self, game_id, npc_name=None):
        """Remove an NPC from a game.

        If npc_name is None, removes one NPC preferring players_waiting.
        Raises:
            CardGameError: If game_id is invalid or no matching NPC found.
        """
        if game_id not in self.games:
            raise CardGameError(f"Game {game_id} not found")

        game = self.games[game_id]
        npc = None
        if npc_name is None:
            # Prefer waiting players so we don't disrupt an active hand
            for player in game.players_waiting + game.players:
                if player.is_npc:
                    npc = player
                    break
            if npc is None:
                raise CardGameError("No NPC found in game")
        else:
            for player in game.players + game.players_waiting:
                if player.name == npc_name and player.is_npc:
                    npc = player
                    break
            if npc is None:
                raise CardGameError(f"NPC '{npc_name}' not found in game")

        game.leave(npc)
        self._dirty_games.add(game_id)

    def publish_event(self, event_type, data):
        logging.debug(f"Publishing event {event_type}: {data}")
        self.redis.publish(event_type, json.dumps(data))

    def game_output(self, game_id, output):
        self.publish_event(
            f"game_updates_{game_id}",
            {'game_id': game_id, 'text': output}
        )

    EMPTY_GAME_TIMEOUT = 600  # seconds before an idle empty game is removed

    def _process_message(self, data):
        game_id = data.get('game_id')

        if game_id is None:
            logging.debug(f"Got casino message: {data}")
            if data['event_type'] == 'casino_action':
                if data['action'] == 'new_game':
                    request_id = data.get('request_id')
                    if request_id:
                        guild_id = data.get('guild_id')
                        channel_id = data.get('channel_id')
                        num_bots = int(data.get('num_bots', 0))
                        deck_data = data.get('deck')
                        initial_deck = deserialize_hand(deck_data) if deck_data else None
                        game_id = self.new_game(guild_id, channel_id, num_bots=num_bots,
                                                initial_deck=initial_deck)
                        self.publish_event(
                            'casino_update',
                            {
                                'event_type': 'new_game',
                                'request_id': request_id,
                                'game_id': game_id
                            }
                        )
                elif data['action'] == 'list_games':
                    request_id = data.get('request_id')
                    if request_id:
                        self._handle_list_games(request_id)
                elif data['action'] == 'get_usage':
                    request_id = data.get('request_id')
                    if request_id:
                        self._handle_get_usage(request_id)
                elif data['action'] == 'get_debug':
                    request_id = data.get('request_id')
                    if request_id:
                        self._handle_get_debug(request_id)
                elif data['action'] == 'get_stats':
                    request_id = data.get('request_id')
                    player_name = data.get('player')
                    if request_id and player_name:
                        self._handle_get_stats(request_id, player_name)
                elif data['action'] == 'get_wallet':
                    request_id = data.get('request_id')
                    player_name = data.get('player')
                    if request_id and player_name:
                        self._handle_get_wallet(request_id, player_name)
                elif data['action'] == 'lookup_wallet':
                    request_id = data.get('request_id')
                    target = data.get('target')
                    if request_id and target:
                        self._handle_lookup_wallet(request_id, target)
                elif data['action'] == 'set_wallet':
                    request_id = data.get('request_id')
                    target = data.get('target')
                    mode = data.get('mode', 'set')
                    amount = data.get('amount', 0)
                    if request_id and target:
                        self._handle_set_wallet(request_id, target, mode, amount)
                elif data['action'] == 'npc_limits':
                    request_id = data.get('request_id')
                    if request_id:
                        self._handle_npc_limits(
                            request_id,
                            min_val=data.get('min'),
                            max_val=data.get('max'),
                        )
        elif game_id in self.games.keys():
            logging.debug(f"Got game message: {data}")
            try:
                if data['event_type'] == 'casino_action' and data.get('action') == 'stop_game':
                    logging.info(f"Stopping game {game_id} by admin request")
                    self._delete_game(game_id)
                    del self.games[game_id]
                    self.publish_event(
                        f"game_updates_{game_id}",
                        {'game_id': game_id, 'event_type': 'game_over'}
                    )
                    return
                if data['event_type'] == 'casino_action' and data.get('action') == 'quit_game':
                    logging.info(f"Quitting game {game_id} by request — returning unresolved bets")
                    game = self.games[game_id]
                    all_players = {p.name: p for p in game.players + game.departed_players}
                    refunded = []
                    for player_name, bet_amount in game.bets.items():
                        player = all_players.get(player_name)
                        if player is not None:
                            self.update_wallet(player, bet_amount)
                            refunded.append(f"{player_name} (${format_cents(bet_amount)})")
                            logging.info(
                                f"[{game_id[:8]}] Refunded ${format_cents(bet_amount)} to {player_name}"
                            )
                    if refunded:
                        game.output("🛑 Game called early! Returning bets: " + ", ".join(refunded))
                    else:
                        game.output("🛑 Game called early. No bets to return.")
                    self._delete_game(game_id)
                    del self.games[game_id]
                    self.publish_event(
                        f"game_updates_{game_id}",
                        {'game_id': game_id, 'event_type': 'game_over'}
                    )
                    return
                if data['event_type'] == 'player_action' and data.get('action') == 'join':
                    self._add_pending_bots(game_id)
                if data['event_type'] == 'npc_action':
                    action = data['action']
                    if action == 'add_npc':
                        count = int(data.get('count', 1))
                        self.add_npc(game_id, count)
                    elif action == 'remove_npc':
                        npc_name = data.get('npc_name')  # None = remove any NPC
                        self.remove_npc(game_id, npc_name)
                else:
                    self.games[game_id].action(data)
                    if (data['event_type'] == 'player_action'
                            and data.get('action') == 'join'
                            and self.db is not None):
                        player_name = data.get('player')
                        if player_name:
                            try:
                                self.db.increment_games_played(player_name)
                            except Exception as e:
                                logging.warning(f"Failed to increment games_played for {player_name}: {e}")
                self._mark_dirty(game_id)
            except CardGameError as e:
                logging.warning(f"Game error: {e}")
                self.game_output(game_id, e.user_message())
        else:
            logging.debug(f"Got unknown message: {data}")

    def _tick_games(self):
        for game_id, game in list(self.games.items()):
            try:
                game.tick()
            except CardGameError as e:
                logging.error(f"[{game_id[:8]}] Error ticking game, skipping this cycle: {e}")
                continue

            if game._dirty:
                self._mark_dirty(game_id)
                game._dirty = False

            self._autofill_npcs(game_id, game)

            # Remove idle empty games
            if (game.state == HandState.WAITING
                    and not game.players
                    and not game.players_waiting
                    and time.time() - game.time_last_event > self.EMPTY_GAME_TIMEOUT):
                logging.info(f"Removing idle empty game {game_id}")
                self._delete_game(game_id)
                del self.games[game_id]
                self.publish_event(
                    f"game_updates_{game_id}",
                    {'game_id': game_id, 'event_type': 'game_over'}
                )

        self._flush_dirty_games()

    def listen(self):
        db_loaded = False
        while True:
            pubsub = self.redis.pubsub()
            backoff = 1
            while True:
                try:
                    pubsub.subscribe("casino")
                    break
                except redis.exceptions.ConnectionError:
                    logging.info(f"Couldn't connect to redis; sleeping for {backoff} seconds...")
                    time.sleep(backoff)
                    backoff = min(backoff * 2, 60)

            if not db_loaded:
                db_loaded = True
                self._load_games_from_db()
                self.llm_client  # trigger key detection and log result at startup

            logging.info("Casino online.")

            try:
                while True:
                    message = pubsub.get_message(ignore_subscribe_messages=True,
                                                 timeout=2.0)
                    if message:
                        try:
                            data = json.loads(message['data'])
                        except json.JSONDecodeError as e:
                            logging.error(f"Failed to parse Redis message: {e}")
                            continue
                        self._process_message(data)

                    self._tick_games()
            except redis.exceptions.ConnectionError:
                logging.warning("Lost Redis connection; reconnecting...")
                try:
                    pubsub.close()
                except Exception:
                    pass
