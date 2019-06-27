import numpy as np
import time
import trueskill

from collections import namedtuple, OrderedDict
from numpy import exp, log, sqrt
from scipy.optimize import least_squares

from messages import msg_builder
from save_and_load import save_games, save_single_game, get_game_results
from utils import emit_signal, locking, logger

MINGAMES = 10

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
    def __init__(self, player_manager,
                 mu=25, sigma=25/3, beta=25/6, tau=25/300):
        self.player_manager = player_manager
        self.rank_to_player = OrderedDict()
        self.player_to_rank = {}
        self.wins = {}
        self.ts_env = trueskill.TrueSkill(
            draw_probability=0.0,
            mu=mu,
            sigma=sigma,
            beta=beta,
            tau=tau)
        self.ts_env.make_as_global()

    def __getitem__(self, rank):
        return list(self.rank_to_player.values())[rank]
    
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
                                     signal_update=False)
        
        await emit_signal("ranking_updated")

    def get_player(self, *args, **kwargs):
        return self.player_manager.get_player(*args, **kwargs)

    def leaderboard(self, start, stop):
        """Generate the string content of a leaderboard message."""
        # Convert from base 1 indexing for positive ranks
        if start >= 0:
            start -= 1

        new_content = "\n".join([msg_builder.build("leaderboard_line",
                                                   player=player)
                                 for player in self[start:stop]])
        
        return f"```\n{new_content}\n```"

    @property
    def players(self):
        return self.player_manager.players

    async def register_game(self, game, save=True, signal_update=True):
        if game["winner"] == "":
            game["winner"] = None
        
        if game["loser"] == "":
            game["loser"] = None
            
        if game["winner"] is None or game["loser"] is None:
            return None
            
        winner = self.get_player(game["winner"])
        loser = self.get_player(game["loser"])

        winner_old_rank = winner.rank
        loser_old_rank = loser.rank

        winner.save_state(game["timestamp"], winner_old_rank)
        loser.save_state(game["timestamp"], loser_old_rank)

        if (winner, loser) not in self.wins:
            self.wins[(winner, loser)] = 1
        else:
            self.wins[(winner, loser)] += 1

        winner_old_score = winner.score
        loser_old_score = loser.score

        winner.rating, loser.rating = trueskill.rate_1vs1(winner.rating, loser.rating)
        winner.wins += 1
        loser.losses += 1

        winner_dscore = winner.score - winner_old_score
        loser_dscore = loser.score - loser_old_score

        change = ScoreChange(winner=winner,
                             loser=loser,
                             winner_dscore=winner_dscore,
                             loser_dscore=loser_dscore)

        self.update_ranks(winner, winner_dscore)
        self.update_ranks(loser, loser_dscore)

        if save:
            await save_single_game(game)
            await emit_signal("game_registered", change)
        
        if signal_update:
            await emit_signal("ranking_updated")

        return change

    def update_ranks(self, player, dscore):
        if player.total_games < MINGAMES:
            return
        
        if dscore == 0:
            return
        elif dscore < 0:
            inc = 1
        else:
            inc = -1

        N = len(self.rank_to_player)

        if N == 0:
            player.rank = 0
            self.rank_to_player[0] = player
            return
        
        old_rank = player.rank

        if old_rank is None:
            inc = -1
            old_rank = N
            N += 1

        if inc == -1 and old_rank == 0:
            return
        
        if inc == 1 and old_rank == N - 1:
            return

        k = old_rank + inc
                
        other = self.rank_to_player[k]

        while k > 0 and k < N - 1 and other.score*inc > player.score*inc:
            other.rank = k - inc
            self.rank_to_player[other.rank] = other

            k += inc
            other = self.rank_to_player[k]
        
        if other.score*inc > player.score*inc:
            other.rank  = k - inc
            self.rank_to_player[other.rank] = other
        else:
            k -= inc

        player.rank = k
        self.rank_to_player[k] = player

        if k > 0:
            assert player.score <= self.rank_to_player[k - 1].score
        
        if k < N - 1:
            assert player.score >= self.rank_to_player[k + 1].score
        
    def win_estimate(self, p1, p2):
        delta_mu = p1.mu - p2.mu
        sum_sigma2 = p1.sigma**2 + p2.sigma**2
        denom = sqrt(2 * BETA**2 + sum_sigma2)
        return self.ts_env.cdf(delta_mu / denom)