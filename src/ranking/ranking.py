import numpy as np
import pandas as pd

from sortedcontainers import SortedList

from utils import logger


class AbstractRanking:
    """
    Super class of all ranking.

    Additional keyword parameters are ignored.

    Arguments
    =========
    name: str
        The unique name of the ranking.

    Keyword arguments
    =================
    bot: Kamlbot
        The discord Kamlbot using the ranking. Used to access discord related
        information about the players.
    description: str
        The description of the ranking.
    earliest_timestamp: Unix timestamp
        The timestamp before which games are registered in the ranking.
        TODO Implement this.
    history_dataframe: pandas.DataFrame
        The dataframe used to store the history of this ranking. The following
        columns are required:
            = timestamp
            = winner_id
            - winner_rank
            - winner_score
            = loser_id
            - loser_rank
            - loser_score
    leaderboard_line: template string
        The template used to display player informations in the leaderboard.
    leaderboard_msgs: list of dict
        A list of dict, each representing on of the discord messages used to
        display this ranking leaderboard.
    mingames: int
        The minimum number of games players must play berfore they rank start
        being computed.
    oldest_timestamp: Unix timestamp
        The timestamp after which games are registered in the ranking.
    ranking_dataframe: pandas.DataFrame
        The dataframe used to represent the ranking internally. The following
        columns are required:
            - rank
            - score
            - n_games
    """
    def __init__(self, name,
                 bot=None,
                 description="A ranking",
                 earliest_timestamp=np.Inf,
                 history_dataframe=None,
                 leaderboard_line=None,
                 leaderboard_msgs=None,
                 mingames=0,
                 oldest_timestamp=0,
                 ranking_dataframe=None,
                 **kwargs):
        logger.info(f"Generic initialization of the ranking named {name}")

        self.bot = bot
        self.description = description
        self.earliest_timestamp = earliest_timestamp
        self.history = history_dataframe
        self.leaderboard_line = leaderboard_line
        self.leaderboard_msgs = leaderboard_msgs
        self.mingames = mingames
        self.name = name
        self.oldest_timestamp = oldest_timestamp
        self.ranking = ranking_dataframe

        # Fetch all players already known to the bot and add them
        for player_id in bot.players.index:
            self.add_new_player(player_id)

        # Sorted list of scores sorted from highest to lowest
        self.sorted_scores = SortedList([], key=lambda s: -s)

        # Add the scores of all ranked players with enough games
        for player_id, player_data in self.ranking.iterrows():
            if player_data["n_games"] >= self.mingames:
                self.sorted_scores.add(player_data["score"])

    def add_new_player(self, player_id):
        """
        Add a new player to the ranking with the given player ID.

        New player must be initialized with
            rank = np.nan
            n_games = 0

        Must be implemented by subclasses.

        Arguments
        =========
        player_id: int
            The ID of the player to be added.
        """
        raise NotImplementedError()

    def apply_new_states(self, game_id, winner_state, loser_state):
        """
        Apply ranking specific change to the ranking and history dataframes.

        As opposed to the `compute_player_states` function, this one is allowed
        to have side effect and can rely on the fact entries for the game
        resulting in the given states have been added to the dataframes.

        Arguments
        =========
        game_id: int
            ID of the game that resulting in the given states. Is used to index
            the game in the history DataFrame.
        winner_state: dict
            State of the winner returned by the compute_player_states function.
        loser_state: dict
            State of the loser returned by the compute_player_states function.
        """

    def compute_player_states(self, winner_id, loser_id):
        """
        Compute the new states of the players involved in a game during which
        the player with ID `winner_id` won against the player with ID
        `loser_id`.

        This function must not have any side effect, to make sure that
        the generic `AbstractRanking.register_game` method works as expected.

        Must return a dict with a field "score". This dict will later be passed
        to the `AbstractRanking.apply_new_states` method in which additional
        updates can be performed with side effects.

        Must be implemented by subclasses.

        Arguments
        =========
        winner_id: int
        loser_id: int
        """
        raise NotImplementedError()

    def leaderboard(self, start, stop):
        """
        Generate a string containing the leaderboard between rank `start` and
        `stop`.

        Must be implemented by subclasses.

        Arguments
        =========
        start: int
        stop: int
        """
        raise NotImplementedError()

    def register_game(self, winner_id=0, loser_id=0, timestamp=0, **kwargs):
        """
        Register a game in the ranking.

        Keywords arguments
        ==================
        winner_id: int
        loser_id: int
        timestamp: int

        Additional keyword arguments are ignored.
        """
        # Ignore games that are outside the considered period
        # if not (self.oldest_timestamp <= timestamp < self.earliest_timestamp):
        #     return None

        # Add missing players
        if winner_id not in self.ranking.index:
            self.add_new_player(winner_id)

        if loser_id not in self.ranking.index:
            self.add_new_player(loser_id)

        # Request the new player states from method implemented by the subclass
        winner_state, loser_state = self.compute_player_states(
            winner_id,
            loser_id)

        winner_score = winner_state["score"]
        loser_score = loser_state["score"]

        self.ranking.loc[winner_id, "n_games"] += 1
        self.ranking.loc[loser_id, "n_games"] += 1

        # When the old score is not None that means this player was already
        # When the old rank is not NaN, that means this player was already
        # previously ranked. Thus we remove their score from the score list
        # and when we insert it again it will be correctly ranked. 
        winner_old_rank = self.ranking.loc[winner_id, "rank"]

        if not np.isnan(winner_old_rank):
            winner_old_score = self.ranking.loc[winner_id, "score"]
            self.sorted_scores.remove(winner_old_score)

        loser_old_rank = self.ranking.loc[loser_id, "rank"]

        if not np.isnan(loser_old_rank):
            loser_old_score = self.ranking.loc[loser_id, "score"]
            self.sorted_scores.remove(loser_old_score)

        # We don't need the old score anymore so we can overwrite it.
        self.ranking.loc[winner_id, "score"] = winner_score
        self.ranking.loc[loser_id, "score"] = loser_score

        # By default a player rank is None, it got a value only if the player
        # played enough games.
        winner_state["rank"] = None
        loser_state["rank"] = None

        winner_is_ranked = self.ranking.loc[winner_id, "n_games"] >= self.mingames
        loser_is_ranked = self.ranking.loc[loser_id, "n_games"] >= self.mingames

        # Both scores must be added before further processing to ensure the
        # ranks are correct in all cases.
        if winner_is_ranked:
            self.sorted_scores.add(winner_score)

        if loser_is_ranked:
            self.sorted_scores.add(loser_score)

        # Rank information is updated.
        if winner_is_ranked:
            winner_rank = self.sorted_scores.index(winner_score)
            self.ranking.loc[winner_id, "rank"] = winner_rank
            winner_state["rank"] = winner_rank

        if loser_is_ranked:
            loser_rank = self.sorted_scores.index(loser_score)
            self.ranking.loc[loser_id, "rank"] = loser_rank
            loser_state["rank"] = loser_rank

        # Game IDs are incremented by one when the new game is appended
        game_id = len(self.history)

        # Add common information to the history dataframe
        self.history = self.history.append(
            dict(
                timestamp=timestamp,
                winner_id=winner_state["id"],
                winner_rank=winner_state["rank"],
                winner_score=winner_state["score"],
                loser_id=loser_state["id"],
                loser_rank=loser_state["rank"],
                loser_score=loser_state["score"]
            ),
            ignore_index=True
        )

        # Now that all informations common to all rankings
        # have been updated, we can let the subclass apply these new states
        # without worrying about the side effects.
        self.apply_new_states(game_id, winner_state, loser_state)

    async def update_leaderboard(self):
        """
        Update the leaderboard messages of the ranking with up to date
        information.
        """
        for msg in self.leaderboard_msgs:
            T = msg["type"]

            if T == "header":
                pass
            elif T == "content":
                msg["content"] = self.leaderboard(msg["min"], msg["max"])
                await msg["msg"].edit(content=msg["content"])
            else:
                raise KeyError(f"Leaderboard message of unkown type {T} "
                               f"in Ranking {self.name}.")

    # def register_many(self, games):
    #     raise NotImplementedError

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