import asyncio
import json
import logging
import uuid

import aioconsole
import redis.asyncio as redis

logging.basicConfig(level=logging.INFO)


class CasinoCli:
    def __init__(self):
        self.redis = redis.Redis()
        self.pubsub = self.redis.pubsub()
        self.player_name = None
        self.game_id = None
        self.quit = False

    async def process_commands(self):
        while not self.quit:
            line = await aioconsole.ainput("> ")
            if line:
                args = line.strip().split()
                cmd = args[0]
                if cmd == "quit":
                    self.quit = True
                else:
                    message = {
                        "player": self.player_name,
                        "event_type": "player_action",
                        "game_id" : self.game_id,
                        "action": cmd
                    }
                    await self.redis.publish("casino", json.dumps(message))

    async def get_updates(self):
        topic = f"game_updates_{self.game_id}"
        await self.pubsub.subscribe(topic)
        while not self.quit:
            message = await self.pubsub.get_message(ignore_subscribe_messages=True,
                                                    timeout=2.0)
            if not message:
                continue
            data = json.loads(message['data'])
            print(data['text'])

    async def main(self):
        self.player_name = input("Enter your name: ")
        print(f"Welcome {self.player_name}")
        print("Creating new game...")

        request_id = str(uuid.uuid4())
        await self.pubsub.subscribe("casino_update")
        message = {
            'event_type': 'casino_action',
            'action': 'new_game',
            'request_id': request_id
        }
        await self.redis.publish("casino", json.dumps(message))

        while self.game_id is None:
            message = await self.pubsub.get_message(ignore_subscribe_messages=True,
                                                    timeout=3.0)
            if not message:
                print("Still waiting...")
                continue

            data = json.loads(message['data'])
            if data.get('event_type') == 'new_game' and data.get('request_id') == request_id:
                self.game_id = data.get('game_id')

        print(f"Game created: {self.game_id}")

        async with asyncio.TaskGroup() as tg:
            cmd_task = tg.create_task(self.process_commands())
            update_task = tg.create_task(self.get_updates())


if __name__ == "__main__":
    cli = CasinoCli()
    asyncio.run(cli.main())
