import numpy as np
import time

from collections import OrderedDict


class Player:
    """Class representing a player in a given ranking.

    Associate an Identity to a ranking state and keep track of the history
    of states.
    """
    def __init__(self, player_identity, initial_state):
        self.identity = player_identity
        self.saved_states = OrderedDict()
        self.state = initial_state

    def __getattr__(self, attr):
        return getattr(self.state, attr)

    def __repr__(self):
        return self.__str__()

    def __str__(self):
        return f"Player {self.display_name} rank {self.rank} with score {self.score} ({self.state})"

    def asdict(self):
        return dict(
            states={t: s.asdict() for t, s in self.states.items()}
        )

    @property
    def display_name(self):
        return self.identity.display_name

    @property
    def leaderboard_name(self):
        return self.identity.leaderboard_name

    @property
    def display_rank(self):
        if self.rank is None:
            return None

        return self.rank + 1

    @property
    def losses(self):
        return self.state.losses

    @property
    def rank(self):
        return self.state.rank

    @rank.setter
    def rank(self, new_rank):
        self.state.rank = new_rank

    @property
    def ranks(self):
        return np.array([s.rank for s in self.states.values()])

    @property
    def score(self):
        return self.state.score

    @property
    def scores(self):
        return np.array([s.score for s in self.states.values()])

    @property
    def states(self):
        return {time.time(): self.state, **self.saved_states}

    @property
    def times(self):
        return np.array(list(self.states.keys()))

    @property
    def total_games(self):
        return self.wins + self.losses

    def update_state(self, new_state, timestamp=None):
        if timestamp is None:
            timestamp = time.time()

        self.saved_states[timestamp] = self.state
        self.state = new_state

    @property
    def win_ratio(self):
        return self.wins/self.total_games

    @property
    def wins(self):
        return self.state.wins
