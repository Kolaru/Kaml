import time

from collections import namedtuple
from math import log, exp, sqrt

from save_and_load import save_games, save_single_game, get_game_results
from utils import emit_signal, locking, logger


MU_SHIFT = 60
SIGMA_SCALE = 0.02


class ScoreChange:
    def __init__(self, winner, loser):
        self.winner = winner
        self.loser = loser

        self.prior_estimate = winner.win_estimate(loser)
        self.prior_mu = dict(winner=winner.mu, loser=loser.mu)
        self.prior_logsigma = dict(winner=winner.logsigma, loser=loser.logsigma)

        self.relerr = winner.relerr(loser)
        self.dmu = int((1 - self.prior_estimate) * MU_SHIFT)

        if self.prior_estimate > 0.5:
            scaling = - (1 - self.prior_estimate)
        else:
            scaling = self.prior_estimate
        
        self.dlogsigma = scaling * SIGMA_SCALE #/self.relerr
        self.winner_dsigma = int( exp(self.prior_logsigma["winner"] + self.dlogsigma)
                                  - exp(self.prior_logsigma["winner"]) )
        self.loser_dsigma = int( exp(self.prior_logsigma["loser"] + self.dlogsigma) 
                                 - exp(self.prior_logsigma["loser"]) )
    
    def apply_change(self, winner, loser):
        winner.mu += self.dmu
        winner.logsigma += self.dlogsigma
        winner.wins += 1

        loser.mu -= self.dmu
        loser.logsigma += self.dlogsigma
        loser.losses += 1


Comparison = namedtuple("Comparison", ["wins",
                                       "losses",
                                       "win_estimate",
                                       "total",
                                       "win_empirical"])

class Ranking:
    def __init__(self, player_manager):
        self.player_manager = player_manager
        self.ranked_players = []
        self.player_to_rank = {}
        self.wins = {}

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
                          win_estimate=100*p1.win_estimate(p2))

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

        change = ScoreChange(winner, loser)
        change.apply_change(winner, loser)

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

