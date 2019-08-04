import csv
import json
import re

from collections import OrderedDict

from utils import locking, logger

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


def parse_matchboard_msg(msg):
    """Parse a message on the matchboard, return the result as the tuple `winner, loser` or `None`
    if winner and loser can not be determined (e.g. messages with only one name).
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

    return OrderedDict(timestamp=msg.created_at.timestamp(),
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

        game_results.append(game)

    return game_results


async def get_game_results(matchboard):
    # First retrieve saved games.
    loaded_results = await load_game_results()

    if len(loaded_results) > 0:
        last_id = int(loaded_results[-1]["id"])
        last_message = await matchboard.fetch_message(last_id)
    else:
        last_message = None

    # Second fetch messages not yet saved from the matchboard.
    # New results are directly saved.
    logger.info("Fetching missing results from matchboard.")

    fetched_game_results = await fetch_game_results(matchboard, after=last_message)

    logger.info(f"{len(fetched_game_results)} new results fetched from matchboard.")

    await save_games(fetched_game_results)

    return loaded_results + fetched_game_results


def game_results_writer(file):
    """Return a `Writer` for game results for a given file.

    Using this ensure consistent formatting of the results.
    """
    return csv.DictWriter(file, fieldnames=["timestamp", "id", "winner", "loser"])


@locking("raw_results.csv")
async def load_game_results():
    try:
        logger.info("Retrieving saved games.")
        with open("data/raw_results.csv", "r", encoding="utf-8", newline="") as file:
            game_results = list(csv.DictReader(file))

            logger.info(f"{len(game_results)} game results retrieved from save.")

    except FileNotFoundError:
        logger.warning("File `raw_results.csv` not found, creating a new one.")

        with open("data/raw_results.csv", "w", encoding="utf-8", newline="") as file:
            writer = game_results_writer(file)
            writer.writeheader()
            game_results = []

    for k, game in enumerate(game_results):
        game_results[k]["timestamp"] = float(game["timestamp"])

    return game_results


def load_ranking_configs():
    with open("config/ranking_config.json", "r", encoding="utf-8") as file:
        configs = json.load(file)
    return configs


def load_tokens():
    with open("config/tokens.json", "r", encoding="utf-8") as file:
        d = json.load(file)
    return d


@locking("raw_results.csv")
async def save_games(games):
    with open("data/raw_results.csv", "a",
              encoding="utf-8", newline="") as file:
        writer = game_results_writer(file)

        for game in games:
            writer.writerow(game)


def save_single_game(game):
    with open("data/raw_results.csv", "a",
              encoding="utf-8", newline="") as file:
        writer = game_results_writer(file)
        writer.writerow(game)
