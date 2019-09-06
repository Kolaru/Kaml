from .ranking import AbstractRanking


class DuchuRanking(AbstractRanking):
    def __init__(self, name, identity_manager,
                 **kwargs):

        super().__init__(name, identity_manager, **kwargs)

        self.unexpected_points = {
            1.00: 20,
            0.99: 22,
            0.98: 23,
            0.97: 24,
            0.96: 26,
            0.95: 28,
            0.94: 29,
            0.93: 31,
            0.92: 29,
            0.91: 28,
            0.9: 26,
            0.89: 24,
            0.88: 23,
            0.87: 22,
            0.86: 20,
            0.85: 19,
            0.84: 18,
            0.83: 17,
            0.82: 16,
            0.81: 15,
            0.8: 14,
            0.79: 13,
            0.78: 13,
            0.77: 12,
            0.76: 11,
            0.75: 10,
            0.74: 10,
            0.73: 9,
            0.72: 9,
            0.71: 8,
            0.7: 8,
            0.69: 7,
            0.68: 7,
            0.67: 6,
            0.66: 6,
            0.65: 5,
            0.64: 5,
            0.63: 5,
            0.62: 4,
            0.61: 4,
            0.6: 4,
            0.59: 4,
            0.58: 3,
            0.57: 3,
            0.56: 3,
            0.55: 3,
            0.54: 2,
            0.53: 2,
            0.52: 2,
            0.51: 2,
            0.5: 2,
            0.49: 2,
            0.48: 2,
            0.47: 2,
            0.46: 1,
            0.45: 1,
            0.44: 1,
            0.43: 1,
            0.42: 1,
            0.41: 1,
            0.4: 1,
            0.39: 1,
            0.38: 1,
            0.37: 1,
            0.36: 1,
            0.35: 1,
            0.34: 1,
            0.33: 1,
            0.32: 1,
            0.31: 1,
            0.3: 1,
            0.29: 1,
            0.28: 1,
            0.27: 1,
            0.26: 1,
            0.25: 1,
            0.24: 1,
            0.23: 1,
            0.22: 1,
            0.21: 1,
            0.2: 1,
            0.19: 1,
            0.18: 1,
            0.17: 1,
            0.16: 1,
            0.15: 1,
            0.14: 1,
            0.13: 1,
            0.12: 1,
            0.11: 1,
            0.1: 1,
            0.09: 1,
            0.08: 1,
            0.07: 1,
            0.06: 1,
            0.05: 1,
            0.04: 1,
            0.03: 1,
            0.02: 1,
            0.01: 1
            }

        self.expected_points = dict(self.unexpected_points)

        for r, pt in self.unexpected_points.items():
            if r >= 0.86:
                self.expected_points[r] = 40 - pt

    def initial_player_state(self):
        return DuchuState()

    def update_players(self, winner, loser, timestamp=None):
        if winner.score > loser.score:
            ratio = loser.score/winner.score
            ratio = round(ratio, 2)
            dscore = self.expected_points[ratio]
        else:
            ratio = winner.score/loser.score
            ratio = round(ratio, 2)
            dscore = self.expected_points[ratio]

        winner.update_state(DuchuState(
            rank=winner.rank,
            score=winner.score + dscore,
            wins=winner.wins + 1,
            losses=winner.losses))

        loser.update_state(DuchuState(
            rank=loser.rank,
            score=max(0, loser.score - dscore),
            wins=loser.wins,
            losses=loser.losses + 1))
