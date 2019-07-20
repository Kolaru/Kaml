import numpy as np
import os
import time

from collections import namedtuple, OrderedDict
from itertools import chain
from math import log, exp, sqrt
from random import randint, sample
from random import random as rand
from scipy.stats import norm as Gaussian

from utils import locking, logger
from utils import ChainedDict


class Player:
    wins = 0
    losses = 0
    rank = None

    def __init__(self, player_identity, initial_state):
        self.identity = player_identity
        self.states = OrderedDict()
        self.state = initial_state
    
    def __str__(self):
        return f"Player {self.identity.display_name} ({self.current_state})"

    def asdict(self):
        return dict(
            states={t:s.asdict() for t, s in self.states.items()}
        )

    @property
    def display_name(self):
        return self.identity.display_name

    @property
    def display_rank(self):
        return self.rank + 1

    @property
    def ranks(self):
        return np.array([s.rank for s in self.states.values()])

    @property
    def score(self):
        return self.current_state.score
    
    @property
    def scores(self):
        return np.array([s.score for s in self.states.values()])

    @property
    def times(self):
        return np.array(list(self.states.keys()) + [time.time()])

    @property
    def total_games(self):
        return self.wins + self.losses
    
    def update_state(self, new_state, timestamp=None):
        if timestamp is None:
            timestamp = time.time()

        self.states[timestamp] = self.current_state
        self.current_state = new_state

    @property
    def win_ratio(self):
        return self.wins/self.total_games


class PlayerNotFoundError(Exception):
    def __init__(self, player_id=None):
        self.player_id = player_id
    
    def __str__(self):
        if self.player_id is None:
            return "Tried to find player without giving an identifier."
            
        return f"No player found with identifier {self.player_id}."


class PlayerManager:
    id_to_player = None
    alias_manager = None

    @property
    def alias_to_player(self):
        return ChainedDict(self.alias_manager, self.id_to_player)
    
    @property
    def claimed_players(self):
        return [p for p in self.players if p.claimed]

    @property
    def players(self):
        return list(self.id_to_player.values())

    def get_player(self, alias,
                test_mention=False,
                create_missing=True):
        player_id = None

        t = time.time()

        # Check if alias is a player id
        if isinstance(alias, int):
            player_id = alias
            if not self.id_exists(player_id):
                logger.error(f"No player found with id {player_id}.")
                raise PlayerNotFoundError(player_id)
            
            player = self.id_to_player[player_id]
        else:
            if test_mention:
                # Check if alias is a discord mention
                player_id = parse_mention_to_id(alias)

            if player_id is not None:
                player = self.id_to_player[player_id]
            elif not self.alias_exists(alias):
                if create_missing:
                    logger.debug(f"New player created with name {alias} in get_player.")
                    player = self.add_player(name=alias)
                else:
                    logger.error(f"No player found with name {player_id}.")
                    raise PlayerNotFoundError(alias)
            else:
                player = self.alias_to_player[alias]
        
        return player

    def add_player(self, name=None,
                   player_id=None,
                   aliases=None):
        
        player = Player(name=name, player_id=player_id, aliases=aliases)

        player_id = player.id
        self.id_to_player[player_id] = player
        self.alias_to_id[name] = player_id

        return player