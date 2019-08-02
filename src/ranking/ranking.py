import json
import os
from collections import namedtuple, OrderedDict

from messages import msg_builder
from player import Player
from save_and_load import save_single_game
from utils import ChainedDict
from utils import emit_signal, logger

MINGAMES = 10

os.makedirs("rankings", exist_ok=True)

ScoreChange = namedtuple("ScoreChange", ["winner",
                                         "loser",
                                         "winner_dscore",
                                         "loser_dscore"])


class AbstractState:
    rank = 0

    """Abstract class for a player relative to a ranking."""
    def asdict(self):
        raise NotImplementedError()

    @property
    def score(self):
        raise NotImplementedError()


class AbstractRanking:
    def __init__(self, name, identity_manager,
                 oldest_timestamp_to_consider=0,
                 leaderboard_msgs=None, description="A ranking",
                 **kwargs):
        self.name = name
        self.save_path = f"data/rankings/{name}.json"
        self.oldest_timestamp_to_consider = oldest_timestamp_to_consider
        self.identity_manager = identity_manager
        self.leaderboard_msgs = leaderboard_msgs
        self.description = description

        self.identity_to_player = dict()
        self.rank_to_player = OrderedDict()
        self.wins = {}

        self.alias_to_player = ChainedDict(self.identity_manager,
                                           self.identity_to_player)

    def __getitem__(self, identity):
        return self.identity_to_player[identity]

    def add_player(self, discord_id=None, aliases=None):
        identity = self.identity_manager.add_identity(
                            discord_id=discord_id,
                            aliases=aliases)

        player = Player(identity, self.initial_player_state())
        self.identity_to_player[identity] = player

    def ensure_alias_existence(self, alias):
        if alias not in self.identity_manager.aliases:
            self.add_player(aliases=set(alias))

    def initial_player_state(self):
        raise NotImplementedError()

    def leaderboard(self, start, stop):
        """Generate the string content of a leaderboard message."""
        # Convert from base 1 indexing for positive ranks
        if start >= 0:
            start -= 1

        new_content = "\n".join([msg_builder.build("leaderboard_line",
                                                   player=player)
                                 for player in self[start:stop]])

        return f"```\n{new_content}\n```"

    @property
    def players(self):
        return list(self.rank_to_player.values())

    def register_game(self, game, save=True, signal_update=True):
        if game["timestamp"] <= self.oldest_timestamp_to_consider:
            return None

        self.ensure_alias_existence(game["winner"])
        self.ensure_alias_existence(game["loser"])

        winner = self.alias_to_player(game["winner"])
        loser = self.alias_to_player(game["loser"])

        winner_old_rank = winner.rank
        loser_old_rank = loser.rank

        winner.save_state(game["timestamp"], winner_old_rank)
        loser.save_state(game["timestamp"], loser_old_rank)

        if (winner, loser) not in self.wins:
            self.wins[(winner, loser)] = 1
        else:
            self.wins[(winner, loser)] += 1

        winner_old_score = winner.score
        loser_old_score = loser.score

        self.update_players(winner, loser)

        winner.wins += 1
        loser.losses += 1

        winner_dscore = winner.score - winner_old_score
        loser_dscore = loser.score - loser_old_score

        change = ScoreChange(winner=winner,
                             loser=loser,
                             winner_dscore=winner_dscore,
                             loser_dscore=loser_dscore)

        self.update_ranks(winner, winner_dscore)
        self.update_ranks(loser, loser_dscore)

        if save:
            await save_single_game(game)
            await emit_signal("game_registered", change)

        if signal_update:
            await emit_signal("rankings_updated")

        return change

    def leaderboard_messages(self):
        msgs = []

        for m in self.leaderboard_msgs:
            msg = dict(id=m["id"])
            T = m["type"]

            if T == "header":
                msg["content"] = self.description
            elif T == "content":
                msg["content"] = self.leaderboard(m["min"], m["max"])
            else:
                raise KeyError(f"Leaderboard message of unkown type {T}"
                               f"(id: {m['id']}) in Ranking {self.name}.")

            msgs.append(msg)

        return msgs

    def update_players(self, winner, loser):
        raise NotImplementedError()

    def update_ranks(self, player, dscore):
        if player.total_games < MINGAMES:
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
            assert player.score <= self.rank_to_player[k - 1].score

        if k < N - 1:
            assert player.score >= self.rank_to_player[k + 1].score

    def save(self):
        with open(self.save_path, "w", encoding="utf-8") as file:
            json.dump([p.asdict() for p in self.players], file)
