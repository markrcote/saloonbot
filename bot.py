import os
import subprocess


import nextcord
from nextcord.ext import commands

from card_game import Card, CardGame, PlayerNotFoundError
from wwnames import WildWestNames

bot = commands.Bot()
git_sha = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                         text=True).stdout.strip()
card_game = CardGame()


def determine_player_name(interaction, player):
    if player == '':
        player = interaction.user.name
    return player


@bot.event
async def on_ready():
    print('Howdy folks.')


@bot.slash_command(description='Version')
async def wwname_version(interaction: nextcord.Interaction):
    await interaction.send(git_sha)


@bot.slash_command(description='Generate a name')
async def wwname(interaction: nextcord.Interaction, gender: str = '',
                 number: int = 1):
    names = WildWestNames()
    await interaction.send(names.random_name(gender, number))


@bot.slash_command(description='Deal one or more cards to a player')
async def deal_hand(interaction: nextcord.Interaction, number: int = 1,
                    player: str = ''):
    player = determine_player_name(interaction, player)
    card_game.deal(card_game.get_player(player, add=True), number)
    await interaction.send(f'{player} was dealt {number} cards.')


@bot.slash_command(description='Deal one or more cards to all players')
async def deal_all(interaction: nextcord.Interaction, number: int = 1):
    if not card_game.players:
        await interaction.send('No players to deal to.')
        return
    for player in card_game.players:
        card_game.deal(player, number)
    await interaction.send(f'All players were dealt {number} cards.')


@bot.slash_command(description='Discard a card from a player')
async def discard(interaction: nextcord.Interaction, card_value: str,
                  card_suit: str, player: str = ''):
    player = determine_player_name(interaction, player)
    card = Card(card_suit, int(card_value))
    try:
        card_game.discard(card_game.get_player(player), card)
    except PlayerNotFoundError as e:
        await interaction.send(e)
        return
    await interaction.send(f'{player} discarded {card}.')


@bot.slash_command(description='Discard all cards from a player')
async def discard_all(interaction: nextcord.Interaction, player: str = ''):
    player = determine_player_name(interaction, player)
    try:
        card_game.discard_all(card_game.get_player(player))
    except PlayerNotFoundError as e:
        await interaction.send(e)
        return
    await interaction.send(f'{player} discarded all their cards.')


@bot.slash_command(description='Shuffle the deck')
async def shuffle_deck(interaction: nextcord.Interaction):
    card_game.shuffle()
    await interaction.send('The deck was shuffled.')


@bot.slash_command(description='Show a player\'s hand')
async def show_hand(interaction: nextcord.Interaction, player: str = '',
                    short: bool = False):
    player = determine_player_name(interaction, player)
    hand = card_game.get_player(player, add=True).hand
    hand_str = ', '.join(card.str(short) for card
                         in hand) if hand else '<empty>'
    await interaction.send(f'{player}\'s hand: {hand_str}')


bot.run(os.getenv('DISCORD_TOKEN'))
