import os
import sqlite3

DB_PATH = "data/database.db"


class DataManager:
    def __init__(self):
        create_new = not os.isfile(DB_PATH)
        self.db = sqlite3.connect(DB_PATH)

        if create_new:
            self.create_tables()

    def create_tables(self):
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
                    FOREIGN KEY (player_id) REFERENCES players (player_id)
                )
                """)

            self.db.execute(
                """
                CREATE TABLE games
                (
                    game_id int,
                    msg_id int UNIQUE,
                    timestamp int NOT NULL,
                    winner_id int NOT NULL,
                    loser_id int NOT NULL,
                    PRIMARY KEY (game_id),
                    FOREIGN KEY (winner_id) REFERENCES players (player_id),
                    FOREIGN KEY (loser_id) REFERENCES players (player_id)
                )
                """
                )

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

    def execute(self, cmd, arg):
        return self.db.execute(cmd, arg)

    def id_from_alias(self, alias):
        req = self.db.execute(
            """
            SELECT player_id
            FROM aliases
            WHERE alias=?
            """,
            (alias,)
            )

        result = req.fetchone()
        if result is None:
            with self.db:
                req = self.db.execute(
                    """
                    INSERT INTO players (display_name)
                    VALUES (?)
                    """,
                    (alias,))

                player_id = req.lastrowid

                self.db.execute(
                    """
                    INSERT INTO aliases (player_id, alias)
                    VALUES (?, ?)
                    """,
                    (player_id, alias)
                    )

            return player_id
        else:
            return result[0]

    def id_from_discord_id(self, discord_id):
        req = self.db.execute(
            """
            SELECT player_id
            FROM players
            WHERE discord_id=?
            """,
            (discord_id,))

        result = req.fetchone()
        if result is None:
            return None
        else:
            return result[0]