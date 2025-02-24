import asyncio
import logging

import aioconsole

from cardgames.card_game import Player
from cardgames.blackjack import Blackjack

logging.basicConfig(level=logging.INFO)

game = Blackjack()
game.output_func = print


async def get_command(prompt):
    line = await aioconsole.ainput('> ' if prompt else '')
    if line:
        args = line.strip().split()
        return (args[0], args[1:])
    return (None, [])


async def process_command(player, cmd, args):
    output = []

    if cmd == 'quit':
        raise KeyboardInterrupt
    elif cmd == 'help':
        output.extend([
            'Commands:',
            '  quit',
            '  help',
            '  hit',
            '  stand',
            '  bet <amount>',
            '  split',
            '  double',
            '  insurance',
            '  surrender',
        ])
    elif cmd == 'standup':
        await game.stand_up(player)
    elif cmd == 'sitdown':
        await game.sit_down(player)
    elif cmd == 'hit':
        await game.hit(player)
    elif cmd == 'stand':
        await game.stand(player)
    elif cmd.startswith('bet'):
        try:
            amount = int(args[0])
        except ValueError:
            output.append('Invalid bet amount')
        else:
            game.bet(amount)
    elif cmd == 'split':
        game.split(player)
    elif cmd == 'double':
        game.double(player)
    elif cmd == 'insurance':
        game.insurance(player)
    elif cmd == 'surrender':
        game.surrender(player)
    else:
        output.append('Unknown command')
    return output


async def main():
    await game.tick()

    player_name = input('Enter your name: ')
    player = Player(player_name)
    print(f'Welcome {player.name}')

    quit = False
    timed_out = False

    while not quit:
        cmd = None
        args = []

        try:
            cmd, args = await asyncio.wait_for(get_command(prompt=not timed_out), timeout=1)
            timed_out = False
        except asyncio.TimeoutError:
            timed_out = True

        await game.tick()

        if cmd:
            if cmd == 'quit':
                quit = True
            else:
                await process_command(player, cmd, args)


if __name__ == "__main__":
    asyncio.run(main())
