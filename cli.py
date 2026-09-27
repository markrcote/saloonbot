import asyncio
import json
import logging
import os
import uuid

import aioconsole
import redis.asyncio as redis

from cardgames.money import dollars_to_cents


REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = os.getenv("REDIS_PORT", 6379)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

HELP_TEXT = """
Commands:
  join              - Join the game (sit down at the table)
  bet <amount>      - Place a bet during the betting phase
  hit               - Draw another card
  stand             - Hold your current hand
  leave             - Leave the game
  addnpc [count]    - Add roster NPC(s) to the game (default: 1)
  removenpc [name]  - Remove an NPC (by name, or any if omitted)
  help              - Show this message
  quit              - Exit the CLI
"""


def _prompt_int(prompt, default):
    """Read an int from the console, falling back to default on blank or bad input
    (the server clamps NPC limits to its own range)."""
    raw = input(prompt).strip()
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


class CasinoCli:
    def __init__(self):
        self.redis = redis.Redis(host=REDIS_HOST, port=REDIS_PORT)
        self.pubsub = self.redis.pubsub()
        self.player_name = None
        self.game_id = None
        self.quit = False

    async def send_player_action(self, action, extra=None):
        message = {
            "player": self.player_name,
            "event_type": "player_action",
            "game_id": self.game_id,
            "action": action,
        }
        if extra:
            message.update(extra)
        await self.redis.publish("casino", json.dumps(message))

    async def process_commands(self):
        while not self.quit:
            line = await aioconsole.ainput("> ")
            if not line:
                continue
            args = line.strip().split()
            cmd = args[0]

            if cmd == "quit":
                self.quit = True
            elif cmd == "help":
                print(HELP_TEXT)
            elif cmd == "addnpc":
                try:
                    count = int(args[1]) if len(args) > 1 else 1
                except ValueError:
                    logging.error("Usage: addnpc [count]")
                    continue
                message = {
                    "event_type": "npc_action",
                    "game_id": self.game_id,
                    "action": "add_npc",
                    "count": count,
                }
                await self.redis.publish("casino", json.dumps(message))
            elif cmd == "removenpc":
                message = {
                    "event_type": "npc_action",
                    "game_id": self.game_id,
                    "action": "remove_npc",
                }
                if len(args) > 1:
                    message["npc_name"] = args[1]
                await self.redis.publish("casino", json.dumps(message))
            elif cmd == "bet":
                if len(args) < 2:
                    logging.error("Usage: bet <amount>")
                    continue
                try:
                    amount = int(args[1])
                except ValueError:
                    logging.error("Invalid bet amount. Usage: bet <amount>")
                    continue
                await self.send_player_action("bet", {"amount": dollars_to_cents(amount)})
            else:
                await self.send_player_action(cmd)

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

        npc_min = _prompt_int("Fewest NPC players to keep at the table? (0-6, default 3): ", 3)
        npc_max = _prompt_int("Most NPC players allowed? (0-6, default 5): ", 5)

        logging.info(f"Welcome {self.player_name}! Creating new game...")

        request_id = str(uuid.uuid4())
        await self.pubsub.subscribe("casino_update")
        message = {
            'event_type': 'casino_action',
            'action': 'new_game',
            'request_id': request_id,
            'npc_min': npc_min,
            'npc_max': npc_max,
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

        # Auto-join so bots are added and the game can start
        await self.send_player_action("join")
        logging.info("Joined game. Type 'help' for commands.")

        async with asyncio.TaskGroup() as tg:
            tg.create_task(self.process_commands())
            tg.create_task(self.get_updates())


if __name__ == "__main__":
    cli = CasinoCli()
    asyncio.run(cli.main())
