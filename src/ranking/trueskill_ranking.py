import numpy as np
import trueskill

from math import sqrt
from pandas import concat, DataFrame

from .ranking import AbstractRanking
from utils import logger


class TrueSkillRanking(AbstractRanking):
    def __init__(self, name,
                 mu=25, sigma=25/3, beta=25/6, tau=25/300,
                 **kwargs):

        logger.info(f"Init ranking {name}")

        self.ts_env = trueskill.TrueSkill(
            draw_probability=0.0,
            mu=mu,
            sigma=sigma,
            beta=beta,
            tau=tau)

        self.ranking = DataFrame(
            columns=[
                "rank",
                "score",
                "n_games",
                "mu",
                "sigma"
            ]
        )

        self.history = DataFrame(
            columns=[
                "timestamp",
                "winner_id",
                "winner_rank",
                "winner_mu",
                "winner_sigma",
                "loser_id",
                "loser_rank",
                "loser_mu",
                "loser_sigma"
            ]
        )

        super().__init__(name, **kwargs)

    def add_player(self, player_id):
        rating = self.ts_env.Rating()  # Rating with default values

        player_data = DataFrame(
            dict(
                mu=rating.mu,
                sigma=rating.sigma,
                score=self.score(rating),
                n_games=0,
                rank=np.nan
            ),
            index=[player_id]
        )
        self.ranking = concat([player_data, self.ranking])

    def leaderboard(self, start, stop):
        """Generate the string content of a leaderboard message."""
        data = self.ranking[self.ranking["rank"].notna()].iloc[start:stop]
        lines = []

        for player_id, row in data.iterrows():
            wins = len(self.history[self.history["winner_id"] == player_id])
            losses = len(self.history[self.history["loser_id"] == player_id])
            lines.append(self.leaderboard_line.format(
                rank=row["rank"],
                score=row["score"],
                sigma=row["sigma"],
                leaderboard_name=self.players.loc[player_id, "display_name"],
                wins=wins,
                losses=losses
            ))

        new_content = "\n".join(lines)
        return f"```\n{new_content}\n```"

    def load_rating(self, player_id):
        if player_id in self.ranking.index:
            player_data = self.ranking.loc[player_id]
            return self.ts_env.Rating(
                mu=player_data["mu"],
                sigma=player_data["sigma"])

        return self.ts_env.Rating()

    def process_scores(self, winner_id, loser_id, timestamp):
        wrating = self.load_rating(winner_id)
        lrating = self.load_rating(loser_id)

        wrating, lrating = self.ts_env.rate_1vs1(wrating, lrating)

        self.update_rating(winner_id, wrating)
        self.update_rating(loser_id, lrating)

        self.history = self.history.append(
            dict(
                timestamp=timestamp,
                winner_id=winner_id,
                winner_mu=wrating.mu,
                winner_sigma=wrating.sigma,
                loser_id=loser_id,
                loser_mu=lrating.mu,
                loser_sigma=lrating.sigma
            ),
            ignore_index=True
        )

        return self.score(wrating), self.score(lrating)

    def score(self, rating):
        return rating.mu - 3*rating.sigma

    def update_rating(self, player_id, rating):
        if player_id not in self.ranking.index:
            self.add_player(player_id)
        else:
            self.ranking.loc[player_id, "mu"] = rating.mu
            self.ranking.loc[player_id, "sigma"] = rating.sigma
            self.ranking.loc[player_id, "score"] = self.score(rating)

    def win_estimate(self, p1, p2):
        delta_mu = p1.mu - p2.mu
        sum_sigma2 = p1.sigma**2 + p2.sigma**2
        denom = sqrt(2 * self.ts_env.beta**2 + sum_sigma2)
        return self.ts_env.cdf(delta_mu / denom)
