from bisect import bisect

class AbstractRanking:
    def __init__(self, name, data_manager,
                 oldest_timestamp_to_consider=0,
                 mingames=0,
                 leaderboard_msgs=None,
                 leaderboard_line=None,
                 description="A ranking",
                 **kwargs):
        self.name = name
        self.ranking_table = name + "_ranking"
        self.history_table = name + "_history"
        self.oldest_timestamp_to_consider = oldest_timestamp_to_consider
        self.db = data_manager
        self.mingames = mingames
        self.leaderboard_msgs = leaderboard_msgs
        self.leaderboard_line = leaderboard_line
        self.description = description

    def get(self, player_id, attr):
        req = self.db.execute(
            f"""
            SELECT {attr}
            FROM {self.ranking_table}
            WHERE player_id=?
            """,
            player_id
            )

        return req.fetchone()[0]

    def initial_player_state(self):
        raise NotImplementedError()

    def leaderboard(self, start, stop):
        """Generate the string content of a leaderboard message."""
        raise NotImplementedError()

    def leaderboard_messages(self):
        msgs = []

        for m in self.leaderboard_msgs:
            T = m["type"]

            if T == "header":
                pass
            elif T == "content":
                m["content"] = self.leaderboard(m["min"], m["max"])
            else:
                raise KeyError(f"Leaderboard message of unkown type {T} "
                               f"in Ranking {self.name}.")

            msgs.append(m)

        return msgs

    # Should not error if one of the player id is not in DB
    def process_game(elf, winner_id, loser_id, timestamp):
        raise NotImplementedError()

    def register_game(self, game):
        if game["timestamp"] <= self.oldest_timestamp_to_consider:
            return None

        winner_score, loser_score = self.process_game(game["winner_id"],
                                                      game["loser_id"],
                                                      game["timestamp"])

        req = self.db.execute(
            f"""
            SELECT total_games
            FROM players
            WHERE player_id=?
            """,
            ((game["winner_id"],), (game["loser_id"],))
            )

        rank_winner, rank_loser = [row[0] + 1 >= self.mingames for row in req]

        if rank_winner or rank_loser:
            req = self.db.execute(
                f"""
                SELECT score, player_id
                FROM {self.ranking_table}
                WHERE player_id != ? AND player_id != ? AND rank IS NOT NULL
                ORDER BY score ASC
                """,
                (game["winner_id"], game["loser_id"])
                )

            scores, player_ids = zip(*req.fetchall())
            if rank_winner:
                winner_rank, scores, player_ids = self.rerank_players(
                                            scores, player_ids,
                                            winner_score, game["winner_id"])

            if rank_loser:
                loser_rank, scores, player_ids = self.rerank_players(
                                            scores, player_ids,
                                            loser_score, game["loser_id"])

            # If loser_rank get inserted before winner_rank it shifts it by one
            try:
                if winner_rank > loser_rank:
                    winner_rank += 1
            except TypeError:
                pass

            with self.db:
                self.db.execute(
                    f"""
                    UPDATE {self.history_table}
                    SET winner_rank=?, loser_rank=?
                    WHERE timestamp=?
                    """,
                    (winner_rank, loser_rank, game["timestamp"])
                )

                self.db.executemany(
                    f"""
                    UPDATE {self.ranking_table}
                    SET rank=?
                    WHERE player_id=?
                    """,
                    [(k+1, player_id) for k, player_id in player_ids]
                    )

    def register_many(self, games):
        raise NotImplementedError

    def rerank_players(self, scores, player_ids, player_score, player_id):
        rank = bisect(scores, player_score)
        scores.insert(rank, player_score)
        player_ids.insert(rank, player_id)

        return rank + 1, scores, player_ids

    def get_kamlboard_stuff(self):
        # There are 3 potential scenarios:
        # 1) a player was ranked None and continues to be None (X more games for rank assignment)
        # 2) a player was ranked None and obtains a rank (⮝ to new rank)
        # 3) a player rises or falls in an existing rank (⮝ or ⮞0 or ⮟)

        # Scenario 1
        if winner.total_games < self.mingames:
            winner_drank = str(self.mingames - winner.total_games) + " more games required"
        # Scenario 2
        elif winner.total_games == self.mingames or winner_old_rank is None:
            winner_drank = "▲" + str(winner_rank)
        # Scenario 3
        elif winner_rank == winner_old_rank:
            winner_drank = "➤0"
        elif winner_rank < winner_old_rank:  # they are placed higher
            winner_drank = "▲" + str(abs(winner_old_rank - winner_rank))
        else:  # they are placed lower
            winner_drank = "▼" + str(winner.rank - winner_old_rank)

        # Scenario 1
        if loser.total_games < self.mingames:
            loser_drank = str(self.mingames - loser.total_games) + " more games required"
        # Scenario 2
        elif loser.total_games == self.mingames or loser_old_rank is None:
            loser_drank = "▲" + str(loser_rank)
        # Scenario 3
        elif loser_rank == loser_old_rank:
            loser_drank = "➤0"
        elif loser_rank > loser_old_rank:  # they have placed lower
            loser_drank = "▼" + str(abs(loser_rank - loser_old_rank))
        else:  # they have placed higher
            loser_drank = "▲" + str(loser_old_rank - loser.rank)

        h2h_record = f"{self.wins.get((winner, loser),0)} – {self.wins.get((loser, winner),0)}"

        change = ScoreChange(winner=winner,
                             loser=loser,
                             winner_dscore=winner_dscore,
                             loser_dscore=loser_dscore,
                             winner_rank=winner_rank,
                             loser_rank=loser_rank,
                             winner_drank=winner_drank,
                             loser_drank=loser_drank,
                             h2h_record=h2h_record)

        return change