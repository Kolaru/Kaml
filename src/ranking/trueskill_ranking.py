import progressbar
import trueskill

from bisect import bisect
from math import sqrt

from .ranking import AbstractRanking
from utils import logger, RankedDict


class TrueSkillRanking(AbstractRanking):
    def __init__(self, name, identity_manager,
                 mu=25, sigma=25/3, beta=25/6, tau=25/300,
                 **kwargs):

        logger.info(f"Init ranking {name}")

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
                    player_id INTEGER UNIQUE NOT NULL,
                    rank INTEGER,
                    mu REAL NOT NULL DEFAULT ({mu}),
                    sigma REAL NOT NULL DEFAULT ({sigma}),
                    score REAL NOT NULL DEFAULT (0),
                    total_games INTEGER NOT NULL DEFAULT (0),
                    FOREIGN KEY (player_id) REFERENCES players (player_id)
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
                f"""
                CREATE TABLE {self.history_table}
                (
                    timestamp INTEGER NOT NULL,
                    winner_id INTEGER NOT NULL,
                    winner_rank INTEGER,
                    winner_mu REAL NOT NULL,
                    winner_sigma REAL NOT NULL,
                    loser_id INTEGER NOT NULL,
                    loser_rank INTEGER,
                    loser_mu REAL NOT NULL,
                    loser_sigma REAL NOT NULL,
                    FOREIGN KEY (winner_id) REFERENCES players (player_id),
                    FOREIGN KEY (loser_id) REFERENCES players (player_id)
                )
                """)

    def default_state_dict(self):
        return {"rank": None,
                "rating": self.ts_env.Rating(),
                "total_games": 0}

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
            return self.ts_env.Rating(mu=res[0], sigma=res[1])

    def process_game(self, winner_id, loser_id, timestamp):
        wrating = self.load_rating(winner_id)
        lrating = self.load_rating(loser_id)

        wrating, lrating = self.ts_env.rate_1vs1(wrating, lrating)

        self.store_rating(winner_id, wrating)
        self.store_rating(loser_id, lrating)

        with self.db:
            self.db.execute(
                f"""
                INSERT INTO {self.history_table}
                (
                    timestamp,
                    winner_id, winner_mu, winner_sigma,
                    loser_id, loser_mu, loser_sigma
                )
                VALUES
                    (?,
                     ?, ?, ?,
                     ?, ?, ?)
                """,
                (timestamp,
                 winner_id, wrating.mu, wrating.sigma,
                 loser_id, lrating.mu, lrating.sigma))

        return self.score(wrating), self.score(lrating)

    def register_many(self, games):
        thres = bisect([game["timestamp"] for game in games],
                       self.oldest_timestamp_to_consider)
        # games = games[thres:]  TODO uncomment when tests are done

        logger.info(f"Registering a bundle of {len(games)} games.")

        req = self.db.execute(
            f"""
            SELECT player_id, rank, mu, sigma, total_games
            FROM {self.ranking_table}
            """
            )

        players = {row[0]: {
            "player_id": row[0],
            "rating": self.ts_env.Rating(mu=row[2], sigma=row[3]),
            "total_games": row[4]
        } for row in req}

        for pid in players:
            players[pid]["score"] = self.score(players[pid]["rating"])

        logger.info(
            f"""Known players before registration begins (len = {len(players)}):
            {players}
            """)

        players = RankedDict(players)

        logger.info(
            f"""Known players before registration begins (len = {len(players)}):
            {players}
            """)

        history = []

        try:
            for game in progressbar.progressbar(games):
                wstate = players.get(game["winner_id"],
                                     self.default_state_dict())
                lstate = players.get(game["loser_id"],
                                     self.default_state_dict())

                wstate["total_games"] += 1
                lstate["total_games"] += 1

                wstate["rating"], lstate["rating"] = self.ts_env.rate_1vs1(
                    wstate["rating"], lstate["rating"])

                wstate["score"] = self.score(wstate["rating"])
                lstate["score"] = self.score(lstate["rating"])

                players.delete(key=game["winner_id"])
                players.delete(key=game["loser_id"])

                winner_rank, loser_rank = None, None

                if wstate["total_games"] > self.mingames:
                    self.rerank_players(players, wstate)

                    winner_rank = players.get_rank(game["winner_id"])

                if lstate["total_games"] > self.mingames:
                    self.rerank_players(players, lstate)

                    loser_rank = players.get_rank(game["loser_id"])

                history.append(
                    (game["timestamp"],
                     game["winner_id"],
                     winner_rank,
                     wstate["rating"].mu,
                     wstate["rating"].sigma,
                     game["loser_id"],
                     loser_rank,
                     lstate["rating"].mu,
                     lstate["rating"].sigma)
                    )

        except Exception:
            logger.error(f"""
                An error occurred while processing a game in register_many

                Game
                {game}

                Winner state
                {wstate}

                Loser state
                {lstate}

                """)
            raise

        with self.db:
            self.db.executemany(
                f"""
                INSERT OR REPLACE INTO {self.ranking_table}
                (
                    player_id,
                    rank,
                    mu,
                    sigma,
                    score,
                    total_games
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                [(pid,
                  state["rank"],
                  state["rating"].mu,
                  state["rating"].sigma,
                  self.score(state["rating"]),
                  state["total_games"]) for pid, state in players.items()]
                )

            self.db.executemany(
                f"""
                INSERT INTO {self.history_table}
                (
                    timestamp,
                    winner_id,
                    winner_rank,
                    winner_mu,
                    winner_sigma,
                    loser_id,
                    loser_rank,
                    loser_mu,
                    loser_sigma
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                history
                )

    def score(self, rating):
        return rating.mu - 3*rating.sigma

    def store_rating(self, player_id, rating):
        with self.db:
            self.db.execute(
                f"""
                INSERT INTO {self.ranking_table} (player_id, mu, sigma, score)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(player_id)
                DO UPDATE SET mu=?, sigma=?, score=?, total_games=total_games+1
                """,
                (player_id,
                 rating.mu, rating.sigma, self.score(rating),
                 rating.mu, rating.sigma, self.score(rating))
                )

    def win_estimate(self, p1, p2):
        delta_mu = p1.mu - p2.mu
        sum_sigma2 = p1.sigma**2 + p2.sigma**2
        denom = sqrt(2 * self.ts_env.beta**2 + sum_sigma2)
        return self.ts_env.cdf(delta_mu / denom)
