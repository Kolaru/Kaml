import json
import re
import pandas as pd

from collections import OrderedDict

from utils import logger

## Parsing

# WIN_PATTERN = re.compile(r":crown: \*\*(.+)\*\* \(.+\) vs \*\*(.+)\*\* \(.+\)")
# LOSS_PATTERN = re.compile(r"\*\*(.+)\*\* \(.+\) vs :crown: \*\*(.+)\*\* \(.+\)")
# HALF_WIN_PATTERN = re.compile(r":crown: \*\*(.+)\*\* \(.+\) has won a match!")
# HALF_LOSS_PATTERN = re.compile(r"\*\*(.+)\*\* \(.+\) has lost a match.")
# MENTION_PATTERN = re.compile(r"<@(.+)>")
WIN_PATTERN = r":crown: \*\*(.+)\*\* \(.+\) vs \*\*(.+)\*\* \(.+\)"
LOSS_PATTERN = r"\*\*(.+)\*\* \(.+\) vs :crown: \*\*(.+)\*\* \(.+\)"
HALF_WIN_PATTERN = r":crown: \*\*(.+)\*\* \(.+\) has won a match!"
HALF_LOSS_PATTERN = r"\*\*(.+)\*\* \(.+\) has lost a match."
MENTION_PATTERN = r"<@(.+)>"


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

    # return OrderedDict(timestamp=int(msg.created_at.timestamp()),
    #                    id=msg.id,
    #                    winner=winner,
    #                    loser=loser)

    return {
        "timestamp":int(msg.created_at.timestamp()),
        "id":msg.id,
        "winner":winner,
        "loser":loser
    }


def assign_regex_pattern(s):
    """Takes a series of matchboard descriptions and returns a series
    corresponding to the regex pattern to be used for processing it.

    Args:
        s (Series): Series of matchboard descriptions

    Returns:
        regex_pat (Series): 0 for WIN_PATTERN, 
                            1 for LOSS_PATTERN,
                            2 for HALF_WIN_PATTERN,
                            3 for HALF_LOSS_PATTERN
    """
    regex_pat = s.copy()
    regex_pat[s.str.contains('has won a match!', regex=False)] = 2
    regex_pat[s.str.contains('has lost a match.', regex=False)] = 3
    regex_pat[regex_pat.str.startswith(':crown:', na=False)] = 0
    regex_pat[s.str.contains('vs :crown:', regex=False)] = 1
    regex_pat[~regex_pat.isin([0,1,2,3])] = -1  # does not fit any pattern
    regex_pat = regex_pat.convert_dtypes()
    return regex_pat

def parse_matchboard_msgs(df):
    """Receives a dataframe of games and expands 
    description column into winner and loser fields

    Args:
        df (DataFrame): Pandas Dataframe containing a 
        Description column containing matchboard text messages

    Returns:
        Dataframe: Dataframe with winner and loser appended.
    """
    logger.debug('Parsing matchboard matches now')
    df = df[df['title'] == '🏅 Ranked battle has ended']  # filter df to only include ranked
    df = df.assign(regex_pattern=assign_regex_pattern(df['description']))  # create column specifying regex pat to use
    winner_loser_df = pd.concat([df[df.regex_pattern == 0]['description'].str.extract(WIN_PATTERN),
                                 df[df.regex_pattern == 1]['description'].str.extract(LOSS_PATTERN).rename({0:1,1:0},axis=1),
                                 df[df.regex_pattern == 2]['description'].str.extract(HALF_WIN_PATTERN),
                                 df[df.regex_pattern == 3]['description'].str.extract(HALF_LOSS_PATTERN).rename({0:1,1:0},axis=1)])
    winner_loser_df.index.name = 'msg_id'
    df = df.merge(winner_loser_df, how='left', on='msg_id').rename({0:'winner',1:'loser'}, axis=1)
    df.to_csv('data/test.csv')
    
    return df


def parse_mention_to_id(mention):
    m = re.match(MENTION_PATTERN, mention)

    if m is None:
        return None

    return int(m.group(1))


def convert_msgs_to_df(history):
    """Splits each message into a DataFrame 
    with columns of interest.

    Args:
        history (List): Flattened list of matchboard messages

    Returns:
        DataFrame: Records of split messages
    """
    list_of_dicts = []
    for msg in history:
        if len(msg.embeds) == 0:
            continue
        list_of_dicts.append(
            {
                "title":msg.embeds[0].title,
                "msg_id":msg.id,
                "color":msg.embeds[0].color,
                "description":msg.embeds[0].description,
                "timestamp":msg.embeds[0].timestamp.timestamp(),
                "match_time":msg.embeds[0].footer.text
            }
        )
        
    return pd.DataFrame(list_of_dicts).set_index("msg_id")


## File reading/writing

async def fetch_game_results(matchboard, after=None):
    """Fetches games from local directory if previous record exists
    and from PW's discord matchboard channel

    Args:
        matchboard (TextChannel object): The matchboard channel
        after (timestamp or msg_id?, optional): Fetch messages after this timestamp or id. 
            Defaults to None.

    Returns:
        DataFrame: Consists of all the games fetched from matchboard after data wrangling.
    """
    game_results = []
    history = await matchboard.history(oldest_first=True,
                                 after=after,
                                 limit=3000).flatten()  # TODO Put back None once testing is done

    games_df = convert_msgs_to_df(history)
    games_df = parse_matchboard_msgs(games_df)

    # for msg in history:
    #     for msg.embeds[0]

    # for msg in history:
    #     game = parse_matchboard_msg(msg)

    #     if game is None:
    #         continue

    #     game.loc["msg_id"] = msg.id
    #     game_results.append(game)
    
    # games_df = pd.DataFrame(game_results).set_index("msg_id")

    return games_df


def load_ranking_configs():
    logger.info("Loading ranking configurations from file.")
    with open("config/ranking_config.json", "r", encoding="utf-8") as file:
        configs = json.load(file)
    return configs


def load_tokens():
    with open("config/tokens.json", "r", encoding="utf-8") as file:
        d = json.load(file)
    return d
