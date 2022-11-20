import os

import nextcord
from nextcord.ext import commands

from wwnames import WildWestNames

TESTING_GUILD_ID = 770741674740678666

bot = commands.Bot()

@bot.event
async def on_ready():
    print(f'Howdy folks.')

@bot.slash_command(description='Generate a name', guild_ids=[TESTING_GUILD_ID])
async def wwname(interaction: nextcord.Interaction, gender: str=''):
    names = WildWestNames()
    await interaction.send(names.random_name(gender))

bot.run(os.getenv('DISCORD_TOKEN'))
