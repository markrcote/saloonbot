import os


import nextcord
from nextcord.ext import commands

from wwnames import WildWestNames

bot = commands.Bot()


@bot.event
async def on_ready():
    print('Howdy folks.')


@bot.slash_command(description='Generate a name')
async def wwname(interaction: nextcord.Interaction, gender: str = '', number: int = 1):
    names = WildWestNames()
    await interaction.send(names.random_name(gender, number))

bot.run(os.getenv('DISCORD_TOKEN'))
