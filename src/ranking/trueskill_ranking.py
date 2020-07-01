import numpy as np
import pandas as pd
import trueskill

from math import sqrt

from .ranking import AbstractRanking
from utils import logger


class TrueSkillRanking(AbstractRanking):
    """
    Ranking according to TrueSkill rating.

    See trueskill.py documentation for the description of the keyword arguments.

    Arguments
    =========
    name: str
        The unique name of the ranking.

    Keyword arguments
    =================
    mu: number
    sigma: number
    beta: number
    tau: number

    Addition keyword arguments are passed to the constructor of the super class.
    """
    def __init__(self, name,
                 mu=25, sigma=25/3, beta=25/6, tau=25/300,
                 **kwargs):

        logger.info(f"Initialization of the TrueSkillRanking named '{name}' "
                    f"with parameters:\n"
                    f"  mu    = {mu}\n"
                    f"  sigma = {sigma}\n"
                    f"  beta  = {beta}\n"
                    f"  tau   = {tau}")

        # Initialize the TrueSkill environment
        self.ts_env = trueskill.TrueSkill(
            draw_probability=0.0,
            mu=mu,
            sigma=sigma,
            beta=beta,
            tau=tau)

        # Initialize TrueSkill specific dataframes
        history_dataframe = pd.DataFrame(
            columns=[
                "timestamp",
                "winner_id",
                "winner_rank",
                "winner_score",
                "winner_mu",
                "winner_sigma",
                "loser_id",
                "loser_rank",
                "loser_score",
                "loser_mu",
                "loser_sigma"
            ]
        )

        ranking_dataframe = pd.DataFrame(
            columns=[
                "rank",
                "score",
                "n_games",
                "mu",
                "sigma"
            ]
        )

        super().__init__(name,
                         ranking_dataframe=ranking_dataframe,
                         history_dataframe=history_dataframe,
                         **kwargs)

    def add_new_player(self, player_id):
        # Init new players with a rating with envrionnement default values
        rating = self.ts_env.Rating()

        # player_data = pd.DataFrame(
        #     dict(
        #         mu=rating.mu,
        #         sigma=rating.sigma,
        #         score=self.score(rating),
        #         n_games=0,
        #         rank=np.nan
        #     ),
        #     index=[player_id]
        # )
        # self.ranking = pd.concat([player_data, self.ranking])

        self.ranking.loc[player_id] = {
            "mu": rating.mu, 
            "sigma": rating.sigma, 
            "score": self.score(rating), 
            "n_games": 0, 
            "rank": np.nan
        }

    def apply_new_states(self, game_id, winner_state, loser_state):
        winner_rating = winner_state["rating"]
        loser_rating = loser_state["rating"]
        self.update_rating(winner_state["id"], winner_rating)
        self.update_rating(loser_state["id"], loser_rating)

        self.history.loc[game_id, "winner_mu"] = winner_rating.mu
        self.history.loc[game_id, "winner_sigma"] = winner_rating.sigma
        self.history.loc[game_id, "loser_mu"] = loser_rating.mu
        self.history.loc[game_id, "loser_sigma"] = loser_rating.sigma

    def compute_player_states(self, winner_id, loser_id):
        winner_rating = self.load_rating(winner_id)
        loser_rating = self.load_rating(loser_id)

        wrating, lrating = self.ts_env.rate_1vs1(winner_rating, loser_rating)

        winner_state = dict(
            id=winner_id,
            score=self.score(winner_rating),
            rating=winner_rating
        )

        loser_state = dict(
            id=loser_id,
            score=self.score(loser_rating),
            rating=loser_rating
        )

        return winner_state, loser_state

    def leaderboard(self, start, stop):
        # Mask selecting player in the correct rank range
        mask = np.logical_and(self.ranking["rank"] >= start,
                              self.ranking["rank"] < stop)
        data = sorted(self.ranking[mask], lambda pid_row: pid_row[1]["rank"])
        lines = []

        for player_id, row in data:
            wins = len(self.history[self.history["winner_id"] == player_id])
            losses = len(self.history[self.history["loser_id"] == player_id])
            lines.append(self.leaderboard_line.format(
                rank=row["rank"],
                score=row["score"],
                sigma=row["sigma"],
                leaderboard_name=self.bot.players.loc[player_id, "display_name"],
                wins=wins,
                losses=losses
            ))

        new_content = "\n".join(lines)
        return f"```\n{new_content}\n```"

    def load_rating(self, player_id):
        """
        Return the TrueSkill rating of a player given their player ID.

        Arguments
        =========
        player_id: int
        """
        if player_id in self.ranking.index:
            player_data = self.ranking.loc[player_id]
            return self.ts_env.Rating(
                mu=player_data["mu"],
                sigma=player_data["sigma"])

        return self.ts_env.Rating()

    def score(self, rating):
        return rating.mu - 3*rating.sigma

    def update_rating(self, player_id, new_rating):
        self.ranking.loc[player_id, "mu"] = new_rating.mu
        self.ranking.loc[player_id, "sigma"] = new_rating.sigma

    def win_estimate(self, p1, p2):
        # TODO Update this to the new architecture
        delta_mu = p1.mu - p2.mu
        sum_sigma2 = p1.sigma**2 + p2.sigma**2
        denom = sqrt(2 * self.ts_env.beta**2 + sum_sigma2)
        return self.ts_env.cdf(delta_mu / denom)
