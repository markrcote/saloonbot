import logging
import os
import subprocess

import nextcord
from nextcord.ext import commands

from cardgames.blackjack import Blackjack
from wwnames.wwnames import WildWestNames

logging.basicConfig(level=logging.INFO)

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

    @commands.Cog.listener()
    async def on_ready(self):
        logging.info("Blackjack cog initialized.")

    @nextcord.slash_command(name="new_game", guild_ids=guild_ids)
    async def new_game(self, interaction: nextcord.Interaction):
        """Start a game if none in progress"""
        if self.game:
            await interaction.send("A game is already in progress.")
            return

        self.game = Blackjack()
        await interaction.send("New game started.")


bot.add_cog(BlackjackCog(bot))
bot.run(os.getenv("DISCORD_TOKEN"))
