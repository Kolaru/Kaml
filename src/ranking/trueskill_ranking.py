import trueskill

from collections import namedtuple
from math import sqrt

from .ranking import AbstractRanking, AbstractState


BETA = 25/6

Comparison = namedtuple("Comparison", ["wins",
                                       "losses",
                                       "win_estimate",
                                       "total",
                                       "win_empirical"])


class TrueSkillState(AbstractState):
    def __init__(self, rating, rank=None, wins=0, losses=0):
        self.rank = rank
        self.wins = wins
        self.losses = losses
        self.rating = rating

    @property
    def mu(self):
        return self.rating.mu

    @property
    def score(self):
        return self.mu - 3*self.sigma

    @property
    def sigma(self):
        return self.rating.sigma

    @property
    def variance(self):
        return self.sigma**2


class TrueSkillRanking(AbstractRanking):
    def __init__(self, name, identity_manager,
                 mu=25, sigma=25/3, beta=25/6, tau=25/300,
                 **kwargs):

        self.ts_env = trueskill.TrueSkill(
            draw_probability=0.0,
            mu=mu,
            sigma=sigma,
            beta=beta,
            tau=tau)

        super().__init__(name, identity_manager, **kwargs)

    def comparison(self, p1, p2):
        wins = self.wins.get((p1, p2), 0)
        losses = self.wins.get((p2, p1), 0)
        if wins + losses == 0:
            return None

        return Comparison(wins=wins,
                          losses=losses,
                          total=wins + losses,
                          win_empirical=100*wins/(wins + losses),
                          win_estimate=100*self.win_estimate(p1, p2))

    def initial_player_state(self):
        return TrueSkillState(self.ts_env.Rating())

    def update_players(self, winner, loser, timestamp=None):
        wrating, lrating = self.ts_env.rate_1vs1(winner.state.rating,
                                                 loser.state.rating)

        wstate = TrueSkillState(wrating,
                                rank=winner.rank,
                                wins=winner.wins + 1,
                                losses=winner.losses)
        winner.update_state(wstate, timestamp)

        lstate = TrueSkillState(lrating,
                                rank=loser.rank,
                                wins=loser.wins,
                                losses=loser.losses + 1)
        loser.update_state(lstate, timestamp)

    def win_estimate(self, p1, p2):
        delta_mu = p1.mu - p2.mu
        sum_sigma2 = p1.sigma**2 + p2.sigma**2
        denom = sqrt(2 * self.ts_env.beta**2 + sum_sigma2)
        return self.ts_env.cdf(delta_mu / denom)
