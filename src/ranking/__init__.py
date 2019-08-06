from .trueskill_ranking import TrueSkillRanking
from .eel_ranking import EelRanking
from .duchu_ranking import DuchuRanking

ranking_types = dict(trueskill=TrueSkillRanking,
                     eel=EelRanking,
                     duchu=DuchuRanking)
