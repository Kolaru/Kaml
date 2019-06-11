import numpy as np
import time
import trueskill

from collections import namedtuple
from numpy import exp, log, sqrt
from scipy.optimize import least_squares

from save_and_load import save_games, save_single_game, get_game_results
from utils import emit_signal, locking, logger


MU_SHIFT = 60
SIGMA_SCALE = 0.02

BETA = 25/6

Comparison = namedtuple("Comparison", ["wins",
                                       "losses",
                                       "win_estimate",
                                       "total",
                                       "win_empirical"])

ScoreChange = namedtuple("ScoreChange", ["winner",
                                         "loser",
                                         "winner_dscore",
                                         "loser_dscore"])


class Ranking:
    def __init__(self, player_manager):
        self.player_manager = player_manager
        self.ranked_players = []
        self.player_to_rank = {}
        self.wins = {}
        self.ts_env = trueskill.TrueSkill(draw_probability=0.0)
        self.ts_env.make_as_global()

    def __getitem__(self, rank):
        return self.ranked_players[rank]
    
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

    async def fetch_data(self, matchboard):
        logger.info("Building Ranking")
        logger.info("Ranking - Fetching game results.")

        game_results = await get_game_results(matchboard)

        logger.info(f"Ranking - Registering {len(game_results)} fetched games.")

        for g in game_results:
            await self.register_game(g, save=False,
                                     update_ranking=False)
        
        await self.update_ranking()

    def get_player(self, *args, **kwargs):
        return self.player_manager.get_player(*args, **kwargs)

    @property
    def players(self):
        return self.player_manager.players

    async def register_game(self, game, save=True, update_ranking=True):
        winner = self.get_player(game["winner"])
        loser = self.get_player(game["loser"])

        if (winner, loser) not in self.wins:
            self.wins[(winner, loser)] = 1
        else:
            self.wins[(winner, loser)] += 1

        winner_old_score = winner.score
        loser_old_score = loser.score

        winner.rating, loser.rating = trueskill.rate_1vs1(winner.rating, loser.rating)
        winner.wins += 1
        loser.losses += 1

        change = ScoreChange(winner=winner,
                             loser=loser,
                             winner_dscore=winner.score - winner_old_score,
                             loser_dscore=loser.score - loser_old_score)

        if save:
            await save_single_game(game)
            await emit_signal("game_registered", change)
        
        if update_ranking:
            await self.update_ranking()

        return change
    
    async def update_ranking(self):
        self.ranked_players = sorted(self.players, key=lambda p: -p.score)
        self.player_to_rank = {p:(k+1) for k, p in enumerate(self.ranked_players)}

        await emit_signal("ranking_updated")
    
    def lsq_ranking(self):
        ps = [p for p in self.players if p.total_games > 200]
        N = len(ps)

        print(f"{N} players considered")

        indices = []
        ws = []
        ns = []

        for i, p1 in enumerate(ps):
            for j, p2 in enumerate(ps):
                if j <= i:
                    continue

                wins = self.wins.get((p1, p2), 0)
                losses = self.wins.get((p2, p1), 0)
                if wins + losses > 0:
                    indices.append((i, j))
                    ws.append(wins/(wins + losses))
                    ns.append(wins + losses)
        
        ws = np.asarray(ws)
        ns = np.asarray(ns)

        x0 = np.zeros(2*N)
        x0[N:] = 5*np.ones(N)

        res = least_squares(lambda x: resfunc(x, ws, ns, indices), x0)

        print(f"Refunc {res.cost}")
        print(f"{res.message}")
        print(f"{len(ws)}")
        print(np.sum(res.fun))
        
        J = res.jac
        cov = np.linalg.inv(J.T.dot(J))

        lsq_ranking = []

        ys = np.abs(res.x[N:])

        for p, x, y in zip(ps, res.x, ys):
            lsq_ranking.append((p, x - y, y))
        
        return sorted(lsq_ranking, key=lambda v: -v[1])
    
    def win_estimate(self, p1, p2):
        delta_mu = p1.mu - p2.mu
        sum_sigma2 = p1.sigma**2 + p2.sigma**2
        denom = sqrt(2 * BETA**2 + sum_sigma2)
        return self.ts_env.cdf(delta_mu / denom)



def resfunc(x, ws, ns, indices):
    N = len(x)//2
    s = np.zeros(len(ws))
    y = x[N:]

    for k, ind in enumerate(indices):
        i, j = ind
        s[k] = 1/(1 + exp(-(x[i] - x[j])/np.sqrt(y[i]**2 + y[j]**2)))

    res = np.zeros(len(ws) + 1)
    res[0] = np.abs(np.mean(x))
    res[1:] = np.abs(ws - s)*np.sqrt(ns)

    return res