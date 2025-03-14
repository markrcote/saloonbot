import logging
import os
import subprocess

import nextcord
from nextcord.ext import commands, tasks

from cardgames.blackjack import Blackjack
from wwnames.wwnames import WildWestNames

debug_logging = os.getenv("WWNAMES_DEBUG")
if debug_logging:
    log_level = logging.DEBUG
else:
    log_level = logging.INFO

logging.basicConfig(level=log_level)

guild_ids_env = os.getenv("DISCORD_GUILDS")
guild_ids = [int(x) for x in guild_ids_env.split(",")] if guild_ids_env else None

bot = commands.Bot()
git_sha = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                         text=True).stdout.strip()

game = None


def determine_player_name(interaction, player):
    if player == "":
        player = interaction.user.name
    return player


@bot.event
async def on_ready():
    logging.info("Howdy folks.")


@bot.slash_command(description="Version", guild_ids=guild_ids)
async def wwname_version(interaction: nextcord.Interaction):
    await interaction.send(git_sha)


@bot.slash_command(description="Generate a name", guild_ids=guild_ids)
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

    @nextcord.slash_command(name="new_game", guild_ids=guild_ids)
    async def new_game(self, interaction: nextcord.Interaction):
        """Start a game if none in progress"""
        if self.game:
            await interaction.send("A game is already in progress.")
            return

        self.game_channel = interaction.channel
        self.game = Blackjack()
        self.game.output_func = self.game_channel.send
        await interaction.send("New game started.")

    @nextcord.slash_command(name="status", guild_ids=guild_ids)
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
bot.run(os.getenv("DISCORD_TOKEN"))
