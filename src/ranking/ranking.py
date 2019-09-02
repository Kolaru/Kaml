import json
from collections import namedtuple, deque

from player import Player
from utils import ChainedDict

ScoreChange = namedtuple("ScoreChange", ["winner",
                                         "loser",
                                         "winner_dscore",
                                         "loser_dscore",
                                         "winner_rank",
                                         "loser_rank",
                                         "winner_drank",
                                         "loser_drank",
                                         "h2h_record",
                                         "h2h_history_len",
                                         "h2h_history"])


class AbstractState:
    """Abstract class for a player relative to a ranking."""
    rank = None
    wins = 0
    losses = 0

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
        self.wins_history = {}
        self.rank_to_player = dict()
        self.identity_to_player = dict()

        for identity in self.identity_manager:
            player = Player(identity, self.initial_player_state())
            self.identity_to_player[identity] = player

        self.alias_to_player = ChainedDict(self.identity_manager,
                                           self.identity_to_player)

    def __getitem__(self, identity):
        return self.identity_to_player[identity]

    def asdict(self):
        players = [p.asdict() for p in self.players]
        return dict(name=self.name,
                    players=players,
                    wins=self.wins
                    )

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

    def register_game(self, game):
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

        if (winner, loser) in self.wins_history or (loser, winner) in self.wins_history:
            self.wins_history[(winner, loser)] = deque('1', maxlen=15)
            invert_history = False
        elif (winner, loser) in self.wins_history:
            self.wins_history[(winner, loser)].appendleft('1')
            invert_history = False
        elif (loser, winner) in self.wins_history:
            self.wins_history[(loser, winner)].appendleft('0')
            invert_history = True

        self.update_players(winner, loser, timestamp=game["timestamp"])

        winner_dscore = winner.score - winner_old_score
        loser_dscore = loser.score - loser_old_score

        winner_old_rank = winner.display_rank
        loser_old_rank = loser.display_rank

        self.update_ranks(winner, winner_dscore)
        self.update_ranks(loser, loser_dscore)

        winner_rank = winner.display_rank
        loser_rank = loser.display_rank

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

        if not invert_history:
            h2h_history_len = len(self.wins_history[(winner, loser)])
            h2h_history = "".join(self.wins_history[(winner, loser)])
            h2h_history = h2h_history.replace("1", ":crown:").replace("0", ":meat_on_bone:")
        elif invert_history:
            h2h_history_len = len(self.wins_history[(loser, winner)])
            h2h_history = "".join(self.wins_history[(loser, winner)])
            h2h_history = h2h_history.replace("1", ":meat_on_bone:").replace("0", ":crown:")

        change = ScoreChange(winner=winner,
                             loser=loser,
                             winner_dscore=winner_dscore,
                             loser_dscore=loser_dscore,
                             winner_rank=winner_rank,
                             loser_rank=loser_rank,
                             winner_drank=winner_drank,
                             loser_drank=loser_drank,
                             h2h_record=h2h_record,
                             h2h_history_len=h2h_history_len,
                             h2h_history=h2h_history)

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

        other_score = other.score
        player_score = player.score
        if other_score*inc > player_score*inc:
            other.rank = k - inc
            self.rank_to_player[other.rank] = other
        else:
            k -= inc

        player.rank = k
        self.rank_to_player[k] = player

        if k > 0:
            if player_score > self.rank_to_player[k - 1].score:
                for rank, player in self.rank_to_player.items():
                    print(f"{rank}    : {player}")
                raise Exception(
                    f"{player} not reranked correctly from {old_rank}"
                    f"(dscore = {dscore}, inc = {inc}).")

        if k < N - 1:
            if player_score < self.rank_to_player[k + 1].score:
                for rank, player in self.rank_to_player.items():
                    print(f"{rank}    : {player}")
                raise Exception(
                    f"{player} not reranked correctly from {old_rank}"
                    f"(dscore = {dscore}, inc = {inc}).")

    def save(self):
        with open(self.save_path, "w", encoding="utf-8") as file:
            json.dump([p.asdict() for p in self.players], file)
