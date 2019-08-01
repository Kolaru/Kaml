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
    def __init__(self, rating):
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
                 mu=25, sigma=25/3, beta=25/6, tau=25/300):

        super().__init__(name, identity_manager)

        self.ts_env = trueskill.TrueSkill(
            draw_probability=0.0,
            mu=mu,
            sigma=sigma,
            beta=beta,
            tau=tau)
        self.ts_env.make_as_global()

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
        return trueskill.Rating()

    def update_players(self, winner, loser):
        wrating, lrating = trueskill.rate_1vs1(winner.rating, loser.rating)

    def win_estimate(self, p1, p2):
        delta_mu = p1.mu - p2.mu
        sum_sigma2 = p1.sigma**2 + p2.sigma**2
        denom = sqrt(2 * BETA**2 + sum_sigma2)  # TODO Get beta from ranking
        return self.ts_env.cdf(delta_mu / denom)
