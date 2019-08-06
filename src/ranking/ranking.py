import json
from collections import namedtuple

from player import Player
from save_and_load import save_single_game
from utils import ChainedDict

ScoreChange = namedtuple("ScoreChange", ["winner",
                                         "loser",
                                         "winner_dscore",
                                         "loser_dscore"])


class AbstractState:
    rank = None
    wins = 0
    losses = 0

    """Abstract class for a player relative to a ranking."""
    def asdict(self):
        raise NotImplementedError()

    @property
    def score(self):
        raise NotImplementedError()


class AbstractRanking:
    def __init__(self, name, identity_manager,
                 oldest_timestamp_to_consider=0,
                 mingames=0,
                 leaderboard_msgs=None,
                 leaderboard_line=None,
                 description="A ranking",
                 **kwargs):
        self.name = name
        self.save_path = f"data/rankings/{name}.json"
        self.oldest_timestamp_to_consider = oldest_timestamp_to_consider
        self.identity_manager = identity_manager
        self.mingames = mingames
        self.leaderboard_msgs = leaderboard_msgs
        self.leaderboard_line = leaderboard_line
        self.description = description

        self.wins = {}
        self.rank_to_player = dict()
        self.identity_to_player = dict()

        for identity in self.identity_manager:
            player = Player(identity, self.initial_player_state())
            self.identity_to_player[identity] = player

        self.alias_to_player = ChainedDict(self.identity_manager,
                                           self.identity_to_player)

    def __getitem__(self, identity):
        return self.identity_to_player[identity]

    def ensure_alias_existence(self, alias):
        if alias not in self.identity_manager.aliases:
            identity = self.identity_manager.add_identity(
                            discord_id=None,
                            aliases=[alias])
        else:
            identity = self.identity_manager[alias]

        if identity not in self.identity_to_player:
            player = Player(identity, self.initial_player_state())
            self.identity_to_player[identity] = player

    def initial_player_state(self):
        raise NotImplementedError()

    def leaderboard(self, start, stop):
        """Generate the string content of a leaderboard message."""
        # Convert from base 1 indexing for positive ranks
        if start >= 0:
            start -= 1

        new_content = "\n".join([self.leaderboard_line.format(player=player)
                                 for player in self.ranked_players[start:stop]])

        return f"```\n{new_content}\n```"

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

    @property
    def players(self):
        return list(self.rank_to_player.values())

    def register_game(self, game, save=True):
        if game["timestamp"] <= self.oldest_timestamp_to_consider:
            return None

        self.ensure_alias_existence(game["winner"])
        self.ensure_alias_existence(game["loser"])

        winner = self.alias_to_player[game["winner"]]
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

        change = ScoreChange(winner=winner,
                             loser=loser,
                             winner_dscore=winner_dscore,
                             loser_dscore=loser_dscore)

        self.update_ranks(winner, winner_dscore)
        self.update_ranks(loser, loser_dscore)

        if save:
            save_single_game(game)

        return change

    @property
    def ranked_players(self):
        n = len(self.rank_to_player)
        return [self.rank_to_player[k] for k in range(n)]

    def update_players(self, winner, loser, timestamp=None):
        raise NotImplementedError()

    def update_ranks(self, player, dscore):
        if player.total_games < self.mingames:
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
            other.rank = k - inc
            self.rank_to_player[other.rank] = other
        else:
            k -= inc

        player.rank = k
        self.rank_to_player[k] = player

        if k > 0:
            if player.score > self.rank_to_player[k - 1].score:
                for rank, player in self.rank_to_player.items():
                    print(f"{rank}    : {player}")
                raise Exception(
                    f"{player} not reranked correctly from {old_rank}"
                    f"(dscore = {dscore}, inc = {inc}).")

        if k < N - 1:
            if player.score < self.rank_to_player[k + 1].score:
                for rank, player in self.rank_to_player.items():
                    print(f"{rank}    : {player}")
                raise Exception(
                    f"{player} not reranked correctly from {old_rank}"
                    f"(dscore = {dscore}, inc = {inc}).")

    def save(self):
        with open(self.save_path, "w", encoding="utf-8") as file:
            json.dump([p.asdict() for p in self.players], file)
