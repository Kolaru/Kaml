import csv
import sqlite3


class DataManager:
    def __init__(self):
        self.db = sqlite3.connect("data/database.db")

        with self.db:
            self.db.execute(
                """
                CREATE TABLE players
                (
                    player_id int,
                    discord_id int,
                    display_name text,
                    PRIMARY KEY (player_id)
                )
                """)

            self.db.execute(
                """
                CREATE TABLE aliases
                (
                    alias text NOT NULL UNIQUE,
                    player_id int,
                    FOREIGN KEY (player_id) REFERENCES identities (player_id)
                )
                """)

            self.db.execute(
                """
                CREATE TABLE main_ranking
                (
                    player_id int,
                    rank int UNIQUE,
                    mu real NOT NULL,
                    sigma real NOT NULL,
                    FOREIGN KEY (player_id) REFERENCES identities (player_id)
                )
                """)

            # All field refer to the value before the game happened
            self.db.execute(
                """
                CREATE TABLE main_history
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

        with open("data/aliases.csv", "r", encoding="utf-8") as file:
            for line in file:
                discord_id, *aliases = line.split(",")
                discord_id = int(discord_id)

                if isinstance(aliases, str):
                    aliases = [aliases]

                with self.db:
                    c = self.db.execute(
                        """
                        INSERT INTO players (discord_id)
                        VALUES (?)
                        """,
                        (discord_id,))

                    player_id = c.lastrowid

                with self.db:
                    self.db.executemany(
                        """
                        INSERT INTO aliases (alias, player_id)
                        VALUES (?, ?)
                        """,
                        [(alias.strip(), player_id) for alias in aliases])

    def id_from_alias(self, alias):
        req = self.db.execute(
            """
            SELECT player_id
            FROM aliases
            WHERE alias=?
            """,
            alias
            )

        result = req.fetchone()
        if result is None:
            with self.db:
                req = self.db.execute(
                    """
                    INSERT INTO players
                    VALUES ()
                    """
                    )

            return req.lastrowid
        else:
            return result[0]

    def register_game(self, game, ranking):
        if game["timestamp"] <= self.oldest_timestamp_to_consider:
            return None

        winner_id = self.id_from_alias[game["winner"]]
        loser_id = self.id_from_alias[game["loser"]]

        self.update_players_data(winner_id, loser_id)

        with self.db:
            self.db.execute(
                """
                INSERT OR IGNORE INTO main_ranking (player_id, rank, mu, sigma)
                VALUES (?, ?, ?, ?)
                """,
                (winner_id, *ranking.initial_state)
                )

            self.db.execute(
                """
                UPDATE main_ranking (rank, mu, sigma)
                VALUES (?, ?, ?)
                WHERE player_id=?
                """,
                (rank, mu, sigma, player_id)
            )
        loser = self.alias_to_player[game["loser"]]

        winner_old_score = winner.score
        loser_old_score = loser.score

        if (winner, loser) not in self.wins:
            self.wins[(winner, loser)] = 1
        else:
            self.wins[(winner, loser)] += 1

        self.update_players(winner, loser, timestamp=game["timestamp"])

        winner_dscore = winner.score - winner_old_score
        loser_dscore = loser.score - loser_old_score

        winner_old_rank = winner.display_rank
        loser_old_rank = loser.display_rank

        self.update_ranks(winner, winner_dscore)
        self.update_ranks(loser, loser_dscore)

        winner_rank = winner.display_rank
        loser_rank = loser.display_rank

    def fetch_player_data(self, player_id):
        req = self.db.execute(
            """
            SELECT rank, mu, sigma, score
            FROM main_ranking
            WHERE player_id=?
            """,
            (player_id,)
            )

        result = req.fetchone()
        if result is None:
            return {"rank": None,
                    "mu": 25,
                    "sigma": 25/3,
                    "score": 0}
        else:
            return result

    def update_players_data(self, winner_id, loser_id, timestamp):
        winner_data = self.fetch_player_data(winner_id)
        loser_data = self.fetch_player_data(loser_id)

        winner_rating = trueskill.Rating(mu=winner_data["mu"],
                                         sigma=loser_data["sigma"])
        loser_rating = trueskill.Rating(mu=winner_data["mu"],
                                        sigma=loser_data["sigma"])

        winner_rating, loser_rating = trueskill.rate_1vs1(winner_rating,
                                                          loser_rating)

        with self.db:
            self.db.execute(
                """
                INSERT OR IGNORE INTO main_ranking (player_id)
                VALUES (?)
                """,
                (winner_id,)
                )

            self.db.execute(
                """
                UPDATE main_ranking (rank, mu, sigma, score)
                VALUES (?, ?, ?)
                WHERE player_id=?
                """,
                (rank, mu, sigma, score, player_id)
            )



d = DataManager()
