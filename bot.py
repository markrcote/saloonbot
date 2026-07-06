import json
import logging
import os
import subprocess
import sys
import uuid
from enum import Enum

import asyncio

import nextcord
import redis.asyncio
import redis.exceptions
from nextcord.ext import commands, tasks

from cardgames.money import dollars_to_cents, format_cents
from wwnames.wwnames import WildWestNames

_wwnames = WildWestNames()


def sanitize_username(name: str) -> str:
    return name[:32]


def read_env(env_var):
    value = os.environ.get(env_var)
    if value:
        return value
    file_path = os.environ.get(f"{env_var}_FILE") or f"/run/secrets/{env_var.lower()}"
    if os.path.isfile(file_path):
        with open(file_path) as f:
            return f.read().strip() or None
    return None


DEBUG_LOGGING = os.getenv("SALOONBOT_DEBUG")
if DEBUG_LOGGING:
    LOG_LEVEL = logging.DEBUG
else:
    LOG_LEVEL = logging.INFO

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))

SALOON_NAME = os.getenv("SALOON_NAME", "The Rusty Spur")
SALOON_TOWN = os.getenv("SALOON_TOWN", "Redemption, Texas")

logging.basicConfig(
    level=LOG_LEVEL,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

DISCORD_TOKEN = read_env("DISCORD_TOKEN")
GUILD_IDS_STR = read_env("DISCORD_GUILDS")

if not DISCORD_TOKEN:
    logging.error("No Discord token provided.")
    sys.exit(1)

GUILD_IDS = [int(x) for x in GUILD_IDS_STR.split(",")] if GUILD_IDS_STR else None

MESSAGE_PACING_DELAY = 1.2  # seconds between game messages sent to Discord

VERSION = None

try:
    with open('.version') as version_file:
        VERSION = version_file.readline().strip()
except FileNotFoundError:
    pass

if not VERSION:
    try:
        VERSION = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                                 text=True).stdout.strip()
    except FileNotFoundError:
        pass


logging.info("=== Bot Configuration ===")
logging.info(f"  Redis: {REDIS_HOST}:{REDIS_PORT}")
logging.info(f"  DISCORD_TOKEN: {'set' if DISCORD_TOKEN else 'not set'}")
logging.info(f"  DISCORD_GUILDS: {GUILD_IDS_STR or '(all guilds)'}")
logging.info(f"  Debug logging: {'enabled' if DEBUG_LOGGING else 'disabled'}")
logging.info(f"  Version: {VERSION or 'unknown'}")
logging.info("=========================")

intents = nextcord.Intents.default()
intents.message_content = True  # Enable message content

bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    logging.info("Howdy folks.")
    logging.debug("Debug logs enabled.")


@bot.slash_command(description="Version", guild_ids=GUILD_IDS)
async def version(interaction: nextcord.Interaction):
    if VERSION:
        response = VERSION
    else:
        response = "?"
    await interaction.send(response)


@bot.slash_command(description="Generate a name", guild_ids=GUILD_IDS)
async def wwname(interaction: nextcord.Interaction, gender: str = "",
                 number: int = 1):
    await interaction.send(f"🤠 {_wwnames.random_name(gender, number)}")


class GameState(Enum):
    """Explicit states for a blackjack game."""
    WAITING = "waiting"
    ACTIVE = "active"
    FINISHED = "finished"


class BlackjackGame:
    def __init__(self, guild_id, channel_id, channel, state=GameState.WAITING):
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.channel = channel
        self.state = state
        self.game_id = None
        self.request_id = None

    def generate_request_id(self):
        self.request_id = str(uuid.uuid4())

    def topic(self):
        return f"game_updates_{self.game_id}"


class BlackjackCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.redis = redis.asyncio.Redis(host=REDIS_HOST, port=REDIS_PORT)
        self.pubsub = self.redis.pubsub()
        self.games = []
        self.subscribed = asyncio.Event()
        self.subscribe_task = None
        self._list_games_request_id = None
        self._pending_usage_interactions = {}  # request_id -> interaction
        self._pending_stats_interactions = {}  # request_id -> interaction
        self._pending_debug_interactions = {}  # request_id -> interaction
        self._pending_wallet_interactions = {}  # request_id -> interaction
        self._pending_checkwallet_interactions = {}  # request_id -> interaction
        self._pending_setwallet_interactions = {}  # request_id -> interaction (set + adjust)
        self._pending_npclimits_interactions = {}  # request_id -> interaction

    def cog_unload(self):
        self.listen.stop()
        if self.subscribe_task:
            self.subscribe_task.cancel()

    @commands.Cog.listener()
    async def on_ready(self):
        if self.subscribe_task is None or self.subscribe_task.done():
            self.subscribe_task = asyncio.create_task(self.try_subscribe())
        if not self.listen.is_running():
            self.listen.start()

        # Request list of active games for recovery
        await self._request_list_games()

        logging.info("Blackjack cog initialized.")

    async def _request_list_games(self):
        """Request list of active games from server for recovery."""
        request_id = str(uuid.uuid4())
        self._list_games_request_id = request_id
        message = {
            'event_type': 'casino_action',
            'action': 'list_games',
            'request_id': request_id
        }
        try:
            await self.redis.publish("casino", json.dumps(message))
            logging.info("Requested list of active games for recovery")
        except redis.exceptions.ConnectionError as e:
            logging.error(f"Failed to request list of games: {e}")

    async def _handle_list_games_response(self, games_info):
        """Handle list_games response and restore game wrappers."""
        restored_count = 0
        for game_info in games_info:
            game_id = game_info.get('game_id')
            guild_id = game_info.get('guild_id')
            channel_id = game_info.get('channel_id')

            if not guild_id or not channel_id:
                logging.warning(f"Game {game_id} has no channel info, skipping")
                continue

            # Check if we already have this game
            existing = self.find_game(guild_id, channel_id)
            if existing:
                logging.debug(f"Game {game_id} already tracked, skipping")
                continue

            # Try to get the channel
            channel = self.bot.get_channel(channel_id)
            if not channel:
                logging.warning(f"Could not find channel {channel_id} for game {game_id}")
                continue

            # Create game wrapper
            game = BlackjackGame(guild_id, channel_id, channel, GameState.ACTIVE)
            game.game_id = game_id
            self.games.append(game)

            # Subscribe to game topic
            try:
                await self.pubsub.subscribe(game.topic())
                restored_count += 1
                logging.info(f"Restored game {game_id} in channel {channel_id}")

                # Announce reconnection
                await channel.send("🔄 Bot reconnected. Game in progress.")
            except Exception as e:
                logging.error(f"Failed to subscribe to game {game_id} topic: {e}")

        if restored_count > 0:
            logging.info(f"Restored {restored_count} active games")
        else:
            logging.info("No active games to restore")

    async def _handle_usage_stats_response(self, interaction, rows):
        """Format and send LLM usage stats as an ephemeral followup."""
        if not rows:
            await interaction.followup.send("No LLM usage recorded in the past 7 days.", ephemeral=True)
            return

        lines = []
        total_in = total_out = 0
        for r in rows:
            in_tok = r.get('total_input', 0) or 0
            out_tok = r.get('total_output', 0) or 0
            total_in += in_tok
            total_out += out_tok
            lines.append(
                f"**{r['purpose']}** ({r['model']}) — "
                f"{r.get('call_count', 0)} calls, "
                f"{in_tok:,} in / {out_tok:,} out tokens"
            )

        lines.append(f"\n**Total:** {total_in:,} input / {total_out:,} output tokens")
        embed = nextcord.Embed(
            title="LLM Usage (past 7 days)",
            description="\n".join(lines),
            color=0x4169e1,
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @commands.Cog.listener()
    async def on_message(self, message: nextcord.Message):
        if message.author == self.bot.user:
            return
        if not message.guild:
            return

        game = self.find_game(message.guild.id, message.channel.id)
        if not game:
            return

        parts = message.content.split()
        command = parts[0]
        if len(command) > 20:
            return

        # Handle bet command with amount
        if command == "bet" and len(parts) > 1:
            try:
                amount = int(parts[1])
                if amount <= 0:
                    await message.channel.send("⚠️ Bet amount must be positive.")
                    return
                await self.send_command(
                    sanitize_username(message.author.name), game, command,
                    amount=dollars_to_cents(amount)
                )
            except ValueError:
                await message.channel.send("⚠️ Invalid bet amount. Usage: bet <amount>")
        else:
            await self.send_command(sanitize_username(message.author.name), game, command)

    @nextcord.slash_command(name="saloon", guild_ids=GUILD_IDS,
                            description="Show info about the saloon")
    async def saloon_info(self, interaction: nextcord.Interaction):
        active_games = [g for g in self.games if g.state == GameState.ACTIVE]
        if active_games:
            table_lines = []
            for g in active_games:
                channel_mention = f"<#{g.channel_id}>"
                table_lines.append(f"• {channel_mention}")
            tables_str = "\n".join(table_lines)
        else:
            tables_str = "No games in progress."
        embed = nextcord.Embed(
            title=f"🤠 {SALOON_NAME}",
            description=f"*{SALOON_TOWN}*",
            color=0xc8a96e,
        )
        embed.add_field(name="Active Tables", value=tables_str, inline=False)
        await interaction.send(embed=embed)

    @nextcord.slash_command(name="usage", guild_ids=GUILD_IDS,
                            description="Show LLM usage stats for the past 7 days (admin only)",
                            default_member_permissions=nextcord.Permissions(administrator=True))
    async def usage_stats(self, interaction: nextcord.Interaction):
        await interaction.response.defer(ephemeral=True)
        request_id = str(uuid.uuid4())
        self._pending_usage_interactions[request_id] = interaction
        message = {
            'event_type': 'casino_action',
            'action': 'get_usage',
            'request_id': request_id,
        }
        try:
            await self.redis.publish("casino", json.dumps(message))
        except Exception as e:
            logging.error(f"Redis publish error for get_usage: {e}")
            self._pending_usage_interactions.pop(request_id, None)
            await interaction.followup.send("❌ Could not reach game server.", ephemeral=True)

    @nextcord.slash_command(name="debug", guild_ids=GUILD_IDS,
                            description="Show full internal state for debugging (admin only)",
                            default_member_permissions=nextcord.Permissions(administrator=True))
    async def debug_state(self, interaction: nextcord.Interaction):
        await interaction.response.defer(ephemeral=True)
        request_id = str(uuid.uuid4())
        self._pending_debug_interactions[request_id] = interaction
        message = {
            'event_type': 'casino_action',
            'action': 'get_debug',
            'request_id': request_id,
        }
        try:
            await self.redis.publish("casino", json.dumps(message))
        except Exception as e:
            logging.error(f"Redis publish error for get_debug: {e}")
            self._pending_debug_interactions.pop(request_id, None)
            await interaction.followup.send("❌ Could not reach game server.", ephemeral=True)

    async def _handle_debug_response(self, interaction, data):
        """Format and send full debug state as ephemeral embeds."""
        embeds = []

        # --- Bot-side state ---
        bot_lines = []
        for g in self.games:
            bot_lines.append(
                f"`{g.game_id or '(pending)'}` ch=<#{g.channel_id}> state={g.state.value}"
            )
        embeds.append(nextcord.Embed(
            title="Bot game tracking",
            description="\n".join(bot_lines) if bot_lines else "No games tracked",
            color=0x888888,
        ))

        # --- Games ---
        for g in data.get('games', []):
            gid = g['game_id']
            dirty = " [dirty]" if g.get('dirty') else ""
            desc_lines = [
                f"State: **{g['state']}**{dirty} | "
                f"Deck: {g['deck_remaining']} remaining, {g['discards']} discarded | "
                f"Current player idx: {g['current_player_idx']}",
                f"Dealer: {' '.join(g['dealer_hand']) or '—'}",
            ]
            if g.get('pending_bots'):
                desc_lines.append(f"Pending bots to add: {g['pending_bots']}")
            for p in g['players']:
                npc_tag = f" ({p['npc_type']}/{p['personality']})" if p['is_npc'] else ""
                hand_str = ' '.join(p['hand']) if p['hand'] else '—'
                desc_lines.append(f"**{p['name']}**{npc_tag} | {hand_str} | Bet: ${format_cents(p['bet_cents'])}")
            if g.get('players_waiting'):
                waiting = ', '.join(p['name'] for p in g['players_waiting'])
                desc_lines.append(f"Waiting: {waiting}")
            embeds.append(nextcord.Embed(
                title=f"Game {gid[:8]}",
                description="\n".join(desc_lines),
                color=0xc8a96e,
            ))

        if not data.get('games'):
            embeds.append(nextcord.Embed(title="Games", description="No active games", color=0xc8a96e))

        # --- NPC Roster ---
        npc_lines = []
        for npc in data.get('npcs', []):
            status = f"in game `{str(npc['current_game_id'])[:8]}`" if npc.get('current_game_id') else "idle"
            npc_lines.append(
                f"**{npc['name']}** ({npc['personality_name']}) | ${format_cents(npc['wallet_cents'])} | {status}"
            )
        embeds.append(nextcord.Embed(
            title="NPC Roster",
            description="\n".join(npc_lines) if npc_lines else "No NPCs in roster",
            color=0x4169e1,
        ))

        await interaction.followup.send(embeds=embeds, ephemeral=True)

    async def _handle_stats_response(self, interaction, player_name, stats):
        """Format and send player stats as an ephemeral followup."""
        if stats is None:
            await interaction.followup.send(
                "No record found. Join a game and play some hands first!", ephemeral=True
            )
            return

        games_played = stats.get('games_played', 0)
        fame = stats.get('fame', 'unknown stranger')
        lines = [
            f"**Fame:** {fame}",
            f"**Games joined:** {games_played}",
            f"**Hands played:** {stats.get('hands_played', 0)}",
            f"**Total won:** ${format_cents(stats.get('total_won_cents', 0))}",
            f"**Total lost:** ${format_cents(stats.get('total_lost_cents', 0))}",
            f"**Biggest win:** ${format_cents(stats.get('biggest_win_cents', 0))}",
        ]
        embed = nextcord.Embed(
            title=f"🌟 {player_name}'s Saloon Record",
            description="\n".join(lines),
            color=0xc8a96e,
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    async def _handle_wallet_info_response(self, interaction, data):
        """Format and send wallet info as an ephemeral followup."""
        target = data.get('target', '?')
        kind = data.get('kind')
        balance = data.get('balance_cents')

        if kind is None:
            await interaction.followup.send(
                f"⚠️ No player or NPC named **{target}** found.", ephemeral=True
            )
            return

        kind_label = "Player" if kind == 'player' else "NPC"
        await interaction.followup.send(
            f"💰 **{target}** ({kind_label}): **${format_cents(balance)}**", ephemeral=True
        )

    async def _handle_wallet_set_response(self, interaction, data):
        """Format and send wallet set/adjust result as an ephemeral followup."""
        ok = data.get('ok', False)
        msg = data.get('message', 'Unknown error')
        if ok:
            await interaction.followup.send(f"✅ {msg}", ephemeral=True)
        else:
            await interaction.followup.send(f"❌ {msg}", ephemeral=True)

    @nextcord.slash_command(name="checkwallet", guild_ids=GUILD_IDS,
                            description="Check any player's or NPC's wallet (admin only)",
                            default_member_permissions=nextcord.Permissions(administrator=True))
    async def check_wallet(self, interaction: nextcord.Interaction, target: str):
        await interaction.response.defer(ephemeral=True)
        request_id = str(uuid.uuid4())
        self._pending_checkwallet_interactions[request_id] = interaction
        message = {
            'event_type': 'casino_action',
            'action': 'lookup_wallet',
            'request_id': request_id,
            'target': target,
        }
        try:
            await self.redis.publish("casino", json.dumps(message))
        except Exception as e:
            logging.error(f"Redis publish error for lookup_wallet: {e}")
            self._pending_checkwallet_interactions.pop(request_id, None)
            await interaction.followup.send("❌ Could not reach game server.", ephemeral=True)

    @nextcord.slash_command(name="setwallet", guild_ids=GUILD_IDS,
                            description="Set any player's or NPC's wallet to an exact amount (admin only)",
                            default_member_permissions=nextcord.Permissions(administrator=True))
    async def set_wallet(self, interaction: nextcord.Interaction, target: str, amount: int):
        """amount is entered in dollars; converted to cents before publishing."""
        await interaction.response.defer(ephemeral=True)
        request_id = str(uuid.uuid4())
        self._pending_setwallet_interactions[request_id] = interaction
        message = {
            'event_type': 'casino_action',
            'action': 'set_wallet',
            'request_id': request_id,
            'target': target,
            'mode': 'set',
            'amount': dollars_to_cents(amount),
        }
        try:
            await self.redis.publish("casino", json.dumps(message))
        except Exception as e:
            logging.error(f"Redis publish error for set_wallet: {e}")
            self._pending_setwallet_interactions.pop(request_id, None)
            await interaction.followup.send("❌ Could not reach game server.", ephemeral=True)

    @nextcord.slash_command(name="givechips", guild_ids=GUILD_IDS,
                            description="Adjust any player's or NPC's wallet by a delta (admin only)",
                            default_member_permissions=nextcord.Permissions(administrator=True))
    async def give_chips(self, interaction: nextcord.Interaction, target: str, amount: int):
        """Positive amount adds chips; negative takes them away. amount is in dollars."""
        await interaction.response.defer(ephemeral=True)
        request_id = str(uuid.uuid4())
        self._pending_setwallet_interactions[request_id] = interaction
        message = {
            'event_type': 'casino_action',
            'action': 'set_wallet',
            'request_id': request_id,
            'target': target,
            'mode': 'adjust',
            'amount': dollars_to_cents(amount),
        }
        try:
            await self.redis.publish("casino", json.dumps(message))
        except Exception as e:
            logging.error(f"Redis publish error for givechips: {e}")
            self._pending_setwallet_interactions.pop(request_id, None)
            await interaction.followup.send("❌ Could not reach game server.", ephemeral=True)

    @nextcord.slash_command(name="stats", guild_ids=GUILD_IDS,
                            description="View your stats at the saloon")
    async def player_stats(self, interaction: nextcord.Interaction):
        await interaction.response.defer(ephemeral=True)
        player_name = sanitize_username(interaction.user.name)
        request_id = str(uuid.uuid4())
        self._pending_stats_interactions[request_id] = interaction
        message = {
            'event_type': 'casino_action',
            'action': 'get_stats',
            'request_id': request_id,
            'player': player_name,
        }
        try:
            await self.redis.publish("casino", json.dumps(message))
        except Exception as e:
            logging.error(f"Redis publish error for get_stats: {e}")
            self._pending_stats_interactions.pop(request_id, None)
            await interaction.followup.send("❌ Could not reach game server.", ephemeral=True)

    @nextcord.slash_command(name="wad", guild_ids=GUILD_IDS,
                            description="Check your current wad (only you can see this)")
    async def check_wad(self, interaction: nextcord.Interaction):
        await interaction.response.defer(ephemeral=True)
        player_name = sanitize_username(interaction.user.name)
        request_id = str(uuid.uuid4())
        self._pending_wallet_interactions[request_id] = interaction
        message = {
            'event_type': 'casino_action',
            'action': 'get_wallet',
            'request_id': request_id,
            'player': player_name,
        }
        try:
            await self.redis.publish("casino", json.dumps(message))
        except Exception as e:
            logging.error(f"Redis publish error for get_wallet: {e}")
            self._pending_wallet_interactions.pop(request_id, None)
            await interaction.followup.send("❌ Could not reach game server.", ephemeral=True)

    async def _handle_npc_limits_response(self, interaction, data):
        """Format and send NPC limits response as an ephemeral followup."""
        ok = data.get('ok', True)
        npc_min = data.get('min', 0)
        npc_max = data.get('max', 4)
        msg = data.get('message', '')
        if ok:
            lines = [f"**NPC autofill:** min={npc_min}, max={npc_max}"]
            if msg:
                lines.append(msg)
            await interaction.followup.send("\n".join(lines), ephemeral=True)
        else:
            await interaction.followup.send(f"❌ {msg}", ephemeral=True)

    @nextcord.slash_command(name="npclimits", guild_ids=GUILD_IDS,
                            description="View or set NPC autofill min/max per table (admin only)",
                            default_member_permissions=nextcord.Permissions(administrator=True))
    async def npc_limits(
        self,
        interaction: nextcord.Interaction,
        min: int = nextcord.SlashOption(
            name="min",
            description="Minimum NPCs to keep at each table (0 = no auto-fill)",
            required=False,
            default=None,
            min_value=0,
            max_value=6,
        ),
        max: int = nextcord.SlashOption(
            name="max",
            description="Maximum NPCs allowed at each table",
            required=False,
            default=None,
            min_value=0,
            max_value=6,
        ),
    ):
        """View current NPC autofill limits (no args) or set new ones."""
        await interaction.response.defer(ephemeral=True)
        request_id = str(uuid.uuid4())
        self._pending_npclimits_interactions[request_id] = interaction
        message = {
            'event_type': 'casino_action',
            'action': 'npc_limits',
            'request_id': request_id,
        }
        if min is not None:
            message['min'] = min
        if max is not None:
            message['max'] = max
        try:
            await self.redis.publish("casino", json.dumps(message))
        except Exception as e:
            logging.error(f"Redis publish error for npc_limits: {e}")
            self._pending_npclimits_interactions.pop(request_id, None)
            await interaction.followup.send("❌ Could not reach game server.", ephemeral=True)

    @nextcord.slash_command(name="addnpc", guild_ids=GUILD_IDS,
                            description="Add NPC(s) to the current game (admin only)",
                            default_member_permissions=nextcord.Permissions(administrator=True))
    async def add_npc(
        self,
        interaction: nextcord.Interaction,
        count: int = nextcord.SlashOption(
            name="count",
            description="Number of NPCs to add (default: 1)",
            required=False,
            default=1,
            min_value=1,
            max_value=6,
        ),
    ):
        """Add one or more roster NPCs to the current channel's game."""
        game = self.find_game_by_interaction(interaction)
        if not game:
            await interaction.send("⚠️ No game currently in progress.", ephemeral=True)
            return

        message = {
            "event_type": "npc_action",
            "action": "add_npc",
            "game_id": game.game_id,
            "count": count,
        }
        try:
            await self.redis.publish("casino", json.dumps(message))
        except Exception as e:
            logging.error(f"Redis publish error for addnpc: {e}")
            await interaction.send("❌ Could not reach game server.", ephemeral=True)
            return

        await interaction.send(f"🤠 Adding {count} NPC(s) to the game.", ephemeral=True)

    @nextcord.slash_command(name="removenpc", guild_ids=GUILD_IDS,
                            description="Remove an NPC from the current game (admin only)",
                            default_member_permissions=nextcord.Permissions(administrator=True))
    async def remove_npc(
        self,
        interaction: nextcord.Interaction,
        name: str = nextcord.SlashOption(
            name="name",
            description="NPC name to remove (omit to remove any NPC)",
            required=False,
            default=None,
        ),
    ):
        """Remove an NPC from the current channel's game (by name or any)."""
        game = self.find_game_by_interaction(interaction)
        if not game:
            await interaction.send("⚠️ No game currently in progress.", ephemeral=True)
            return

        message = {
            "event_type": "npc_action",
            "action": "remove_npc",
            "game_id": game.game_id,
        }
        if name is not None:
            message["npc_name"] = name
        try:
            await self.redis.publish("casino", json.dumps(message))
        except Exception as e:
            logging.error(f"Redis publish error for removenpc: {e}")
            await interaction.send("❌ Could not reach game server.", ephemeral=True)
            return

        target = f"**{name}**" if name else "an NPC"
        await interaction.send(f"🤠 Removing {target} from the game.", ephemeral=True)

    @nextcord.slash_command(name="help", guild_ids=GUILD_IDS,
                            description="Show all available commands")
    async def show_help(self, interaction: nextcord.Interaction):
        player_cmds = (
            "`/joingame` — Join the blackjack game in this channel\n"
            "`/leavegame` — Leave the current game\n"
            "`/bet <amount>` — Place a bet during the betting phase\n"
            "`/hit` — Take another card\n"
            "`/stand` — End your turn and hold your hand\n"
            "(`join`, `leave`, `bet`, `hit`, `stand` also work typed directly in chat)\n"
            "`/wad` — Check your own wallet balance (private)\n"
            "`/stats` — View your stats and fame level\n"
            "`/saloon` — Show saloon info and active tables\n"
            "`/wwname` — Generate a random Old West name"
        )
        admin_cmds = (
            "`/newgame [num_bots]` — Start a new blackjack game (0–4 bots)\n"
            "`/stopgame` — Stop the current game (bets not returned)\n"
            "`/quitgame` — End the game and refund all bets\n"
            "`/checkwallet <target>` — Check any player's or NPC's balance\n"
            "`/setwallet <target> <amount>` — Set a wallet to an exact amount\n"
            "`/givechips <target> <amount>` — Adjust a wallet by a delta\n"
            "`/npclimits [min] [max]` — View or set NPC autofill limits per table\n"
            "`/addnpc [count]` — Add NPC(s) to the current game\n"
            "`/removenpc [name]` — Remove an NPC from the current game\n"
            "`/usage` — LLM token usage for the past 7 days\n"
            "`/debug` — Full internal state dump"
        )
        embed = nextcord.Embed(
            title=f"🤠 {SALOON_NAME} — Commands",
            color=0xc8a96e,
        )
        embed.add_field(name="Player commands", value=player_cmds, inline=False)
        embed.add_field(name="Admin only", value=admin_cmds, inline=False)
        await interaction.send(embed=embed, ephemeral=True)

    @nextcord.slash_command(name="newgame", guild_ids=GUILD_IDS,
                            default_member_permissions=nextcord.Permissions(administrator=True))
    async def new_game(
        self,
        interaction: nextcord.Interaction,
        num_bots: int = nextcord.SlashOption(
            name="num_bots",
            description="How many bot players to add (0–4)",
            required=False,
            default=0,
            min_value=0,
            max_value=4,
        ),
    ):
        """Start a game if none in progress in this guild and channel."""
        game = self.find_game_by_interaction(interaction)
        if game:
            await interaction.send("⚠️ A game is already in progress in this channel.")
            return

        game = BlackjackGame(interaction.guild_id, interaction.channel_id, interaction.channel)
        game.generate_request_id()
        self.games.append(game)

        message = {
            'event_type': 'casino_action',
            'action': 'new_game',
            'request_id': game.request_id,
            'guild_id': game.guild_id,
            'channel_id': game.channel_id,
            'num_bots': num_bots,
        }
        try:
            await self.redis.publish("casino", json.dumps(message))
            await interaction.send("🎲 Starting new game...")
        except redis.exceptions.ConnectionError as e:
            logging.error(f"Redis publish error: {e}")
            await interaction.send("❌ Failed to communicate with game server.")

    @nextcord.slash_command(name="joingame", guild_ids=GUILD_IDS)
    async def join_game(self, interaction: nextcord.Interaction):
        game = self.find_game_by_interaction(interaction)
        if game:
            if game.state != GameState.ACTIVE:
                await interaction.send("⚠️ Game is not active.")
            else:
                await self.send_command(sanitize_username(interaction.user.name), game, "join")
                await interaction.send("🎰 Joining game...")
        else:
            await interaction.send("⚠️ No game currently in progress.")

    @nextcord.slash_command(name="leavegame", guild_ids=GUILD_IDS)
    async def leave_game(self, interaction: nextcord.Interaction):
        game = self.find_game_by_interaction(interaction)
        if not game:
            await interaction.send("⚠️ No game currently in progress.")
            return

        await self.send_command(sanitize_username(interaction.user.name), game, "leave")
        await interaction.send("👋 Leaving game...")

    @nextcord.slash_command(name="stopgame", guild_ids=GUILD_IDS,
                            default_member_permissions=nextcord.Permissions(administrator=True))
    async def stop_game(self, interaction: nextcord.Interaction):
        """Stop the current game (admins only)."""
        game = self.find_game_by_interaction(interaction)
        if not game:
            await interaction.send("⚠️ No game currently in progress.", ephemeral=True)
            return

        message = {
            "event_type": "casino_action",
            "action": "stop_game",
            "game_id": game.game_id,
        }
        try:
            await self.redis.publish("casino", json.dumps(message))
        except Exception as e:
            logging.error(f"Redis publish error: {e}")
            await interaction.send("⚠️ Failed to stop game.", ephemeral=True)
            return

        await interaction.send("🛑 Game stopped by admin.")

    @nextcord.slash_command(name="quitgame", guild_ids=GUILD_IDS,
                            default_member_permissions=nextcord.Permissions(administrator=True))
    async def quit_game(self, interaction: nextcord.Interaction):
        """Terminate the current game and return all unresolved bets (admins only)."""
        game = self.find_game_by_interaction(interaction)
        if not game:
            await interaction.send("⚠️ No game currently in progress.", ephemeral=True)
            return

        message = {
            "event_type": "casino_action",
            "action": "quit_game",
            "game_id": game.game_id,
        }
        try:
            await self.redis.publish("casino", json.dumps(message))
        except Exception as e:
            logging.error(f"Redis publish error: {e}")
            await interaction.send("⚠️ Failed to quit game.", ephemeral=True)
            return

        await interaction.send("🛑 Game terminated, bets returned.")

    @nextcord.slash_command(name="bet", guild_ids=GUILD_IDS)
    async def place_bet(self, interaction: nextcord.Interaction, amount: int):
        """Place a bet in the current game. amount is entered in dollars."""
        game = self.find_game_by_interaction(interaction)
        if not game:
            await interaction.send("⚠️ No game currently in progress.")
            return

        if game.state != GameState.ACTIVE:
            await interaction.send("⚠️ Game is not active.")
            return

        await self.send_command(
            sanitize_username(interaction.user.name), game, "bet", amount=dollars_to_cents(amount)
        )
        await interaction.send(f"💵 Placing bet of ${amount}...")

    @nextcord.slash_command(name="hit", guild_ids=GUILD_IDS)
    async def hit(self, interaction: nextcord.Interaction):
        """Take another card."""
        game = self.find_game_by_interaction(interaction)
        if not game:
            await interaction.send("⚠️ No game currently in progress.")
            return

        if game.state != GameState.ACTIVE:
            await interaction.send("⚠️ Game is not active.")
            return

        await self.send_command(sanitize_username(interaction.user.name), game, "hit")
        await interaction.send("🃏 Hitting...")

    @nextcord.slash_command(name="stand", guild_ids=GUILD_IDS)
    async def stand(self, interaction: nextcord.Interaction):
        """End your turn and hold your hand."""
        game = self.find_game_by_interaction(interaction)
        if not game:
            await interaction.send("⚠️ No game currently in progress.")
            return

        if game.state != GameState.ACTIVE:
            await interaction.send("⚠️ Game is not active.")
            return

        await self.send_command(sanitize_username(interaction.user.name), game, "stand")
        await interaction.send("✋ Standing...")

    @tasks.loop(seconds=0.5)
    async def listen(self):
        '''Background tasks that listens for messages on self.pubsub.'''
        # Wait until subscription is live
        await self.subscribed.wait()
        try:
            message = await self.pubsub.get_message(ignore_subscribe_messages=True, timeout=0)
            if message:
                await self.process_message(message)
            # drain messages
            while True:
                message = await self.pubsub.get_message(ignore_subscribe_messages=True, timeout=0)
                if not message:
                    break
                await self.process_message(message)
        except Exception as e:
            logging.error(f"Redis pubsub error: {e}")
            self.subscribed.clear()
            # Start a background resubscribe loop
            if self.subscribe_task is None or self.subscribe_task.done():
                self.subscribe_task = asyncio.create_task(self.try_subscribe())

    async def process_message(self, message):
        logging.debug(f"Got message: {message}")

        data = json.loads(message['data'])
        topic = message['channel'].decode()

        if topic == "casino_update":
            if data.get("event_type") == "new_game":
                game = self.find_game_by_request_id(data.get("request_id"))
                if game:
                    if game.state != GameState.WAITING:
                        logging.error(f"Got new-game message for game in state {game.state}")
                        return
                    game.state = GameState.ACTIVE
                    game.game_id = data.get("game_id")

                    # Use embed for game creation
                    embed = nextcord.Embed(
                        title="🎲 New Blackjack Game",
                        description=f"Game {game.game_id} created.\n⏳ Waiting for players.",
                        color=0x00ff00  # Green
                    )
                    await game.channel.send(embed=embed)
                    logging.debug(f"Game created: {game.game_id}")
                    try:
                        await self.pubsub.subscribe(game.topic())
                    except Exception as e:
                        logging.error(f"Failed to subscribe to game topic: {e}")

            elif data.get("event_type") == "list_games":
                request_id = data.get("request_id")
                if hasattr(self, '_list_games_request_id') and \
                   request_id == self._list_games_request_id:
                    await self._handle_list_games_response(data.get("games", []))

            elif data.get("event_type") == "usage_stats":
                request_id = data.get("request_id")
                interaction = self._pending_usage_interactions.pop(request_id, None)
                if interaction:
                    await self._handle_usage_stats_response(interaction, data.get("rows", []))

            elif data.get("event_type") == "debug_state":
                request_id = data.get("request_id")
                interaction = self._pending_debug_interactions.pop(request_id, None)
                if interaction:
                    await self._handle_debug_response(interaction, data)

            elif data.get("event_type") == "player_stats":
                request_id = data.get("request_id")
                interaction = self._pending_stats_interactions.pop(request_id, None)
                if interaction:
                    await self._handle_stats_response(
                        interaction, data.get("player", ""), data.get("stats")
                    )
            elif data.get("event_type") == "player_wallet":
                request_id = data.get("request_id")
                interaction = self._pending_wallet_interactions.pop(request_id, None)
                if interaction:
                    balance = data.get("balance_cents")
                    if balance is None:
                        await interaction.followup.send(
                            "No record found. Join a game and place a bet first!", ephemeral=True
                        )
                    else:
                        await interaction.followup.send(
                            f"💰 Your wad: **${format_cents(balance)}**", ephemeral=True
                        )
            elif data.get("event_type") == "wallet_info":
                request_id = data.get("request_id")
                interaction = self._pending_checkwallet_interactions.pop(request_id, None)
                if interaction:
                    await self._handle_wallet_info_response(interaction, data)
            elif data.get("event_type") == "wallet_set":
                request_id = data.get("request_id")
                interaction = self._pending_setwallet_interactions.pop(request_id, None)
                if interaction:
                    await self._handle_wallet_set_response(interaction, data)
            elif data.get("event_type") == "npc_limits":
                request_id = data.get("request_id")
                interaction = self._pending_npclimits_interactions.pop(request_id, None)
                if interaction:
                    await self._handle_npc_limits_response(interaction, data)
        else:
            for game in self.games:
                if game.topic() == topic:
                    logging.debug("Got game message")

                    if data.get('event_type') == 'game_over':
                        game.state = GameState.FINISHED
                        self.games.remove(game)
                        try:
                            await self.pubsub.unsubscribe(game.topic())
                        except Exception as e:
                            logging.error(f"Failed to unsubscribe from game topic: {e}")
                        logging.info(f"Game {game.game_id} ended, removed from tracking")
                        break

                    text = data["text"]

                    # Use embeds for special messages
                    if text.startswith("🤠") and ': "' in text:
                        msg_type = "npc_quip"
                        embed = nextcord.Embed(description=text, color=0xc8a96e)  # Sepia
                        await game.channel.send(embed=embed)
                    elif "🏆 strikes gold" in text:
                        msg_type = "win"
                        embed = nextcord.Embed(description=text, color=0xffd700)  # Gold
                        await game.channel.send(embed=embed)
                    elif "💥" in text and ("bust" in text.lower() or "lost" in text.lower()):
                        msg_type = "bust"
                        embed = nextcord.Embed(description=text, color=0xff0000)  # Red
                        await game.channel.send(embed=embed)
                    elif "✨ ~*~ The dust settles" in text:
                        msg_type = "hand_result"
                        logging.debug(f"[{game.game_id[:8]}] Dramatic pause: 1.0s (hand_result)")
                        async with game.channel.typing():
                            await asyncio.sleep(1.0)
                        embed = nextcord.Embed(description=text, color=0x4169e1)  # Royal blue
                        await game.channel.send(embed=embed)
                    elif "🃏 The dealer shuffles" in text:
                        msg_type = "new_hand"
                        embed = nextcord.Embed(description=text, color=0x9370db)  # Medium purple
                        await game.channel.send(embed=embed)
                    elif "💰 Ante up" in text:
                        msg_type = "bet_prompt"
                        embed = nextcord.Embed(description=text, color=0xff8c00)  # Dark orange
                        await game.channel.send(embed=embed)
                    elif "🔄 Dealer flips" in text:
                        msg_type = "dealer_reveal"
                        logging.debug(f"[{game.game_id[:8]}] Dramatic pause: 1.5s (dealer_reveal)")
                        async with game.channel.typing():
                            await asyncio.sleep(1.5)
                        await game.channel.send(text)
                    else:
                        msg_type = "game_event"
                        await game.channel.send(text)

                    logging.info(f"[{game.game_id[:8]}] → Discord: {msg_type} | {text[:70]!r}")
                    logging.debug(f"[{game.game_id[:8]}] Pacing: {MESSAGE_PACING_DELAY:.1f}s")
                    await asyncio.sleep(MESSAGE_PACING_DELAY)
                    break
            else:
                logging.debug(f"Got unknown message from channel {message['channel']}: {message}")

    async def send_command(self, player_name, game, cmd, **kwargs):
        extra = f" ${format_cents(kwargs['amount'])}" if 'amount' in kwargs else ""
        logging.info(f"[{game.game_id[:8]}] Player {player_name!r}: {cmd}{extra}")
        message = {
            "player": player_name,
            "event_type": "player_action",
            "game_id": game.game_id,
            "action": cmd
        }
        message.update(kwargs)
        try:
            await self.redis.publish("casino", json.dumps(message))
        except Exception as e:
            logging.error(f"Redis publish error: {e}")
            if game.channel:
                await game.channel.send("❌ Command failed — could not reach game server. Please try again.")

    async def try_subscribe(self):
        backoff = 2
        while True:
            try:
                await self.pubsub.subscribe("casino_update")
                for game in self.games:
                    if game.game_id:
                        await self.pubsub.subscribe(game.topic())
                self.subscribed.set()
                logging.info("Subscribed to casino_update.")
                return
            except redis.exceptions.ConnectionError as e:
                self.subscribed.clear()
                logging.warning(f"Failed to subscribe to casino_update: {e}")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)  # Exponential backoff up to 60s

    def find_game(self, guild_id, channel_id):
        for game in self.games:
            if (game.guild_id == guild_id and game.channel_id == channel_id
                    and game.state != GameState.FINISHED):
                return game
        return None

    def find_game_by_interaction(self, interaction):
        return self.find_game(interaction.guild_id, interaction.channel_id)

    def find_game_by_request_id(self, request_id):
        for game in self.games:
            if game.request_id == request_id:
                return game
        return None


bot.add_cog(BlackjackCog(bot))
bot.run(DISCORD_TOKEN)
