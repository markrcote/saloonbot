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

from wwnames.wwnames import WildWestNames


def read_env_file(env_var):
    filename = os.getenv(env_var)
    if not filename:
        return None
    if not os.path.isfile(filename):
        return None
    return open(filename).read().strip()


DEBUG_LOGGING = os.getenv("SALOONBOT_DEBUG")
if DEBUG_LOGGING:
    LOG_LEVEL = logging.DEBUG
else:
    LOG_LEVEL = logging.INFO

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = os.getenv("REDIS_PORT", 6379)

logging.basicConfig(
    level=LOG_LEVEL,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN") or read_env_file("DISCORD_TOKEN_FILE")
GUILD_IDS_STR = os.getenv("DISCORD_GUILDS") or read_env_file("DISCORD_GUILDS_FILE")

if not DISCORD_TOKEN:
    logging.error("No Discord token provided.")
    sys.exit(1)

GUILD_IDS = [int(x) for x in GUILD_IDS_STR.split(",")] if GUILD_IDS_STR else None

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
    names = WildWestNames()
    await interaction.send(names.random_name(gender, number))


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
        logging.info("Blackjack cog initialized.")

    @commands.Cog.listener()
    async def on_message(self, message: nextcord.Message):
        if message.author == self.bot.user:
            return

        game = self.find_game(message.guild.id, message.channel.id)
        if not game:
            return

        parts = message.content.split()
        command = parts[0]

        # Handle bet command with amount
        if command == "bet" and len(parts) > 1:
            try:
                amount = int(parts[1])
                await self.send_command(message.author.name, game, command, amount=amount)
            except ValueError:
                await message.channel.send("Invalid bet amount. Usage: bet <amount>")
        else:
            await self.send_command(message.author.name, game, command)

    @nextcord.slash_command(name="newgame", guild_ids=GUILD_IDS)
    async def new_game(self, interaction: nextcord.Interaction):
        """Start a game if none in progress in this guild and channel."""
        game = self.find_game_by_interaction(interaction)
        if game:
            await interaction.send("A game is already in progress in this channel.")
            return

        game = BlackjackGame(interaction.guild_id, interaction.channel_id, interaction.channel)
        game.generate_request_id()
        self.games.append(game)

        message = {
            'event_type': 'casino_action',
            'action': 'new_game',
            'request_id': game.request_id
        }
        try:
            await self.redis.publish("casino", json.dumps(message))
            await interaction.send("Starting new game...")
        except redis.exceptions.ConnectionError as e:
            logging.error(f"Redis publish error: {e}")
            await interaction.send("Failed to communicate with game server.")

    @nextcord.slash_command(name="joingame", guild_ids=GUILD_IDS)
    async def join_game(self, interaction: nextcord.Interaction):
        game = self.find_game_by_interaction(interaction)
        if game:
            if game.state != GameState.ACTIVE:
                await interaction.send("Game is not active.")
            else:
                await self.send_command(interaction.user.name, game, "join")
                await interaction.send("Joining game...")
        else:
            await interaction.send("No game currently in progress.")

    @nextcord.slash_command(name="leavegame", guild_ids=GUILD_IDS)
    async def leave_game(self, interaction: nextcord.Interaction):
        game = self.find_game_by_interaction(interaction)
        if not game:
            await interaction.send("No game currently in progress.")
            return

        await self.send_command(interaction.user.name, game, "leave")
        await interaction.send("Leaving game...")

    @nextcord.slash_command(name="bet", guild_ids=GUILD_IDS)
    async def place_bet(self, interaction: nextcord.Interaction, amount: int):
        """Place a bet in the current game."""
        game = self.find_game_by_interaction(interaction)
        if not game:
            await interaction.send("No game currently in progress.")
            return

        if game.state != GameState.ACTIVE:
            await interaction.send("Game is not active.")
            return

        await self.send_command(interaction.user.name, game, "bet", amount=amount)
        await interaction.send(f"Placing bet of ${amount}...")

    @tasks.loop(seconds=3.0)
    async def listen(self):
        '''Background tasks that listens for messages on self.pubsub.'''
        # Wait until subscription is live
        await self.subscribed.wait()
        try:
            message = await self.pubsub.get_message(ignore_subscribe_messages=True, timeout=3.0)
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
                    await game.channel.send(f"Game {game.game_id} created.")
                    await game.channel.send("Waiting for players.")
                    logging.debug(f"Game created: {game.game_id}")
                    try:
                        await self.pubsub.subscribe(game.topic())
                    except Exception as e:
                        logging.error(f"Failed to subscribe to game topic: {e}")
        else:
            for game in self.games:
                if game.topic() == topic:
                    logging.debug("Got game message")
                    await game.channel.send(data["text"])
            else:
                logging.debug(f"Got unknown message from channel {message['channel']}: {message}")

    async def send_command(self, player_name, game, cmd, **kwargs):
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

    async def try_subscribe(self):
        backoff = 2
        while True:
            try:
                await self.pubsub.subscribe("casino_update")
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
            if game.guild_id == guild_id and game.channel_id == channel_id:
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
