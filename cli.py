import asyncio
import json
import logging
import os
import uuid

import aioconsole
import redis.asyncio as redis

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = os.getenv("REDIS_PORT", 6379)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)


class CasinoCli:
    def __init__(self):
        self.redis = redis.Redis(host=REDIS_HOST, port=REDIS_PORT)
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
                elif cmd == "addbot":
                    bot_name = args[1] if len(args) > 1 else None
                    bot_type = args[2] if len(args) > 2 else "simple"
                    message = {
                        "event_type": "bot_action",
                        "game_id": self.game_id,
                        "action": "add_bot",
                        "bot_type": bot_type,
                    }
                    if bot_name:
                        message["bot_name"] = bot_name
                    await self.redis.publish("casino", json.dumps(message))
                elif cmd == "removebot":
                    if len(args) < 2:
                        logging.error("Usage: removebot <bot_name>")
                        continue
                    message = {
                        "event_type": "bot_action",
                        "game_id": self.game_id,
                        "action": "remove_bot",
                        "bot_name": args[1],
                    }
                    await self.redis.publish("casino", json.dumps(message))
                else:
                    message = {
                        "player": self.player_name,
                        "event_type": "player_action",
                        "game_id": self.game_id,
                        "action": cmd
                    }
                    # Handle bet command with amount
                    if cmd == "bet" and len(args) > 1:
                        try:
                            message["amount"] = int(args[1])
                        except ValueError:
                            logging.error("Invalid bet amount. Usage: bet <amount>")
                            continue
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
            logging.info(data['text'])

    async def main(self):
        self.player_name = input("Enter your name: ")
        logging.info(f"Welcome {self.player_name}")
        logging.info("Creating new game...")

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
                logging.info("Still waiting...")
                continue

            data = json.loads(message['data'])
            if data.get('event_type') == 'new_game' and data.get('request_id') == request_id:
                self.game_id = data.get('game_id')

        logging.info(f"Game created: {self.game_id}")

        async with asyncio.TaskGroup() as tg:
            tg.create_task(self.process_commands())
            tg.create_task(self.get_updates())


if __name__ == "__main__":
    cli = CasinoCli()
    asyncio.run(cli.main())
