import numpy as np
import os
import time
import trueskill

from collections import namedtuple, OrderedDict
from itertools import chain
from math import log, exp, sqrt
from random import randint, sample
from random import random as rand
from scipy.stats import norm as Gaussian

from save_and_load import parse_mention_to_id, save_aliases
from utils import locking, logger
from utils import ChainedDict


PlayerState = namedtuple("PlayerState", ["rank", "mu", "sigma", "score"])


class Player:
    _id_counter = 0
    wins = 0
    losses = 0
    rank = None

    # TODO Better safeguard for invalid arg combinations
    def __init__(self, player_id=None, name=None):
        if name is not None:
            self.id = Player._id_counter
            self.mention = name
            Player._id_counter += 1
        else:
            self.aliases = set(aliases)
            self.id = player_id
            self.mention = "Some discord person"
        
        self.rating = trueskill.Rating()
        self.states = OrderedDict()
    
    def __hash__(self):
        return self.id
            
    def __str__(self):
        return f"Player {self.mention} (mu = {self.mu}, sigma = {self.sigma})"

    @property
    def mu(self):
        return self.rating.mu
    
    @property
    def ranks(self):
        return np.array([s.rank for s in self.states.values()] + [self.rank])

    @property
    def score(self):
        return self.mu - 3*self.sigma
    
    @property
    def scores(self):
        return np.array([s.score for s in self.states.values()] + [self.score])
    
    @property
    def sigma(self):
        return self.rating.sigma

    @property
    def times(self):
        return np.array(list(self.states.keys()) + [time.time()])
    
    @property
    def total_games(self):
        return self.wins + self.losses

    @property
    def variance(self):
        return self.sigma**2
    
    @property
    def win_ratio(self):
        return self.wins/self.total_games
    
    def asdict(self):
        return dict(
            rank=self.rank,
            id=self.id,
            aliases=list(self.aliases),
            mention=self.mention,
            claimed=self.claimed,
            mu=self.mu,
            sigma=self.sigma,
            score=self.score,
            states={t:s._asdict() for t, s in self.states.items()}
        )
    
    def save_state(self, timestamp, rank):
        self.states[float(timestamp)] = PlayerState(rank=rank,
                                             mu=self.mu,
                                             sigma=self.sigma,
                                             score=self.score)


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