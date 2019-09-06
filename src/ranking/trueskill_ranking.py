import trueskill

from math import sqrt

from .ranking import AbstractRanking


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

        with self.db:
            self.db.execute(
                f"""
                CREATE TABLE {self.ranking_table}
                (
                    player_id int,
                    rank int UNIQUE,
                    mu real NOT NULL DEFAULT ({mu}),
                    sigma real NOT NULL DEFAULT ({sigma}),
                    score real NOT NULL DEFAULT (0),
                    FOREIGN KEY (player_id) REFERENCES identities (player_id)
                )
                """)

            # Add players that have aliases
            self.db.execute(
                f"""
                INSERT INTO {self.ranking_table} (player_id)
                SELECT player_id
                FROM players
                """
            )

            # All fields refer to the value after the game happened
            self.db.execute(
                """
                CREATE TABLE {self.history_table}
                (
                    timestamp int NOT NULL,
                    winner_id int,
                    winner_rank int,
                    winner_mu real NOT NULL,
                    winner_sigma real NOT NULL,
                    loser_id int,
                    loser_rank int,
                    loser_mu real NOT NULL,
                    loser_sigma real NOT NULL,
                    FOREIGN KEY (winner_id) REFERENCES identities (player_id),
                    FOREIGN KEY (loser_id) REFERENCES identities (player_id)
                )
                """)

    def fetch_player_data(self, player_id):
        req = self.db.execute(
            f"""
            SELECT rank, mu, sigma, score
            FROM {self.ranking_table}
            WHERE player_id=?
            """,
            (player_id,)
            )

        result = req.fetchone()
        if result is None:
            return self.initial_state()
        else:
            return result

    def initial_player_state(self):
        return {"rank": None,
                "mu": self.ts_env.mu,
                "sigma": self.ts_env.sigma,
                "score": self.ts_env.mu - 3*self.ts_env.sigma}

    def leaderboard(self, start, stop):
        """Generate the string content of a leaderboard message."""
        # TODO reimplement python like negative indexes

        req = self.db.execute(
            f"""
            SELECT display_name, rank, score, sigma,
                COUNT(*) AS wins,
                COUNT(*) AS losses
            FROM players
            INNER JOIN {self.ranking_table} as ranking
                ON ranking.player_id = players.player_id
            INNER JOIN {self.history_table} AS win
                ON win.winner_id = players.player_id
            INNER JOIN {self.history_table} AS loss
                ON loss.loser_id = players.player_id
            WHERE rank BETWEEN ? AND ?
            GROUP BY players.player_id
            ORDER BY rank ASC
            """,
            (start, stop)
            )

        new_content = "\n".join([self.leaderboard_line.format(**row)
                                 for row in req])

        return f"```\n{new_content}\n```"

    def load_rating(self, player_id):
        req = self.db.execute(
            f"""
            SELECT mu, sigma
            FROM {self.ranking_table}
            WHERE player_id=?
            """,
            (player_id,)
            )

        res = req.fetchone()

        if res is None:
            return self.ts_env.Rating()
        else:
            return self.ts_env.Rating(mu=res["mu"], sigma=res["sigma"])

    def score(self, rating):
        return rating.mu - 3*rating.sigma

    def store_rating(self, player_id, rating):
        with self.db:
            self.db.execute(
                f"""
                INSERT INTO {self.ranking_table} (player_id, mu, sigma, score)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(player_id)
                DO UPDATE SET mu=?, sigma=?, score=?
                """,
                (player_id,
                 rating.mu, rating.sigma, self.score(rating),
                 rating.mu, rating.sigma, self.score(rating))
                )

    def process_game(self, winner_id, loser_id, timestamp):
        wrating = self.load_rating(winner_id)
        lrating = self.loard_rating(loser_id)

        wrating, lrating = self.ts_env.rate_1vs1(wrating, lrating)

        self.store_rating(winner_id, wrating)
        self.store_rating(loser_id, lrating)

        with self.db:
            self.db.execute(
                f"""
                INSERT INTO {self.history_table}
                    (timestamp,
                     winner_id, winner_mu, winner_sigma,
                     loser_id, loser_mu, loser_sigma)
                VALUES
                    (?,
                     ?, ?, ?,
                     ?, ?, ?)
                """,
                (timestamp,
                 winner_id, wrating.mu, wrating.sigma,
                 loser_id, lrating.mu, lrating.sigma))

        return self.score(wrating), self.score(lrating)

    def win_estimate(self, p1, p2):
        delta_mu = p1.mu - p2.mu
        sum_sigma2 = p1.sigma**2 + p2.sigma**2
        denom = sqrt(2 * self.ts_env.beta**2 + sum_sigma2)
        return self.ts_env.cdf(delta_mu / denom)
