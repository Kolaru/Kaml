import os
import sqlite3

DB_PATH = "data/database.db"


class DataManager:
    def __enter__(self, *args, **kwargs):
        self.db.__enter__(*args, **kwargs)

    def __exit__(self, *args, **kwargs):
        self.db.__exit__(*args, **kwargs)

    def __init__(self):
        create_new = not os.path.isfile(DB_PATH)
        self.db = sqlite3.connect(DB_PATH)

        print(f"Connection to database. Create new = {create_new}")

        if create_new:
            self.create_tables()

    def create_tables(self):
        with self.db:
            self.db.execute(
                """
                CREATE TABLE players
                (
                    player_id INTEGER PRIMARY KEY,
                    discord_id INTEGER UNIQUE,
                    display_name TEXT
                )
                """)

            self.db.execute(
                """
                CREATE TABLE aliases
                (
                    alias TEXT NOT NULL UNIQUE,
                    player_id INTEGER,
                    FOREIGN KEY (player_id) REFERENCES players (player_id)
                )
                """)

            self.db.execute(
                """
                CREATE TABLE games
                (
                    game_id INTEGER PRIMARY KEY,
                    msg_id INTEGER UNIQUE,
                    timestamp INTEGER NOT NULL,
                    winner_id INTEGER NOT NULL,
                    loser_id INTEGER NOT NULL,
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

    def execute(self, cmd, *args):
        return self.db.execute(cmd, *args)

    def executemany(self, cmd, *args):
        return self.db.executemany(cmd, *args)

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