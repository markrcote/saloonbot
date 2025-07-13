import asyncio
import json
import logging

import aioconsole
import redis.asyncio as redis

logging.basicConfig(level=logging.INFO)

rcli = redis.Redis()
player_name = None
quit = False

async def process_commands():
    global quit
    while not quit:
        line = await aioconsole.ainput("> ")
        if line:
            args = line.strip().split()
            cmd = args[0]
            if cmd == "quit":
                quit = True
            else:
                message = {
                    "player": player_name,
                    "event_type": "player_action",
                    "action": cmd
                }
                await rcli.publish("blackjack", json.dumps(message))

async def get_updates():
    global quit
    pubsub = rcli.pubsub()
    await pubsub.subscribe("game_updates_0")
    while not quit:
        message = await pubsub.get_message(ignore_subscribe_messages=True,
                                           timeout=2.0)
        if not message:
            continue
        data = json.loads(message['data'])
        print(data['text'])


async def main():
    global player_name
    player_name = input("Enter your name: ")
    print(f"Welcome {player_name}")

    async with asyncio.TaskGroup() as tg:
        cmd_task = tg.create_task(process_commands())
        update_task = tg.create_task(get_updates())


if __name__ == "__main__":
    asyncio.run(main())
