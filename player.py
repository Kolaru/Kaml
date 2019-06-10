import time

from itertools import chain
from math import log, exp, sqrt
from random import randint, sample
from random import random as rand
from scipy.stats import norm as Gaussian

from save_and_load import load_alias_tables, parse_mention_to_id, save_aliases
from utils import locking, logger
from utils import ChainedDict

ALPHA = 0.1
BETA = Gaussian.ppf((1 + ALPHA)/2)

WIN = True
LOSS = False

def sigmoid(x):
    return 1/(1 + exp(-x))

class Player:
    mu = 1000
    logsigma = 6
    _id_counter = 0
    wins = 0
    losses = 0

    # TODO Better safeguard for invalid arg combinations
    def __init__(self, player_id=None, aliases=None, name=None):
        if name is not None:
            self.aliases = set([name])
            self.id = Player._id_counter
            self.mention = name
            self.claimed = False
            Player._id_counter += 1
        else:
            self.aliases = set(aliases)
            self.id = player_id
            self.claimed = True
    
    def __hash__(self):
        return self.id
            
    def __str__(self):
        return f"Player {self.mention} (mu = {self.mu}, sigma = {self.sigma})"

    def combined_sigma(self, other):
        return sqrt(self.variance + other.variance)

    def diff_estimate(self, other):
        return self.mu - other.mu

    def diff_error(self, other):
        return BETA * self.combined_sigma(other)

    def relerr(self, other):
        mag = self.diff_estimate(other)
        if mag == 0:
            return 10.0**10.0
        return abs(self.diff_error(other)/mag)

    @property
    def score(self):
        return self.mu - self.sigma

    @property
    def sigma(self):
        return int(sqrt(self.variance))
    
    @property
    def total_games(self):
        return self.wins + self.losses

    @property
    def variance(self):
        return exp(2*self.logsigma)

    def win_estimate(self, other):
        return 1 - Gaussian.cdf(-self.diff_estimate(other)/self.combined_sigma(other))
    
    @property
    def win_ratio(self):
        return self.wins/self.total_games


class TestPlayer(Player):
    def __init__(self, name, mu, sigma):
        super().__init__(name)
        self.true_mu = mu
        self.true_sigma = sigma

    def __str__(self):
        base = super().__str__()
        return base + "\n  True values: mu = {:0.0f}, sigma = {:0.0f}".format(self.true_mu, self.true_sigma)

    def win_exact(self, other):
        # print(- (self.mu - other.mu)/sqrt(self.variance + other.variance))
        return 1 - Gaussian.cdf(-(self.true_mu - other.true_mu)/sqrt(self.true_sigma**2 + other.true_sigma**2))


class PlayerNotFoundError(Exception):
    def __init__(self, player_id):
        self.player_id = player_id
    
    def __str__(self):
        return f"No player found with identifier {self.player_id}."


class PlayerManager:
    # Core dicts
    alias_to_id = None
    id_to_player = None

    def __init__(self):
        self.alias_to_id = {}
        self.id_to_player = {}
    
    async def load_data(self):
        logger.info("Building PlayerManager.")
        logger.info("PlayerManager - Fetching alias tables.")

        self.alias_to_id, id_to_aliases = await load_alias_tables()
        self.id_to_player = dict()

        logger.info(f"PlayerManager - Constructing {len(id_to_aliases)} player objects.")

        for player_id, aliases in id_to_aliases.items():
            self.id_to_player[player_id] = Player(player_id=player_id,
                                                  aliases=aliases)
    
    def alias_exists(self, alias):
        return alias in self.alias_to_id

    @property
    def alias_to_player(self):
        return ChainedDict(self.alias_to_id, self.id_to_player)

    @property
    def aliases(self):
        return self.get_aliases()
    
    @property
    def claimed_aliases(self):
        return self.get_aliases(filter=lambda p: p.claimed)
    
    @property
    def claimed_players(self):
        return [p for p in self.players if p.claimed]

    @property
    def players(self):
        return list(self.id_to_player.values())
    
    @property
    def id_to_claimed_aliases(self):
        return {p.id:p.aliases for p in self.players if p.claimed}

    def add_player(self, name=None,
                   player_id=None,
                   aliases=None):
        if name is not None:
            player = Player(name=name)
        else:
            player = Player(player_id=player_id, aliases=aliases)

        player_id = player.id
        self.id_to_player[player_id] = player
        self.alias_to_id[name] = player_id

        return player

    @locking("player_manager") 
    async def associate_aliases(self, player_id, aliases):
        # Assume that none of the aliases is already taken
        # Assume len(aliases) > 0

        found = [alias for alias in aliases if self.alias_exists(alias)]
        not_found = [alias for alias in aliases if not self.alias_exists(alias)]

        if not self.id_exists(player_id):
            self.add_player(player_id=player_id,
                            aliases=aliases)
        else:
            player = self.id_to_player[player_id]
            player.aliases.update(aliases)
            
        for alias in found:
            past_id = self.alias_to_id[alias]
            del self.id_to_player[past_id]
        
        for alias in aliases:
            self.alias_to_id[alias] = player_id
            
        await save_aliases(self.id_to_claimed_aliases)

        return found, not_found

    def extract_claims(self, aliases):
        return {alias:self.alias_to_player[alias] for alias in aliases
                if self.is_claimed(alias)}

    def get_aliases(self, filter=lambda p: True):
        return set(chain.from_iterable([p.aliases for p in self.players
                                        if filter(p)]))

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

    def id_exists(self, player_id):
        return player_id in self.id_to_player
    
    def is_claimed(self, alias):
        return alias in self.claimed_aliases