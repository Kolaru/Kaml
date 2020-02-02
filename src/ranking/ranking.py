from bisect import bisect

from pandas import concat, DataFrame

from utils import logger


class AbstractRanking:
    def __init__(self, name,
                 players=None,
                 oldest_timestamp_to_consider=0,
                 mingames=0,
                 leaderboard_msgs=None,
                 leaderboard_line=None,
                 description="A ranking",
                 **kwargs):
        self.name = name
        self.oldest_timestamp_to_consider = oldest_timestamp_to_consider
        self.mingames = mingames
        self.leaderboard_msgs = leaderboard_msgs
        self.leaderboard_line = leaderboard_line
        self.description = description

        self.players = players
        for player_id in players.index:
            self.add_player(player_id)

    def add_player(self, player_id):
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

    def process_scores(elf, winner_id, loser_id, timestamp):
        raise NotImplementedError()

    def register_game(self, game):
        if game["timestamp"] <= self.oldest_timestamp_to_consider:
            return None

        winner_score, loser_score = self.process_scores(game["winner_id"],
                                                        game["loser_id"],
                                                        game["timestamp"])

        winner_data = self.ranking.loc(game["winner_id"])
        loser_data = self.ranking.loc(game["loser_id"])

        winner_data["n_games"] += 1
        loser_data["n_games"] += 1

        if winner_data["n_games"] >= self.mingames:
            winner_data["score"] = winner_score
            self.rerank_players(winner_data)

        if loser_data["n_games"] >= self.mingames:
            loser_data["score"] = loser_score
            self.rerank_players(loser_data)

    def register_many(self, games):
        raise NotImplementedError

    def rerank_players(self, player_data):
        try:
            self.ranking.drop(player_data.name, inplace=True)
            scores = self.ranking["score"].values
            rank = bisect(scores, player_data["score"])
            self.ranking = concat([
                self.ranking[:rank],
                DataFrame(player_data).T,
                self.ranking[rank+1:]])

        except Exception:
            logger.error(
                f"""
                An errored occured while reranking players.

                Players
                {self.ranking}

                Player
                {player_data}

                """)
            raise

    # def get_kamlboard_stuff(self):
    #     # There are 3 potential scenarios:
    #     # 1) a player was ranked None and continues to be None (X more games for rank assignment)
    #     # 2) a player was ranked None and obtains a rank (⮝ to new rank)
    #     # 3) a player rises or falls in an existing rank (⮝ or ⮞0 or ⮟)

    #     # Scenario 1
    #     if winner.total_games < self.mingames:
    #         winner_drank = str(self.mingames - winner.total_games) + " more games required"
    #     # Scenario 2
    #     elif winner.total_games == self.mingames or winner_old_rank is None:
    #         winner_drank = "▲" + str(winner_rank)
    #     # Scenario 3
    #     elif winner_rank == winner_old_rank:
    #         winner_drank = "➤0"
    #     elif winner_rank < winner_old_rank:  # they are placed higher
    #         winner_drank = "▲" + str(abs(winner_old_rank - winner_rank))
    #     else:  # they are placed lower
    #         winner_drank = "▼" + str(winner.rank - winner_old_rank)

    #     # Scenario 1
    #     if loser.total_games < self.mingames:
    #         loser_drank = str(self.mingames - loser.total_games) + " more games required"
    #     # Scenario 2
    #     elif loser.total_games == self.mingames or loser_old_rank is None:
    #         loser_drank = "▲" + str(loser_rank)
    #     # Scenario 3
    #     elif loser_rank == loser_old_rank:
    #         loser_drank = "➤0"
    #     elif loser_rank > loser_old_rank:  # they have placed lower
    #         loser_drank = "▼" + str(abs(loser_rank - loser_old_rank))
    #     else:  # they have placed higher
    #         loser_drank = "▲" + str(loser_old_rank - loser.rank)

    #     h2h_record = f"{self.wins.get((winner, loser),0)} – {self.wins.get((loser, winner),0)}"

    #     change = ScoreChange(winner=winner,
    #                          loser=loser,
    #                          winner_dscore=winner_dscore,
    #                          loser_dscore=loser_dscore,
    #                          winner_rank=winner_rank,
    #                          loser_rank=loser_rank,
    #                          winner_drank=winner_drank,
    #                          loser_drank=loser_drank,
    #                          h2h_record=h2h_record)

    #     return change