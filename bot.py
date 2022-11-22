import os

import nextcord
from nextcord.ext import commands

from wwnames import WildWestNames

bot = commands.Bot()

@bot.event
async def on_ready():
    print(f'Howdy folks.')

@bot.slash_command(description='Generate a name')
async def wwname(interaction: nextcord.Interaction, gender: str=''):
    names = WildWestNames()
    await interaction.send(names.random_name(gender))

bot.run(os.getenv('DISCORD_TOKEN'))
