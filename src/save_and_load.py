import json
import re

from collections import OrderedDict

from utils import logger

## Parsing

WIN_PATTERN = re.compile(r":crown: \*\*(.+)\*\* \(.+\) vs \*\*(.+)\*\* \(.+\)")
LOSS_PATTERN = re.compile(r"\*\*(.+)\*\* \(.+\) vs :crown: \*\*(.+)\*\* \(.+\)")
HALF_WIN_PATTERN = re.compile(r":crown: \*\*(.+)\*\* \(.+\) has won a match!")
HALF_LOSS_PATTERN = re.compile(r"\*\*(.+)\*\* \(.+\) has lost a match.")
MENTION_PATTERN = re.compile(r"<@(.+)>")


def clean_name(s):
    if s is None:
        return None
    return s.strip().replace(",", "_").replace("\n", " ")


def leaderboard_name(self):
    text = self.display_name
    text_len = wcswidth(self.display_name)

    one_space_count = 0
    two_space_count = 0
    for char in text:
        char_len = wcwidth(char)
        if char_len == 1:
            one_space_count += 1
        elif char_len == 2:
            two_space_count += 1
    is_asian = two_space_count > one_space_count

    width_size = 20
    if is_asian:  # must be 22 width (width_size + 2)
        if text_len > (width_size + 2):  # add characters until 22
            current_len = 0
            formatted_text = u""
            for char in text:
                formatted_text += char
                current_len += wcwidth(char)
                if current_len == (width_size + 2):
                    break
                elif current_len == (width_size + 3):
                    formatted_text = formatted_text[:-1] + u" "
                    break
            return formatted_text
        elif text_len < (width_size + 2):  # add ideographic space (　) until 22 or 21
            current_len = text_len
            formatted_text = text
            while current_len != (width_size + 2):
                formatted_text += u"　"
                current_len += 2
                if current_len == (width_size + 3):
                    formatted_text = formatted_text[:-1] + u" "
                    break
            return formatted_text
    elif not is_asian:  # must be 20 width
        if text_len > width_size:
            return text[:width_size]
        elif text_len < width_size:
            return text + u" " * (width_size - text_len)
        else:
            return text


def parse_matchboard_msg(msg):
    """Parse a message on the matchboard, return the result as the tuple
    `winner, loser` or `None` if winner and loser can not be determined.
    """
    if len(msg.embeds) == 0:
        return None

    logger.debug(msg.embeds[0].to_dict())
    winner, loser = None, None

    result = msg.embeds[0].description
    m = re.match(WIN_PATTERN, result)
    if m is not None:
        winner, loser = m.group(1, 2)
    else:
        m = re.match(LOSS_PATTERN, result)
        if m is not None:
            winner, loser = m.group(2, 1)

    if winner is None:
        m = re.match(HALF_WIN_PATTERN, result)
        if m is not None:
            winner = m.group(1)

    if loser is None:
        m = re.match(HALF_LOSS_PATTERN, result)
        if m is not None:
            loser = m.group(1)

    # Strip comma from game names to avoid messing the csv
    winner = clean_name(winner)
    loser = clean_name(loser)

    return OrderedDict(timestamp=int(msg.created_at.timestamp()),
                       id=msg.id,
                       winner=winner,
                       loser=loser)


def parse_mention_to_id(mention):
    m = re.match(MENTION_PATTERN, mention)

    if m is None:
        return None

    return int(m.group(1))


## File reading/writing

async def fetch_game_results(matchboard, after=None):
    game_results = []
    history = matchboard.history(oldest_first=True,
                                 after=after,
                                 limit=None)

    async for msg in history:
        game = parse_matchboard_msg(msg)

        if game is None:
            continue

        game["msg_id"] = msg.id
        game_results.append(game)

    return game_results


def load_ranking_configs():
    with open("config/ranking_config.json", "r", encoding="utf-8") as file:
        configs = json.load(file)
    return configs


def load_tokens():
    with open("config/tokens.json", "r", encoding="utf-8") as file:
        d = json.load(file)
    return d
