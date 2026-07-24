class Player:
    is_npc = False

    def __init__(self, name):
        self.name = name  # must be unique
        self.hand = []

    def __eq__(self, other):
        return self.name == other.name

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        return hash(self.name)

    def __repr__(self):
        return f"{self.name}"

    def __str__(self):
        return f"{self.name}"

    def hand_str(self):
        return ", ".join([card.str() for card in self.hand])

    def observe_table_event(self, event):
        """Receive a short description of a table event. No-op by default;
        NPCs that keep session memory override this."""
        pass


class PlayerNotFoundError(Exception):

    def __init__(self, playername):
        self.playername = playername

    def __str__(self):
        return f"Player {self.playername} not found"


class PlayerRegistry:
    def __init__(self):
        self.players = {}

    def get_player(self, player_name, add=False):
        player = self.players.get(player_name)
        if player is None:
            if add:
                player = Player(player_name)
                self.players[player_name] = player
            else:
                raise PlayerNotFoundError(player_name)
        return player


registry = PlayerRegistry()
