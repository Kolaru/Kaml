from .ranking import AbstractRanking, AbstractState


class EelState(AbstractState):
    def __init__(self, score=0, rank=None, wins=0, losses=0):
        self.rank = rank
        self.wins = wins
        self.losses = losses
        self._score = score

    @property
    def level(self):
        return min(self.score // 100, 6)

    @property
    def score(self):
        return self._score


class EelRanking(AbstractRanking):
    def __init__(self, name, identity_manager,
                 **kwargs):

        super().__init__(name, identity_manager, **kwargs)

        self.point_table = {
            6: 9,
            5: 12,
            4: 17,
            3: 24,
            2: 30,
            1: 24,
            0: 20,
            -1: 18,
            -2: 15,
            -3: 8,
            -4: 4,
            -5: 2,
            -6: 1}

    def initial_player_state(self):
        return EelState()

    def update_players(self, winner, loser, timestamp=None):
        dlevel = loser.level - winner.level
        dscore = self.point_table[dlevel]

        winner.update_state(EelState(
            score=winner.score + dscore,
            wins=winner.wins + 1,
            losses=winner.losses))

        loser.update_state(EelState(
            score=loser.score - dscore,
            wins=loser.wins,
            losses=loser.losses + 1))
