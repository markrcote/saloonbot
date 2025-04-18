import logging
import os
import subprocess

import nextcord
from nextcord.ext import commands, tasks

from cardgames.blackjack import Blackjack
from wwnames.wwnames import WildWestNames

DEBUG_LOGGING = os.getenv("SALOONBOT_DEBUG")
if DEBUG_LOGGING:
    LOG_LEVEL = logging.DEBUG
else:
    LOG_LEVEL = logging.INFO

logging.basicConfig(level=LOG_LEVEL)

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
        self.game = None
        self.game_channel = None
        self.tick.start()

    def cog_unload(self):
        self.tick.stop()

    @commands.Cog.listener()
    async def on_ready(self):
        logging.info("Blackjack cog initialized.")

    @commands.Cog.listener()
    async def on_message(self, message: nextcord.Message):
        if message.author == self.bot.user:
            return

        if not self.game:
            return

        player = None
        for p in self.game.players:
            if p.name == message.author.name:
                player = p
                break

        if player is None:
            return

        if self.game.current_player_idx is None or self.game.players[self.game.current_player_idx] != player:
            return

        if message.content.startswith('hit'):
            await self.game.hit(player)
        elif message.content.startswith('stand'):
            await self.game.stand(player)

    @nextcord.slash_command(name="newgame", guild_ids=GUILD_IDS)
    async def new_game(self, interaction: nextcord.Interaction):
        """Start a game if none in progress"""
        if self.game:
            await interaction.send("A game is already in progress.")
            return

        self.game_channel = interaction.channel
        self.game = Blackjack()
        self.game.output_func_is_async = True
        self.game.output_func = self.game_channel.send
        await interaction.send("New game started.")

    @nextcord.slash_command(name="sitdown", guild_ids=GUILD_IDS)
    async def sit_down(self, interaction: nextcord.Interaction):
        if not self.game:
            await interaction.send("No game currently in progress.")
            return

        player_name = interaction.user.name
        self.game.sit_down(self.game.get_player(player_name, add=True))
        await interaction.send(f"{player_name} will join the next hand.")

    @nextcord.slash_command(name="status", guild_ids=GUILD_IDS)
    async def status(self, interaction: nextcord.Interaction):
        """Arguably this is better in the Blackjack class."""
        status_str = ""
        if self.game:
            status_str = "A game is in progress."
            if self.game.hand_in_progress():
                # It will never be the dealer's turn, since that is handled
                # synchronously entirely in one tick() call.
                status_str += f" It is {self.game.players[self.game.current_player_idx]}'s turn."
            else:
                status_str += " Waiting for the next hand to begin."
        else:
            status_str = "There is no game in progress."
        await interaction.send(status_str)

    @tasks.loop(seconds=3.0)
    async def tick(self):
        if self.game:
            await self.game.tick()


bot.add_cog(BlackjackCog(bot))
bot.run(DISCORD_TOKEN)
