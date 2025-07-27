import json
import logging
import os
import subprocess
import uuid

import nextcord
import redis.asyncio as redis
from nextcord.ext import commands, tasks

from cardgames import aws
from wwnames.wwnames import WildWestNames


DEBUG_LOGGING = os.getenv("SALOONBOT_DEBUG")
if DEBUG_LOGGING:
    LOG_LEVEL = logging.DEBUG
else:
    LOG_LEVEL = logging.INFO

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = os.getenv("REDIS_PORT", 6379)

logging.basicConfig(level=LOG_LEVEL)

if aws.is_ec2_instance():
    secret = json.loads(aws.get_secret())
    DISCORD_TOKEN = secret["DISCORD_TOKEN"]
    GUILD_IDS_ENV = secret["DISCORD_GUILDS"]
else:
    # This will intentionally cause the bot to fail fast with a KeyError exception
    # if the token is not found.
    DISCORD_TOKEN = os.environ["DISCORD_TOKEN"]
    GUILD_IDS_ENV = os.getenv("DISCORD_GUILDS")

GUILD_IDS = [int(x) for x in GUILD_IDS_ENV.split(",")] if GUILD_IDS_ENV else None

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


class BlackjackCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.redis = redis.Redis(host=REDIS_HOST, port=REDIS_PORT)
        self.pubsub = self.redis.pubsub()
        self.game_request_id = None
        self.game_id = None
        self.game_channel = None

    def cog_unload(self):
        self.listen.stop()

    def game_topic(self):
        return f"game_updates_{self.game_id}"

    async def send_command(self, player_name, cmd):
        message = {
            "player": player_name,
            "event_type": "player_action",
            "game_id" : self.game_id,
            "action": cmd
        }
        await self.redis.publish("casino", json.dumps(message))

    @commands.Cog.listener()
    async def on_ready(self):
        await self.pubsub.subscribe("casino_update")
        self.listen.start()
        logging.info("Blackjack cog initialized.")

    @commands.Cog.listener()
    async def on_message(self, message: nextcord.Message):
        if message.author == self.bot.user:
            return

        if not self.game_id:
            return

        command = message.content.split()[0]
        await self.send_command(message.author.name, command)

    @nextcord.slash_command(name="newgame", guild_ids=GUILD_IDS)
    async def new_game(self, interaction: nextcord.Interaction):
        """Start a game if none in progress"""
        if self.game_id:
            await interaction.send("A game is already in progress.")
            return

        self.game_request_id = str(uuid.uuid4())
        self.game_channel = interaction.channel

        message = {
            'event_type': 'casino_action',
            'action': 'new_game',
            'request_id': self.game_request_id
        }
        await self.redis.publish("casino", json.dumps(message))
        await interaction.send("Starting new game...")

    @nextcord.slash_command(name="joingame", guild_ids=GUILD_IDS)
    async def join_game(self, interaction: nextcord.Interaction):
        if not self.game_id:
            await interaction.send("No game currently in progress.")
            return

        await self.send_command(interaction.user.name, "join")
        await interaction.send("Joining game...")

    @nextcord.slash_command(name="leavegame", guild_ids=GUILD_IDS)
    async def leave_game(self, interaction: nextcord.Interaction):
        if not self.game_id:
            await interaction.send("No game currently in progress.")
            return

        await self.send_command(interaction.user.name, "leave")
        await interaction.send("Leaving game...")

    @tasks.loop(seconds=3.0)
    async def listen(self):
        message = await self.pubsub.get_message(ignore_subscribe_messages=True,
                                                timeout=3.0)

        if not message:
            return

        await self.process_message(message)

        # drain messages
        while True:
            message = await self.pubsub.get_message(ignore_subscribe_messages=True,
                                                    timeout=0)
            if not message:
                break
            await self.process_message(message)

    async def process_message(self, message):
        logging.debug(f"Got message: {message}")

        data = json.loads(message['data'])
        topic = message['channel'].decode()

        if topic == "casino_update":
            if data.get('event_type') == 'new_game' and self.game_id is None and data.get('request_id') == self.game_request_id:
                self.game_id = data.get('game_id')
                await self.game_channel.send(f"Game created.")
                logging.debug(f"Game created: {self.game_id}")
                await self.pubsub.subscribe(self.game_topic())
        elif topic == self.game_topic():
            logging.debug("Got game message")
            await self.game_channel.send(data["text"])
        else:
            logging.debug(f"Got unknown message from channel {message['channel']}")
            logging.debug(f"Game topic is {self.game_topic()}")


bot.add_cog(BlackjackCog(bot))
bot.run(DISCORD_TOKEN)
